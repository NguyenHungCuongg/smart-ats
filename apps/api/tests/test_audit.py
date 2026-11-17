"""Audit Log foundation and Job Activity Timeline (FR-A3.3, ERD §7)."""

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app import ai, audit, jobs, storage, sweep
from app.db import async_tenant_session, tenant_session
from app.main import app
from smart_ats_scoring import pricing
from tests.conftest import API_DIR
from tests.test_jobs import CONFIRMATION, JD, PARSED, FakeLlm, User, make_user
from tests.test_scoring_runs import add_application, make_job

pytestmark = pytest.mark.usefixtures("database")


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!")


@pytest.fixture(autouse=True)
def objects(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    stored: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "put", lambda key, data: stored.__setitem__(key, data))
    monkeypatch.setattr(storage, "get", lambda key: stored[key])
    return stored


@pytest.fixture(autouse=True)
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    sent: list[tuple[str, ...]] = []
    monkeypatch.setattr(jobs.parse, "delay", lambda *args: sent.append(args))
    return sent


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> FakeLlm:
    fake = FakeLlm(PARSED)
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "test-model")
    monkeypatch.setattr(jobs, "llm_from_env", lambda model, **_: fake)
    monkeypatch.setitem(
        pricing.PRICES, "test-model", pricing.Price(Decimal("2"), Decimal("0.5"), Decimal("8"))
    )
    return fake


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def recruiter() -> User:
    return make_user()


@pytest.mark.parametrize(
    "action",
    [
        "job.created",
        "job.status_changed",
        "job.criteria_confirmed",
        "application.created",
        "application.stage_changed",
        "member.revoked",
    ],
)
async def test_agent_cannot_record_mutating_actions(recruiter: User, action: str) -> None:
    target_id = uuid.uuid4()
    with pytest.raises(ValueError, match="AGENT"), tenant_session(recruiter.tenant_id) as session:
        audit.record(
            session,
            actor_type="AGENT",
            actor_user_id=recruiter.id,
            action=action,  # type: ignore[arg-type]
            entity_id=target_id,
        )

    with pytest.raises(ValueError, match="AGENT"):
        async with async_tenant_session(recruiter.tenant_id) as db:
            await audit.arecord(
                db,
                actor_type="AGENT",
                actor_user_id=recruiter.id,
                action=action,  # type: ignore[arg-type]
                entity_id=target_id,
            )

    with tenant_session(recruiter.tenant_id) as session:
        count = session.scalar(
            text("SELECT count(*) FROM audit_logs WHERE entity_id = :id"),
            {"id": target_id},
        )
    assert count == 0


def test_agent_can_record_scoring_run_started(recruiter: User) -> None:
    job_id = uuid.uuid4()
    run_id = uuid.uuid4()
    with tenant_session(recruiter.tenant_id) as session:
        audit.record(
            session,
            actor_type="AGENT",
            actor_user_id=recruiter.id,
            action="job.scoring_run_started",
            entity_id=job_id,
            after={"scoring_run_id": str(run_id), "application_count": 3},
        )

    with tenant_session(recruiter.tenant_id) as session:
        row = session.execute(
            text(
                "SELECT actor_type, actor_user_id, action, entity_type, entity_id, before, after,"
                "  request_id, ip"
                " FROM audit_logs WHERE entity_id = :id"
            ),
            {"id": job_id},
        ).one()
    assert (
        row.actor_type,
        row.actor_user_id,
        row.action,
        row.entity_type,
        row.entity_id,
        row.before,
        row.after,
        row.request_id,
        row.ip,
    ) == (
        "AGENT",
        recruiter.id,
        "job.scoring_run_started",
        "job",
        job_id,
        None,
        {"scoring_run_id": str(run_id), "application_count": 3},
        None,
        None,
    )


