"""AI Usage Ledger, pre-enqueue budget checks, usage API & concurrency limits (FR-C1.4, ERD §7)."""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from functools import cache
from typing import Literal, NoReturn
from uuid import UUID

from celery import current_task
from celery.exceptions import Ignore
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.auth import Authenticated
from smart_ats_scoring.llm import Usage
from smart_ats_scoring.pricing import cost, price

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

FeatureName = Literal[
    "JOB_PARSE",
    "CV_PARSE",
    "OCR",
    "SCORING",
    "INTERVIEW_Q",
    "EMAIL",
    "AGENT",
    "EMBEDDING",
]

# Fallback estimated cost per model call when a tenant has no 30-day ledger history for that
# feature (FR-C1.4, SAD §6). Kept in one place so every enqueue check shares the same defaults.
DEFAULT_COST_PER_CALL_USD: dict[FeatureName, Decimal] = {
    "JOB_PARSE": Decimal("0.01"),
    "CV_PARSE": Decimal("0.01"),
    "OCR": Decimal("0.01"),
    "SCORING": Decimal("0.05"),
    "INTERVIEW_Q": Decimal("0.02"),
    "EMAIL": Decimal("0.01"),
    "AGENT": Decimal("0.05"),
    "EMBEDDING": Decimal("0.0001"),
}

LLM_SLOT_LEASE_SECONDS = 120.0
LLM_SLOT_RETRY_COUNTDOWN = 5.0

_ACQUIRE_SLOT_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local token = ARGV[3]
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000.0
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if limit <= 0 or redis.call('ZCARD', key) >= limit then
    return 0
