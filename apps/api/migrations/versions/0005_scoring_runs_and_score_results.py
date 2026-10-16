"""scoring_runs and score_results with forced RLS (ERD §4)

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _force_rls(table: str) -> None:
    # The one policy every tenant table gets (ERD §1), as in 0001.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
          USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    """)


def upgrade() -> None:
    # campaign_id comes with campaigns (M4), as a nullable column that needs no backfill.
    op.execute("""
        CREATE TABLE scoring_runs (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          job_id uuid NOT NULL,
          trigger_mode text NOT NULL CHECK (trigger_mode IN ('MANUAL', 'AGENT')),
          weights jsonb NOT NULL,
          criteria_snapshot jsonb NOT NULL,
          model text NOT NULL,
          prompt_version text NOT NULL,
          rubric_version text NOT NULL,
          status text NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'PARTIAL')),
          created_by uuid,
          created_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          UNIQUE (tenant_id, id),
          FOREIGN KEY (tenant_id, job_id) REFERENCES jobs (tenant_id, id),
          FOREIGN KEY (tenant_id, created_by) REFERENCES users (tenant_id, id)
        )
    """)
    # The latest run of a Job.
    op.execute("CREATE INDEX ON scoring_runs (tenant_id, job_id, created_at)")
    _force_rls("scoring_runs")

    op.execute("""
        CREATE TABLE score_results (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          scoring_run_id uuid NOT NULL,
          application_id uuid NOT NULL,
          cv_document_id uuid NOT NULL,
          status text NOT NULL CHECK (status IN ('PENDING', 'SCORED', 'FAILED')),
          technical_score numeric(5, 2),
          soft_skills_score numeric(5, 2),
          experience_score numeric(5, 2),
          must_have_coverage numeric(4, 3),
          must_have_detail jsonb,
          total_score numeric(5, 2),
          rubric_grades jsonb,
          fit_gap_report jsonb,
          grounding_rate numeric(4, 3),
          error_code text,
          created_at timestamptz NOT NULL DEFAULT now(),
          -- The idempotency key: a redelivered task finds its own row (SAD §5.2).
          UNIQUE (scoring_run_id, application_id),
          UNIQUE (tenant_id, id),
          FOREIGN KEY (tenant_id, scoring_run_id) REFERENCES scoring_runs (tenant_id, id),
          FOREIGN KEY (tenant_id, application_id) REFERENCES applications (tenant_id, id),
          FOREIGN KEY (tenant_id, cv_document_id) REFERENCES cv_documents (tenant_id, id)
        )
    """)
    _force_rls("score_results")


def downgrade() -> None:
    op.execute("DROP TABLE score_results")
    op.execute("DROP TABLE scoring_runs")
