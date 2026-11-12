"""AI Usage Ledger, pre-enqueue budget checks, usage API and LLM concurrency semaphore (FR-C1.4)."""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any

import pytest
import redis as redis_lib
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app import apply, jobs, scoring_runs, storage, uploads
from app.db import tenant_session
from app.main import app
from smart_ats_scoring import pricing
from smart_ats_scoring.embedding import EmbeddingResult
from smart_ats_scoring.llm import LlmResult, Usage
from tests.test_jobs import JD, PARSED, FakeLlm, make_user
from tests.test_scoring_runs import (
    EMBEDDING_MODEL,
    MODEL,
    SCORED,
    add_application,
    calibrate_embedding,
    make_job,
)
from tests.test_tenancy import owner_engine
from tests.test_uploads import CV, PROFILE

pytestmark = pytest.mark.usefixtures("database", "redis")


@pytest.fixture(autouse=True)
def env_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!")
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "test-model")
    monkeypatch.setenv("LLM_REASONING_MODEL", MODEL)
    monkeypatch.setitem(
        pricing.PRICES, "test-model", pricing.Price(Decimal("2"), Decimal("0.5"), Decimal("8"))
    )
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
def enqueued(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[tuple[str, ...]]]:
    sent: dict[str, list[tuple[str, ...]]] = {
        "jobs.parse": [],
        "uploads.parse_cv": [],
        "scoring_runs.score_application": [],
        "apply.parse_cv": [],
    }
    monkeypatch.setattr(jobs.parse, "delay", lambda *a: sent["jobs.parse"].append(a))
    monkeypatch.setattr(uploads.parse_cv, "delay", lambda *a: sent["uploads.parse_cv"].append(a))
    monkeypatch.setattr(
        scoring_runs.score_application,
        "delay",
        lambda *a: sent["scoring_runs.score_application"].append(a),
    )
    monkeypatch.setattr(apply.parse_cv, "delay", lambda *a: sent["apply.parse_cv"].append(a))
    return sent


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def set_tenant_limits(
    tenant_id: uuid.UUID,
    *,
    budget_usd: Decimal | None = None,
    max_concurrency: int | None = None,
) -> None:
    with owner_engine().begin() as conn:
        if budget_usd is not None:
            conn.execute(
                text("UPDATE tenants SET ai_budget_monthly_usd = :b WHERE id = :id"),
                {"b": budget_usd, "id": tenant_id},
            )
        if max_concurrency is not None:
            conn.execute(
                text("UPDATE tenants SET max_llm_concurrency = :c WHERE id = :id"),
                {"c": max_concurrency, "id": tenant_id},
            )


def insert_usage_entry(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    feature: str,
    cost_usd: Decimal,
    *,
    created_at_sql: str = "now()",
    model: str = "gpt-6-luna",
) -> None:
    with tenant_session(tenant_id) as session:
        session.execute(
            text(
                "INSERT INTO ai_usage_entries (tenant_id, user_id, feature, model,"
                "  input_tokens, output_tokens, cached_tokens, cost_usd, created_at)"
                " VALUES (:tenant_id, :user_id, :feature, :model, 100, 50, 0, :cost,"
                f" {created_at_sql})"
            ),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "feature": feature,
                "model": model,
                "cost": cost_usd,
            },
        )


def tenant_count(tenant_id: uuid.UUID, table: str) -> int:
    with tenant_session(tenant_id) as session:
        return int(session.scalar(text(f"SELECT count(*) FROM {table}")) or 0)


