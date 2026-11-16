"""audit_logs with forced RLS, append-only, backfilled from stage history (ERD §7)

Revision ID: 0014
Revises: 0013
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # campaign_id comes with campaigns (FR-A0).
    # entity_id has no foreign key: it points to a Job, Application, Invitation or Member.
    op.execute("""
        CREATE TABLE audit_logs (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          actor_type text NOT NULL CHECK (actor_type IN ('USER', 'AGENT', 'SYSTEM', 'PUBLIC')),
          actor_user_id uuid,
          action text NOT NULL,
          entity_type text NOT NULL,
          entity_id uuid NOT NULL,
          before jsonb,
          after jsonb,
          request_id text,
          ip inet,
          created_at timestamptz NOT NULL DEFAULT now(),
          CHECK ((actor_type IN ('USER', 'AGENT')) = (actor_user_id IS NOT NULL)),
          FOREIGN KEY (tenant_id, actor_user_id) REFERENCES users (tenant_id, id)
        )
    """)
    # Keyset pagination of an entity's Activity Timeline, newest first.
    op.execute("CREATE INDEX ON audit_logs (tenant_id, entity_type, entity_id, created_at, id)")
    # The one policy every tenant table gets (ERD §1), as in 0001.
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON audit_logs
          USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    """)
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM ats_app")

    # Backfill existing Stage history rows into audit_logs, Tenant by Tenant under forced RLS.
    op.execute("""
        DO $$
        DECLARE t uuid;
        BEGIN
          FOR t IN SELECT id FROM tenants LOOP
            PERFORM set_config('app.current_tenant_id', t::text, true);
            INSERT INTO audit_logs (tenant_id, actor_type, actor_user_id, action,
              entity_type, entity_id, before, after, created_at)
            SELECT
              h.tenant_id,
              CASE WHEN h.changed_by IS NULL THEN 'PUBLIC' ELSE 'USER' END,
              h.changed_by,
              CASE WHEN h.from_stage IS NULL THEN 'application.created'
                   ELSE 'application.stage_changed' END,
              'application',
              h.application_id,
              CASE WHEN h.from_stage IS NULL THEN NULL
                   ELSE jsonb_build_object('stage', h.from_stage) END,
              CASE WHEN h.from_stage IS NULL THEN jsonb_build_object(
                     'source', a.source,
                     'candidate_id', a.candidate_id,
                     'cv_document_id', a.cv_document_id,
                     'stage', h.to_stage
                   )
                   ELSE jsonb_build_object('stage', h.to_stage) END,
              h.changed_at
            FROM application_stage_history h
            JOIN applications a ON a.id = h.application_id
            ORDER BY h.changed_at, h.id;
          END LOOP;
          PERFORM set_config('app.current_tenant_id', '', true);
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE audit_logs")
