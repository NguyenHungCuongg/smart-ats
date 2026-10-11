"""Forced RLS on tenant tables (ADR-0001, SAD §4.2, ERD §1), checked as ats_app."""

import uuid

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.db import async_engine, async_tenant_session, sync_engine, tenant_session

pytestmark = pytest.mark.usefixtures("database")

COUNT_USERS = text("SELECT count(*) FROM users")
PID_AND_TENANT = text("SELECT pg_backend_pid(), current_setting('app.current_tenant_id', true)")


def make_tenant() -> uuid.UUID:
    slug = f"t-{uuid.uuid4().hex}"
    with sync_engine().begin() as conn:
        tenant_id: uuid.UUID = conn.execute(
            text(
                "INSERT INTO tenants (name, slug, plan_type, ai_budget_monthly_usd, status)"
                " VALUES (:slug, :slug, 'FREE', 10, 'ACTIVE') RETURNING id"
            ),
            {"slug": slug},
        ).scalar_one()
    return tenant_id


def insert_user(session: Session, tenant_id: uuid.UUID) -> None:
    session.execute(
        text(
            "INSERT INTO users (tenant_id, email, full_name, role, is_active)"
            " VALUES (:tenant_id, :email, 'Test User', 'RECRUITER', true)"
        ),
        {"tenant_id": tenant_id, "email": f"{uuid.uuid4().hex}@example.com"},
    )


@pytest.fixture
def tenant() -> uuid.UUID:
    """A tenant holding one user."""
    tenant_id = make_tenant()
    with tenant_session(tenant_id) as session:
        insert_user(session, tenant_id)
    return tenant_id


def test_tenant_sees_its_own_rows(tenant: uuid.UUID) -> None:
    with tenant_session(tenant) as session:
        assert session.scalar(COUNT_USERS) == 1


def test_no_context_sees_no_rows(tenant: uuid.UUID) -> None:
    with sync_engine().connect() as conn:
        assert conn.scalar(COUNT_USERS) == 0


def test_other_tenant_context_sees_no_rows(tenant: uuid.UUID) -> None:
    with tenant_session(make_tenant()) as session:
        assert session.scalar(COUNT_USERS) == 0


def test_insert_for_other_tenant_is_rejected(tenant: uuid.UUID) -> None:
    other = make_tenant()
    with pytest.raises(ProgrammingError) as exc, tenant_session(tenant) as session:
        insert_user(session, other)
    assert isinstance(exc.value.orig, psycopg.errors.InsufficientPrivilege)


def test_moving_a_row_to_other_tenant_is_rejected(tenant: uuid.UUID) -> None:
    other = make_tenant()
    with pytest.raises(ProgrammingError) as exc, tenant_session(tenant) as session:
        session.execute(text("UPDATE users SET tenant_id = :other"), {"other": other})
    assert isinstance(exc.value.orig, psycopg.errors.InsufficientPrivilege)


def test_context_does_not_outlive_the_transaction(tenant: uuid.UUID) -> None:
    with tenant_session(tenant) as session:
        pid, _ = session.execute(PID_AND_TENANT).one()

    with sync_engine().connect() as conn:
        # Same pooled connection, context gone: '' rather than NULL once it has been set.
        assert tuple(conn.execute(PID_AND_TENANT).one()) == (pid, "")
        assert conn.scalar(COUNT_USERS) == 0


async def test_async_session_is_scoped_to_its_tenant(tenant: uuid.UUID) -> None:
    async with async_tenant_session(tenant) as session:
        assert await session.scalar(COUNT_USERS) == 1
    async with async_tenant_session(make_tenant()) as session:
        assert await session.scalar(COUNT_USERS) == 0


async def test_async_context_does_not_outlive_the_transaction(tenant: uuid.UUID) -> None:
    # Start from an empty pool so the next checkout returns the same connection; concurrent
    # requests in other tests leave several idle ones behind.
    await async_engine().dispose()
    async with async_tenant_session(tenant) as session:
        pid, _ = (await session.execute(PID_AND_TENANT)).one()

    async with async_engine().connect() as conn:
        assert tuple((await conn.execute(PID_AND_TENANT)).one()) == (pid, "")
        assert await conn.scalar(COUNT_USERS) == 0


# Catalog checks: cover every table, including ones later migrations add.


def test_every_tenant_table_has_forced_rls_and_one_standard_policy() -> None:
    with sync_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,"
                "  array_agg(format('%s %s %s %s', p.polcmd, p.polpermissive,"
                "    pg_get_expr(p.polqual, c.oid), pg_get_expr(p.polwithcheck, c.oid)))"
                "    FILTER (WHERE p.oid IS NOT NULL)"
                " FROM pg_class c"
                " JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id'"
                " LEFT JOIN pg_policy p ON p.polrelid = c.oid"
                " WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')"
                " GROUP BY c.oid"
            )
        ).all()

    current = "NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)"
    standard = f"(tenant_id = ({current})::uuid)"
    assert "users" in {row[0] for row in rows}
    for name, enabled, forced, policies in rows:
        assert (name, enabled, forced) == (name, True, True)
        # '*': applies to all commands; 't': permissive.
        assert (name, policies) == (name, [f"* t {standard} {standard}"])


def test_app_role_owns_nothing_and_cannot_bypass_rls() -> None:
    with sync_engine().connect() as conn:
        assert conn.scalar(text("SELECT current_user")) == "ats_app"
        # Superusers skip RLS too; membership in ats_owner would allow SET ROLE to the owner.
        assert tuple(
            conn.execute(
                text(
                    "SELECT rolbypassrls, rolsuper, pg_has_role('ats_app', 'ats_owner', 'MEMBER')"
                    " FROM pg_roles WHERE rolname = 'ats_app'"
                )
            ).one()
        ) == (False, False, False)
        assert (
            conn.scalar(text("SELECT count(*) FROM pg_class WHERE relowner = 'ats_app'::regrole"))
            == 0
        )