async def test_budget_exceeded_uses_defaults_and_rejects_all_ai_enqueue_endpoints_with_402(
    client: AsyncClient,
    objects: dict[str, bytes],
    enqueued: dict[str, list[tuple[str, ...]]],
) -> None:
    from app import usage

    recruiter = make_user("RECRUITER")
    # Budget allows nothing beyond $0.00 when defaults apply.
    set_tenant_limits(recruiter.tenant_id, budget_usd=Decimal("0.00"))

    # 1. POST /api/jobs (JOB_PARSE) -> 402, zero rows, zero objects, zero tasks.
    r_job = await client.post("/api/jobs", headers=recruiter.headers, data={"text": JD})
    assert r_job.status_code == 402
    assert r_job.json()["detail"]["code"] == "AI_BUDGET_EXCEEDED"
    assert r_job.json()["detail"]["message"]
    assert tenant_count(recruiter.tenant_id, "jobs") == 0
    assert objects == {}
    assert enqueued["jobs.parse"] == []

    # Prepare a confirmed job with 1 application for upload and scoring tests.
    set_tenant_limits(recruiter.tenant_id, budget_usd=Decimal("10.00"))
    job_id = make_job(recruiter, objects, confirmed=True)
    add_application(recruiter, objects, job_id)
    stored_before = dict(objects)

    # Set budget strictly below the default cost of 2 CV_PARSE calls (numeric(10, 2)).
    default_two_cvs = usage.DEFAULT_COST_PER_CALL_USD["CV_PARSE"] * 2
    set_tenant_limits(
        recruiter.tenant_id,
        budget_usd=(
            (default_two_cvs - Decimal("0.000001")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            if default_two_cvs > Decimal("0.00")
            else Decimal("0.00")
        ),
    )

    # 2. POST /api/jobs/{job_id}/uploads -> 402, zero batch/item rows, zero new objects.
    r_upload = await client.post(
        f"/api/jobs/{job_id}/uploads",
        headers=recruiter.headers,
        files=[("files", ("a.docx", CV)), ("files", ("b.docx", CV))],
        data={"consent_confirmed": "true"},
    )
    assert r_upload.status_code == 402
    assert r_upload.json()["detail"]["code"] == "AI_BUDGET_EXCEEDED"
    assert tenant_count(recruiter.tenant_id, "upload_batches") == 0
    assert tenant_count(recruiter.tenant_id, "upload_batch_items") == 0
    assert objects == stored_before
    assert enqueued["uploads.parse_cv"] == []

    # 3. POST /api/jobs/{job_id}/scoring-runs -> 402, zero scoring_runs/score_results rows.
    set_tenant_limits(recruiter.tenant_id, budget_usd=Decimal("0.00"))
    r_score = await client.post(f"/api/jobs/{job_id}/scoring-runs", headers=recruiter.headers)
    assert r_score.status_code == 402
    assert r_score.json()["detail"]["code"] == "AI_BUDGET_EXCEEDED"
    assert tenant_count(recruiter.tenant_id, "scoring_runs") == 0
    assert tenant_count(recruiter.tenant_id, "score_results") == 0
    assert enqueued["scoring_runs.score_application"] == []

    # 4. POST /api/apply/{slug} -> 402, zero new candidates/cvs/applications/emails/tasks.
    slug = f"pub-{uuid.uuid4().hex[:8]}"
    with tenant_session(recruiter.tenant_id) as session:
        session.execute(
            text(
                "UPDATE jobs SET status = 'PUBLISHED', public_apply_enabled = true,"
                " public_slug = :slug WHERE id = :id"
            ),
            {"slug": slug, "id": job_id},
        )
    cand_before = tenant_count(recruiter.tenant_id, "candidates")
    app_before = tenant_count(recruiter.tenant_id, "applications")
    cv_before = tenant_count(recruiter.tenant_id, "cv_documents")
    email_before = tenant_count(recruiter.tenant_id, "email_messages")
    r_apply = await client.post(
        f"/api/apply/{slug}",
        data={
            "full_name": "Nguyen Van B",
            "email": "b@example.com",
            "consent": "true",
        },
        files={"file": ("cv.docx", CV)},
    )
    assert r_apply.status_code == 402
    assert r_apply.json()["detail"]["code"] == "AI_BUDGET_EXCEEDED"
    assert tenant_count(recruiter.tenant_id, "candidates") == cand_before
    assert tenant_count(recruiter.tenant_id, "applications") == app_before
    assert tenant_count(recruiter.tenant_id, "cv_documents") == cv_before
    assert tenant_count(recruiter.tenant_id, "email_messages") == email_before
    assert objects == stored_before
    assert enqueued["apply.parse_cv"] == []


async def test_budget_check_allows_exact_match_and_estimates_from_30_day_history_and_utc_month(
    client: AsyncClient,
    objects: dict[str, bytes],
    enqueued: dict[str, list[tuple[str, ...]]],
) -> None:
    recruiter = make_user("RECRUITER")
    other_tenant_user = make_user("RECRUITER")

    # History from other tenant or > 30 days ago must not count in 30d avg or UTC spend.
    insert_usage_entry(
        other_tenant_user.tenant_id, other_tenant_user.id, "JOB_PARSE", Decimal("9.00")
    )
    insert_usage_entry(
        recruiter.tenant_id,
        recruiter.id,
        "JOB_PARSE",
        Decimal("50.00"),
        created_at_sql="now() - interval '35 days'",
    )
    # Different feature in last 30d must not pollute JOB_PARSE avg; place 1s before UTC month
    # start so it stays within 30d without counting in current UTC month spend.
    prev_month_sql = (
        "(date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') - interval '1 second'"
    )
    insert_usage_entry(
        recruiter.tenant_id,
        recruiter.id,
        "CV_PARSE",
        Decimal("9.50"),
        created_at_sql=prev_month_sql,
    )
    # Historical JOB_PARSE inside last 30d & in previous UTC month: avg = ($1 + $3) / 2 = $2.00.
    insert_usage_entry(
        recruiter.tenant_id,
        recruiter.id,
        "JOB_PARSE",
        Decimal("1.00"),
        created_at_sql=prev_month_sql,
    )
    insert_usage_entry(
        recruiter.tenant_id,
        recruiter.id,
        "JOB_PARSE",
        Decimal("3.00"),
        created_at_sql=prev_month_sql,
    )
    # Current UTC month spend: $5.00 of another feature (INTERVIEW_Q).
    insert_usage_entry(
        recruiter.tenant_id,
        recruiter.id,
        "INTERVIEW_Q",
        Decimal("5.00"),
        created_at_sql=(
            "(date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')"
            " + interval '1 second'"
        ),
    )

    # Current UTC month spent = $5.00; estimated JOB_PARSE = $2.00 -> total $7.00.
    # Budget = $6.99 -> rejected with 402!
    set_tenant_limits(recruiter.tenant_id, budget_usd=Decimal("6.99"))
    refused = await client.post("/api/jobs", headers=recruiter.headers, data={"text": JD})
    assert refused.status_code == 402
    assert refused.json()["detail"]["code"] == "AI_BUDGET_EXCEEDED"
    assert tenant_count(recruiter.tenant_id, "jobs") == 0

    # Budget = $7.00 -> exact boundary allowed (202)!
    set_tenant_limits(recruiter.tenant_id, budget_usd=Decimal("7.00"))
    allowed = await client.post("/api/jobs", headers=recruiter.headers, data={"text": JD})
    assert allowed.status_code == 202
    assert len(enqueued["jobs.parse"]) == 1

    # Also verify CV_PARSE multi-call multiplication: avg CV_PARSE = $9.50 -> 2 CVs = $19.00.
    # Current spent $5.00 + 2 * $9.50 = $24.00.
    job_id = make_job(recruiter, objects, confirmed=True)
    set_tenant_limits(recruiter.tenant_id, budget_usd=Decimal("23.99"))
    refused_batch = await client.post(
        f"/api/jobs/{job_id}/uploads",
        headers=recruiter.headers,
        files=[("files", ("a.docx", CV)), ("files", ("b.docx", CV))],
        data={"consent_confirmed": "true"},
    )
    assert refused_batch.status_code == 402

    set_tenant_limits(recruiter.tenant_id, budget_usd=Decimal("24.00"))
    allowed_batch = await client.post(
        f"/api/jobs/{job_id}/uploads",
        headers=recruiter.headers,
        files=[("files", ("a.docx", CV)), ("files", ("b.docx", CV))],
        data={"consent_confirmed": "true"},
    )
    assert allowed_batch.status_code == 202
    assert len(enqueued["uploads.parse_cv"]) == 2


async def test_get_usage_roles_and_80_percent_warning_and_month_filter(
    client: AsyncClient,
) -> None:
    admin = make_user("COMPANY_ADMIN")
    recruiter1 = make_user("RECRUITER", admin.tenant_id)
    recruiter2 = make_user("RECRUITER", admin.tenant_id)
    reviewer = make_user("REVIEWER", admin.tenant_id)
    set_tenant_limits(admin.tenant_id, budget_usd=Decimal("10.00"))

    now_month = datetime.now(UTC).strftime("%Y-%m")
    # Entries in current UTC month:
    # recruiter1: 2 JOB_PARSE ($1.50 + $0.50 = $2.00), 1 SCORING ($3.00) -> total $5.00
    insert_usage_entry(admin.tenant_id, recruiter1.id, "JOB_PARSE", Decimal("1.50"))
    insert_usage_entry(admin.tenant_id, recruiter1.id, "JOB_PARSE", Decimal("0.50"))
    insert_usage_entry(admin.tenant_id, recruiter1.id, "SCORING", Decimal("3.00"))
    # recruiter2: 1 CV_PARSE ($2.00)
    insert_usage_entry(admin.tenant_id, recruiter2.id, "CV_PARSE", Decimal("2.00"))
    # public apply (user_id IS NULL): 1 CV_PARSE ($0.99) -> tenant total = $7.99 (< 80%)
    insert_usage_entry(admin.tenant_id, None, "CV_PARSE", Decimal("0.99"))
    # Old entry in 2025-01 (excluded from current month, included when ?month=2025-01)
    insert_usage_entry(
        admin.tenant_id,
        recruiter1.id,
        "AGENT",
        Decimal("4.25"),
        created_at_sql="TIMESTAMPTZ '2025-01-15T12:00:00Z'",
    )

    # Reviewer -> 403
    assert (await client.get("/api/usage", headers=reviewer.headers)).status_code == 403

    # Invalid month -> 422
    assert (await client.get("/api/usage?month=2026-13", headers=admin.headers)).status_code == 422

    # Admin below 80% ($7.99 / $10.00 = 0.799): warning False
    res_admin = await client.get("/api/usage", headers=admin.headers)
    assert res_admin.status_code == 200
    body_admin = res_admin.json()
    assert body_admin["month"] == now_month
    assert body_admin["scope"] == "TENANT"
    assert body_admin["budget_usd"] == pytest.approx(10.0)
    assert body_admin["total_cost_usd"] == pytest.approx(7.99)
    assert body_admin["total_calls"] == 5
    assert body_admin["usage_ratio"] == pytest.approx(0.799)
    assert body_admin["budget_warning"] is False
    assert sorted(body_admin["features"], key=lambda f: f["feature"]) == [
        {"feature": "CV_PARSE", "calls": 2, "cost_usd": pytest.approx(2.99)},
        {"feature": "JOB_PARSE", "calls": 2, "cost_usd": pytest.approx(2.0)},
        {"feature": "SCORING", "calls": 1, "cost_usd": pytest.approx(3.0)},
    ]

    # Exact 80% threshold ($8.00 / $10.00 = 0.8): warning True for Admin
    insert_usage_entry(admin.tenant_id, None, "EMBEDDING", Decimal("0.01"))
    res_warn = await client.get(f"/api/usage?month={now_month}", headers=admin.headers)
    assert res_warn.status_code == 200
    warn_body = res_warn.json()
    assert warn_body["total_cost_usd"] == pytest.approx(8.0)
    assert warn_body["usage_ratio"] == pytest.approx(0.8)
    assert warn_body["budget_warning"] is True

    # Recruiter1 sees ONLY own entries ($5.00), never tenant's 80% warning
    res_rec = await client.get("/api/usage", headers=recruiter1.headers)
    assert res_rec.status_code == 200
    rec_body = res_rec.json()
    assert rec_body["scope"] == "USER"
    assert rec_body["total_cost_usd"] == pytest.approx(5.0)
    assert rec_body["total_calls"] == 3
    assert rec_body["budget_usd"] == pytest.approx(10.0)
    assert rec_body["usage_ratio"] == pytest.approx(0.5)
    assert rec_body["budget_warning"] is False
    assert sorted(rec_body["features"], key=lambda f: f["feature"]) == [
        {"feature": "JOB_PARSE", "calls": 2, "cost_usd": pytest.approx(2.0)},
        {"feature": "SCORING", "calls": 1, "cost_usd": pytest.approx(3.0)},
    ]

    # Specific historical month
    res_old = await client.get("/api/usage?month=2025-01", headers=admin.headers)
    assert res_old.status_code == 200
    assert res_old.json()["total_cost_usd"] == pytest.approx(4.25)
    assert res_old.json()["features"] == [
        {"feature": "AGENT", "calls": 1, "cost_usd": pytest.approx(4.25)}
    ]


@pytest.mark.cross_tenant
async def test_get_usage_is_isolated_across_tenants(client: AsyncClient) -> None:
    admin_a = make_user("COMPANY_ADMIN")
    admin_b = make_user("COMPANY_ADMIN")
    set_tenant_limits(admin_a.tenant_id, budget_usd=Decimal("10.00"))
    set_tenant_limits(admin_b.tenant_id, budget_usd=Decimal("25.00"))
    insert_usage_entry(admin_a.tenant_id, admin_a.id, "JOB_PARSE", Decimal("8.50"))

    res_b = await client.get("/api/usage", headers=admin_b.headers)
    assert res_b.status_code == 200
    assert res_b.json()["budget_usd"] == pytest.approx(25.0)
    assert res_b.json()["total_cost_usd"] == 0.0
    assert res_b.json()["total_calls"] == 0
    assert res_b.json()["budget_warning"] is False
    assert res_b.json()["features"] == []


class BlockingLlm(FakeLlm):
    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(data)
        self.entered = threading.Event()
        self.release = threading.Event()

    def structured(self, *args: Any, **kwargs: Any) -> LlmResult:
        self.entered.set()
        self.release.wait(10)
        return super().structured(*args, **kwargs)


class CountingConcurrencyLlm(FakeLlm):
    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(data)
        self._lock = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0

    def structured(self, *args: Any, **kwargs: Any) -> LlmResult:
        with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        time.sleep(0.05)
        try:
            return super().structured(*args, **kwargs)
        finally:
            with self._lock:
                self.in_flight -= 1


async def test_llm_semaphore_reschedules_when_full_and_does_not_block_other_tenants(
    client: AsyncClient,
    objects: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_a = make_user("RECRUITER")
    tenant_b = make_user("RECRUITER")
    set_tenant_limits(tenant_a.tenant_id, max_concurrency=1)
    set_tenant_limits(tenant_b.tenant_id, max_concurrency=1)

    job_a1 = (await client.post("/api/jobs", headers=tenant_a.headers, data={"text": JD})).json()[
        "id"
    ]
    job_a2 = (await client.post("/api/jobs", headers=tenant_a.headers, data={"text": JD})).json()[
        "id"
    ]
    job_b1 = (await client.post("/api/jobs", headers=tenant_b.headers, data={"text": JD})).json()[
        "id"
    ]

    blocker = BlockingLlm(PARSED)
    fast = FakeLlm(PARSED)
    lock = threading.Lock()

    rescheduled: list[dict[str, Any]] = []
    monkeypatch.setattr(
        jobs.parse,
        "apply_async",
        lambda **kwargs: rescheduled.append(kwargs),
    )

    def pick_llm(model: str) -> FakeLlm:
        with lock:
            return blocker if not blocker.entered.is_set() else fast

    monkeypatch.setattr(jobs, "llm_from_env", pick_llm)

    t1 = threading.Thread(
        target=lambda: jobs.parse.apply(
            args=(str(tenant_a.tenant_id), job_a1, str(tenant_a.id))
        ).get()
    )
    t1.start()
    assert blocker.entered.wait(5), "task 1 never entered LLM call"

    try:
        # Tenant A task 2 sees full slot: rescheduled without LLM, row stays PENDING / attempts=1.
        res2 = jobs.parse.apply(args=(str(tenant_a.tenant_id), job_a2, str(tenant_a.id)))
        assert res2.state == "IGNORED"
        assert fast.calls == 0
        assert len(rescheduled) == 1
        assert rescheduled[0]["args"] == (str(tenant_a.tenant_id), job_a2, str(tenant_a.id))
        assert rescheduled[0]["retries"] == 0
        assert rescheduled[0]["countdown"] > 0

        with tenant_session(tenant_a.tenant_id) as session:
            row = session.execute(
                text("SELECT parse_status, parse_attempts FROM jobs WHERE id = :id"),
                {"id": job_a2},
            ).one()
            assert (row.parse_status, row.parse_attempts) == ("PENDING", 1)

        # Other tenant runs freely without being blocked by tenant A's slot!
        jobs.parse.apply(args=(str(tenant_b.tenant_id), job_b1, str(tenant_b.id))).get()
        assert fast.calls == 1
        b1 = (await client.get(f"/api/jobs/{job_b1}", headers=tenant_b.headers)).json()
        assert b1["parse_status"] == "SUCCEEDED"
    finally:
        blocker.release.set()
        t1.join(timeout=5)

    # Once task 1 released its slot, running rescheduled task 2 succeeds!
    jobs.parse.apply(args=rescheduled[0]["args"]).get()
    a2 = (await client.get(f"/api/jobs/{job_a2}", headers=tenant_a.headers)).json()
    assert a2["parse_status"] == "SUCCEEDED"


async def test_llm_semaphore_releases_slot_on_failure_and_expires_stale_leases(
    client: AsyncClient,
    objects: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import usage

    recruiter = make_user("RECRUITER")
    set_tenant_limits(recruiter.tenant_id, max_concurrency=1)

    job1 = (await client.post("/api/jobs", headers=recruiter.headers, data={"text": JD})).json()[
        "id"
    ]
    job2 = (await client.post("/api/jobs", headers=recruiter.headers, data={"text": JD})).json()[
        "id"
    ]

    class BoomLlm(FakeLlm):
        def structured(self, *args: Any, **kwargs: Any) -> LlmResult:
            raise RuntimeError("provider exploded")

    monkeypatch.setattr(jobs, "llm_from_env", lambda model: BoomLlm(PARSED))
    jobs.parse.apply(args=(str(recruiter.tenant_id), job1, str(recruiter.id))).get()
    assert (await client.get(f"/api/jobs/{job1}", headers=recruiter.headers)).json()[
        "parse_status"
    ] == "FAILED"

    # Simulate a crashed worker leaving an expired lease token in Redis.
    r = redis_lib.Redis.from_url(os.environ["REDIS_URL"])
    slot_key = usage.llm_slot_key(recruiter.tenant_id)
    r.zadd(slot_key, {"crashed-worker-token": time.time() - 5})
    r.close()

    # Next task succeeds because failed task released its slot and expired lease is evicted.
    good = FakeLlm(PARSED)
    monkeypatch.setattr(jobs, "llm_from_env", lambda model: good)
    jobs.parse.apply(args=(str(recruiter.tenant_id), job2, str(recruiter.id))).get()
    assert good.calls == 1
    assert (await client.get(f"/api/jobs/{job2}", headers=recruiter.headers)).json()[
        "parse_status"
    ] == "SUCCEEDED"


async def test_llm_semaphore_limits_concurrent_executions_for_all_llm_tasks(
    client: AsyncClient,
    objects: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recruiter = make_user("RECRUITER")
    set_tenant_limits(recruiter.tenant_id, max_concurrency=2)

    counter = CountingConcurrencyLlm(PARSED)
    monkeypatch.setattr(jobs, "llm_from_env", lambda model: counter)

    rescheduled: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        jobs.parse,
        "apply_async",
        lambda **kwargs: rescheduled.append(kwargs["args"]),
    )

    job_ids = [
        (await client.post("/api/jobs", headers=recruiter.headers, data={"text": JD})).json()["id"]
        for _ in range(4)
    ]
    threads = [
        threading.Thread(
            target=lambda jid=jid: jobs.parse.apply(
                args=(str(recruiter.tenant_id), jid, str(recruiter.id))
            ).get()
        )
        for jid in job_ids
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert counter.max_in_flight <= 2
    assert counter.calls >= 2
    # Any rescheduled tasks run cleanly after slots free up.
    for args in rescheduled:
        jobs.parse.apply(args=args).get()
    assert counter.calls == 4

    # Also verify uploads.parse_cv, scoring_runs.score_application and apply.parse_cv use slots.
    job_confirmed = make_job(recruiter, objects, confirmed=True)
    app_info = add_application(recruiter, objects, job_confirmed)
    r_up = await client.post(
        f"/api/jobs/{job_confirmed}/uploads",
        headers=recruiter.headers,
        files=[("files", ("c.docx", CV))],
        data={"consent_confirmed": "true"},
    )
    [item_id] = r_up.json()["item_ids"]
    r_sc = await client.post(f"/api/jobs/{job_confirmed}/scoring-runs", headers=recruiter.headers)
    run_id = r_sc.json()["run_id"]

    # Occupy the single slot on this tenant.
    set_tenant_limits(recruiter.tenant_id, max_concurrency=1)
    r = redis_lib.Redis.from_url(os.environ["REDIS_URL"])
    slot_key = f"llm_slots:{recruiter.tenant_id}"
    r.zadd(slot_key, {"held-token": time.time() + 60})
    try:
        up_resched: list[Any] = []
        sc_resched: list[Any] = []
        ap_resched: list[Any] = []
        monkeypatch.setattr(uploads.parse_cv, "apply_async", lambda **kw: up_resched.append(kw))
        monkeypatch.setattr(
            scoring_runs.score_application, "apply_async", lambda **kw: sc_resched.append(kw)
        )
        monkeypatch.setattr(apply.parse_cv, "apply_async", lambda **kw: ap_resched.append(kw))

        upload_llm = FakeLlm(PROFILE)
        scoring_llm = FakeLlm(SCORED, MODEL)
        monkeypatch.setattr(uploads, "llm_from_env", lambda m: upload_llm)
        monkeypatch.setattr(scoring_runs, "llm_from_env", lambda m: scoring_llm)
        monkeypatch.setattr(apply, "llm_from_env", lambda m: upload_llm)
        monkeypatch.setattr(
            scoring_runs,
            "embedder_from_env",
            lambda m: type(
                "E",
                (),
                {
                    "model": EMBEDDING_MODEL,
                    "embed": lambda self, texts: EmbeddingResult(
                        [[1.0] for _ in texts], Usage(EMBEDDING_MODEL, 10, 0, 0)
                    ),
                },
            )(),
        )

        # Insert a PENDING apply cv_document
        with tenant_session(recruiter.tenant_id) as session:
            cand_id = session.scalar(
                text(
                    "INSERT INTO candidates (tenant_id, full_name, email, consent_source,"
                    "  consent_at, last_activity_at)"
                    " VALUES (:tid, 'Apply', 'ap@example.com', 'PUBLIC_APPLY_CONSENT',"
                    "  now(), now()) RETURNING id"
                ),
                {"tid": recruiter.tenant_id},
            )
            key = f"t/{recruiter.tenant_id}/cv/ap.docx"
            objects[key] = CV
            doc_id = session.scalar(
                text(
                    "INSERT INTO cv_documents (tenant_id, candidate_id, storage_key, file_name,"
                    "  mime_type, sha256, parse_status)"
                    " VALUES (:tid, :cid, :k, 'ap.docx', 'docx', :sha, 'PENDING') RETURNING id"
                ),
                {"tid": recruiter.tenant_id, "cid": cand_id, "k": key, "sha": uuid.uuid4().hex},
            )

        assert uploads.parse_cv.apply(args=(str(recruiter.tenant_id), item_id)).state == "IGNORED"
        assert (
            scoring_runs.score_application.apply(
                args=(str(recruiter.tenant_id), run_id, app_info["id"])
            ).state
            == "IGNORED"
        )
        assert apply.parse_cv.apply(args=(str(recruiter.tenant_id), str(doc_id))).state == "IGNORED"
        assert len(up_resched) == 1
        assert len(sc_resched) == 1
        assert len(ap_resched) == 1
        assert upload_llm.calls == 0
        assert scoring_llm.calls == 0
    finally:
        r.zrem(slot_key, "held-token")
        r.close()
