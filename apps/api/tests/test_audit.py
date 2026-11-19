"""Audit Log foundation and Activity Timelines for Jobs and Applications (FR-A3.3, ERD §7)."""

import json
import smtplib
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

import httpx
import openai
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app import ai, apply, audit, emails, jobs, scoring_runs, storage, sweep, uploads
from app.auth import _redis
from app.db import async_tenant_session, tenant_session
from app.main import app
from smart_ats_scoring import embedding, parsing, pricing
from smart_ats_scoring.llm import LlmResult, Usage
from tests.conftest import API_DIR
from tests.test_apply import PDF_SAMPLE
from tests.test_jobs import CONFIRMATION, JD, PARSED, FakeLlm, User, make_user
from tests.test_scoring_runs import (
    EMBEDDING_MODEL,
    MODEL,
    SCORED,
    FakeEmbedder,
    add_application,
    calibrate_embedding,
    make_job,
)
from tests.test_uploads import docx, profile

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


async def test_migration_0014_backfills_stage_history_per_tenant(
    client: AsyncClient, recruiter: User
) -> None:
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

    upload_timeline = await get_application_timeline(client, recruiter, app_upload)
    assert [
        (i["action"], i["actor_type"], i["before"], i["after"]) for i in upload_timeline["items"]
    ] == [
        ("application.stage_changed", "USER", {"stage": "APPLIED"}, {"stage": "SCREENING"}),
        (
            "application.created",
            "USER",
            None,
            {
                "source": "UPLOAD",
                "candidate_id": str(upload_meta.candidate_id),
                "cv_document_id": str(upload_meta.cv_document_id),
                "stage": "APPLIED",
            },
        ),
    ]
    assert "secret" not in json.dumps(upload_timeline)

    public_timeline = await get_application_timeline(client, recruiter, app_public)
    assert [
        (i["action"], i["actor_type"], i["actor"], i["before"], i["after"])
        for i in public_timeline["items"]
    ] == [
        (
            "application.created",
            "PUBLIC",
            None,
            None,
            {
                "source": "PUBLIC_APPLY",
                "candidate_id": str(public_meta.candidate_id),
                "cv_document_id": str(public_meta.cv_document_id),
                "stage": "APPLIED",
            },
        )
    ]


async def get_timeline(
    client: AsyncClient, user: User, job_id: str, **params: Any
) -> dict[str, Any]:
    response = await client.get(f"/api/jobs/{job_id}/timeline", headers=user.headers, params=params)
    assert response.status_code == 200
    data: dict[str, Any] = response.json()
    return data


async def get_application_timeline(
    client: AsyncClient, user: User, application_id: str, **params: Any
) -> dict[str, Any]:
    response = await client.get(
        f"/api/applications/{application_id}/timeline", headers=user.headers, params=params
    )
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


