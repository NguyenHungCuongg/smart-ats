"""ats_app reads only its own tenants row and writes none (ERD §2)

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Default privileges gave ats_app DML here; Tenants are created as ats_owner (app.seed).
    op.execute("REVOKE ALL ON tenants FROM ats_app")
    op.execute("GRANT SELECT ON tenants TO ats_app")
    # Enabled, not forced: the owner still sees every Tenant, which auth_find_user's
    # SECURITY DEFINER loop over all Tenants relies on (ERD §8).
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY own_tenant ON tenants FOR SELECT
          USING (id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY own_tenant ON tenants")
    op.execute("ALTER TABLE tenants DISABLE ROW LEVEL SECURITY")
    op.execute("GRANT INSERT, UPDATE, DELETE ON tenants TO ats_app")
