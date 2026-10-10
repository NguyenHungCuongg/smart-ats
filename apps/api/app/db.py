"""Database sessions under forced RLS (ADR-0001, ADR-0002, SAD §4.2).

The app connects as ats_app (DATABASE_URL). Tenant tables are visible only inside
tenant_session / async_tenant_session; a bare connection sees none of their rows.
"""

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from functools import cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import Session

# is_local=true scopes the setting to the transaction, so a pooled connection never carries it
# into its next checkout. SET LOCAL would do the same but takes no bind parameter.
_SET_TENANT = text("SELECT set_config('app.current_tenant_id', :tenant_id, true)")


@cache
def sync_engine() -> Engine:
    return create_engine(os.environ["DATABASE_URL"])


@cache
def async_engine() -> AsyncEngine:
    return create_async_engine(os.environ["DATABASE_URL"])


@contextmanager
def tenant_session(tenant_id: UUID) -> Iterator[Session]:
    """One transaction scoped to tenant_id, for workers: commits on exit, rolls back on error."""
    with Session(sync_engine()) as session, session.begin():
        session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
        yield session


@asynccontextmanager
async def async_tenant_session(tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    """The API's counterpart of tenant_session."""
    async with AsyncSession(async_engine()) as session, session.begin():
        await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
        yield session