def test_migration_0014_backfills_stage_history_per_tenant(recruiter: User) -> None:
    objects: dict[str, bytes] = {}
    job_id = make_job(recruiter, objects)
    app_upload = add_application(recruiter, objects, job_id)["id"]
    app_public = add_application(recruiter, objects, job_id)["id"]

    with tenant_session(recruiter.tenant_id) as session:
        session.execute(
            text("UPDATE applications SET source = 'PUBLIC_APPLY' WHERE id = :id"),
            {"id": app_public},
        )
        # Clear any audit_logs and set up exact stage history rows as before migration 0014.
        session.execute(
            text(
                "INSERT INTO application_stage_history"
                "  (tenant_id, application_id, from_stage, to_stage, changed_by, note, changed_at)"
                " VALUES"
                "  (:t, :u_app, NULL, 'APPLIED', :uid, NULL, '2026-01-01T10:00:00Z'),"
                "  (:t, :u_app, 'APPLIED', 'SCREENING', :uid, 'secret', '2026-01-02T10:00:00Z'),"
                "  (:t, :p_app, NULL, 'APPLIED', NULL, NULL, '2026-01-03T10:00:00Z')"
            ),
            {
                "t": recruiter.tenant_id,
                "u_app": app_upload,
                "p_app": app_public,
                "uid": recruiter.id,
            },
        )
        upload_meta = session.execute(
            text("SELECT candidate_id, cv_document_id FROM applications WHERE id = :id"),
            {"id": app_upload},
        ).one()
        public_meta = session.execute(
            text("SELECT candidate_id, cv_document_id FROM applications WHERE id = :id"),
            {"id": app_public},
        ).one()

    cfg = Config(API_DIR / "alembic.ini")
    command.downgrade(cfg, "0013")
    command.upgrade(cfg, "head")

    with tenant_session(recruiter.tenant_id) as session:
        rows: list[Any] = list(
            session.execute(
                text(
                    "SELECT entity_id, actor_type, actor_user_id, action, before, after, created_at"
                    " FROM audit_logs"
                    " WHERE entity_type = 'application' AND entity_id IN (:u_app, :p_app)"
                    "  AND created_at IN ("
                    "    '2026-01-01T10:00:00Z'::timestamptz,"
                    "    '2026-01-02T10:00:00Z'::timestamptz,"
                    "    '2026-01-03T10:00:00Z'::timestamptz"
                    "  )"
                    " ORDER BY created_at"
                ),
                {"u_app": app_upload, "p_app": app_public},
            )
        )

    assert [
        (r.entity_id, r.actor_type, r.actor_user_id, r.action, r.before, r.after) for r in rows
    ] == [
        (
            uuid.UUID(app_upload),
            "USER",
            recruiter.id,
            "application.created",
            None,
            {
                "source": "UPLOAD",
                "candidate_id": str(upload_meta.candidate_id),
                "cv_document_id": str(upload_meta.cv_document_id),
                "stage": "APPLIED",
            },
        ),
        (
            uuid.UUID(app_upload),
            "USER",
            recruiter.id,
            "application.stage_changed",
            {"stage": "APPLIED"},
            {"stage": "SCREENING"},
        ),
        (
            uuid.UUID(app_public),
            "PUBLIC",
            None,
            "application.created",
            None,
            {
                "source": "PUBLIC_APPLY",
                "candidate_id": str(public_meta.candidate_id),
                "cv_document_id": str(public_meta.cv_document_id),
                "stage": "APPLIED",
            },
        ),
    ]


async def get_timeline(
    client: AsyncClient, user: User, job_id: str, **params: Any
) -> dict[str, Any]:
    response = await client.get(f"/api/jobs/{job_id}/timeline", headers=user.headers, params=params)
    assert response.status_code == 200
    data: dict[str, Any] = response.json()
    return data


