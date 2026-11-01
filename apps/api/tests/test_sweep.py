"""beat's sweep of stuck PENDING rows (SAD §6): lost enqueues are sent again, in their own Tenant.

Object storage, the LLM and the broker are faked; the API, the tasks and PostgreSQL are real.
"""

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app import emails, jobs, scoring_runs, storage, sweep, uploads
from app.db import sync_engine, tenant_session
from app.main import app
from smart_ats_scoring import pricing
from tests.test_jobs import JD, PARSED, FakeLlm, User, make_user
from tests.test_scoring_runs import MODEL, add_application, calibrate_embedding
from tests.test_scoring_runs import make_job as make_confirmed_job
from tests.test_tenancy import owner_engine
from tests.test_uploads import CV

pytestmark = pytest.mark.usefixtures("database", "redis")


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!")
    monkeypatch.setenv("LLM_REASONING_MODEL", MODEL)
    monkeypatch.setenv("WEB_BASE_URL", "https://ats.example")
    monkeypatch.setitem(
        pricing.PRICES, MODEL, pricing.Price(Decimal("2"), Decimal("0.2"), Decimal("10"))
    )
    calibrate_embedding(monkeypatch)


@pytest.fixture(autouse=True)
def objects(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    stored: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "put", lambda key, data: stored.__setitem__(key, data))
    monkeypatch.setattr(storage, "get", lambda key: stored[key])
    return stored


@pytest.fixture(autouse=True)
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[str, ...]]]:
    """Every task sent to the broker, as (name, args): none of them ever reaches a worker."""
    sent: list[tuple[str, tuple[str, ...]]] = []
    for task in (
        jobs.parse,
        uploads.parse_cv,
        scoring_runs.score_application,
        emails.send_email,
        sweep.tenant,
    ):
        monkeypatch.setattr(
            task, "delay", lambda *args, name=task.name: sent.append((name, tuple(args)))
        )
    return sent


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


class Stuck:
    """One Tenant's Job parse, upload item and score result, each enqueued once and then lost."""

    def __init__(self, user: User, job_id: str, item_id: str, run_id: str, application_id: str):
        self.user, self.job_id, self.item_id = user, job_id, item_id
        self.run_id, self.application_id = run_id, application_id
        tid = str(user.tenant_id)
        self.tasks = sorted(
            [
                ("jobs.parse", (tid, job_id, str(user.id))),
                ("uploads.parse_cv", (tid, item_id)),
                ("scoring_runs.score_application", (tid, run_id, application_id)),
            ]
        )


async def stuck(
    client: AsyncClient, objects: dict[str, bytes], enqueued: list[Any], *, attempts: int = 1
) -> Stuck:
    user = make_user()
    job_id = (await client.post("/api/jobs", headers=user.headers, data={"text": JD})).json()["id"]
    scored = make_confirmed_job(user, objects)
    application = add_application(user, objects, scored)
    item_id = (
        await client.post(
            f"/api/jobs/{scored}/uploads",
            headers=user.headers,
            files={"files": ("an.docx", CV)},
            data={"consent_confirmed": "true"},
        )
    ).json()["item_ids"][0]
    run_id = (await client.post(f"/api/jobs/{scored}/scoring-runs", headers=user.headers)).json()[
        "run_id"
    ]
    enqueued.clear()
    # Last enqueued 11 minutes ago, past the 10 of SAD §6.
    with tenant_session(user.tenant_id) as session:
        for sql in (
            "UPDATE jobs SET parse_enqueued_at = parse_enqueued_at - interval '11 minutes',"
            "  parse_attempts = :attempts WHERE parse_status = 'PENDING'",
            "UPDATE upload_batch_items SET enqueued_at = enqueued_at - interval '11 minutes',"
            "  attempts = :attempts",
            "UPDATE score_results SET enqueued_at = enqueued_at - interval '11 minutes',"
            "  attempts = :attempts",
        ):
            assert session.execute(text(sql), {"attempts": attempts}).rowcount == 1  # type: ignore[attr-defined]
    return Stuck(user, job_id, item_id, run_id, application["id"])


def sweep_tenant(user: User) -> None:
    sweep.tenant.apply(args=[str(user.tenant_id)]).get()


def suspended_tenant() -> uuid.UUID:
    tenant_id = make_user().tenant_id
    with owner_engine().begin() as conn:
        conn.execute(
            text("UPDATE tenants SET status = 'SUSPENDED' WHERE id = :id"), {"id": tenant_id}
        )
    return tenant_id


def test_sweep_visits_every_active_tenant_and_skips_suspended_ones(
    enqueued: list[tuple[str, tuple[str, ...]]],
) -> None:
    active, suspended = make_user().tenant_id, suspended_tenant()

    sweep.stuck_rows.apply().get()

    visited = {args[0] for name, args in enqueued if name == "sweep.tenant"}
    assert str(active) in visited
    assert str(suspended) not in visited