end
redis.call('ZADD', key, now + ttl, token)
redis.call('EXPIRE', key, math.ceil(ttl) + 5)
return 1
"""

_RELEASE_SLOT_LUA = """
return redis.call('ZREM', KEYS[1], ARGV[1])
"""


def priced(model: str) -> bool:
    """Whether the ledger can price model. Checked before every call: tokens it cannot price
    must not be spent."""
    if price(model) is None:
        log.error("no price for model %s in smart_ats_scoring.pricing.PRICES", model)
        return False
    return True


def record(
    session: Session,
    user_id: UUID | None,
    feature: FeatureName,
    usage: Usage,
    ref_type: str,
    ref_id: UUID,
) -> None:
    session.execute(
        text(
            "INSERT INTO ai_usage_entries (tenant_id, user_id, feature, model, input_tokens,"
            "  output_tokens, cached_tokens, cost_usd, ref_type, ref_id)"
            " VALUES (:tenant_id, :user_id, :feature, :model, :input_tokens,"
            "  :output_tokens, :cached_tokens, :cost_usd, :ref_type, :ref_id)"
        ),
        {
            "tenant_id": session.info["tenant_id"],
            "user_id": user_id,
            "feature": feature,
            "model": usage.model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cached_tokens": usage.cached_tokens,
            "cost_usd": cost(usage),
            "ref_type": ref_type,
            "ref_id": ref_id,
        },
    )


async def estimate_cost(db: AsyncSession, planned_calls: Mapping[FeatureName, int]) -> Decimal:
    """Estimate USD cost of planned_calls from the tenant's 30-day per-feature ledger average,
    falling back to DEFAULT_COST_PER_CALL_USD when a feature has no recent history."""
    active = {feature: calls for feature, calls in planned_calls.items() if calls > 0}
    if not active:
        return Decimal(0)
    for feature in active:
        _ = DEFAULT_COST_PER_CALL_USD[feature]

    rows = (
        await db.execute(
            text(
                "SELECT feature, avg(cost_usd) AS avg_cost"
                " FROM ai_usage_entries"
                " WHERE created_at >= now() - interval '30 days'"
                "  AND feature = ANY(:features)"
                " GROUP BY feature"
            ),
            {"features": list(active)},
        )
    ).all()
    averages = {row.feature: Decimal(row.avg_cost) for row in rows if row.avg_cost is not None}
    return sum(
        (
            averages.get(feature, DEFAULT_COST_PER_CALL_USD[feature]) * calls
            for feature, calls in active.items()
        ),
        Decimal(0),
    )


async def check_budget(db: AsyncSession, planned_calls: Mapping[FeatureName, int]) -> None:
    """Reject with 402 AI_BUDGET_EXCEEDED when current UTC month spend plus estimated cost
    exceeds tenants.ai_budget_monthly_usd. Called before inserting rows or enqueuing tasks."""
    _, month_start, month_end = _month_bounds_utc(None)
    row = (
        await db.execute(
            text(
                "SELECT"
                "  (SELECT ai_budget_monthly_usd FROM tenants) AS budget_usd,"
                "  ("
                "    SELECT coalesce(sum(cost_usd), 0)"
                "    FROM ai_usage_entries"
                "    WHERE created_at >= :month_start"
                "      AND created_at < :month_end"
                "  ) AS spent_usd"
            ),
            {"month_start": month_start, "month_end": month_end},
        )
    ).one()
    budget = Decimal(row.budget_usd)
    spent = Decimal(row.spent_usd)
    estimated = await estimate_cost(db, planned_calls)
    # ponytail: tasks already enqueued in another request are not in ai_usage_entries yet, so two
    # near-simultaneous requests can pass this check and exceed monthly budget by one batch.
    if spent + estimated > budget:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            {"code": "AI_BUDGET_EXCEEDED", "message": "Monthly AI budget exceeded"},
        )


def llm_slot_key(tenant_id: UUID) -> str:
    return f"llm_slots:{tenant_id}"


@cache
def _redis_for(url: str) -> Redis:
    return Redis.from_url(url)


def _sync_redis() -> Redis:
    return _redis_for(os.environ["REDIS_URL"])


def reschedule_llm_task(countdown: float = LLM_SLOT_RETRY_COUNTDOWN) -> NoReturn:
    """Re-queue the current task for later without counting an attempt and abort this run."""
    task = current_task
    if task is not None and not task.request.called_directly:
        req = task.request
        task.apply_async(
            args=req.args,
            kwargs=req.kwargs,
            countdown=countdown,
            retries=req.retries,
            queue=getattr(task, "queue", None),
        )
    raise Ignore()


@contextmanager
def llm_slot(
    session: Session,
    tenant_id: UUID,
    *,
    lease_seconds: float = LLM_SLOT_LEASE_SECONDS,
    retry_countdown: float = LLM_SLOT_RETRY_COUNTDOWN,
) -> Iterator[None]:
    """Acquire one Redis concurrency slot up to tenants.max_llm_concurrency; release on exit or
    reschedule without advancing attempts if all slots are busy."""
    limit = session.scalar(text("SELECT max_llm_concurrency FROM tenants"))
    max_concurrency = 0 if limit is None else int(limit)
    client = _sync_redis()
    acquire = client.register_script(_ACQUIRE_SLOT_LUA)
    key = llm_slot_key(tenant_id)
    token = str(uuid.uuid4())
    if not bool(acquire(keys=[key], args=[max_concurrency, lease_seconds, token])):
        reschedule_llm_task(countdown=retry_countdown)
    release = client.register_script(_RELEASE_SLOT_LUA)
    try:
        yield
    finally:
        try:
            release(keys=[key], args=[token])
        except Exception:
            # Lease TTL guarantees an unreachable Redis during release will not hold the slot.
            log.warning(
                "failed to release LLM slot %s for tenant %s", token, tenant_id, exc_info=True
            )


class FeatureUsage(BaseModel):
    feature: str
    calls: int
    cost_usd: float


class UsageSummary(BaseModel):
    month: str
    scope: Literal["TENANT", "USER"]
    budget_usd: float
    total_cost_usd: float
    total_calls: int
    usage_ratio: float
    budget_warning: bool
    features: list[FeatureUsage]


def _month_bounds_utc(month: str | None) -> tuple[str, datetime, datetime]:
    if month is None:
        now = datetime.now(UTC)
        year, mon = now.year, now.month
        label = f"{year:04d}-{mon:02d}"
    else:
        year_s, mon_s = month.split("-")
        year, mon = int(year_s), int(mon_s)
        label = month
    start = datetime(year, mon, 1, tzinfo=UTC)
    end = datetime(year + (mon // 12), (mon % 12) + 1, 1, tzinfo=UTC)
    return label, start, end


@router.get("/usage")
async def summary(
    auth: Authenticated,
    month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
) -> UsageSummary:
    """AI cost and call counts for the given UTC month, monthly budget and 80% warning (FR-C1.4)."""
    if auth.role == "REVIEWER":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Reviewers cannot view AI usage")
    label, start, end = _month_bounds_utc(month)
    scope: Literal["TENANT", "USER"] = "TENANT" if auth.role == "COMPANY_ADMIN" else "USER"
    budget = Decimal(await auth.db.scalar(text("SELECT ai_budget_monthly_usd FROM tenants")) or 0)
    user_filter = "" if scope == "TENANT" else " AND user_id = :user_id"
    rows = (
        await auth.db.execute(
            text(
                "SELECT feature, count(*) AS calls, coalesce(sum(cost_usd), 0) AS cost_usd"
                " FROM ai_usage_entries"
                f" WHERE created_at >= :start AND created_at < :end{user_filter}"
                " GROUP BY feature"
                " ORDER BY cost_usd DESC, feature ASC"
            ),
            {"start": start, "end": end, "user_id": auth.user_id},
        )
    ).all()
    total_cost = sum((Decimal(r.cost_usd) for r in rows), Decimal(0))
    total_calls = sum(int(r.calls) for r in rows)
    if budget > 0:
        usage_ratio = float(total_cost / budget)
        threshold_reached = total_cost * 10 >= budget * 8
    else:
        usage_ratio = 1.0 if total_cost > 0 else 0.0
        threshold_reached = total_cost > 0
    return UsageSummary(
        month=label,
        scope=scope,
        budget_usd=float(budget),
        total_cost_usd=float(total_cost),
        total_calls=total_calls,
        usage_ratio=usage_ratio,
        budget_warning=auth.role == "COMPANY_ADMIN" and threshold_reached,
        features=[
            FeatureUsage(feature=r.feature, calls=int(r.calls), cost_usd=float(r.cost_usd))
            for r in rows
        ],
    )
