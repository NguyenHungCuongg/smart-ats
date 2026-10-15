"""jobs and ai_usage_entries with forced RLS (ERD §3, §7)

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
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
    op.execute("""
        CREATE TABLE jobs (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          title text NOT NULL,
          level text NOT NULL
            CHECK (level IN ('INTERN', 'JUNIOR', 'MID', 'SENIOR', 'LEAD', 'MANAGER')),
          department text,
          location text,
          work_mode text CHECK (work_mode IN ('REMOTE', 'HYBRID', 'ONSITE')),
          status text NOT NULL
            CHECK (status IN ('DRAFT', 'PUBLISHED', 'PAUSED', 'CLOSED', 'ARCHIVED')),
          jd_document_key text,
          parse_status text NOT NULL CHECK (parse_status IN ('PENDING', 'SUCCEEDED', 'FAILED')),
          parse_error text,
          criteria jsonb,
          criteria_verification jsonb,
          criteria_confirmed_at timestamptz,
          criteria_embedding vector(1536),
          weight_technical numeric(3, 2) NOT NULL CHECK (weight_technical >= 0),
          weight_soft_skills numeric(3, 2) NOT NULL CHECK (weight_soft_skills >= 0),
          weight_experience numeric(3, 2) NOT NULL CHECK (weight_experience >= 0),
          public_apply_enabled boolean NOT NULL DEFAULT false,
          public_slug text UNIQUE,
          apply_deadline date,
          created_by uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          -- FR-A1.1: the three axes make 100%.
          CHECK (weight_technical + weight_soft_skills + weight_experience = 1.00),
          -- Only confirmed criteria get scored, so there must be criteria to confirm.
          CHECK (criteria_confirmed_at IS NULL OR criteria IS NOT NULL),
          UNIQUE (tenant_id, id),
          FOREIGN KEY (tenant_id, created_by) REFERENCES users (tenant_id, id)
        )
    """)
    _force_rls("jobs")

    op.execute("""
        CREATE TABLE ai_usage_entries (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          user_id uuid,
          feature text NOT NULL CHECK (feature IN ('JOB_PARSE', 'CV_PARSE', 'OCR', 'SCORING',
            'INTERVIEW_Q', 'EMAIL', 'AGENT', 'EMBEDDING')),
          model text NOT NULL,
          input_tokens int NOT NULL,
          output_tokens int NOT NULL,
          cached_tokens int NOT NULL,
          cost_usd numeric(12, 6) NOT NULL,
          ref_type text,
          ref_id uuid,
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (tenant_id, id),
          FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id)
        )
    """)
    # Monthly cost per Tenant (ERD §9).
    op.execute("CREATE INDEX ON ai_usage_entries (tenant_id, created_at)")
    _force_rls("ai_usage_entries")
    # Append-only: the ledger is what AI Budget is checked against (FR-C1.4).
    op.execute("REVOKE UPDATE, DELETE ON ai_usage_entries FROM ats_app")


def downgrade() -> None:
    op.execute("DROP TABLE ai_usage_entries")
    op.execute("DROP TABLE jobs")