async def test_stuck_rows_are_enqueued_again_exactly_once_in_their_own_tenant(
    client: AsyncClient, objects: dict[str, bytes], enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    a = await stuck(client, objects, enqueued)
    b = await stuck(client, objects, enqueued)

    for _ in range(2):  # the second pass finds them freshly enqueued
        sweep_tenant(a.user)
        sweep_tenant(b.user)

    assert sorted(enqueued) == sorted(a.tasks + b.tasks)


async def test_redelivered_parse_runs_once_in_its_tenant(
    client: AsyncClient,
    objects: dict[str, bytes],
    enqueued: list[tuple[str, tuple[str, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeLlm(PARSED)
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "test-model")
    monkeypatch.setattr(jobs, "llm_from_env", lambda model: fake)
    monkeypatch.setitem(
        pricing.PRICES, "test-model", pricing.Price(Decimal("2"), Decimal("0.5"), Decimal("8"))
    )
    s = await stuck(client, objects, enqueued)
    sweep_tenant(s.user)
    [args] = [args for name, args in enqueued if name == "jobs.parse"]

    jobs.parse.apply(args=args).get()
    jobs.parse.apply(args=args).get()  # the lost one turns up after all

    job = (await client.get(f"/api/jobs/{s.job_id}", headers=s.user.headers)).json()
    assert job["parse_status"] == "SUCCEEDED"
    assert fake.calls == 1
    with tenant_session(s.user.tenant_id) as session:
        assert session.scalar(text("SELECT count(*) FROM ai_usage_entries")) == 1


async def test_row_a_task_is_working_on_is_not_stuck(
    client: AsyncClient, objects: dict[str, bytes], enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    s = await stuck(client, objects, enqueued)

    # The tasks hold these locks for as long as they run, however long that is.
    with tenant_session(s.user.tenant_id) as worker:
        worker.execute(
            text("SELECT 1 FROM jobs WHERE id = :id FOR NO KEY UPDATE"), {"id": s.job_id}
        )
        worker.execute(text("SELECT 1 FROM upload_batch_items FOR UPDATE"))
        worker.execute(text("SELECT 1 FROM score_results FOR UPDATE"))
        sweep_tenant(s.user)

    assert enqueued == []


async def test_row_still_stuck_after_three_redeliveries_fails_as_stuck(
    client: AsyncClient, objects: dict[str, bytes], enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    s = await stuck(client, objects, enqueued, attempts=4)

    sweep_tenant(s.user)

    assert enqueued == []
    headers = s.user.headers
    job = (await client.get(f"/api/jobs/{s.job_id}", headers=headers)).json()
    assert (job["parse_status"], job["parse_error"]) == ("FAILED", "STUCK")
    with tenant_session(s.user.tenant_id) as session:
        item = session.execute(
            text(
                "SELECT i.status, i.error_code, b.status AS batch FROM upload_batch_items i"
                " JOIN upload_batches b ON b.id = i.batch_id"
            )
        ).one()
        run = session.execute(
            text(
                "SELECT r.status, s.status AS result, s.error_code FROM scoring_runs r"
                " JOIN score_results s ON s.scoring_run_id = r.id"
            )
        ).one()
    assert tuple(item) == ("FAILED", "STUCK", "COMPLETED")
    assert tuple(run) == ("PARTIAL", "FAILED", "STUCK")


async def stuck_email(
    client: AsyncClient, enqueued: list[tuple[str, tuple[str, ...]]], *, attempts: int = 1
) -> tuple[User, tuple[str, ...]]:
    """A Member invitation whose email was enqueued and then lost; returns its send_email args."""
    admin = make_user("COMPANY_ADMIN")
    response = await client.post(
        "/api/invitations",
        headers=admin.headers,
        json={"email": f"{uuid.uuid4().hex}@example.com", "role": "RECRUITER"},
    )
    assert response.status_code == 201
    [(_, args)] = enqueued
    enqueued.clear()
    with tenant_session(admin.tenant_id) as session:
        session.execute(
            text(
                "UPDATE email_messages SET enqueued_at = enqueued_at - interval '11 minutes',"
                "  attempts = :attempts"
            ),
            {"attempts": attempts},
        )
    return admin, args


async def test_stuck_email_is_enqueued_again_once_in_its_own_tenant(
    client: AsyncClient, enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    a, a_args = await stuck_email(client, enqueued)
    b, b_args = await stuck_email(client, enqueued)

    for _ in range(2):
        sweep_tenant(a)
        sweep_tenant(b)

    assert sorted(enqueued) == sorted(
        [("emails.send_email", a_args), ("emails.send_email", b_args)]
    )


async def test_email_still_stuck_after_three_redeliveries_fails_with_its_token_masked(
    client: AsyncClient, enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    admin, _ = await stuck_email(client, enqueued, attempts=4)

    sweep_tenant(admin)

    assert enqueued == []
    with tenant_session(admin.tenant_id) as session:
        email = session.execute(text("SELECT status, body FROM email_messages")).one()
    assert email.status == "FAILED"
    assert "token=[redacted]" in email.body


def test_active_tenant_ids_is_the_only_way_for_ats_app_to_list_tenants() -> None:
    with sync_engine().connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM tenants")) == 0  # RLS: no context, no row
        assert conn.scalar(text("SELECT count(*) FROM active_tenant_ids()")) > 0
        grants = conn.execute(
            text(
                "SELECT p.prosecdef, pg_get_userbyid(p.proowner),"
                "  has_function_privilege('ats_app', p.oid, 'EXECUTE'),"
                "  has_function_privilege('public', p.oid, 'EXECUTE')"
                " FROM pg_proc p WHERE p.proname = 'active_tenant_ids'"
            )
        ).one()
    assert tuple(grants) == (True, "ats_owner", True, False)
