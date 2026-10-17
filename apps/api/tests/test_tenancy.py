"""Forced RLS on tenant tables (ADR-0001, SAD §4.2, ERD §1), checked as ats_app."""

import os
import uuid
from functools import cache

import psycopg
import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.db import async_engine, async_tenant_session, sync_engine, tenant_session

pytestmark = pytest.mark.usefixtures("database")

COUNT_USERS = text("SELECT count(*) FROM users")
PID_AND_TENANT = text("SELECT pg_backend_pid(), current_setting('app.current_tenant_id', true)")


@cache
def owner_engine() -> Engine:
    """ats_owner: ats_app cannot write tenants, so tests create them as the owner, like the seed."""
    return create_engine(os.environ["DATABASE_MIGRATION_URL"])


def make_tenant() -> uuid.UUID:
    slug = f"t-{uuid.uuid4().hex}"
    with owner_engine().begin() as conn:
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


@pytest.mark.cross_tenant
def test_other_tenant_context_sees_no_rows(tenant: uuid.UUID) -> None:
    with tenant_session(make_tenant()) as session:
        assert session.scalar(COUNT_USERS) == 0


@pytest.mark.cross_tenant
def test_insert_for_other_tenant_is_rejected(tenant: uuid.UUID) -> None:
    other = make_tenant()
    with pytest.raises(ProgrammingError) as exc, tenant_session(tenant) as session:
        insert_user(session, other)
    assert isinstance(exc.value.orig, psycopg.errors.InsufficientPrivilege)


@pytest.mark.cross_tenant
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


@pytest.mark.cross_tenant
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


@pytest.mark.cross_tenant
def test_tenant_reads_only_its_own_tenant_row(tenant: uuid.UUID) -> None:
    make_tenant()
    with tenant_session(tenant) as session:
        assert session.scalars(text("SELECT id FROM tenants")).all() == [tenant]


@pytest.mark.cross_tenant
def test_no_context_reads_no_tenant_row(tenant: uuid.UUID) -> None:
    with sync_engine().connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM tenants")) == 0


@pytest.mark.cross_tenant
@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO tenants (name, slug, plan_type, ai_budget_monthly_usd, status)"
        " VALUES ('x', :slug, 'FREE', 10, 'ACTIVE')",
        "UPDATE tenants SET ai_budget_monthly_usd = 1000 WHERE id IN (:own, :other)",
        "DELETE FROM tenants WHERE id IN (:own, :other)",
    ],
)
def test_tenant_cannot_write_tenants(tenant: uuid.UUID, statement: str) -> None:
    params = {"slug": f"t-{uuid.uuid4().hex}", "own": tenant, "other": make_tenant()}
    with pytest.raises(ProgrammingError) as exc, tenant_session(tenant) as session:
        session.execute(text(statement), params)
    assert isinstance(exc.value.orig, psycopg.errors.InsufficientPrivilege)


# One INSERT per tenant table, in foreign-key order. Every value comes from :t (the Tenant) or
# ids[...], so the same statements seed Tenant A and then attempt to write into it from B.

TENANT_TABLES = {
    "jobs": (
        "INSERT INTO jobs (id, tenant_id, title, level, status, parse_status, weight_technical,"
        " weight_soft_skills, weight_experience, created_by)"
        " VALUES (:jobs, :t, 'Engineer', 'MID', 'DRAFT', 'PENDING', 0.5, 0.25, 0.25, :users)"
    ),
    "candidates": (
        "INSERT INTO candidates (id, tenant_id, consent_source, consent_at, last_activity_at)"
        " VALUES (:candidates, :t, 'RECRUITER_ATTESTED', now(), now())"
    ),
    "cv_documents": (
        "INSERT INTO cv_documents (id, tenant_id, candidate_id, storage_key, file_name, mime_type,"
        " sha256, parse_status) VALUES (:cv_documents, :t, :candidates, 'k', 'cv.pdf',"
        " 'application/pdf', :cv_documents, 'PENDING')"
    ),
    "applications": (
        "INSERT INTO applications (id, tenant_id, job_id, candidate_id, cv_document_id, source,"
        " stage) VALUES (:applications, :t, :jobs, :candidates, :cv_documents, 'UPLOAD', 'APPLIED')"
    ),
    "upload_batches": (
        "INSERT INTO upload_batches (id, tenant_id, job_id, created_by, total_count, status)"
        " VALUES (:upload_batches, :t, :jobs, :users, 1, 'PROCESSING')"
    ),
    "upload_batch_items": (
        "INSERT INTO upload_batch_items (id, tenant_id, batch_id, file_name, storage_key, status)"
        " VALUES (:upload_batch_items, :t, :upload_batches, 'cv.pdf', 'k', 'PENDING')"
    ),
    "scoring_runs": (
        "INSERT INTO scoring_runs (id, tenant_id, job_id, trigger_mode, weights, criteria_snapshot,"
        " model, prompt_version, rubric_version, status)"
        " VALUES (:scoring_runs, :t, :jobs, 'MANUAL', '{}', '{}', 'm', 'p', 'r', 'RUNNING')"
    ),
    "score_results": (
        "INSERT INTO score_results (id, tenant_id, scoring_run_id, application_id, cv_document_id,"
        " status) VALUES (:score_results, :t, :scoring_runs, :applications, :cv_documents,"
        " 'PENDING')"
    ),
    "ai_usage_entries": (
        "INSERT INTO ai_usage_entries (id, tenant_id, feature, model, input_tokens, output_tokens,"
        " cached_tokens, cost_usd) VALUES (:ai_usage_entries, :t, 'SCORING', 'm', 1, 1, 0, 0.01)"
    ),
}


