"""Unit tests for AI Budget estimation, check_budget, GET /api/usage and LLM slot control."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

import pytest
from celery.exceptions import Ignore
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

os.environ.setdefault("REDIS_URL", "memory://")

from app import auth, usage  # noqa: E402
from app.auth import _access_token  # noqa: E402
from app.main import app  # noqa: E402


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def one(self) -> Any:
        assert len(self._rows) == 1
        return self._rows[0]


@dataclass
class _Row:
    feature: str | None = None
    calls: int = 0
    cost_usd: Decimal = Decimal(0)
    avg_cost: Decimal | None = None
    budget_usd: Decimal = Decimal(0)
    spent_usd: Decimal = Decimal(0)


class _FakeAsyncDb:
    def __init__(
        self,
        *,
        budget_usd: Decimal = Decimal("10.00"),
        spent_usd: Decimal = Decimal("0.00"),
        avg_by_feature: dict[str, Decimal] | None = None,
        summary_rows: list[tuple[str, int, Decimal]] | None = None,
    ) -> None:
        self.budget_usd = budget_usd
        self.spent_usd = spent_usd
        self.avg_by_feature = avg_by_feature or {}
        self.summary_rows = summary_rows or []
        self.executed: list[tuple[str, dict[str, Any] | None]] = []

    async def scalar(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        sql = str(stmt)
        self.executed.append((sql, params))
        if "ai_budget_monthly_usd" in sql:
            return self.budget_usd
        return None

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        sql = str(stmt)
        self.executed.append((sql, params))
        if "AS avg_cost" in sql:
            features = (params or {}).get("features", [])
            return _FakeResult(
                [
                    _Row(feature=f, avg_cost=self.avg_by_feature[f])
                    for f in features
                    if f in self.avg_by_feature
                ]
            )
        if "AS spent_usd" in sql:
            return _FakeResult([_Row(budget_usd=self.budget_usd, spent_usd=self.spent_usd)])
        if "GROUP BY feature" in sql:
            return _FakeResult(
                [_Row(feature=f, calls=c, cost_usd=cost) for f, c, cost in self.summary_rows]
            )
        raise AssertionError(f"unexpected SQL: {sql}")


class _FakeSyncSession:
    def __init__(self, limit: int | None) -> None:
        self.limit = limit

    def scalar(self, stmt: Any) -> int | None:
        return self.limit


def test_month_bounds_utc() -> None:
    label, start, end = usage._month_bounds_utc("2026-12")
    assert label == "2026-12"
    assert start.isoformat() == "2026-12-01T00:00:00+00:00"
    assert end.isoformat() == "2027-01-01T00:00:00+00:00"

    label2, start2, end2 = usage._month_bounds_utc("2026-02")
    assert label2 == "2026-02"
    assert end2.isoformat() == "2026-03-01T00:00:00+00:00"
    assert start2.month == 2


async def test_estimate_cost_uses_history_and_default_fallback() -> None:
    db = cast(AsyncSession, _FakeAsyncDb(avg_by_feature={"CV_PARSE": Decimal("0.25")}))
    # CV_PARSE uses 30d avg ($0.25 * 3 = $0.75); EMBEDDING uses shared default constant.
    est = await usage.estimate_cost(db, {"CV_PARSE": 3, "EMBEDDING": 2, "JOB_PARSE": 0})
    expected = Decimal("0.75") + usage.DEFAULT_COST_PER_CALL_USD["EMBEDDING"] * 2
    assert est == expected


async def test_check_budget_boundary_and_402_payload() -> None:
    db_ok = cast(
        AsyncSession,
        _FakeAsyncDb(
            budget_usd=Decimal("10.00"),
            spent_usd=Decimal("9.99"),
            avg_by_feature={"JOB_PARSE": Decimal("0.01")},
        ),
    )
    await usage.check_budget(db_ok, {"JOB_PARSE": 1})

    db_over = cast(
        AsyncSession,
        _FakeAsyncDb(
            budget_usd=Decimal("10.00"),
            spent_usd=Decimal("9.99"),
            avg_by_feature={"JOB_PARSE": Decimal("0.02")},
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await usage.check_budget(db_over, {"JOB_PARSE": 1})
    assert exc.value.status_code == 402
    detail: Any = exc.value.detail
    assert detail == {
        "code": "AI_BUDGET_EXCEEDED",
        "message": "Monthly AI budget exceeded",
    }
    spent_query, spent_params = next(
        (sql, params)
        for sql, params in cast(_FakeAsyncDb, db_over).executed
        if "AS spent_usd" in sql
    )
    assert ":month_start" in spent_query and ":month_end" in spent_query
    assert spent_params is not None and "month_start" in spent_params


async def test_public_apply_checks_budget_before_inserts_or_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import apply, storage

    job_row = type(
        "PublicJob",
        (),
        {
            "job_id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "title": "Engineer",
            "status": "PUBLISHED",
            "public_apply_enabled": True,
            "apply_deadline": None,
            "tenant_name": "Acme",
        },
    )()
    executed: list[str] = []
    stored: dict[str, bytes] = {}

    class FakeConn:
        async def execute(self, stmt: Any, params: Any = None) -> Any:
            return type("Res", (), {"one_or_none": lambda self: job_row})()

    class FakeEngine:
        @asynccontextmanager
        async def begin(self) -> AsyncIterator[FakeConn]:
            yield FakeConn()

    class FakeApplyDb(_FakeAsyncDb):
        async def scalar(self, stmt: Any, params: Any = None) -> Any:
            executed.append(str(stmt))
            return None

        async def execute(self, stmt: Any, params: Any = None) -> Any:
            sql = str(stmt)
            executed.append(sql)
            if "FROM cv_documents" in sql:
                return type("Res", (), {"one_or_none": lambda self: None})()
            if "AS spent_usd" in sql or "AS avg_cost" in sql:
                return await super().execute(stmt, params)
            raise AssertionError(f"must not write DB after 402: {sql}")

    @asynccontextmanager
    async def fake_tenant_session(tenant_id: uuid.UUID) -> AsyncIterator[FakeApplyDb]:
        yield FakeApplyDb(budget_usd=Decimal("0.00"), spent_usd=Decimal("0.00"))

    async def allow_rate_limit(key: str) -> bool:
        return True

    monkeypatch.setattr(apply, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(apply, "async_engine", lambda: FakeEngine())
    monkeypatch.setattr(apply, "async_tenant_session", fake_tenant_session)
    monkeypatch.setattr(storage, "put", lambda k, d: stored.__setitem__(k, d))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/apply/demo-slug",
            data={"full_name": "Candidate", "email": "cand@example.com", "consent": "true"},
            files={"file": ("cv.pdf", b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF")},
        )
    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "AI_BUDGET_EXCEEDED"
    assert stored == {}
    assert not any("INSERT INTO" in sql for sql in executed)


async def test_usage_endpoint_roles_80_percent_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!")
    fake_db = _FakeAsyncDb(
        budget_usd=Decimal("10.00"),
        summary_rows=[("SCORING", 2, Decimal("5.00")), ("JOB_PARSE", 1, Decimal("3.00"))],
    )

    @asynccontextmanager
    async def fake_session(tenant_id: uuid.UUID) -> AsyncIterator[Any]:
        yield fake_db

    monkeypatch.setattr(auth, "async_tenant_session", fake_session)
    tenant_id = uuid.uuid4()
    admin_hdr = {
        "Authorization": f"Bearer {_access_token(uuid.uuid4(), tenant_id, 'COMPANY_ADMIN')}"
    }
    rec_hdr = {"Authorization": f"Bearer {_access_token(uuid.uuid4(), tenant_id, 'RECRUITER')}"}
    rev_hdr = {"Authorization": f"Bearer {_access_token(uuid.uuid4(), tenant_id, 'REVIEWER')}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/usage", headers=rev_hdr)).status_code == 403
        assert (await client.get("/api/usage?month=2026-13", headers=admin_hdr)).status_code == 422

        r_admin = await client.get("/api/usage?month=2026-11", headers=admin_hdr)
        assert r_admin.status_code == 200
        body = r_admin.json()
        assert body["scope"] == "TENANT"
        assert body["total_cost_usd"] == pytest.approx(8.0)
        assert body["usage_ratio"] == pytest.approx(0.8)
        assert body["budget_warning"] is True
        assert body["total_calls"] == 3
        assert "user_id = :user_id" not in fake_db.executed[-1][0]

        r_rec = await client.get("/api/usage?month=2026-11", headers=rec_hdr)
        assert r_rec.status_code == 200
        assert r_rec.json()["scope"] == "USER"
        assert r_rec.json()["budget_warning"] is False
        assert "user_id = :user_id" in fake_db.executed[-1][0]

        # Below 80% ($7.999999 < $8.00) and zero-budget edge cases.
        fake_db.summary_rows = [("JOB_PARSE", 1, Decimal("7.999999"))]
        assert (await client.get("/api/usage", headers=admin_hdr)).json()["budget_warning"] is False

        fake_db.budget_usd = Decimal("0.00")
        fake_db.summary_rows = []
        r_zero = (await client.get("/api/usage", headers=admin_hdr)).json()
        assert (r_zero["usage_ratio"], r_zero["budget_warning"]) == (0.0, False)


def test_llm_slot_acquires_releases_on_error_and_reschedules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str], list[Any]]] = []

    class FakeRedis:
        def __init__(self, acquire_result: int) -> None:
            self.acquire_result = acquire_result

        def register_script(self, script: str) -> Any:
            kind = "acquire" if "ZCARD" in script else "release"

            def run(*, keys: list[str], args: list[Any]) -> int:
                calls.append((kind, keys, args))
                return self.acquire_result if kind == "acquire" else 1

            return run

    tid = uuid.uuid4()

    # 1. Normal acquire & release
    monkeypatch.setattr(usage, "_sync_redis", lambda: FakeRedis(1))
    with usage.llm_slot(cast(Session, _FakeSyncSession(3)), tid):
        assert [c[0] for c in calls] == ["acquire"]
        assert calls[0][1] == [f"llm_slots:{tid}"]
        assert calls[0][2][0] == 3
    assert [c[0] for c in calls] == ["acquire", "release"]
    assert calls[1][2] == [calls[0][2][2]]  # exact token released

    # 2. Failed task still releases slot
    calls.clear()
    with pytest.raises(RuntimeError), usage.llm_slot(cast(Session, _FakeSyncSession(2)), tid):
        raise RuntimeError("boom")
    assert [c[0] for c in calls] == ["acquire", "release"]

    # 3. Full slot triggers reschedule via apply_async without counting retries & raises Ignore
    calls.clear()
    monkeypatch.setattr(usage, "_sync_redis", lambda: FakeRedis(0))
    sent: list[dict[str, Any]] = []

    class FakeRequest:
        called_directly = False
        args = (str(tid), "job-1", "user-1")
        kwargs: dict[str, Any] = {}
        retries = 0

    monkeypatch.setattr(
        usage,
        "current_task",
        type(
            "T",
            (),
            {
                "request": FakeRequest(),
                "queue": "llm",
                "apply_async": lambda self, **kw: sent.append(kw),
            },
        )(),
    )

    with (
        pytest.raises(Ignore),
        usage.llm_slot(cast(Session, _FakeSyncSession(1)), tid, retry_countdown=7.0),
    ):
        raise AssertionError("body must not run when slot is full")
    assert [c[0] for c in calls] == ["acquire"]
    assert sent == [
        {
            "args": (str(tid), "job-1", "user-1"),
            "kwargs": {},
            "countdown": 7.0,
            "retries": 0,
            "queue": "llm",
        }
    ]
