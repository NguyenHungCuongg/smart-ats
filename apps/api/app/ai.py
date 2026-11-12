"""Shared LLM retry policy, provider circuit breaker, and degraded-status API (FR-C2.3, SAD §6)."""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import redis.asyncio
from celery import current_task
from celery.exceptions import TaskPredicate
from fastapi import APIRouter
from pydantic import BaseModel

from app import usage
from app.auth import Authenticated
from smart_ats_scoring.llm import is_transient_error, llm_provider

log = logging.getLogger(__name__)

# FR-C2.3 exponential backoff schedule in seconds (3 retries = 4 total attempts).
RETRY_BACKOFF_SECONDS: tuple[int, ...] = (5, 15, 60)
RETRYABLE_ERROR_CODE = "LLM_UNAVAILABLE"
RETRYABLE_ERRORS: frozenset[str] = frozenset({RETRYABLE_ERROR_CODE})

# FR-C2.3 circuit breaker thresholds: >= 5 consecutive transient failures within 1m opens for 2m.
BREAKER_FAILURE_THRESHOLD = 5
BREAKER_FAILURE_WINDOW_SECONDS = 60
BREAKER_OPEN_SECONDS = 120
BREAKER_PROBE_LEASE_SECONDS = 120
# Keep open_until past BREAKER_OPEN_SECONDS so half-open probing can detect an expired window,
# while still expiring automatically if traffic ceases completely.
_OPEN_KEY_SAFETY_TTL_SECONDS = BREAKER_OPEN_SECONDS * 5

# Returns ["CLOSED"], ["PROBE"], or ["OPEN", open_until_timestamp_str].
_ACQUIRE_BREAKER_LUA = """
local open_until = tonumber(redis.call("GET", KEYS[1]))
if not open_until then
    return {"CLOSED"}
end
local now = tonumber(ARGV[1])
if now < open_until then
    return {"OPEN", tostring(open_until)}
end
local acquired = redis.call("SET", KEYS[2], "1", "NX", "EX", tonumber(ARGV[2]))
if acquired then
    return {"PROBE"}
end
return {"OPEN", tostring(open_until)}
"""

_RECORD_SUCCESS_LUA = """
redis.call("DEL", KEYS[1], KEYS[2], KEYS[3])
return 1
"""

# Records a transient error. If a half-open probe fails (open_until exists and now >= open_until),
# immediately re-opens for open_seconds. Otherwise tracks failures inside the sliding window and
# opens once count >= threshold. Returns 1 if the breaker is now open, 0 otherwise.
_RECORD_FAILURE_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local threshold = tonumber(ARGV[3])
local open_seconds = tonumber(ARGV[4])
local safety_ttl = tonumber(ARGV[5])
local member = ARGV[6]

local open_until = tonumber(redis.call("GET", KEYS[2]))
if open_until and now >= open_until then
    redis.call("SET", KEYS[2], tostring(now + open_seconds), "EX", safety_ttl)
    redis.call("DEL", KEYS[1], KEYS[3])
    return 1
end

local cutoff = now - window
redis.call("ZREMRANGEBYSCORE", KEYS[1], "-inf", cutoff)
redis.call("ZADD", KEYS[1], now, member)
redis.call("EXPIRE", KEYS[1], math.floor(window) + 60)
local count = redis.call("ZCARD", KEYS[1])
if count >= threshold then
    redis.call("SET", KEYS[2], tostring(now + open_seconds), "EX", safety_ttl)
    redis.call("DEL", KEYS[1], KEYS[3])
    return 1
end
return 0
"""

_RELEASE_PROBE_LUA = """
redis.call("DEL", KEYS[1])
return 1
"""

# Clears the consecutive transient failure streak on a deterministic (non-transient) error
# and releases any half-open probe lease when ARGV[1] == "1".
_RECORD_NON_TRANSIENT_LUA = """
redis.call("DEL", KEYS[1])
if ARGV[1] == "1" then
    redis.call("DEL", KEYS[2])
