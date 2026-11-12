"""End-to-end tests for AI retry/backoff, circuit breaker degraded mode, and manual retry APIs."""

from __future__ import annotations

import io
import os
import time
import uuid
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

import httpx
import openai
import pytest
import redis as redis_lib
from celery.exceptions import Retry
from httpx import AsyncClient
from sqlalchemy import text

from app import ai, jobs, scoring_runs, storage, uploads
from app.auth import _access_token, _redis
from app.db import tenant_session
from smart_ats_scoring.embedding import EmbeddingResult
from smart_ats_scoring.llm import LlmResult, UnusableResponse, Usage
from tests.test_tenancy import owner_engine

pytestmark = pytest.mark.usefixtures("database", "redis")

LLM_MODEL = "gpt-5-mini"
EMBEDDING_MODEL = "text-embedding-3-small"

PARSED_JOB = {
    "title": "Backend Engineer",
    "level": "MID",
    "skills": [{"name": "Python", "must_have": True}],
    "min_years_experience": 2,
    "education": "CS",
    "responsibilities": ["Build APIs"],
    "work_mode": "HYBRID",
    "salary_range": None,
    "department": "Engineering",
    "location": "HCMC",
}

PARSED_CV = {
    "contact": {
        "full_name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": None,
        "links": [],
    },
    "work_history": [
        {
            "company": "Analytical",
            "title": "Engineer",
            "start": "2021-01",
            "end": "2024-01",
            "responsibilities": ["Python"],
            "achievements": ["Built API"],
        }
    ],
    "skills": {"hard": ["Python"], "soft": [], "tools": [], "languages": []},
    "education": [{"institution": "UIT", "degree": "BS", "start": "2017", "end": "2021"}],
    "certifications": [],
    "anomalies": [],
}

SCORED_REPORT = {
    "technical": {"evidence": ["Python"], "reason": "Matches Python.", "grade": 5},
    "soft_skills": {"evidence": ["Built API"], "reason": "Clear work.", "grade": 4},
    "experience": {"evidence": ["2021-01 to 2024-01"], "reason": "3 years.", "grade": 4},
    "strengths": [{"text": "Strong Python.", "evidence": ["Python"]}],
    "gaps": [{"text": "None noted.", "evidence": ["2021-01"]}],
    "recommendations": [{"text": "Proceed.", "evidence": ["Built API"]}],
}


@dataclass
class User:
    id: uuid.UUID
    tenant_id: uuid.UUID
    headers: dict[str, str]


@pytest.fixture(autouse=True)
async def _clean_breaker() -> None:
    await _redis().delete(*ai.breaker_keys())


@pytest.fixture(autouse=True)
def objects(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    store: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "put", lambda k, data, ct: store.__setitem__(k, data))
    monkeypatch.setattr(storage, "get", lambda k: store[k])
    monkeypatch.setattr(storage, "delete", lambda k: store.pop(k, None))
    return store


@pytest.fixture(autouse=True)
def enqueued(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[tuple[str, ...]]]:
    sent: dict[str, list[tuple[str, ...]]] = {
        "jobs.parse": [],
        "uploads.parse_cv": [],
        "scoring_runs.score_application": [],
    }
    monkeypatch.setattr(jobs.parse, "delay", lambda *a: sent["jobs.parse"].append(a))
    monkeypatch.setattr(uploads.parse_cv, "delay", lambda *a: sent["uploads.parse_cv"].append(a))
    monkeypatch.setattr(
        scoring_runs.score_application,
        "delay",
        lambda *a: sent["scoring_runs.score_application"].append(a),
    )
    return sent


