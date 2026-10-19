"""Per-user progress events over SSE (ADR-0003, SAD §4.3).

EventSource cannot send an Authorization header, so a signed-in client first trades its access
token for a one-time ticket, then opens GET /api/events?ticket=... . The stream relays the Redis
channel sse:{tenant_id}:{user_id} of the ticket's user, and no other.
"""

import json
import os
import secrets
from collections.abc import AsyncIterator
from datetime import timedelta
from functools import cache
from typing import Annotated, Any
from uuid import UUID

import redis.asyncio
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel
from redis import Redis
from redis.asyncio.client import PubSub
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.auth import Authenticated, _redis

# ADR-0003.
TICKET_TTL = timedelta(seconds=60)
# SAD §4.3.
MAX_STREAMS_PER_USER = 5
MAX_STREAM_CONNECTIONS = 500

router = APIRouter(prefix="/api/events")


def channel(tenant_id: UUID, user_id: UUID) -> str:
    return f"sse:{tenant_id}:{user_id}"


@cache
def _stream_redis() -> redis.asyncio.Redis:
    # Every open stream holds a connection: a capped pool of their own, so streams can neither
    # starve the API's other Redis calls nor push Redis, the broker of every Tenant, to maxclients.
    client: redis.asyncio.Redis = redis.asyncio.Redis.from_url(
        os.environ["REDIS_URL"], max_connections=MAX_STREAM_CONNECTIONS
    )
    return client


async def _open_streams(channel: str) -> int:
    """The user's open streams, wherever they run: each is one subscriber of the channel, which
    Redis forgets when its connection drops."""
    count: int = (await _redis().pubsub_numsub(channel))[0][1]
    return count


@cache
def _sync_redis() -> Redis:
    client: Redis = Redis.from_url(os.environ["REDIS_URL"])
    return client


def publish(session: Session, user_id: UUID, name: str, data: Any) -> None:
    """Send event `name` with JSON `data` to the user's open streams once `session` commits.

    The Tenant is the session's own (tenant_session), so a task cannot reach another's channel.

    For @tenant_task bodies: a client reloads on the event, so it must not arrive before the
    data it announces is visible; a rolled-back transaction sends nothing.
    """
    message = json.dumps({"event": name, "data": data})
    event.listen(
        session,
        "after_commit",
        lambda _: _sync_redis().publish(channel(session.info["tenant_id"], user_id), message),
        once=True,
    )


class Ticket(BaseModel):
    ticket: str


def _too_many_streams() -> HTTPException:
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many open event streams")


@router.post("/ticket")
async def ticket(auth: Authenticated) -> Ticket:
    granted = channel(auth.tenant_id, auth.user_id)
    if await _open_streams(granted) >= MAX_STREAMS_PER_USER:
        raise _too_many_streams()
    value = secrets.token_urlsafe(32)
    await _redis().set(_ticket_key(value), granted, px=TICKET_TTL)
    return Ticket(ticket=value)


def _ticket_key(ticket: str) -> str:
    return f"sse_ticket:{ticket}"


async def _redeem(ticket: str = "") -> str:
    """The channel a ticket grants; GETDEL makes it single-use even under concurrent requests."""
    granted: bytes | None = await _redis().getdel(_ticket_key(ticket)) if ticket else None
    if granted is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired SSE ticket")
    return granted.decode()


async def _subscribe(granted: Annotated[str, Depends(_redeem)]) -> AsyncIterator[PubSub]:
    """The pubsub listening on the granted channel, before the response starts: a client that
    reloads once the stream is open then misses no event (SAD §6)."""
    async with _stream_redis().pubsub() as pubsub:
        try:
            await pubsub.subscribe(granted)
            # Redis confirms the subscription before anything else on this connection.
            confirmed = await pubsub.get_message(timeout=5)
        except redis.ConnectionError as e:  # the pool is used up
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Try again later") from e
        if confirmed is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Try again later")
        # Counted once subscribed, so tickets taken ahead cannot open more streams together.
        if await _open_streams(granted) > MAX_STREAMS_PER_USER:
            raise _too_many_streams()
        yield pubsub


@router.get("", response_class=EventSourceResponse)
async def stream(pubsub: Annotated[PubSub, Depends(_subscribe)]) -> AsyncIterator[ServerSentEvent]:
    async for message in pubsub.listen():
        if message["type"] == "message":
            sent = json.loads(message["data"])
            yield ServerSentEvent(event=sent["event"], data=sent["data"])
