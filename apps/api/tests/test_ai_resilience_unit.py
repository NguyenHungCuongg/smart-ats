"""Unit tests for LLM retry classification/backoff, circuit breaker state machine, and retry guards.

These tests run cleanly without Docker by using an in-memory Redis Lua emulator and stubbed DB
sessions so resilience invariants are verified on every local edit.
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from typing import Any, cast

import httpx
import openai
import pytest
from celery.exceptions import Ignore, Retry
from fastapi import HTTPException
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app import ai, jobs, outbox, scoring_runs, uploads, usage
from app.auth import Auth
from app.main import app


class FakeBreakerRedis:
    """Minimal in-memory Redis implementing the circuit breaker Lua scripts."""

    def __init__(self) -> None:
        self.strings: dict[str, tuple[str, float]] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.now_fn = __import__("time").time

    def _prune_expired(self, key: str) -> None:
        if key in self.strings:
            _, exp = self.strings[key]
            if self.now_fn() >= exp:
                del self.strings[key]

    def get(self, key: str) -> bytes | None:
        self._prune_expired(key)
        item = self.strings.get(key)
        return None if item is None else item[0].encode()

    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> Any:
        keys = keys_and_args[:numkeys]
        args = keys_and_args[numkeys:]
        if script is ai._ACQUIRE_BREAKER_LUA:
            open_key, probe_key = keys
            now = float(args[0])
            probe_lease = float(args[1])
            self._prune_expired(open_key)
            self._prune_expired(probe_key)
            raw = self.strings.get(open_key)
            if raw is None:
                return [b"CLOSED"]
            open_until = float(raw[0])
            if now < open_until:
                return [b"OPEN", str(open_until).encode()]
            if probe_key not in self.strings:
                self.strings[probe_key] = ("1", self.now_fn() + probe_lease)
                return [b"PROBE"]
            return [b"OPEN", str(open_until).encode()]

        if script is ai._RECORD_SUCCESS_LUA:
            failures_key, open_key, probe_key = keys
            self.zsets.pop(failures_key, None)
            self.strings.pop(open_key, None)
            self.strings.pop(probe_key, None)
            return 1

        if script is ai._RECORD_FAILURE_LUA:
            failures_key, open_key, probe_key = keys
            now = float(args[0])
            window = float(args[1])
            threshold = int(args[2])
            open_seconds = float(args[3])
            safety_ttl = float(args[4])
            member = args[5]
            self._prune_expired(open_key)
            raw = self.strings.get(open_key)
            if raw is not None and now >= float(raw[0]):
                self.strings[open_key] = (str(now + open_seconds), self.now_fn() + safety_ttl)
                self.zsets.pop(failures_key, None)
                self.strings.pop(probe_key, None)
                return 1
            cutoff = now - window
            zset = self.zsets.setdefault(failures_key, {})
            for m in [k for k, score in zset.items() if score <= cutoff]:
                del zset[m]
            zset[member] = now
            if len(zset) >= threshold:
                self.strings[open_key] = (str(now + open_seconds), self.now_fn() + safety_ttl)
                self.zsets.pop(failures_key, None)
                self.strings.pop(probe_key, None)
                return 1
            return 0

        if script is ai._RELEASE_PROBE_LUA:
            (probe_key,) = keys
            self.strings.pop(probe_key, None)
            return 1

        if script is ai._RECORD_NON_TRANSIENT_LUA:
            failures_key, probe_key = keys
            self.zsets.pop(failures_key, None)
            if args[0] == "1":
                self.strings.pop(probe_key, None)
            return 1

        raise AssertionError("Unexpected Lua script")


class FakeAsyncRedis:
    def __init__(self, sync: FakeBreakerRedis) -> None:
        self.sync = sync
        self.closed = False

    async def get(self, key: str) -> bytes | None:
        return self.sync.get(key)

    async def aclose(self) -> None:
        self.closed = True


@contextmanager
def _noop_slot(*_args: Any, **_kwargs: Any) -> Any:
    yield


def _transient_exc(code: int = 503) -> openai.APIStatusError:
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    resp = httpx.Response(code, request=req)
    return openai.APIStatusError("transient", response=cast(Any, resp), body=None)


def test_breaker_opens_on_five_consecutive_transient_errors_and_recovers_via_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = FakeBreakerRedis()
    now = [1_700_000_000.0]
    fake_redis.now_fn = lambda: now[0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    monkeypatch.setattr(usage, "_sync_redis", lambda: fake_redis)
    monkeypatch.setattr(usage, "llm_slot", _noop_slot)
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    # Circuit breaker keys must never carry tenant identifiers.
    assert all(str(tenant_id) not in key for key in ai.breaker_keys())

    # Non-transient errors do not trip the breaker even if repeated.
    for _ in range(6):
        with pytest.raises(ValueError), ai.llm_call(object(), tenant_id):
            raise ValueError("schema error")
    assert not ai.is_degraded()

    # Four transient errors followed by a success resets the consecutive count.
    for _ in range(4):
        now[0] += 1.0
        with pytest.raises(openai.APIStatusError), ai.llm_call(object(), tenant_id):
            raise _transient_exc(429)
    assert not ai.is_degraded()

    with ai.llm_call(object(), tenant_id):
        pass
    assert not ai.is_degraded()

    # Four transient errors followed by a deterministic error also resets the consecutive count,
    # so one more transient error afterwards stays closed instead of opening at 5.
    for _ in range(4):
        now[0] += 1.0
        with pytest.raises(openai.APIStatusError), ai.llm_call(object(), tenant_id):
            raise _transient_exc(503)
    now[0] += 1.0
    with pytest.raises(ValueError), ai.llm_call(object(), tenant_id):
        raise ValueError("schema error")
    now[0] += 1.0
    with pytest.raises(openai.APIStatusError), ai.llm_call(object(), tenant_id):
        raise _transient_exc(503)
    assert not ai.is_degraded()

    # Reset streak before testing window expiry cleanly.
    with ai.llm_call(object(), tenant_id):
        pass

    # Old errors beyond 60s slide out of the window.
    for _ in range(3):
        now[0] += 1.0
        with pytest.raises(openai.APIStatusError), ai.llm_call(object(), tenant_id):
            raise _transient_exc(503)
    now[0] += 65.0
    for _ in range(4):
        now[0] += 1.0
        with pytest.raises(openai.APIStatusError), ai.llm_call(object(), tenant_id):
            raise _transient_exc(503)
    assert not ai.is_degraded()

    # Reaching the 5th consecutive error inside 60s opens the breaker for 120s.
    now[0] += 1.0
    with pytest.raises(openai.APIStatusError), ai.llm_call(object(), tenant_id):
        raise _transient_exc(503)
    assert ai.is_degraded()

    # Any tenant's next LLM call skips the model and reschedules via usage.reschedule_llm_task.
    rescheduled: list[float] = []

    def _fake_reschedule(*, countdown: float = 0) -> None:
        rescheduled.append(countdown)
        raise Ignore()

    monkeypatch.setattr(usage, "reschedule_llm_task", _fake_reschedule)
    entered = False
    with pytest.raises(Ignore), ai.llm_call(object(), other_tenant_id):
        entered = True
    assert not entered
    assert len(rescheduled) == 1
    assert 110.0 <= rescheduled[0] <= 120.0

    # After 120s, degraded status ends before any probe runs, while open_key stays for probe
    # coordination; if the half-open probe fails, it immediately re-opens for 120s.
    now[0] += 121.0
    assert not ai.is_degraded()
    with pytest.raises(openai.APIStatusError), ai.llm_call(object(), tenant_id):
        raise _transient_exc(503)
    assert ai.is_degraded()
    with pytest.raises(Ignore), ai.llm_call(object(), tenant_id):
        pytest.fail("Breaker should be open immediately after a failed half-open probe")

    # After another 120s, one probe runs; concurrent calls see OPEN; probe success closes breaker.
    now[0] += 121.0
    with ai.llm_call(object(), tenant_id):
        assert fake_redis.get(ai.breaker_keys()[2]) == b"1"
        with pytest.raises(Ignore), ai.llm_call(object(), other_tenant_id):
            pytest.fail("Second caller while probe runs must reschedule instead of probing")
    assert not ai.is_degraded()


def test_breaker_releases_probe_on_task_predicate_or_deterministic_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = FakeBreakerRedis()
    now = [1_700_000_000.0]
    fake_redis.now_fn = lambda: now[0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    monkeypatch.setattr(usage, "_sync_redis", lambda: fake_redis)
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    _, open_key, probe_key = ai.breaker_keys()
    fake_redis.strings[open_key] = (str(now[0] - 1.0), now[0] + 600.0)

    # Full per-tenant slot triggers Ignore -> probe lease must be released cleanly.
    @contextmanager
    def _full_slot(*_args: Any, **_kwargs: Any) -> Any:
        raise Ignore()
        yield

    monkeypatch.setattr(usage, "llm_slot", _full_slot)
    with pytest.raises(Ignore), ai.llm_call(object(), uuid.uuid4()):
        pass
    assert fake_redis.get(probe_key) is None

    # Deterministic error during probe also releases probe lease without touching open_until.
    monkeypatch.setattr(usage, "llm_slot", _noop_slot)
    with pytest.raises(ValueError), ai.llm_call(object(), uuid.uuid4()):
        raise ValueError("corrupt payload")
    assert fake_redis.get(probe_key) is None


def test_retry_transient_error_uses_exponential_backoff_then_returns_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded_countdowns: list[int] = []

    class _FakeTask:
        def __init__(self, retries: int) -> None:
            self.request = type("Req", (), {"retries": retries})()

        def retry(self, *, exc: BaseException, countdown: int) -> Retry:
            recorded_countdowns.append(countdown)
            return Retry(exc=exc, when=countdown)

    exc = _transient_exc(429)
    for retries, expected_countdown in enumerate((5, 15, 60)):
        monkeypatch.setattr(ai, "current_task", _FakeTask(retries))
        with pytest.raises(Retry):
            ai.retry_transient_error(exc)
        assert recorded_countdowns[-1] == expected_countdown

    assert recorded_countdowns == [5, 15, 60]

    # Attempt 4 (retries == 3): exhausted, returns retryable code without scheduling retry.
    monkeypatch.setattr(ai, "current_task", _FakeTask(3))
    assert ai.retry_transient_error(exc) == "LLM_UNAVAILABLE"


async def test_ai_status_endpoint_auth_and_degraded_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_sync = FakeBreakerRedis()
    fake_async = FakeAsyncRedis(fake_sync)

    async def _fake_async_redis() -> Any:
        return fake_async

    monkeypatch.setattr(ai, "_async_redis", _fake_async_redis)
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauth = await client.get("/api/ai/status")
        assert unauth.status_code == 401

        route = next(r for r in ai.router.routes if isinstance(r, APIRoute))
        auth_dep = route.dependant.dependencies[0].call
        assert auth_dep is not None
        app.dependency_overrides[auth_dep] = lambda: Auth(
            uuid.uuid4(), uuid.uuid4(), "RECRUITER", cast(AsyncSession, object())
        )
        try:
            closed = await client.get("/api/ai/status")
            assert closed.status_code == 200
            assert closed.json() == {"degraded": False}
            assert fake_async.closed

            _, open_key, _ = ai.breaker_keys()
            fake_sync.strings[open_key] = ("9999999999", 9999999999)
            opened = await client.get("/api/ai/status")
            assert opened.status_code == 200
            assert opened.json() == {"degraded": True}

            # Once the 2-minute open window has elapsed, status stops reporting degraded even
            # before a probe clears open_key.
            fake_sync.strings[open_key] = ("1", 9999999999)
            expired = await client.get("/api/ai/status")
            assert expired.status_code == 200
            assert expired.json() == {"degraded": False}
        finally:
            app.dependency_overrides.clear()


class _Row:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)

    @property
    def _mapping(self) -> dict[str, Any]:
        return dict(self.__dict__)


class _Result:
    def __init__(self, row: _Row | None) -> None:
        self._row = row

    def one_or_none(self) -> _Row | None:
        return self._row

    def one(self) -> _Row:
        assert self._row is not None
        return self._row


class _FakeAsyncSession:
    def __init__(
        self,
        *,
        execute_results: list[_Result] | None = None,
        scalar_results: list[Any] | None = None,
    ) -> None:
        self._execute = list(execute_results or [])
        self._scalars = list(scalar_results or [])
        self.executed_sql: list[str] = []

    async def execute(self, stmt: Any, _params: Any = None) -> _Result:
        self.executed_sql.append(str(stmt))
        return self._execute.pop(0) if self._execute else _Result(None)

    async def scalar(self, stmt: Any, _params: Any = None) -> Any:
        self.executed_sql.append(str(stmt))
        return self._scalars.pop(0) if self._scalars else None


def _auth(db: Any, role: str = "RECRUITER") -> Auth:
    return Auth(uuid.uuid4(), uuid.uuid4(), role, cast(AsyncSession, db))


async def test_retry_parse_guards_and_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = uuid.uuid4()

    # Non-FAILED or non-retryable error -> 409.
    for status_val, err in [("PENDING", None), ("SUCCEEDED", None), ("FAILED", "PARSE_FAILED")]:
        db = _FakeAsyncSession(
            execute_results=[_Result(_Row(parse_status=status_val, parse_error=err))]
        )
        with pytest.raises(HTTPException) as exc:
            await jobs.retry_parse(job_id, _auth(db))
        assert exc.value.status_code == 409

    # Budget exceeded -> 402 without mutating DB or enqueueing.
    async def _budget_fail(*_args: Any, **_kwargs: Any) -> None:
        raise HTTPException(402, {"code": "AI_BUDGET_EXCEEDED"})

    monkeypatch.setattr(usage, "check_budget", _budget_fail)
    db_budget = _FakeAsyncSession(
        execute_results=[_Result(_Row(parse_status="FAILED", parse_error="LLM_UNAVAILABLE"))]
    )
    with pytest.raises(HTTPException) as exc:
        await jobs.retry_parse(job_id, _auth(db_budget))
    assert exc.value.status_code == 402
    assert len(db_budget.executed_sql) == 1

    # Happy path -> resets job to PENDING, clears parse_error, enqueues jobs.parse.
    async def _budget_ok(*_args: Any, **_kwargs: Any) -> None:
        return None

    enqueued: list[tuple[Any, tuple[Any, ...]]] = []
    monkeypatch.setattr(usage, "check_budget", _budget_ok)
    monkeypatch.setattr(
        outbox,
        "enqueue_after_commit",
        lambda _db, task, *calls: enqueued.extend((task, c) for c in calls),
    )
    expected_job = jobs.Job(
        id=job_id,
        title="Backend",
        level="MID",
        department=None,
        location=None,
        work_mode=None,
        status="DRAFT",
        parse_status="PENDING",
        parse_error=None,
        criteria=None,
        verification=None,
        weights=jobs.Weights(technical=50, soft_skills=20, experience=30),
        criteria_confirmed_at=None,
        apply_deadline=None,
        published_at=None,
        public_apply_enabled=False,
        public_slug=None,
    )

    async def _fake_get_job(_db: Any, _jid: uuid.UUID) -> jobs.Job:
        return expected_job

    monkeypatch.setattr(jobs, "_job", _fake_get_job)
    auth = _auth(
        _FakeAsyncSession(
            execute_results=[
                _Result(_Row(parse_status="FAILED", parse_error="LLM_UNAVAILABLE")),
                _Result(None),
            ]
        )
    )
    out = await jobs.retry_parse(job_id, auth)
    assert out.parse_status == "PENDING"
    assert enqueued == [(jobs.parse, (str(auth.tenant_id), str(job_id), str(auth.user_id)))]


async def test_retry_item_guards_and_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id, item_id, batch_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    # Missing / wrong job / wrong tenant -> 404.
    with pytest.raises(HTTPException) as exc:
        await uploads.retry_item(
            job_id, item_id, _auth(_FakeAsyncSession(execute_results=[_Result(None)]))
        )
    assert exc.value.status_code == 404

    # Non-retryable error -> 409.
    db_nonretry = _FakeAsyncSession(
        execute_results=[
            _Result(_Row(id=item_id, batch_id=batch_id, status="FAILED", error_code="CORRUPT_FILE"))
        ]
    )
    with pytest.raises(HTTPException) as exc:
        await uploads.retry_item(job_id, item_id, _auth(db_nonretry))
    assert exc.value.status_code == 409

    # Happy path -> updates item to PENDING, resets batch to PROCESSING, enqueues uploads.parse_cv.
    async def _budget_ok(*_args: Any, **_kwargs: Any) -> None:
        return None

    enqueued: list[tuple[Any, tuple[Any, ...]]] = []
    monkeypatch.setattr(usage, "check_budget", _budget_ok)
    monkeypatch.setattr(
        outbox,
        "enqueue_after_commit",
        lambda _db, task, *calls: enqueued.extend((task, c) for c in calls),
    )
    updated_row = _Row(
        id=item_id,
        file_name="cv.pdf",
        status="PENDING",
        dedupe=None,
        error_code=None,
        error_message=None,
    )
    db_ok = _FakeAsyncSession(
        execute_results=[
            _Result(
                _Row(id=item_id, batch_id=batch_id, status="FAILED", error_code="LLM_UNAVAILABLE")
            ),
            _Result(updated_row),
            _Result(None),
        ]
    )
    auth = _auth(db_ok)
    res = await uploads.retry_item(job_id, item_id, auth)
    assert res.status == "PENDING"
    assert res.error_code is None
    assert any(
        "UPDATE upload_batches SET status = 'PROCESSING'" in sql for sql in db_ok.executed_sql
    )
    assert enqueued == [(uploads.parse_cv, (str(auth.tenant_id), str(item_id)))]


async def test_retry_result_guards_and_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id, run_id, app_id, row_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    # Missing / wrong tenant -> 404.
    with pytest.raises(HTTPException) as exc:
        await scoring_runs.retry_result(
            job_id, run_id, app_id, _auth(_FakeAsyncSession(execute_results=[_Result(None)]))
        )
    assert exc.value.status_code == 404

    # Another running scoring run on the same Job -> 409.
    db_conflict = _FakeAsyncSession(
        execute_results=[_Result(_Row(id=row_id, status="FAILED", error_code="LLM_UNAVAILABLE"))],
        scalar_results=[True],
    )
    with pytest.raises(HTTPException) as exc:
        await scoring_runs.retry_result(job_id, run_id, app_id, _auth(db_conflict))
    assert exc.value.status_code == 409

    # Non-retryable error -> 409.
    db_nonretry = _FakeAsyncSession(
        execute_results=[_Result(_Row(id=row_id, status="FAILED", error_code="SCORING_FAILED"))],
        scalar_results=[False],
    )
    with pytest.raises(HTTPException) as exc:
        await scoring_runs.retry_result(job_id, run_id, app_id, _auth(db_nonretry))
    assert exc.value.status_code == 409

    # Happy path -> resets result to PENDING, resets run to RUNNING, enqueues score_application.
    async def _budget_ok(*_args: Any, **_kwargs: Any) -> None:
        return None

    enqueued: list[tuple[Any, tuple[Any, ...]]] = []
    monkeypatch.setattr(usage, "check_budget", _budget_ok)
    monkeypatch.setattr(
        outbox,
        "enqueue_after_commit",
        lambda _db, task, *calls: enqueued.extend((task, c) for c in calls),
    )
    cv_id = uuid.uuid4()
    refreshed = _Row(
        application_id=app_id,
        full_name="Ada",
        status="PENDING",
        cv_document_id=cv_id,
        current_cv_document_id=cv_id,
        technical_score=None,
        soft_skills_score=None,
        experience_score=None,
        total_score=None,
        must_have_coverage=None,
        must_have_detail=None,
        experience_detail=None,
        rubric_grades=None,
        fit_gap_report=None,
        grounding_rate=None,
        error_code=None,
    )
    db_ok = _FakeAsyncSession(
        execute_results=[
            _Result(_Row(id=row_id, status="FAILED", error_code="LLM_UNAVAILABLE")),
            _Result(None),
            _Result(None),
            _Result(refreshed),
        ],
        scalar_results=[False],
    )
    auth = _auth(db_ok)
    res = await scoring_runs.retry_result(job_id, run_id, app_id, auth)
    assert res.status == "PENDING"
    assert res.error_code is None
    assert any("UPDATE scoring_runs SET status = 'RUNNING'" in sql for sql in db_ok.executed_sql)
    assert enqueued == [
        (scoring_runs.score_application, (str(auth.tenant_id), str(run_id), str(app_id)))
    ]


def test_retry_routes_use_job_writer_and_recruiter_rbac() -> None:
    expected = [
        (jobs.router, "/api/jobs/{job_id}/parse/retry"),
        (uploads.router, "/api/jobs/{job_id}/uploads/items/{item_id}/retry"),
        (
            scoring_runs.router,
            "/api/jobs/{job_id}/scoring-runs/{run_id}/results/{application_id}/retry",
        ),
    ]
    for router_obj, path in expected:
        route = next(r for r in router_obj.routes if isinstance(r, APIRoute) and r.path == path)
        assert route.methods is not None and "POST" in route.methods
        # Walk dependency tree to ensure _recruiter (REVIEWER -> 403) guards every retry route.
        stack = list(route.dependant.dependencies)
        calls = []
        while stack:
            dep = stack.pop()
            calls.append(dep.call)
            stack.extend(dep.dependencies)
        assert jobs._recruiter in calls
