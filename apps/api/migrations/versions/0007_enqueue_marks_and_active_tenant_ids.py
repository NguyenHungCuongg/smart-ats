"""Enqueue marks on the outbox-style rows and active_tenant_ids for beat's sweep (ERD §3, §4, §8)

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Set and counted by every enqueue, first or by the sweep (SAD §6).
    op.execute("ALTER TABLE jobs ADD parse_attempts int NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE jobs ADD parse_enqueued_at timestamptz")
    op.execute("ALTER TABLE upload_batch_items ADD enqueued_at timestamptz")
    op.execute("ALTER TABLE score_results ADD attempts int NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE score_results ADD enqueued_at timestamptz")
    # Rows pending now count as enqueued once, now: the sweep takes them up if they stay so.
    op.execute(
        "UPDATE jobs SET parse_attempts = 1, parse_enqueued_at = now()"
        " WHERE parse_status = 'PENDING'"
    )
    for table in ("upload_batch_items", "score_results"):
        op.execute(
            f"UPDATE {table} SET attempts = greatest(attempts, 1), enqueued_at = now()"
            " WHERE status = 'PENDING'"
        )

    # The sweep runs in no Tenant, and ats_app sees only its own tenants row (0006). tenants
    # has RLS enabled but not forced, so the owner sees every row here.
    op.execute("""
        CREATE FUNCTION active_tenant_ids() RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$ SELECT id FROM tenants WHERE status = 'ACTIVE' $$
    """)
    op.execute("REVOKE EXECUTE ON FUNCTION active_tenant_ids() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION active_tenant_ids() TO ats_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION active_tenant_ids()")
    op.execute("ALTER TABLE score_results DROP enqueued_at, DROP attempts")
    op.execute("ALTER TABLE upload_batch_items DROP enqueued_at")
    op.execute("ALTER TABLE jobs DROP parse_enqueued_at, DROP parse_attempts")
