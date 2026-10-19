"""Outbox-style status rows (SAD §5.1, §6): their tasks are sent once the rows commit, and a
parent row completes from its children's rows rather than from a chord."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


def enqueue_after_commit(session: Session | AsyncSession, task: Any, *calls: Sequence[str]) -> None:
    """Send task once per args in calls when session commits; not at all if it rolls back.

    Sent earlier, a task could run before the row it works on is visible.
    """
    sync = session.sync_session if isinstance(session, AsyncSession) else session
    event.listen(sync, "after_commit", lambda _: [task.delay(*args) for args in calls], once=True)


def complete_parent(
    session: Session, parent: str, parent_id: UUID | str, children: str, key: str, assign: str
) -> None:
    """SET assign on the parent row once none of its children (children.key = id) is PENDING.

    assign may refer to the parent's id as :id. Children finishing together each lock the parent
    first, so the last one to commit sees every other one done.
    """
    session.execute(text(f"SELECT 1 FROM {parent} WHERE id = :id FOR UPDATE"), {"id": parent_id})
    session.execute(
        text(
            f"UPDATE {parent} SET {assign} WHERE id = :id AND NOT EXISTS ("
            f"  SELECT 1 FROM {children} WHERE {key} = :id AND status = 'PENDING')"
        ),
        {"id": parent_id},
    )