@pytest.mark.usefixtures("redis")
async def test_cv_upload_retry_and_dedupe_audit_logs_without_pii(
    client: AsyncClient,
    recruiter: User,
    objects: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploader = make_user("RECRUITER", recruiter.tenant_id)
    job_id = make_job(recruiter, objects)
    second_job_id = make_job(recruiter, objects)

    cv_enqueued: list[tuple[str, ...]] = []
    monkeypatch.setattr(uploads.parse_cv, "delay", lambda *args: cv_enqueued.append(args))
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "test-model")
    monkeypatch.setitem(
        pricing.PRICES, "test-model", pricing.Price(Decimal("2"), Decimal("0.5"), Decimal("8"))
    )

    secret_name = "Ứng Viên Bí Mật"
    secret_email = "secret.candidate@example.com"
    secret_phone = "0987654321"
    secret_filename = "ung_vien_bi_mat.docx"
    fake_cv_llm = FakeLlm(profile(full_name=secret_name, email=secret_email, phone=secret_phone))
    monkeypatch.setattr(uploads, "llm_from_env", lambda model, **_: fake_cv_llm)

    # Rejected upload (missing consent -> 422) leaves no audit row.
    bad_up = await client.post(
        f"/api/jobs/{job_id}/uploads",
        headers=uploader.headers,
        files=[("files", (secret_filename, docx("CV 1")))],
        data={"consent_confirmed": "false"},
    )
    assert bad_up.status_code == 422
    assert (await get_timeline(client, recruiter, job_id))["items"] == []

    # 1. Valid upload batch (2 files) records job.cvs_uploaded.
    cv1 = docx("CV 1")
    cv2 = docx("CV 2")
    up_res = await client.post(
        f"/api/jobs/{job_id}/uploads",
        headers=uploader.headers,
        files=[("files", (secret_filename, cv1)), ("files", ("other_cv.docx", cv2))],
        data={"consent_confirmed": "true"},
    )
    assert up_res.status_code == 202
    batch_id = up_res.json()["batch_id"]
    item1_id, item2_id = up_res.json()["item_ids"]

    job_items = (await get_timeline(client, recruiter, job_id))["items"]
    assert len(job_items) == 1
    assert job_items[0]["action"] == "job.cvs_uploaded"
    assert job_items[0]["actor_type"] == "USER"
    assert job_items[0]["actor"]["id"] == str(uploader.id)
    assert job_items[0]["before"] is None
    assert job_items[0]["after"] == {"upload_batch_id": batch_id, "file_count": 2}
    assert "ip" not in job_items[0] and "request_id" not in job_items[0]

    # Fail item 1 with LLM_UNAVAILABLE so we can retry it.
    with monkeypatch.context() as mp:
        mp.setattr(uploads, "is_transient_error", lambda e: True)
        mp.setattr(ai, "retry_transient_error", lambda e: "LLM_UNAVAILABLE")

        def boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("ai down")

        mp.setattr(parsing, "parse_cv", boom)
        uploads.parse_cv.apply(args=cv_enqueued.pop(0)).get()

    # Retrying non-FAILED item 2 (409) leaves no audit row.
    assert (
        await client.post(
            f"/api/jobs/{job_id}/uploads/items/{item2_id}/retry", headers=uploader.headers
        )
    ).status_code == 409
    assert len((await get_timeline(client, recruiter, job_id))["items"]) == 1

    # 2. Retry failed item 1 -> records job.cv_parse_retried.
    retry_res = await client.post(
        f"/api/jobs/{job_id}/uploads/items/{item1_id}/retry", headers=uploader.headers
    )
    assert retry_res.status_code == 202

    job_items = (await get_timeline(client, recruiter, job_id))["items"]
    assert [i["action"] for i in job_items] == ["job.cv_parse_retried", "job.cvs_uploaded"]
    assert job_items[0]["actor"]["id"] == str(uploader.id)
    assert job_items[0]["before"] == {"status": "FAILED", "error_code": "LLM_UNAVAILABLE"}
    assert job_items[0]["after"] == {
        "upload_batch_id": batch_id,
        "item_id": item1_id,
        "status": "PENDING",
        "error_code": None,
    }

    # 3. Parse retried item 1 -> creates Application with USER = uploader.
    uploads.parse_cv.apply(args=cv_enqueued.pop(-1)).get()
    apps = (await client.get(f"/api/jobs/{job_id}/applications", headers=recruiter.headers)).json()
    assert len(apps) == 1
    app_id = apps[0]["id"]

    app_timeline = await get_application_timeline(client, recruiter, app_id)
    assert len(app_timeline["items"]) == 1
    created_entry = app_timeline["items"][0]
    assert created_entry["action"] == "application.created"
    assert created_entry["actor_type"] == "USER"
    assert created_entry["actor"]["id"] == str(uploader.id)
    assert created_entry["before"] is None
    assert created_entry["after"]["source"] == "UPLOAD"
    assert created_entry["after"]["stage"] == "APPLIED"
    assert uuid.UUID(created_entry["after"]["candidate_id"])
    assert uuid.UUID(created_entry["after"]["cv_document_id"])
    assert "ip" not in created_entry and "request_id" not in created_entry

    # Zero candidate PII or filename in either timeline!
    for tl in (job_items, app_timeline):
        dumped = json.dumps(tl, ensure_ascii=False)
        for pii in (secret_name, secret_email, secret_phone, secret_filename):
            assert pii not in dumped

    # 4. Dedupe: ALREADY_APPLIED & CV_REPLACED do NOT write application.created.
    await client.post(
        f"/api/jobs/{job_id}/uploads",
        headers=uploader.headers,
        files=[("files", (secret_filename, cv1))],
        data={"consent_confirmed": "true"},
    )
    uploads.parse_cv.apply(args=cv_enqueued.pop(-1)).get()
    await client.post(
        f"/api/jobs/{job_id}/uploads",
        headers=uploader.headers,
        files=[("files", ("updated.docx", docx("CV updated 2026")))],
        data={"consent_confirmed": "true"},
    )
    uploads.parse_cv.apply(args=cv_enqueued.pop(-1)).get()
    assert len((await get_application_timeline(client, recruiter, app_id))["items"]) == 1

    # 5. Dedupe: EXISTING_CANDIDATE on second Job writes application.created for the new row.
    await client.post(
        f"/api/jobs/{second_job_id}/uploads",
        headers=uploader.headers,
        files=[("files", (secret_filename, cv1))],
        data={"consent_confirmed": "true"},
    )
    uploads.parse_cv.apply(args=cv_enqueued.pop(-1)).get()
    second_apps = (
        await client.get(f"/api/jobs/{second_job_id}/applications", headers=recruiter.headers)
    ).json()
    assert len(second_apps) == 1
    second_tl = await get_application_timeline(client, recruiter, second_apps[0]["id"])
    assert [i["action"] for i in second_tl["items"]] == ["application.created"]


