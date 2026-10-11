"""refresh_tokens with forced RLS and auth_find_user (ERD §2, §8)

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE refresh_tokens (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          user_id uuid NOT NULL,
          family_id uuid NOT NULL,
          token_hash text NOT NULL UNIQUE,
          expires_at timestamptz NOT NULL,
          revoked_at timestamptz,
          replaced_by_id uuid,
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (tenant_id, id),
          FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id),
          FOREIGN KEY (tenant_id, replaced_by_id) REFERENCES refresh_tokens (tenant_id, id)
        )
    """)
    # Revoking a family on reuse or logout looks up all its tokens.
    op.execute("CREATE INDEX ON refresh_tokens (tenant_id, family_id)")
    op.execute("ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE refresh_tokens FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON refresh_tokens
          USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    """)

    # Login knows the email but not the Tenant (ERD §8). FORCE RLS binds ats_owner too, so even
    # as SECURITY DEFINER the function sees users only under a tenant context: it tries each
    # Tenant's context in turn, then restores the caller's. Emails are unique platform-wide.
    # ponytail: one users lookup per Tenant per login; a lookup table if Tenants reach thousands.
    op.execute("""
        CREATE FUNCTION auth_find_user(p_email citext)
        RETURNS TABLE (id uuid, tenant_id uuid, role text, password_hash text,
                       is_active boolean, locked_until timestamptz)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
        #variable_conflict use_column
        DECLARE
          caller_tenant text := current_setting('app.current_tenant_id', true);
          t uuid;
        BEGIN
          FOR t IN SELECT tenants.id FROM tenants LOOP
            PERFORM set_config('app.current_tenant_id', t::text, true);
            RETURN QUERY
              SELECT u.id, u.tenant_id, u.role, u.password_hash, u.is_active, u.locked_until
              FROM users u WHERE u.email = p_email;
            EXIT WHEN FOUND;
          END LOOP;
          PERFORM set_config('app.current_tenant_id', coalesce(caller_tenant, ''), true);
        END
        $$
    """)
    op.execute("REVOKE EXECUTE ON FUNCTION auth_find_user(citext) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION auth_find_user(citext) TO ats_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION auth_find_user(citext)")
    op.execute("DROP TABLE refresh_tokens")