def insert_rows(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    ids = {name: uuid.uuid4() for name in TENANT_TABLES} | {"users": user_id}
    for statement in TENANT_TABLES.values():
        session.execute(text(statement), {"t": tenant_id} | ids)


@pytest.fixture
def tenant_with_rows(tenant: uuid.UUID) -> uuid.UUID:
    with tenant_session(tenant) as session:
        user_id = session.scalar(text("SELECT id FROM users"))
        assert user_id is not None
        insert_rows(session, tenant, user_id)
    return tenant


@pytest.mark.cross_tenant
@pytest.mark.parametrize("table", TENANT_TABLES)
def test_other_tenant_context_reads_no_rows_of(table: str, tenant_with_rows: uuid.UUID) -> None:
    count = text(f"SELECT count(*) FROM {table}")
    with tenant_session(tenant_with_rows) as session:
        assert session.scalar(count) == 1
    with tenant_session(make_tenant()) as session:
        assert session.scalar(count) == 0


@pytest.mark.cross_tenant
@pytest.mark.parametrize("table", TENANT_TABLES)
def test_other_tenant_context_cannot_write_rows_of(table: str, tenant_with_rows: uuid.UUID) -> None:
    ids = {name: uuid.uuid4() for name in [*TENANT_TABLES, "users"]}
    with pytest.raises(ProgrammingError) as exc, tenant_session(make_tenant()) as session:
        session.execute(text(TENANT_TABLES[table]), {"t": tenant_with_rows} | ids)
    assert isinstance(exc.value.orig, psycopg.errors.InsufficientPrivilege)


# Catalog checks: each query covers every table, including ones later migrations add, and
# returns the violations, so test_catalog_checks_catch_a_violating_table can prove it works.

CURRENT = "NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)"
STANDARD = f"(tenant_id = ({CURRENT})::uuid)"


def rls_violations(conn: Connection) -> set[str]:
    """Tenant tables without forced RLS and exactly the one standard policy."""
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
    # '*': applies to all commands; 't': permissive.
    standard = (True, True, [f"* t {STANDARD} {STANDARD}"])
    return {name for name, *rls in rows if tuple(rls) != standard}


def nullable_tenant_ids(conn: Connection) -> set[str]:
    return set(
        conn.scalars(
            text(
                "SELECT c.relname FROM pg_class c"
                " JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id'"
                " WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')"
                "  AND NOT a.attnotnull"
            )
        )
    )


def tenant_fks_without_tenant_id(conn: Connection) -> set[str]:
    """Foreign keys between two tenant tables that do not match tenant_id to tenant_id.

    Referential checks skip RLS, so such a key can point at another Tenant's row (ERD §1).
    """
    return set(
        conn.scalars(
            text(
                "SELECT format('%s.%s', k.conrelid::regclass, k.conname) FROM pg_constraint k"
                " JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attname = 'tenant_id'"
                " JOIN pg_attribute r ON r.attrelid = k.confrelid AND r.attname = 'tenant_id'"
                " WHERE k.contype = 'f' AND k.connamespace = 'public'::regnamespace"
                "  AND NOT EXISTS (SELECT FROM unnest(k.conkey, k.confkey) AS key (col, ref)"
                "    WHERE (key.col, key.ref) = (a.attnum, r.attnum))"
            )
        )
    )


def test_every_tenant_table_has_forced_rls_and_one_standard_policy() -> None:
    with sync_engine().connect() as conn:
        assert rls_violations(conn) == set()


def test_tenant_id_is_not_null_except_for_system_admins() -> None:
    # The one exception: a System Admin's users row has no Tenant (ERD §2).
    with sync_engine().connect() as conn:
        assert nullable_tenant_ids(conn) == {"users"}


def test_foreign_keys_between_tenant_tables_include_tenant_id() -> None:
    with sync_engine().connect() as conn:
        assert tenant_fks_without_tenant_id(conn) == set()


def test_catalog_checks_catch_a_violating_table() -> None:
    # Never committed: the connection rolls back on exit, so no other test sees the table.
    with owner_engine().connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE violation (id uuid PRIMARY KEY,"
                " tenant_id uuid REFERENCES tenants (id), job_id uuid REFERENCES jobs (id))"
            )
        )
        assert "violation" in rls_violations(conn)
        assert "violation" in nullable_tenant_ids(conn)
        assert tenant_fks_without_tenant_id(conn) == {"violation.violation_job_id_fkey"}


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
