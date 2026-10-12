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

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.auth import Authenticated, _redis

# ADR-0003.
TICKET_TTL = timedelta(seconds=60)

router = APIRouter(prefix="/api/events")


def channel(tenant_id: UUID, user_id: UUID) -> str:
    return f"sse:{tenant_id}:{user_id}"


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


@router.post("/ticket")
async def ticket(auth: Authenticated) -> Ticket:
    value = secrets.token_urlsafe(32)
    await _redis().set(_ticket_key(value), channel(auth.tenant_id, auth.user_id), px=TICKET_TTL)
    return Ticket(ticket=value)


def _ticket_key(ticket: str) -> str:
    return f"sse_ticket:{ticket}"


async def _redeem(ticket: str = "") -> str:
    """The channel a ticket grants; GETDEL makes it single-use even under concurrent requests."""
    granted: bytes | None = await _redis().getdel(_ticket_key(ticket)) if ticket else None
    if granted is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired SSE ticket")
    return granted.decode()


@router.get("", response_class=EventSourceResponse)
async def stream(granted: Annotated[str, Depends(_redeem)]) -> AsyncIterator[ServerSentEvent]:
    async with _redis().pubsub() as pubsub:
        await pubsub.subscribe(granted)
        async for message in pubsub.listen():
            if message["type"] == "message":
                sent = json.loads(message["data"])
                yield ServerSentEvent(event=sent["event"], data=sent["data"])
