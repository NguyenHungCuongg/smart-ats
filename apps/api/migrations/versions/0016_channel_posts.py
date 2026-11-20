"""channel_posts with forced RLS (ERD §6, SAD §5.6)

Revision ID: 0016
Revises: 0015
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE channel_posts (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          job_id uuid NOT NULL,
          channel text NOT NULL CHECK (channel IN ('FACEBOOK_PAGE')),
          target_id text NOT NULL,
          external_post_id text NOT NULL,
          url text NOT NULL,
          body text NOT NULL,
          posted_by uuid NOT NULL,
          posted_at timestamptz NOT NULL DEFAULT now(),
          FOREIGN KEY (tenant_id, job_id) REFERENCES jobs (tenant_id, id),
          FOREIGN KEY (tenant_id, posted_by) REFERENCES users (tenant_id, id),
          UNIQUE (tenant_id, job_id, channel, target_id)
        )
    """)
    op.execute("ALTER TABLE channel_posts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE channel_posts FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON channel_posts
          USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE channel_posts")