def _docx(body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr(
            "word/document.xml",
            "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
            f"<w:body><w:p><w:r><w:t>{body}</w:t></w:r></w:p></w:body></w:document>",
        )
    return buf.getvalue()


def _transient_exc(code: int = 503) -> openai.APIStatusError:
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    resp = httpx.Response(code, request=req)
    return openai.APIStatusError("transient", response=cast(Any, resp), body=None)


def _make_user(role: str = "RECRUITER", tenant_id: uuid.UUID | None = None) -> User:
    with owner_engine().begin() as conn:
        tid = (
            tenant_id
            or conn.execute(
                text("INSERT INTO tenants (slug, name) VALUES (:slug, 'Tenant') RETURNING id"),
                {"slug": f"t-{uuid.uuid4().hex[:8]}"},
            ).scalar_one()
        )
        uid = conn.execute(
            text(
                "INSERT INTO users (tenant_id, email, full_name, password_hash, role)"
                " VALUES (:tid, :email, 'Test User', 'x', :role) RETURNING id"
            ),
            {"tid": tid, "email": f"{uuid.uuid4().hex[:8]}@example.com", "role": role},
        ).scalar_one()
    token = _access_token(uid, tid, role)
    return User(uid, tid, {"Authorization": f"Bearer {token}"})


class _ScriptedLlm:
    def __init__(self, outcomes: list[dict[str, Any] | Exception], model: str = LLM_MODEL) -> None:
        self._outcomes = list(outcomes)
        self.model = model
        self.calls = 0

    def structured(
        self,
        system: str,
        user: str,
        name: str,
        schema: dict[str, Any],
        temperature: float | None = None,
    ) -> LlmResult:
        _ = system, user, name, schema, temperature
        self.calls += 1
        outcome = self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return LlmResult(outcome, Usage(self.model, 100, 0, 50))


class _FakeEmbedder:
    model = EMBEDDING_MODEL

    def embed(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult([[1.0] for _ in texts], Usage(self.model, 10, 0, 0))


async def _create_job(client: AsyncClient, user: User) -> str:
    resp = await client.post(
        "/api/jobs",
        headers=user.headers,
        data={"title": "Placeholder", "level": "MID"},
        files={"jd": ("jd.docx", _docx("Need Python developer with 2 years experience"))},
    )
    assert resp.status_code == 202
    return cast(str, resp.json()["id"])


async def _setup_scored_job(
    client: AsyncClient,
    user: User,
    enqueued: dict[str, list[tuple[str, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, str, str]:
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", LLM_MODEL)
    monkeypatch.setenv("LLM_REASONING_MODEL", LLM_MODEL)
    monkeypatch.setenv("EMBEDDING_MODEL", EMBEDDING_MODEL)
    monkeypatch.setattr(jobs, "llm_from_env", lambda m, **_: _ScriptedLlm([PARSED_JOB]))
    monkeypatch.setattr(uploads, "llm_from_env", lambda m, **_: _ScriptedLlm([PARSED_CV]))
    monkeypatch.setattr(scoring_runs, "embedder_from_env", lambda m, **_: _FakeEmbedder())

    job_id = await _create_job(client, user)
    jobs.parse.apply(args=enqueued["jobs.parse"].pop(0)).get()
    confirmed = await client.put(
        f"/api/jobs/{job_id}/criteria",
        headers=user.headers,
        json={
            "title": "Backend Engineer",
            "level": "MID",
            "criteria": {
                "skills": [{"name": "Python", "must_have": True}],
                "min_years_experience": 2,
                "education": "CS",
                "responsibilities": ["Build APIs"],
                "salary_range": None,
            },
            "weights": {"technical": 55, "soft_skills": 15, "experience": 30},
        },
    )
    assert confirmed.status_code == 200

    up = await client.post(
        f"/api/jobs/{job_id}/uploads",
        headers=user.headers,
        files={"files": ("cv.docx", _docx("Ada Lovelace ada@example.com Python engineer"))},
    )
    assert up.status_code == 202
    uploads.parse_cv.apply(args=enqueued["uploads.parse_cv"].pop(0)).get()
    apps = (await client.get(f"/api/jobs/{job_id}/applications", headers=user.headers)).json()
    run = await client.post(f"/api/jobs/{job_id}/scoring-runs", headers=user.headers)
    assert run.status_code == 202
    return job_id, run.json()["run_id"], apps[0]["id"]


async def test_transient_retry_then_succeed_across_all_three_tasks_without_duplicate_usage(
    client: AsyncClient,
    enqueued: dict[str, list[tuple[str, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _make_user()
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", LLM_MODEL)
    monkeypatch.setenv("LLM_REASONING_MODEL", LLM_MODEL)
    monkeypatch.setenv("EMBEDDING_MODEL", EMBEDDING_MODEL)

    countdowns: list[float] = []

    def _spy_retry(task: Any) -> Any:
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            if "countdown" in kwargs:
                countdowns.append(kwargs["countdown"])
            return task._orig_retry(*args, **kwargs)

        return _wrapped

    for task in (jobs.parse, uploads.parse_cv, scoring_runs.score_application):
        monkeypatch.setattr(task, "_orig_retry", task.retry, raising=False)
        monkeypatch.setattr(task, "retry", _spy_retry(task))

    # 1. jobs.parse: 429 -> retry (5s) -> succeed, 1 usage row.
    job_llm = _ScriptedLlm([_transient_exc(429), PARSED_JOB])
    monkeypatch.setattr(jobs, "llm_from_env", lambda m, **_: job_llm)
    job_id = await _create_job(client, user)
    jobs.parse.apply(args=enqueued["jobs.parse"].pop(0)).get()
    assert countdowns == [5]
    assert job_llm.calls == 2
    assert (await client.get(f"/api/jobs/{job_id}", headers=user.headers)).json()[
        "parse_status"
    ] == "SUCCEEDED"

    # 2. uploads.parse_cv: 429 -> retry (5s) -> succeed, 1 CV_PARSE usage row.
    await client.put(
        f"/api/jobs/{job_id}/criteria",
        headers=user.headers,
        json={
            "title": "Backend Engineer",
            "level": "MID",
            "criteria": {
                "skills": [{"name": "Python", "must_have": True}],
                "min_years_experience": 2,
                "education": "CS",
                "responsibilities": ["Build APIs"],
                "salary_range": None,
            },
            "weights": {"technical": 55, "soft_skills": 15, "experience": 30},
        },
    )
    upload_llm = _ScriptedLlm([_transient_exc(429), PARSED_CV])
    monkeypatch.setattr(uploads, "llm_from_env", lambda m, **_: upload_llm)
    await client.post(
        f"/api/jobs/{job_id}/uploads",
        headers=user.headers,
        files={"files": ("cv.docx", _docx("Ada Lovelace ada@example.com Python"))},
    )
    uploads.parse_cv.apply(args=enqueued["uploads.parse_cv"].pop(0)).get()
    assert countdowns == [5, 5]
    assert upload_llm.calls == 2

    # 3. scoring_runs.score_application: 503 -> rollback EMBEDDING + retry -> succeed
    #    (1 EMBEDDING + 1 SCORING).
    scoring_llm = _ScriptedLlm([_transient_exc(503), SCORED_REPORT])
    monkeypatch.setattr(scoring_runs, "llm_from_env", lambda m, **_: scoring_llm)
    monkeypatch.setattr(scoring_runs, "embedder_from_env", lambda m, **_: _FakeEmbedder())
    await client.post(f"/api/jobs/{job_id}/scoring-runs", headers=user.headers)
    scoring_runs.score_application.apply(
        args=enqueued["scoring_runs.score_application"].pop(0)
    ).get()
    assert countdowns == [5, 5, 5]
    assert scoring_llm.calls == 2
    latest = (
        await client.get(f"/api/jobs/{job_id}/scoring-runs/latest", headers=user.headers)
    ).json()
    assert latest["status"] == "COMPLETED"
    assert latest["results"][0]["status"] == "SCORED"

    with tenant_session(user.tenant_id) as session:
        counts: dict[str, int] = dict(
            cast(
                Any,
                session.execute(
                    text("SELECT feature, count(*) FROM ai_usage_entries GROUP BY feature")
                ).all(),
            )
        )
    assert counts == {"JOB_PARSE": 1, "CV_PARSE": 1, "EMBEDDING": 1, "SCORING": 1}


async def test_exhausted_transient_fails_with_llm_unavailable_and_deterministic_does_not_retry(
    client: AsyncClient,
    enqueued: dict[str, list[tuple[str, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _make_user()
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", LLM_MODEL)

    countdowns: list[float] = []
    monkeypatch.setattr(jobs.parse, "_orig_retry", jobs.parse.retry, raising=False)

    def _spy_retry(*args: Any, **kwargs: Any) -> Retry:
        countdowns.append(kwargs["countdown"])
        return cast(Retry, jobs.parse._orig_retry(*args, **kwargs))

    monkeypatch.setattr(jobs.parse, "retry", _spy_retry)

    # Persistent 503 (> 3 retries) triggers backoff 5s, 15s, 60s then FAILED with LLM_UNAVAILABLE.
    failing_llm = _ScriptedLlm([_transient_exc(503)])
    monkeypatch.setattr(jobs, "llm_from_env", lambda m, **_: failing_llm)
    job_id = await _create_job(client, user)
    jobs.parse.apply(args=enqueued["jobs.parse"].pop(0)).get()
    assert countdowns == [5, 15, 60]
    assert failing_llm.calls == 4
    job_json = (await client.get(f"/api/jobs/{job_id}", headers=user.headers)).json()
    assert job_json["parse_status"] == "FAILED"
    assert job_json["parse_error"] == "LLM_UNAVAILABLE"

    # UnusableResponse (schema error) fails immediately without retrying and bills once.
    countdowns.clear()
    monkeypatch.setattr(
        jobs,
        "llm_from_env",
        lambda m, **_: _ScriptedLlm([UnusableResponse("bad json", Usage(LLM_MODEL, 50, 0, 10))]),
    )
    bad_job_id = await _create_job(client, user)
    jobs.parse.apply(args=enqueued["jobs.parse"].pop(0)).get()
    assert countdowns == []
    bad_json = (await client.get(f"/api/jobs/{bad_job_id}", headers=user.headers)).json()
    assert bad_json["parse_status"] == "FAILED"
    assert bad_json["parse_error"] == "PARSE_FAILED"


async def test_circuit_breaker_degraded_mode_reschedules_and_recovers_on_probe(
    client: AsyncClient,
    enqueued: dict[str, list[tuple[str, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _make_user()
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", LLM_MODEL)
    monkeypatch.setattr(jobs, "llm_from_env", lambda m, **_: _ScriptedLlm([_transient_exc(503)]))

    # Trigger 5+ consecutive transient errors within 1 minute so Redis breaker opens.
    await _create_job(client, user)
    jobs.parse.apply(args=enqueued["jobs.parse"].pop(0)).get()
    await _create_job(client, user)
    jobs.parse.apply(args=enqueued["jobs.parse"].pop(0)).get()

    status_open = await client.get("/api/ai/status", headers=user.headers)
    assert status_open.status_code == 200
    assert status_open.json() == {"degraded": True}

    # New LLM tasks are rescheduled without calling the model and remain PENDING.
    rescheduled: list[dict[str, Any]] = []
    monkeypatch.setattr(jobs.parse, "apply_async", lambda **kw: rescheduled.append(kw))
    recovered_llm = _ScriptedLlm([PARSED_JOB])
    monkeypatch.setattr(jobs, "llm_from_env", lambda m, **_: recovered_llm)
    j3 = await _create_job(client, user)
    res3 = jobs.parse.apply(args=enqueued["jobs.parse"].pop(0))
    assert res3.state == "IGNORED"
    assert recovered_llm.calls == 0
    assert len(rescheduled) == 1
    assert (await client.get(f"/api/jobs/{j3}", headers=user.headers)).json()[
        "parse_status"
    ] == "PENDING"

    # Non-AI features continue functioning normally while degraded.
    assert (await client.get("/api/jobs", headers=user.headers)).status_code == 200

    # Expire open_until in Redis so next task becomes half-open probe; succeeding closes breaker.
    _, open_key, _ = ai.breaker_keys()
    sync_r = redis_lib.Redis.from_url(os.environ["REDIS_URL"])
    sync_r.set(open_key, str(time.time() - 1.0))
    jobs.parse.apply(args=rescheduled.pop(0)["args"]).get()
    assert recovered_llm.calls == 1
    assert (await client.get(f"/api/jobs/{j3}", headers=user.headers)).json()[
        "parse_status"
    ] == "SUCCEEDED"
    status_closed = await client.get("/api/ai/status", headers=user.headers)
    assert status_closed.json() == {"degraded": False}


async def test_manual_retry_endpoints_permissions_validation_and_reexecution(
    client: AsyncClient,
    enqueued: dict[str, list[tuple[str, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recruiter = _make_user("RECRUITER")
    reviewer = _make_user("REVIEWER", tenant_id=recruiter.tenant_id)
    other_tenant = _make_user("RECRUITER")

    # 1. Job parse failure (LLM_UNAVAILABLE) -> manual retry -> succeeds.
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", LLM_MODEL)
    monkeypatch.setattr(jobs, "llm_from_env", lambda m, **_: _ScriptedLlm([_transient_exc(503)]))
    failed_job_id = await _create_job(client, recruiter)
    jobs.parse.apply(args=enqueued["jobs.parse"].pop(0)).get()

    assert (
        await client.post(f"/api/jobs/{failed_job_id}/parse/retry", headers=reviewer.headers)
    ).status_code == 403
    assert (
        await client.post(f"/api/jobs/{failed_job_id}/parse/retry", headers=other_tenant.headers)
    ).status_code == 404

    retry_job = await client.post(
        f"/api/jobs/{failed_job_id}/parse/retry", headers=recruiter.headers
    )
    assert retry_job.status_code == 202
    assert retry_job.json()["parse_status"] == "PENDING"
    assert (
        await client.post(f"/api/jobs/{failed_job_id}/parse/retry", headers=recruiter.headers)
    ).status_code == 409

    # Recovery run.
    await _redis().delete(*ai.breaker_keys())
    monkeypatch.setattr(jobs, "llm_from_env", lambda m, **_: _ScriptedLlm([PARSED_JOB]))
    jobs.parse.apply(args=enqueued["jobs.parse"].pop(0)).get()
    assert (await client.get(f"/api/jobs/{failed_job_id}", headers=recruiter.headers)).json()[
        "parse_status"
    ] == "SUCCEEDED"

    # 2. Setup Job + Upload + Scoring Run and fail/retry upload item & score result cleanly.
    job_id, run_id, app_id = await _setup_scored_job(client, recruiter, enqueued, monkeypatch)

    await _redis().delete(*ai.breaker_keys())
    monkeypatch.setattr(uploads, "llm_from_env", lambda m, **_: _ScriptedLlm([_transient_exc(503)]))
    up_fail = await client.post(
        f"/api/jobs/{job_id}/uploads",
        headers=recruiter.headers,
        files={"files": ("cv2.docx", _docx("Grace Hopper grace@example.com Python"))},
    )
    assert up_fail.status_code == 202
    item_id = up_fail.json()["item_ids"][0]
    uploads.parse_cv.apply(args=enqueued["uploads.parse_cv"].pop(0)).get()
    assert (
        await client.post(
            f"/api/jobs/{job_id}/uploads/items/{item_id}/retry", headers=reviewer.headers
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/jobs/{job_id}/uploads/items/{item_id}/retry", headers=other_tenant.headers
        )
    ).status_code == 404
    await _redis().delete(*ai.breaker_keys())
    monkeypatch.setattr(uploads, "llm_from_env", lambda m, **_: _ScriptedLlm([PARSED_CV]))
    retry_up = await client.post(
        f"/api/jobs/{job_id}/uploads/items/{item_id}/retry", headers=recruiter.headers
    )
    assert retry_up.status_code == 202
    assert retry_up.json()["status"] == "PENDING"
    uploads.parse_cv.apply(args=enqueued["uploads.parse_cv"].pop(0)).get()

    await _redis().delete(*ai.breaker_keys())
    monkeypatch.setattr(
        scoring_runs, "llm_from_env", lambda m, **_: _ScriptedLlm([_transient_exc(503)])
    )
    scoring_runs.score_application.apply(
        args=enqueued["scoring_runs.score_application"].pop(0)
    ).get()
    assert (
        await client.post(
            f"/api/jobs/{job_id}/scoring-runs/{run_id}/results/{app_id}/retry",
            headers=reviewer.headers,
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/jobs/{job_id}/scoring-runs/{run_id}/results/{app_id}/retry",
            headers=other_tenant.headers,
        )
    ).status_code == 404

    # Exhausting monthly budget blocks manual retry with 402 before mutating.
    with owner_engine().begin() as conn:
        conn.execute(
            text("UPDATE tenants SET ai_budget_monthly_usd = :b WHERE id = :id"),
            {"b": Decimal("0"), "id": recruiter.tenant_id},
        )
    over_budget = await client.post(
        f"/api/jobs/{job_id}/scoring-runs/{run_id}/results/{app_id}/retry",
        headers=recruiter.headers,
    )
    assert over_budget.status_code == 402
    with owner_engine().begin() as conn:
        conn.execute(
            text("UPDATE tenants SET ai_budget_monthly_usd = NULL WHERE id = :id"),
            {"id": recruiter.tenant_id},
        )

    await _redis().delete(*ai.breaker_keys())
    monkeypatch.setattr(scoring_runs, "llm_from_env", lambda m, **_: _ScriptedLlm([SCORED_REPORT]))
    retry_score = await client.post(
        f"/api/jobs/{job_id}/scoring-runs/{run_id}/results/{app_id}/retry",
        headers=recruiter.headers,
    )
    assert retry_score.status_code == 202
    assert retry_score.json()["status"] == "PENDING"
    scoring_runs.score_application.apply(
        args=enqueued["scoring_runs.score_application"].pop(0)
    ).get()
    latest = (
        await client.get(f"/api/jobs/{job_id}/scoring-runs/latest", headers=recruiter.headers)
    ).json()
    assert latest["status"] == "COMPLETED"
    assert latest["results"][0]["status"] == "SCORED"
