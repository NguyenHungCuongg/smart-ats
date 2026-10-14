"""tenants and users with forced RLS (ERD §1, §2)

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Default privileges give ats_app DML on every ats_owner table, this one included.
    op.execute("REVOKE ALL ON alembic_version FROM ats_app")

    # No RLS: a platform table (ERD §2).
    op.execute("""
        CREATE TABLE tenants (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          name text NOT NULL,
          slug text NOT NULL UNIQUE,
          logo_url text,
          plan_type text NOT NULL CHECK (plan_type IN ('FREE', 'STARTER', 'GROWTH')),
          ai_budget_monthly_usd numeric(10, 2) NOT NULL,
          max_llm_concurrency int NOT NULL DEFAULT 5,
          retention_months int NOT NULL DEFAULT 12,
          privacy_notice_url text,
          status text NOT NULL CHECK (status IN ('ACTIVE', 'SUSPENDED')),
          created_at timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE users (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid REFERENCES tenants (id),
          email citext NOT NULL UNIQUE,
          password_hash text,
          google_sub text UNIQUE,
          full_name text NOT NULL,
          role text NOT NULL
            CHECK (role IN ('SYSTEM_ADMIN', 'COMPANY_ADMIN', 'RECRUITER', 'REVIEWER')),
          is_active boolean NOT NULL,
          failed_login_count int NOT NULL DEFAULT 0,
          locked_until timestamptz,
          last_login_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          CHECK ((role = 'SYSTEM_ADMIN') = (tenant_id IS NULL)),
          -- Target of composite (tenant_id, id) foreign keys; also the tenant_id index.
          UNIQUE (tenant_id, id)
        )
    """)
    # The one policy every tenant table gets (ERD §1). NULLIF: a pooled connection that has
    # held the setting reads back '' rather than NULL, and ''::uuid raises (ADR-0001).
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON users
          USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE users")
    op.execute("DROP TABLE tenants")