end
return 1
"""

router = APIRouter(prefix="/api/ai", tags=["ai"])


class AiStatus(BaseModel):
    """System-wide AI availability indicator for the web UI."""

    degraded: bool


def breaker_keys(provider: str | None = None) -> tuple[str, str, str]:
    """Provider-scoped Redis keys for the LLM circuit breaker (no tenant data)."""
    resolved = provider or llm_provider()
    prefix = f"llm:cb:{resolved}"
    return f"{prefix}:failures", f"{prefix}:open_until", f"{prefix}:probe"


def _acquire_breaker(provider: str | None = None) -> tuple[str, float | None]:
    _, open_key, probe_key = breaker_keys(provider)
    now = time.time()
    result = cast(
        list[Any],
        usage._sync_redis().eval(
            _ACQUIRE_BREAKER_LUA,
            2,
            open_key,
            probe_key,
            str(now),
            str(BREAKER_PROBE_LEASE_SECONDS),
        ),
    )
    raw_mode = result[0]
    mode = raw_mode.decode() if isinstance(raw_mode, bytes) else str(raw_mode)
    open_until: float | None = None
    if len(result) > 1 and result[1] is not None:
        raw_until = result[1].decode() if isinstance(result[1], bytes) else str(result[1])
        open_until = float(raw_until)
    return mode, open_until


def _record_success(provider: str | None = None) -> None:
    failures_key, open_key, probe_key = breaker_keys(provider)
    usage._sync_redis().eval(_RECORD_SUCCESS_LUA, 3, failures_key, open_key, probe_key)


def _record_failure(provider: str | None = None) -> bool:
    failures_key, open_key, probe_key = breaker_keys(provider)
    now = time.time()
    member = f"{now:.6f}:{uuid.uuid4().hex}"
    tripped = cast(
        int,
        usage._sync_redis().eval(
            _RECORD_FAILURE_LUA,
            3,
            failures_key,
            open_key,
            probe_key,
            str(now),
            str(BREAKER_FAILURE_WINDOW_SECONDS),
            str(BREAKER_FAILURE_THRESHOLD),
            str(BREAKER_OPEN_SECONDS),
            str(_OPEN_KEY_SAFETY_TTL_SECONDS),
            member,
        ),
    )
    return bool(int(tripped))


def _release_probe(provider: str | None = None) -> None:
    _, _, probe_key = breaker_keys(provider)
    usage._sync_redis().eval(_RELEASE_PROBE_LUA, 1, probe_key)


def _record_non_transient(provider: str | None = None, *, release_probe: bool) -> None:
    failures_key, _, probe_key = breaker_keys(provider)
    usage._sync_redis().eval(
        _RECORD_NON_TRANSIENT_LUA, 2, failures_key, probe_key, "1" if release_probe else "0"
    )


@contextmanager
def llm_call(session: Any, tenant_id: uuid.UUID) -> Iterator[None]:
    """Guard an LLM call with the global circuit breaker and per-tenant concurrency slot.

    When the breaker is open, reschedules the current Celery task via
    ``usage.reschedule_llm_task`` without consuming a retry attempt or opening a
    model connection. On success resets consecutive failures and closes any half-open
    breaker; on transient errors updates the breaker window (or re-opens immediately on
    a failed half-open probe). Non-transient exceptions never trip the breaker.
    """
    provider = llm_provider()
    mode, open_until = _acquire_breaker(provider)
    if mode == "OPEN":
        remaining = float(BREAKER_OPEN_SECONDS)
        if open_until is not None:
            remaining = max(1.0, min(float(BREAKER_OPEN_SECONDS), open_until - time.time()))
        log.warning(
            "LLM circuit breaker open for %s; rescheduling task in %.0fs", provider, remaining
        )
        usage.reschedule_llm_task(countdown=remaining)

    try:
        with usage.llm_slot(session, tenant_id):
            yield
    except TaskPredicate:
        if mode == "PROBE":
            _release_probe(provider)
        raise
    except Exception as exc:
        if is_transient_error(exc):
            if _record_failure(provider):
                log.error("LLM circuit breaker opened for provider %s", provider)
        else:
            _record_non_transient(provider, release_probe=(mode == "PROBE"))
        raise
    else:
        _record_success(provider)


def retry_transient_error(exc: BaseException) -> str:
    """Retry a Celery LLM task using ``RETRY_BACKOFF_SECONDS``, or return ``LLM_UNAVAILABLE``.

    Raises ``celery.exceptions.Retry`` while retry attempts remain; returns
    ``RETRYABLE_ERROR_CODE`` once retries are exhausted so the caller marks the row ``FAILED``.
    """
    task = current_task
    if task is not None:
        retries = int(getattr(task.request, "retries", 0) or 0)
        if retries < len(RETRY_BACKOFF_SECONDS):
            countdown = RETRY_BACKOFF_SECONDS[retries]
            raise task.retry(exc=exc, countdown=countdown)
    return RETRYABLE_ERROR_CODE


async def _async_redis() -> redis.asyncio.Redis:
    return cast(redis.asyncio.Redis, redis.asyncio.Redis.from_url(os.environ["REDIS_URL"]))


def _is_open_until(raw: bytes | str | None) -> bool:
    if raw is None:
        return False
    raw_str = raw.decode() if isinstance(raw, bytes) else str(raw)
    return float(raw_str) > time.time()


def is_degraded() -> bool:
    """Sync check for whether the configured LLM provider's circuit breaker is open."""
    _, open_key, _ = breaker_keys()
    return _is_open_until(cast(bytes | str | None, usage._sync_redis().get(open_key)))


async def is_degraded_async() -> bool:
    """Async check for whether the configured LLM provider's circuit breaker is open."""
    _, open_key, _ = breaker_keys()
    client = await _async_redis()
    try:
        return _is_open_until(await client.get(open_key))
    finally:
        await client.aclose()


@router.get("/status", response_model=AiStatus)
async def ai_status(auth: Authenticated) -> AiStatus:
    """Return whether LLM calls are currently paused due to upstream instability."""
    _ = auth
    return AiStatus(degraded=await is_degraded_async())
