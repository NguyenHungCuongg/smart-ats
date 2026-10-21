"""application_stage_history with forced RLS, append-only, backfilled (ERD §3)

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # campaign_id comes with campaigns (FR-A0).
    op.execute("""
        CREATE TABLE application_stage_history (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          application_id uuid NOT NULL,
          -- The Stages of applications.stage (0004).
          from_stage text CHECK (from_stage IN ('APPLIED', 'SCREENING', 'SHORTLISTED',
            'INTERVIEW', 'OFFER', 'HIRED', 'REJECTED')),
          to_stage text NOT NULL CHECK (to_stage IN ('APPLIED', 'SCREENING', 'SHORTLISTED',
            'INTERVIEW', 'OFFER', 'HIRED', 'REJECTED')),
          changed_by uuid,
          note text,
          changed_at timestamptz NOT NULL DEFAULT now(),
          FOREIGN KEY (tenant_id, application_id) REFERENCES applications (tenant_id, id),
          FOREIGN KEY (tenant_id, changed_by) REFERENCES users (tenant_id, id)
        )
    """)
    # An Application's history, in order.
    op.execute("CREATE INDEX ON application_stage_history (tenant_id, application_id, changed_at)")
    # The one policy every tenant table gets (ERD §1), as in 0001.
    op.execute("ALTER TABLE application_stage_history ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE application_stage_history FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON application_stage_history
          USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    """)
    op.execute("REVOKE UPDATE, DELETE ON application_stage_history FROM ats_app")

    # Each Application so far gets its creation, as near as the data allows: applications has
    # no link to its Upload Batch. Forced RLS binds the owner too, so Tenant by Tenant; tenants
    # is not forced, so the owner sees every one.
    op.execute("""
        DO $$
        DECLARE t uuid;
        BEGIN
          FOR t IN SELECT id FROM tenants LOOP
            PERFORM set_config('app.current_tenant_id', t::text, true);
            INSERT INTO application_stage_history (tenant_id, application_id, from_stage,
              to_stage, changed_by, note, changed_at)
            SELECT a.tenant_id, a.id, NULL, a.stage, j.created_by, 'backfill', a.created_at
            FROM applications a JOIN jobs j ON j.id = a.job_id;
          END LOOP;
          PERFORM set_config('app.current_tenant_id', '', true);
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE application_stage_history")
