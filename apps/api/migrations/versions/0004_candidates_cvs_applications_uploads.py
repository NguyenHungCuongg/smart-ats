"""candidates, cv_documents, applications, upload_batches, upload_batch_items with forced RLS
(ERD §3)

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
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
        CREATE TABLE candidates (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          full_name text,
          email citext,
          phone text,
          links jsonb,
          consent_source text NOT NULL
            CHECK (consent_source IN ('PUBLIC_APPLY_CONSENT', 'RECRUITER_ATTESTED')),
          consent_at timestamptz NOT NULL,
          consent_notice_version text,
          last_activity_at timestamptz NOT NULL,
          anonymized_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          -- Dedupe by email (FR-A1.2); NULLs never collide, so CVs without one stay apart.
          UNIQUE (tenant_id, email),
          UNIQUE (tenant_id, id)
        )
    """)
    _force_rls("candidates")

    op.execute("""
        CREATE TABLE cv_documents (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          candidate_id uuid NOT NULL,
          storage_key text NOT NULL,
          file_name text NOT NULL,
          mime_type text NOT NULL,
          sha256 text NOT NULL,
          parse_status text NOT NULL CHECK (parse_status IN ('PENDING', 'PARSED', 'FAILED')),
          parsed_profile jsonb,
          blind_profile jsonb,
          field_verification jsonb,
          suspicious_content boolean NOT NULL DEFAULT false,
          embedding vector(1536),
          embedding_model text,
          parser_model text,
          parser_prompt_version text,
          parsed_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          -- Dedupe by content (FR-A1.2).
          UNIQUE (tenant_id, sha256),
          UNIQUE (tenant_id, id),
          FOREIGN KEY (tenant_id, candidate_id) REFERENCES candidates (tenant_id, id)
        )
    """)
    _force_rls("cv_documents")

    op.execute("""
        CREATE TABLE applications (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          job_id uuid NOT NULL,
          candidate_id uuid NOT NULL,
          cv_document_id uuid NOT NULL,
          source text NOT NULL CHECK (source IN ('UPLOAD', 'PUBLIC_APPLY', 'REDISCOVERY')),
          stage text NOT NULL CHECK (stage IN ('APPLIED', 'SCREENING', 'SHORTLISTED', 'INTERVIEW',
            'OFFER', 'HIRED', 'REJECTED')),
          rejected_reason text,
          version int NOT NULL DEFAULT 0,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (job_id, candidate_id),
          UNIQUE (tenant_id, id),
          FOREIGN KEY (tenant_id, job_id) REFERENCES jobs (tenant_id, id),
          FOREIGN KEY (tenant_id, candidate_id) REFERENCES candidates (tenant_id, id),
          FOREIGN KEY (tenant_id, cv_document_id) REFERENCES cv_documents (tenant_id, id)
        )
    """)
    _force_rls("applications")

    op.execute("""
        CREATE TABLE upload_batches (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          job_id uuid,
          created_by uuid NOT NULL,
          total_count int NOT NULL,
          status text NOT NULL CHECK (status IN ('PROCESSING', 'COMPLETED')),
          created_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          UNIQUE (tenant_id, id),
          FOREIGN KEY (tenant_id, job_id) REFERENCES jobs (tenant_id, id),
          FOREIGN KEY (tenant_id, created_by) REFERENCES users (tenant_id, id)
        )
    """)
    _force_rls("upload_batches")

    op.execute("""
        CREATE TABLE upload_batch_items (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          batch_id uuid NOT NULL,
          file_name text NOT NULL,
          storage_key text NOT NULL,
          status text NOT NULL CHECK (status IN ('PENDING', 'SUCCEEDED', 'FAILED')),
          cv_document_id uuid,
          dedupe text CHECK (dedupe IN ('EXISTING_CANDIDATE', 'CV_REPLACED', 'ALREADY_APPLIED')),
          error_code text,
          error_message text,
          attempts int NOT NULL DEFAULT 0,
          UNIQUE (tenant_id, id),
          FOREIGN KEY (tenant_id, batch_id) REFERENCES upload_batches (tenant_id, id),
          FOREIGN KEY (tenant_id, cv_document_id) REFERENCES cv_documents (tenant_id, id)
        )
    """)
    op.execute("CREATE INDEX ON upload_batch_items (batch_id)")
    _force_rls("upload_batch_items")


def downgrade() -> None:
    for table in (
        "upload_batch_items",
        "upload_batches",
        "applications",
        "cv_documents",
        "candidates",
    ):
        op.execute(f"DROP TABLE {table}")
