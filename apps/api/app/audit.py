"""Immutable Audit Log and keyset-paginated Activity Timeline (FR-A3.3, ERD §7, SAD §5.8).

Every state-changing operation writes its audit_logs row in the same transaction as the domain
write itself (async `arecord` for API routes, sync `record` for Celery workers); neither helper
opens or commits a transaction. If the operation fails or rolls back, the audit row rolls back
with it.
"""

from __future__ import annotations

import ipaddress
import json
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, get_args
from uuid import UUID

from fastapi import HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

ActorType = Literal["USER", "AGENT", "SYSTEM", "PUBLIC"]
ACTOR_TYPES: frozenset[str] = frozenset(get_args(ActorType))

AuditAction = Literal[
    "job.created",
    "job.parsed",
    "job.parse_retried",
    "job.criteria_confirmed",
    "job.metadata_changed",
    "job.status_changed",
    "job.public_apply_changed",
    "job.reviewers_changed",
    "job.cvs_uploaded",
    "job.cv_parse_retried",
    "job.scoring_run_started",
    "application.created",
    "application.stage_changed",
    "application.score_retried",
    "application.scored",
    "application.email_sent",
    "application.email_failed",
    "invitation.created",
    "invitation.revoked",
    "invitation.accepted",
    "invitation.email_sent",
    "invitation.email_failed",
    "member.role_changed",
    "member.revoked",
    "channel_connection.connected",
    "channel_connection.disconnected",
]
ACTIONS: frozenset[str] = frozenset(get_args(AuditAction))

# FR-A0 & Experiment 3 invariant: before a Recruiter Decision, an Agent only creates derived data.
AGENT_ALLOWED_ACTIONS: frozenset[str] = frozenset({"job.scoring_run_started"})

_INSERT_AUDIT_LOG = text(
    "INSERT INTO audit_logs ("
    "  tenant_id, actor_type, actor_user_id, action, entity_type, entity_id,"
    "  before, after, request_id, ip"
    ") VALUES ("
    "  :tenant_id, :actor_type, :actor_user_id, :action, :entity_type, :entity_id,"
    "  CAST(:before AS jsonb), CAST(:after AS jsonb), NULL, CAST(:ip AS inet)"
    ")"
)


def client_ip(request: Request) -> str | None:
    """Extract a valid client IP address from request, or None when unavailable."""
    host = request.client.host if request.client else None
    return _valid_ip(host)


def _valid_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return None


def _params(
    tenant_id: UUID,
    *,
    actor_type: ActorType,
    actor_user_id: UUID | None,
    action: AuditAction,
    entity_id: UUID,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
    ip: str | None,
) -> dict[str, Any]:
    if actor_type not in ACTOR_TYPES:
        raise ValueError(f"Invalid actor_type: {actor_type}")
    if (actor_type in ("USER", "AGENT")) != (actor_user_id is not None):
        raise ValueError(
            f"actor_user_id must be set iff actor_type is USER or AGENT ({actor_type})"
        )
    if action not in ACTIONS:
        raise ValueError(f"Invalid audit action: {action}")
    if actor_type == "AGENT" and action not in AGENT_ALLOWED_ACTIONS:
        raise ValueError(f"AGENT may only record derived actions, not {action}")
    entity_type = action.partition(".")[0]
    return {
        "tenant_id": tenant_id,
        "actor_type": actor_type,
        "actor_user_id": actor_user_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "before": json.dumps(dict(before)) if before is not None else None,
        "after": json.dumps(dict(after)) if after is not None else None,
        "ip": _valid_ip(ip) if actor_type in ("USER", "PUBLIC") else None,
    }


def record(
    session: Session,
    *,
    actor_type: ActorType,
    actor_user_id: UUID | None = None,
    action: AuditAction,
    entity_id: UUID,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Append one Audit Log row into the worker's open transaction."""
    session.execute(
        _INSERT_AUDIT_LOG,
        _params(
            session.info["tenant_id"],
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            action=action,
            entity_id=entity_id,
            before=before,
            after=after,
            ip=ip,
        ),
    )


async def arecord(
    db: AsyncSession,
    *,
    actor_type: ActorType,
    actor_user_id: UUID | None = None,
    action: AuditAction,
    entity_id: UUID,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Append one Audit Log row into the API request's open transaction."""
    await db.execute(
        _INSERT_AUDIT_LOG,
        _params(
            db.info["tenant_id"],
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            action=action,
            entity_id=entity_id,
            before=before,
            after=after,
            ip=ip,
        ),
    )


class Actor(BaseModel):
    id: uuid.UUID
    full_name: str


class ActivityEntry(BaseModel):
    id: uuid.UUID
    action: AuditAction
    actor_type: ActorType
    actor: Actor | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    created_at: datetime


class ActivityPage(BaseModel):
    items: list[ActivityEntry]
    next_cursor: str | None


def _encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    return f"{created_at.isoformat()}|{row_id}"


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    created_str, sep, id_str = cursor.partition("|")
    if not sep:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid pagination cursor")
    try:
        return datetime.fromisoformat(created_str), uuid.UUID(id_str)
    except ValueError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid pagination cursor"
        ) from e


async def timeline(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: UUID,
    limit: int = 50,
    cursor: str | None = None,
) -> ActivityPage:
    """Read an entity's Activity Timeline newest-first with keyset pagination on (created_at, id).

    Joins `users` without filtering `is_active` so a revoked Member's name stays visible, and
    never selects or exposes `ip` or `request_id`.
    """
    where_cursor = ""
    params: dict[str, Any] = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "limit": limit + 1,
    }
    if cursor is not None:
        cursor_at, cursor_id = _decode_cursor(cursor)
        where_cursor = " AND (l.created_at, l.id) < (:cursor_at, :cursor_id)"
        params["cursor_at"] = cursor_at
        params["cursor_id"] = cursor_id

    rows = (
        await db.execute(
            text(
                "SELECT l.id, l.action, l.actor_type, l.actor_user_id,"
                "  u.full_name AS actor_full_name, l.before, l.after, l.created_at"
                " FROM audit_logs l"
                " LEFT JOIN users u ON u.tenant_id = l.tenant_id AND u.id = l.actor_user_id"
                f" WHERE l.entity_type = :entity_type AND l.entity_id = :entity_id{where_cursor}"
                " ORDER BY l.created_at DESC, l.id DESC"
                " LIMIT :limit"
            ),
            params,
        )
    ).all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [
        ActivityEntry(
            id=row.id,
            action=row.action,
            actor_type=row.actor_type,
            actor=(
                Actor(id=row.actor_user_id, full_name=row.actor_full_name)
                if row.actor_user_id is not None and row.actor_full_name is not None
                else None
            ),
            before=row.before,
            after=row.after,
            created_at=row.created_at,
        )
        for row in page_rows
    ]
    next_cursor = _encode_cursor(items[-1].created_at, items[-1].id) if has_more and items else None
    return ActivityPage(items=items, next_cursor=next_cursor)
