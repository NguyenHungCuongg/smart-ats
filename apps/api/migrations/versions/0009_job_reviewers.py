"""job_reviewers (Reviewer Assignment) with forced RLS (ERD §3)

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # That user_id is a Reviewer is checked by the API: the role is a column of another table.
    op.execute("""
        CREATE TABLE job_reviewers (
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          job_id uuid NOT NULL,
          user_id uuid NOT NULL,
          assigned_by uuid NOT NULL,
          assigned_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (job_id, user_id),
          FOREIGN KEY (tenant_id, job_id) REFERENCES jobs (tenant_id, id),
          FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id),
          FOREIGN KEY (tenant_id, assigned_by) REFERENCES users (tenant_id, id)
        )
    """)
    # A Reviewer's list of Jobs.
    op.execute("CREATE INDEX ON job_reviewers (user_id)")
    # The one policy every tenant table gets (ERD §1), as in 0001.
    op.execute("ALTER TABLE job_reviewers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE job_reviewers FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON job_reviewers
          USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE job_reviewers")
