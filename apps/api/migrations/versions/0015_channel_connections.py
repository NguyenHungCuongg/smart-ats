"""channel_connections with forced RLS (ERD §6, SAD §5.6)

Revision ID: 0015
Revises: 0014
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE channel_connections (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          channel text NOT NULL CHECK (channel IN ('FACEBOOK_PAGE')),
          external_id text NOT NULL,
          name text NOT NULL,
          token_ciphertext bytea NOT NULL,
          connected_by uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          FOREIGN KEY (tenant_id, connected_by) REFERENCES users (tenant_id, id),
          UNIQUE (tenant_id, channel)
        )
    """)
    op.execute("ALTER TABLE channel_connections ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE channel_connections FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON channel_connections
          USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE channel_connections")