@pytest.mark.usefixtures("redis")
async def test_public_apply_records_public_application_created_without_pii_or_duplicate(
    client: AsyncClient,
    recruiter: User,
    objects: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _redis().delete("apply_limit:ip:127.0.0.1", "apply_limit:ip:testclient")
    monkeypatch.setattr(apply.parse_cv, "delay", lambda *args: None)
    monkeypatch.setattr(emails.send_email, "delay", lambda *args: None)

    job_id = make_job(recruiter, objects)
    await client.post(
        f"/api/jobs/{job_id}/transitions", headers=recruiter.headers, json={"action": "publish"}
    )
    job = (
        await client.patch(
            f"/api/jobs/{job_id}/public-apply", headers=recruiter.headers, json={"enabled": True}
        )
    ).json()
    slug = job["public_slug"]

    # Invalid submission (consent=false -> 422) leaves no Application audit row.
    bad_apply = await client.post(
        f"/api/apply/{slug}",
        data={"full_name": "Invalid", "email": "inv@example.com", "consent": "false"},
        files={"file": ("cv.pdf", PDF_SAMPLE, "application/pdf")},
    )
    assert bad_apply.status_code == 422

    cand_name = "Trần Thị Minh Thư"
    cand_email = "minhthu.public@example.com"
    cand_phone = "0911222333"
    res = await client.post(
        f"/api/apply/{slug}",
        data={
            "full_name": cand_name,
            "email": cand_email,
            "phone": cand_phone,
            "consent": "true",
        },
        files={"file": ("tran_thi_minh_thu.pdf", PDF_SAMPLE, "application/pdf")},
    )
    assert res.status_code == 200

    [app_row] = (
        await client.get(f"/api/jobs/{job_id}/applications", headers=recruiter.headers)
    ).json()
    app_id = app_row["id"]

    timeline = await get_application_timeline(client, recruiter, app_id)
    assert len(timeline["items"]) == 1
    entry = timeline["items"][0]
    assert entry["action"] == "application.created"
    assert entry["actor_type"] == "PUBLIC"
    assert entry["actor"] is None
    assert entry["before"] is None
    assert entry["after"]["source"] == "PUBLIC_APPLY"
    assert entry["after"]["stage"] == "APPLIED"
    assert "ip" not in entry and "request_id" not in entry

    dumped = json.dumps(timeline, ensure_ascii=False)
    for pii in (cand_name, cand_email, cand_phone, "tran_thi_minh_thu.pdf"):
        assert pii not in dumped

    # Verify IP was stored in DB for PUBLIC request and request_id stays NULL.
    with tenant_session(recruiter.tenant_id) as session:
        row = session.execute(
            text(
                "SELECT actor_type, ip, request_id FROM audit_logs"
                " WHERE entity_type = 'application' AND entity_id = :id"
            ),
            {"id": app_id},
        ).one()
    assert row.actor_type == "PUBLIC"
    assert row.ip is not None
    assert row.request_id is None

    # Duplicate email submission creates no second Application and writes no Audit Log row.
    dup = await client.post(
        f"/api/apply/{slug}",
        data={"full_name": cand_name, "email": cand_email, "consent": "true"},
        files={"file": ("cv2.pdf", PDF_SAMPLE, "application/pdf")},
    )
    assert dup.status_code == 200
    assert len((await get_application_timeline(client, recruiter, app_id))["items"]) == 1


@pytest.mark.cross_tenant
async def test_application_stage_changes_bulk_errors_pagination_revoked_and_access(
    client: AsyncClient, recruiter: User, objects: dict[str, bytes]
) -> None:
    admin = make_user("COMPANY_ADMIN", recruiter.tenant_id)
    mover = make_user("RECRUITER", recruiter.tenant_id)
    assigned_reviewer = make_user("REVIEWER", recruiter.tenant_id)
    unassigned_reviewer = make_user("REVIEWER", recruiter.tenant_id)
    other_tenant_user = make_user("COMPANY_ADMIN")

    job_id = make_job(recruiter, objects)
    await client.put(
        f"/api/jobs/{job_id}/reviewers",
        headers=recruiter.headers,
        json={"user_ids": [str(assigned_reviewer.id)]},
    )
    app1 = add_application(recruiter, objects, job_id)["id"]
    app2 = add_application(recruiter, objects, job_id)["id"]

    # Single moves with note & rejected_reason: neither note nor reason enters audit_logs.
    r1 = await client.patch(
        f"/api/applications/{app1}/stage",
        headers=mover.headers,
        json={"to_stage": "SCREENING", "version": 0, "note": "Ghi chú nội bộ bí mật"},
    )
    assert r1.status_code == 200
    r2 = await client.patch(
        f"/api/applications/{app1}/stage",
        headers=mover.headers,
        json={"to_stage": "REJECTED", "version": 1, "rejected_reason": "Lý do từ chối riêng"},
    )
    assert r2.status_code == 200

    # Refused 422 (reopen without reason) leaves no audit row.
    assert (
        await client.patch(
            f"/api/applications/{app1}/stage",
            headers=mover.headers,
            json={"to_stage": "INTERVIEW", "version": 2, "note": "   "},
        )
    ).status_code == 422

    # Valid reopen -> version 3.
    r3 = await client.patch(
        f"/api/applications/{app1}/stage",
        headers=mover.headers,
        json={"to_stage": "INTERVIEW", "version": 2, "note": "Bổ sung phỏng vấn"},
    )
    assert r3.status_code == 200

    # Refused 409 stale version leaves no audit row.
    assert (
        await client.patch(
            f"/api/applications/{app1}/stage",
            headers=mover.headers,
            json={"to_stage": "OFFER", "version": 1},
        )
    ).status_code == 409

    # Bulk move of app1 (version 3) and app2 (version 0) to OFFER -> 1 row each.
    bulk_ok = await client.post(
        f"/api/jobs/{job_id}/applications/stage",
        headers=recruiter.headers,
        json={
            "applications": [{"id": app1, "version": 3}, {"id": app2, "version": 0}],
            "to_stage": "OFFER",
        },
    )
    assert bulk_ok.status_code == 200

    # Bulk move with one stale version (409) rolls back completely -> no audit rows added.
    bulk_bad = await client.post(
        f"/api/jobs/{job_id}/applications/stage",
        headers=recruiter.headers,
        json={
            "applications": [{"id": app1, "version": 4}, {"id": app2, "version": 0}],
            "to_stage": "SCREENING",
        },
    )
    assert bulk_bad.status_code == 409

    # Move app2 to HIRED, then refuse moving from HIRED (409) -> no extra row.
    assert (
        await client.patch(
            f"/api/applications/{app2}/stage",
            headers=recruiter.headers,
            json={"to_stage": "HIRED", "version": 1},
        )
    ).status_code == 200
    assert (
        await client.patch(
            f"/api/applications/{app2}/stage",
            headers=recruiter.headers,
            json={"to_stage": "OFFER", "version": 2},
        )
    ).status_code == 409

    # Verify app1 & app2 timelines.
    tl1 = await get_application_timeline(client, recruiter, app1)
    assert [(i["action"], i["before"], i["after"]) for i in tl1["items"]] == [
        ("application.stage_changed", {"stage": "INTERVIEW"}, {"stage": "OFFER"}),
        ("application.stage_changed", {"stage": "REJECTED"}, {"stage": "INTERVIEW"}),
        ("application.stage_changed", {"stage": "SCREENING"}, {"stage": "REJECTED"}),
        ("application.stage_changed", {"stage": "APPLIED"}, {"stage": "SCREENING"}),
    ]
    dumped1 = json.dumps(tl1, ensure_ascii=False)
    for forbidden_note in ("Ghi chú nội bộ bí mật", "Lý do từ chối riêng", "Bổ sung phỏng vấn"):
        assert forbidden_note not in dumped1

    tl2 = await get_application_timeline(client, recruiter, app2)
    assert [(i["action"], i["before"], i["after"]) for i in tl2["items"]] == [
        ("application.stage_changed", {"stage": "OFFER"}, {"stage": "HIRED"}),
        ("application.stage_changed", {"stage": "APPLIED"}, {"stage": "OFFER"}),
    ]

    # Revoking mover keeps their full_name visible on the Application timeline.
    revoked_res = await client.delete(f"/api/members/{mover.id}", headers=admin.headers)
    assert revoked_res.status_code == 204
    tl1_after_revoke = await get_application_timeline(client, admin, app1)
    assert tl1_after_revoke["items"][1]["actor"] == {"id": str(mover.id), "full_name": "Test User"}

    # Keyset pagination across app1 timeline (4 entries, limit=2).
    collected: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        page = await get_application_timeline(client, recruiter, app1, **params)
        collected.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert [i["id"] for i in collected] == [i["id"] for i in tl1["items"]]

    # Archived Job still readable by assigned Reviewer; unassigned/other tenant/missing -> 404.
    for action in ("publish", "close", "archive"):
        await client.post(
            f"/api/jobs/{job_id}/transitions", headers=recruiter.headers, json={"action": action}
        )
    assert (
        await client.get(f"/api/applications/{app1}/timeline", headers=assigned_reviewer.headers)
    ).status_code == 200
    assert (
        await client.get(f"/api/applications/{app1}/timeline", headers=unassigned_reviewer.headers)
    ).status_code == 404
    assert (
        await client.get(f"/api/applications/{app1}/timeline", headers=other_tenant_user.headers)
    ).status_code == 404
    assert (
        await client.get(f"/api/applications/{uuid.uuid4()}/timeline", headers=recruiter.headers)
    ).status_code == 404


def _transient_status_error(code: int = 503) -> openai.APIStatusError:
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    resp = httpx.Response(code, request=req)
    return openai.APIStatusError("transient", response=cast(Any, resp), body=None)


class _ScriptedLlm:
    def __init__(self, outcomes: list[dict[str, Any] | BaseException], model: str = MODEL) -> None:
        self.outcomes = outcomes
        self.model = model
        self.calls = 0

    def structured(self, *args: Any, **kwargs: Any) -> LlmResult:
        idx = min(self.calls, len(self.outcomes) - 1)
        self.calls += 1
        outcome = self.outcomes[idx]
        if isinstance(outcome, BaseException):
            raise outcome
        return LlmResult(outcome, Usage(self.model, 1000, 500, 400))


@pytest.mark.usefixtures("redis")
async def test_scoring_run_start_retry_scored_rollback_and_stuck_audit_logs(
    client: AsyncClient,
    recruiter: User,
    objects: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _redis().delete(*ai.breaker_keys())
    monkeypatch.setenv("LLM_REASONING_MODEL", MODEL)
    monkeypatch.setitem(
        pricing.PRICES, MODEL, pricing.Price(Decimal("2"), Decimal("0.2"), Decimal("10"))
    )
    calibrate_embedding(monkeypatch)
    scoring_enqueued: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        scoring_runs.score_application, "delay", lambda *args: scoring_enqueued.append(args)
    )
    monkeypatch.setattr(
        scoring_runs,
        "embedder_from_env",
        lambda model, **_: {EMBEDDING_MODEL: FakeEmbedder()}[model],
    )

    # 1. Refused Scoring Run starts must leave zero audit rows:
    # (a) Unconfirmed criteria -> 409
    unconfirmed_job = make_job(recruiter, objects, confirmed=False)
    add_application(recruiter, objects, unconfirmed_job)
    assert (
        await client.post(f"/api/jobs/{unconfirmed_job}/scoring-runs", headers=recruiter.headers)
    ).status_code == 409
    assert (await get_timeline(client, recruiter, unconfirmed_job))["items"] == []

    # (b) No applications -> 409
    job_id = make_job(recruiter, objects, confirmed=True)
    assert (
        await client.post(f"/api/jobs/{job_id}/scoring-runs", headers=recruiter.headers)
    ).status_code == 409
    assert (await get_timeline(client, recruiter, job_id))["items"] == []

    app1 = add_application(recruiter, objects, job_id)["id"]
    app2 = add_application(recruiter, objects, job_id)["id"]

    # (c) Unpriced model -> 503
    with monkeypatch.context() as mp:
        mp.setenv("LLM_REASONING_MODEL", "unpriced-model")
        assert (
            await client.post(f"/api/jobs/{job_id}/scoring-runs", headers=recruiter.headers)
        ).status_code == 503

    # (d) Embedding model without similarity threshold -> 503
    with monkeypatch.context() as mp:
        mp.delitem(embedding.THRESHOLDS, EMBEDDING_MODEL)
        assert (
            await client.post(f"/api/jobs/{job_id}/scoring-runs", headers=recruiter.headers)
        ).status_code == 503

    # (e) Budget exceeded -> 402
    with tenant_session(recruiter.tenant_id) as session:
        session.execute(text("UPDATE tenants SET ai_budget_usd = 0"))
    assert (
        await client.post(f"/api/jobs/{job_id}/scoring-runs", headers=recruiter.headers)
    ).status_code == 402
    assert (await get_timeline(client, recruiter, job_id))["items"] == []
    with tenant_session(recruiter.tenant_id) as session:
        session.execute(text("UPDATE tenants SET ai_budget_usd = 100"))

    # 2. Valid Scoring Run start -> records job.scoring_run_started with USER actor.
    started = await client.post(f"/api/jobs/{job_id}/scoring-runs", headers=recruiter.headers)
    assert started.status_code == 202
    run_id = started.json()["run_id"]

    # (f) Another Scoring Run already running -> 409, no duplicate audit row.
    assert (
        await client.post(f"/api/jobs/{job_id}/scoring-runs", headers=recruiter.headers)
    ).status_code == 409

    job_tl = await get_timeline(client, recruiter, job_id)
    assert len(job_tl["items"]) == 1
    assert job_tl["items"][0]["action"] == "job.scoring_run_started"
    assert job_tl["items"][0]["actor_type"] == "USER"
    assert job_tl["items"][0]["actor"]["id"] == str(recruiter.id)
    assert job_tl["items"][0]["before"] is None
    assert job_tl["items"][0]["after"] == {"scoring_run_id": run_id, "application_count": 2}
    assert "ip" not in job_tl["items"][0] and "request_id" not in job_tl["items"][0]

    args_by_app = {args[2]: args for args in scoring_enqueued}
    scoring_enqueued.clear()

    # 3. Transient error then retry -> rollback leaves no duplicate application.scored row.
    flaky_llm = _ScriptedLlm([_transient_status_error(503), SCORED])
    monkeypatch.setattr(scoring_runs, "llm_from_env", lambda model, **_: flaky_llm)
    scoring_runs.score_application.apply(args=args_by_app[app1]).get()
    assert flaky_llm.calls == 2
    # Redelivered task after completion exits early with no duplicate row.
    scoring_runs.score_application.apply(args=args_by_app[app1]).get()

    app1_tl = await get_application_timeline(client, recruiter, app1)
    assert len(app1_tl["items"]) == 1
    assert app1_tl["items"][0]["action"] == "application.scored"
    assert app1_tl["items"][0]["actor_type"] == "SYSTEM"
    assert app1_tl["items"][0]["actor"] is None
    assert app1_tl["items"][0]["before"] == {"status": "PENDING"}
    assert app1_tl["items"][0]["after"]["scoring_run_id"] == run_id
    assert app1_tl["items"][0]["after"]["status"] == "SCORED"
    assert isinstance(app1_tl["items"][0]["after"]["total_score"], float)
    assert "error_code" not in app1_tl["items"][0]["after"]

    # Refused manual retry on a SCORED result (409) leaves no audit row.
    assert (
        await client.post(
            f"/api/jobs/{job_id}/scoring-runs/{run_id}/results/{app1}/retry",
            headers=recruiter.headers,
        )
    ).status_code == 409
    assert len((await get_application_timeline(client, recruiter, app1))["items"]) == 1

    # 4. Exhausted transient failure -> application.scored (FAILED, LLM_UNAVAILABLE),
    # then manual retry -> application.score_retried (USER),
    # then stuck sweep -> application.scored (FAILED, STUCK).
    await _redis().delete(*ai.breaker_keys())
    always_down = _ScriptedLlm([_transient_status_error(503)])
    monkeypatch.setattr(scoring_runs, "llm_from_env", lambda model, **_: always_down)
    scoring_runs.score_application.apply(args=args_by_app[app2]).get()

    app2_tl_failed = await get_application_timeline(client, recruiter, app2)
    assert [
        (i["action"], i["actor_type"], i["before"], i["after"]) for i in app2_tl_failed["items"]
    ] == [
        (
            "application.scored",
            "SYSTEM",
            {"status": "PENDING"},
            {"scoring_run_id": run_id, "status": "FAILED", "error_code": "LLM_UNAVAILABLE"},
        )
    ]

    retry_res = await client.post(
        f"/api/jobs/{job_id}/scoring-runs/{run_id}/results/{app2}/retry",
        headers=recruiter.headers,
    )
    assert retry_res.status_code == 202
    scoring_enqueued.clear()

    with tenant_session(recruiter.tenant_id) as session:
        session.execute(
            text(
                "UPDATE score_results SET attempts = :max_attempts,"
                "  enqueued_at = now() - :past"
                " WHERE scoring_run_id = :run_id AND application_id = :app_id"
            ),
            {
                "max_attempts": sweep.MAX_ATTEMPTS,
                "past": sweep.STUCK_AFTER + timedelta(minutes=1),
                "run_id": run_id,
                "app_id": app2,
            },
        )
    sweep.tenant.apply(args=(str(recruiter.tenant_id),)).get()

    # Refused manual retry on a STUCK result (409) leaves no extra audit row.
    assert (
        await client.post(
            f"/api/jobs/{job_id}/scoring-runs/{run_id}/results/{app2}/retry",
            headers=recruiter.headers,
        )
    ).status_code == 409

    app2_tl = await get_application_timeline(client, recruiter, app2)
    assert [(i["action"], i["actor_type"], i["before"], i["after"]) for i in app2_tl["items"]] == [
        (
            "application.scored",
            "SYSTEM",
            {"status": "PENDING"},
            {"scoring_run_id": run_id, "status": "FAILED", "error_code": "STUCK"},
        ),
        (
            "application.score_retried",
            "USER",
            {"status": "FAILED", "error_code": "LLM_UNAVAILABLE"},
            {"scoring_run_id": run_id, "status": "PENDING", "error_code": None},
        ),
        (
            "application.scored",
            "SYSTEM",
            {"status": "PENDING"},
            {"scoring_run_id": run_id, "status": "FAILED", "error_code": "LLM_UNAVAILABLE"},
        ),
    ]
    assert app2_tl["items"][1]["actor"]["id"] == str(recruiter.id)

    # Zero candidate PII in Job or Application timelines.
    for tl in (job_tl, app1_tl, app2_tl):
        dumped = json.dumps(tl, ensure_ascii=False)
        assert "Nguyễn Văn An" not in dumped


@pytest.mark.usefixtures("redis")
async def test_application_email_sent_failed_and_stuck_audit_logs_without_email_content(
    client: AsyncClient,
    recruiter: User,
    objects: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _redis().delete("apply_limit:ip:127.0.0.1", "apply_limit:ip:testclient")
    monkeypatch.setenv("EMAIL_FROM", "ats@example.com")
    monkeypatch.setattr(apply.parse_cv, "delay", lambda *args: None)
    email_enqueued: list[tuple[str, ...]] = []
    monkeypatch.setattr(emails.send_email, "delay", lambda *args: email_enqueued.append(args))

    admin = make_user("COMPANY_ADMIN", recruiter.tenant_id)
    job_id = make_job(recruiter, objects)
    await client.post(
        f"/api/jobs/{job_id}/transitions", headers=recruiter.headers, json={"action": "publish"}
    )
    job = (
        await client.patch(
            f"/api/jobs/{job_id}/public-apply", headers=recruiter.headers, json={"enabled": True}
        )
    ).json()
    slug = job["public_slug"]

    candidates = [
        ("Lê Minh Khôi", "khoi.sent@example.com", "0901112223"),
        ("Phạm Thu Hà", "ha.failed@example.com", "0904445556"),
        ("Đỗ Quang Huy", "huy.stuck@example.com", "0907778889"),
    ]
    for name, email_addr, phone in candidates:
        res = await client.post(
            f"/api/apply/{slug}",
            data={"full_name": name, "email": email_addr, "phone": phone, "consent": "true"},
            files={"file": ("cv.pdf", PDF_SAMPLE, "application/pdf")},
        )
        assert res.status_code == 200

    assert len(email_enqueued) == 3
    sent_args, failed_args, stuck_args = email_enqueued
    sent_email_id, failed_email_id, stuck_email_id = sent_args[1], failed_args[1], stuck_args[1]

    with tenant_session(recruiter.tenant_id) as session:
        app_by_email_id = {
            str(r.id): str(r.application_id)
            for r in session.execute(
                text(
                    "SELECT id, application_id FROM email_messages WHERE application_id IS NOT NULL"
                )
            ).all()
        }

    # 1. SMTP succeeds -> application.email_sent (SYSTEM); redelivery leaves no duplicate.
    delivered: list[str] = []
    monkeypatch.setattr(emails, "deliver", lambda msg: delivered.append(str(msg["To"])))
    emails.send_email.apply(args=sent_args).get()
    emails.send_email.apply(args=sent_args).get()  # redelivered
    assert delivered == ["khoi.sent@example.com"]

    sent_tl = await get_application_timeline(client, recruiter, app_by_email_id[sent_email_id])
    assert [(i["action"], i["actor_type"], i["before"], i["after"]) for i in sent_tl["items"]] == [
        (
            "application.email_sent",
            "SYSTEM",
            {"status": "QUEUED"},
            {"email_id": sent_email_id, "kind": "APPLY_RECEIPT", "status": "SENT"},
        ),
        (
            "application.created",
            "PUBLIC",
            None,
            sent_tl["items"][1]["after"],
        ),
    ]

    # 2. SMTP fails -> application.email_failed (SYSTEM).
    def smtp_boom(_msg: Any) -> None:
        raise smtplib.SMTPException("550 rejected ha.failed@example.com")

    monkeypatch.setattr(emails, "deliver", smtp_boom)
    emails.send_email.apply(args=failed_args).get()

    failed_tl = await get_application_timeline(client, recruiter, app_by_email_id[failed_email_id])
    assert [
        (i["action"], i["actor_type"], i["before"], i["after"]) for i in failed_tl["items"]
    ] == [
        (
            "application.email_failed",
            "SYSTEM",
            {"status": "QUEUED"},
            {"email_id": failed_email_id, "kind": "APPLY_RECEIPT", "status": "FAILED"},
        ),
        (
            "application.created",
            "PUBLIC",
            None,
            failed_tl["items"][1]["after"],
        ),
    ]

    # 3. Stuck email in sweep -> application.email_failed (SYSTEM).
    with tenant_session(recruiter.tenant_id) as session:
        session.execute(
            text(
                "UPDATE email_messages SET attempts = :max_attempts,"
                "  enqueued_at = now() - :past"
                " WHERE id = :id"
            ),
            {
                "max_attempts": sweep.MAX_ATTEMPTS,
                "past": sweep.STUCK_AFTER + timedelta(minutes=1),
                "id": stuck_email_id,
            },
        )
    sweep.tenant.apply(args=(str(recruiter.tenant_id),)).get()

    stuck_tl = await get_application_timeline(client, recruiter, app_by_email_id[stuck_email_id])
    assert [(i["action"], i["actor_type"], i["before"], i["after"]) for i in stuck_tl["items"]] == [
        (
            "application.email_failed",
            "SYSTEM",
            {"status": "QUEUED"},
            {"email_id": stuck_email_id, "kind": "APPLY_RECEIPT", "status": "FAILED"},
        ),
        (
            "application.created",
            "PUBLIC",
            None,
            stuck_tl["items"][1]["after"],
        ),
    ]

    # 4. Member invitation email (application_id IS NULL) writes no application.email_* row.
    email_enqueued.clear()
    inv = await client.post(
        "/api/invitations",
        headers=admin.headers,
        json={"email": "invitee.nullapp@example.com", "role": "RECRUITER"},
    )
    assert inv.status_code == 201
    monkeypatch.setattr(emails, "deliver", lambda _msg: None)
    emails.send_email.apply(args=email_enqueued.pop(0)).get()
    with tenant_session(recruiter.tenant_id) as session:
        inv_app_emails = session.scalar(
            text(
                "SELECT count(*) FROM audit_logs"
                " WHERE action IN ('application.email_sent', 'application.email_failed')"
            )
        )
    assert inv_app_emails == 3

    # 5. Zero email addresses, subjects, bodies, or candidate PII in any timeline response.
    forbidden = [
        "khoi.sent@example.com",
        "ha.failed@example.com",
        "huy.stuck@example.com",
        "Lê Minh Khôi",
        "Phạm Thu Hà",
        "Đỗ Quang Huy",
        "0901112223",
        "0904445556",
        "0907778889",
        "Xác nhận nhận hồ sơ",
        "Application received",
        "Cảm ơn bạn đã nộp hồ sơ",
        "Thank you for applying",
        "Backend Developer",
    ]
    for tl in (sent_tl, failed_tl, stuck_tl):
        dumped = json.dumps(tl, ensure_ascii=False)
        for secret in forbidden:
            assert secret not in dumped