@pytest.mark.usefixtures("redis")
async def test_all_eight_job_actions_are_recorded_and_exposed_on_timeline(
    client: AsyncClient,
    recruiter: User,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewer = make_user("REVIEWER", recruiter.tenant_id)

    # 1. job.created
    created = await client.post("/api/jobs", headers=recruiter.headers, data={"text": JD})
    assert created.status_code == 202
    job_id = created.json()["id"]

    # 2. job.parsed (FAILED with LLM_UNAVAILABLE so we can retry)
    with monkeypatch.context() as mp:
        mp.setattr(jobs, "is_transient_error", lambda e: True)
        mp.setattr(ai, "retry_transient_error", lambda e: "LLM_UNAVAILABLE")

        def fail_llm(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("provider down")

        mp.setattr(jobs, "parse_job", fail_llm)
        jobs.parse.apply(args=enqueued.pop(0)).get()

    # 3. job.parse_retried
    retried = await client.post(f"/api/jobs/{job_id}/parse/retry", headers=recruiter.headers)
    assert retried.status_code == 202

    # 4. job.parsed (SUCCEEDED)
    jobs.parse.apply(args=enqueued.pop(0)).get()

    # 5. job.criteria_confirmed
    confirmed = await client.put(
        f"/api/jobs/{job_id}/criteria", headers=recruiter.headers, json=CONFIRMATION
    )
    assert confirmed.status_code == 200

    # 6. job.metadata_changed (department is unchanged, only location & apply_deadline change)
    patched = await client.patch(
        f"/api/jobs/{job_id}",
        headers=recruiter.headers,
        json={
            "department": "Engineering",
            "location": "TP.HCM",
            "apply_deadline": "2026-12-31",
        },
    )
    assert patched.status_code == 200

    # 7. job.status_changed
    transitioned = await client.post(
        f"/api/jobs/{job_id}/transitions",
        headers=recruiter.headers,
        json={"action": "publish"},
    )
    assert transitioned.status_code == 200

    # 8. job.public_apply_changed
    toggled = await client.patch(
        f"/api/jobs/{job_id}/public-apply",
        headers=recruiter.headers,
        json={"enabled": True},
    )
    assert toggled.status_code == 200

    # 9. job.reviewers_changed
    assigned = await client.put(
        f"/api/jobs/{job_id}/reviewers",
        headers=recruiter.headers,
        json={"user_ids": [str(reviewer.id)]},
    )
    assert assigned.status_code == 200

    page = await get_timeline(client, recruiter, job_id)
    assert page["next_cursor"] is None
    items = page["items"]
    assert len(items) == 9

    for item in items:
        assert "ip" not in item
        assert "request_id" not in item

    # Chronological order (oldest to newest) by reversing newest-first items
    chronological = list(reversed(items))
    assert [i["action"] for i in chronological] == [
        "job.created",
        "job.parsed",
        "job.parse_retried",
        "job.parsed",
        "job.criteria_confirmed",
        "job.metadata_changed",
        "job.status_changed",
        "job.public_apply_changed",
        "job.reviewers_changed",
    ]

    expected_actor = {"id": str(recruiter.id), "full_name": "Test User"}
    assert chronological[0]["actor_type"] == "USER"
    assert chronological[0]["actor"] == expected_actor
    assert chronological[0]["before"] is None
    assert chronological[0]["after"] == {"status": "DRAFT"}

    assert chronological[1]["actor_type"] == "SYSTEM"
    assert chronological[1]["actor"] is None
    assert chronological[1]["before"] == {"parse_status": "PENDING"}
    assert chronological[1]["after"] == {
        "parse_status": "FAILED",
        "parse_error": "LLM_UNAVAILABLE",
    }

    assert chronological[2]["actor_type"] == "USER"
    assert chronological[2]["actor"] == expected_actor
    assert chronological[2]["before"] == {
        "parse_status": "FAILED",
        "parse_error": "LLM_UNAVAILABLE",
    }
    assert chronological[2]["after"] == {"parse_status": "PENDING", "parse_error": None}

    assert chronological[3]["actor_type"] == "SYSTEM"
    assert chronological[3]["actor"] is None
    assert chronological[3]["before"] == {"parse_status": "PENDING"}
    assert chronological[3]["after"] == {"parse_status": "SUCCEEDED", "parse_error": None}

    assert chronological[4]["actor_type"] == "USER"
    assert chronological[4]["before"]["title"] == "Senior Backend Developer"
    assert chronological[4]["before"]["weights"] == {
        "technical": 55,
        "soft_skills": 15,
        "experience": 30,
    }
    assert chronological[4]["after"] == CONFIRMATION

    assert chronological[5]["actor_type"] == "USER"
    assert chronological[5]["before"] == {"location": None, "apply_deadline": None}
    assert chronological[5]["after"] == {"location": "TP.HCM", "apply_deadline": "2026-12-31"}

    assert chronological[6]["actor_type"] == "USER"
    assert chronological[6]["before"] == {"status": "DRAFT"}
    assert chronological[6]["after"] == {"status": "PUBLISHED", "action": "publish"}

    assert chronological[7]["actor_type"] == "USER"
    assert chronological[7]["before"] == {"public_apply_enabled": False}
    assert chronological[7]["after"] == {"public_apply_enabled": True}

    assert chronological[8]["actor_type"] == "USER"
    assert chronological[8]["before"] == {"user_ids": []}
    assert chronological[8]["after"] == {"user_ids": [str(reviewer.id)]}

    # Verify IP was stored in DB on API USER rows and NULL on SYSTEM rows
    with tenant_session(recruiter.tenant_id) as session:
        ips = session.execute(
            text(
                "SELECT actor_type, ip, request_id FROM audit_logs"
                " WHERE entity_id = :id ORDER BY created_at, id"
            ),
            {"id": job_id},
        ).all()
    assert all(r.request_id is None for r in ips)
    assert all((r.ip is not None) == (r.actor_type == "USER") for r in ips)


@pytest.mark.usefixtures("redis")
async def test_stuck_job_parse_in_sweep_records_system_audit_log(
    client: AsyncClient, recruiter: User, enqueued: list[tuple[str, ...]]
) -> None:
    created = await client.post("/api/jobs", headers=recruiter.headers, data={"text": JD})
    job_id = created.json()["id"]
    enqueued.clear()

    with tenant_session(recruiter.tenant_id) as session:
        session.execute(
            text(
                "UPDATE jobs SET parse_attempts = :max_attempts,"
                "  parse_enqueued_at = now() - :past"
                " WHERE id = :id"
            ),
            {
                "max_attempts": sweep.MAX_ATTEMPTS,
                "past": sweep.STUCK_AFTER + timedelta(minutes=1),
                "id": job_id,
            },
        )

    sweep.tenant.apply(args=(str(recruiter.tenant_id),)).get()

    page = await get_timeline(client, recruiter, job_id)
    assert [(i["action"], i["actor_type"], i["after"]) for i in page["items"]] == [
        ("job.parsed", "SYSTEM", {"parse_status": "FAILED", "parse_error": "STUCK"}),
        ("job.created", "USER", {"status": "DRAFT"}),
    ]


@pytest.mark.usefixtures("redis")
async def test_failed_or_refused_writes_leave_no_audit_log(
    client: AsyncClient, recruiter: User, llm: FakeLlm, enqueued: list[tuple[str, ...]]
) -> None:
    created = await client.post("/api/jobs", headers=recruiter.headers, data={"text": JD})
    job_id = created.json()["id"]
    jobs.parse.apply(args=enqueued.pop(0)).get()

    # Refused operations:
    # 1. Invalid transition (DRAFT -> archive: 409)
    assert (
        await client.post(
            f"/api/jobs/{job_id}/transitions",
            headers=recruiter.headers,
            json={"action": "archive"},
        )
    ).status_code == 409
    # 2. Retry parse when SUCCEEDED (409)
    assert (
        await client.post(f"/api/jobs/{job_id}/parse/retry", headers=recruiter.headers)
    ).status_code == 409
    # 3. Criteria weights != 100% (422)
    bad_weights = CONFIRMATION | {"weights": {"technical": 50, "soft_skills": 20, "experience": 20}}
    assert (
        await client.put(
            f"/api/jobs/{job_id}/criteria", headers=recruiter.headers, json=bad_weights
        )
    ).status_code == 422
    # 4. Metadata invalid title (422)
    assert (
        await client.patch(f"/api/jobs/{job_id}", headers=recruiter.headers, json={"title": ""})
    ).status_code == 422
    # 5. Assign non-reviewer (422)
    assert (
        await client.put(
            f"/api/jobs/{job_id}/reviewers",
            headers=recruiter.headers,
            json={"user_ids": [str(recruiter.id)]},
        )
    ).status_code == 422

    page = await get_timeline(client, recruiter, job_id)
    assert [i["action"] for i in page["items"]] == ["job.parsed", "job.created"]


async def test_revoked_member_name_stays_on_timeline(client: AsyncClient, recruiter: User) -> None:
    admin = make_user("COMPANY_ADMIN", recruiter.tenant_id)
    created = await client.post("/api/jobs", headers=recruiter.headers, data={"text": JD})
    job_id = created.json()["id"]

    revoked = await client.delete(f"/api/members/{recruiter.id}", headers=admin.headers)
    assert revoked.status_code == 204

    page = await get_timeline(client, admin, job_id)
    assert page["items"][0]["actor"] == {"id": str(recruiter.id), "full_name": "Test User"}


async def test_job_timeline_keyset_pagination(client: AsyncClient, recruiter: User) -> None:
    created = await client.post("/api/jobs", headers=recruiter.headers, data={"text": JD})
    job_id = created.json()["id"]
    for action in ("publish", "pause", "resume", "close", "reopen"):
        res = await client.post(
            f"/api/jobs/{job_id}/transitions",
            headers=recruiter.headers,
            json={"action": action},
        )
        assert res.status_code == 200

    full = (await get_timeline(client, recruiter, job_id))["items"]
    assert len(full) == 6

    collected: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        page = await get_timeline(client, recruiter, job_id, **params)
        collected.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert [i["id"] for i in collected] == [i["id"] for i in full]


@pytest.mark.cross_tenant
async def test_job_timeline_access_control_and_archived_read(
    client: AsyncClient, recruiter: User
) -> None:
    assigned_reviewer = make_user("REVIEWER", recruiter.tenant_id)
    unassigned_reviewer = make_user("REVIEWER", recruiter.tenant_id)
    other_tenant_user = make_user("COMPANY_ADMIN")

    created = await client.post("/api/jobs", headers=recruiter.headers, data={"text": JD})
    job_id = created.json()["id"]
    await client.put(
        f"/api/jobs/{job_id}/reviewers",
        headers=recruiter.headers,
        json={"user_ids": [str(assigned_reviewer.id)]},
    )

    # Archive the job (DRAFT -> PUBLISHED -> CLOSED -> ARCHIVED)
    for action in ("publish", "close", "archive"):
        await client.post(
            f"/api/jobs/{job_id}/transitions",
            headers=recruiter.headers,
            json={"action": action},
        )

    assert (
        await client.get(f"/api/jobs/{job_id}/timeline", headers=assigned_reviewer.headers)
    ).status_code == 200
    assert (
        await client.get(f"/api/jobs/{job_id}/timeline", headers=unassigned_reviewer.headers)
    ).status_code == 404
    assert (
        await client.get(f"/api/jobs/{job_id}/timeline", headers=other_tenant_user.headers)
    ).status_code == 404
    assert (
        await client.get(f"/api/jobs/{uuid.uuid4()}/timeline", headers=recruiter.headers)
    ).status_code == 404
