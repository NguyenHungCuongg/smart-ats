"""email_messages, invitations with forced RLS and accept_invitation (ERD §2, §6, §8)

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
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
    # Also the email outbox (SAD §5.4): attempts and enqueued_at as on the other outbox-style
    # rows, for beat's sweep (SAD §6).
    op.execute("""
        CREATE TABLE email_messages (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          application_id uuid,
          kind text NOT NULL CHECK (kind IN ('INVITE_INTERVIEW', 'RESULT', 'FOLLOW_UP',
            'APPLY_RECEIPT', 'MEMBER_INVITATION')),
          tone text CHECK (tone IN ('FORMAL', 'FRIENDLY', 'CONCISE')),
          to_address citext NOT NULL,
          subject text NOT NULL,
          body text NOT NULL,
          status text NOT NULL CHECK (status IN ('DRAFT', 'QUEUED', 'SENT', 'FAILED')),
          provider_message_id text,
          attempts int NOT NULL DEFAULT 0,
          enqueued_at timestamptz,
          sent_by uuid,
          created_at timestamptz NOT NULL DEFAULT now(),
          sent_at timestamptz,
          UNIQUE (tenant_id, id),
          FOREIGN KEY (tenant_id, application_id) REFERENCES applications (tenant_id, id),
          FOREIGN KEY (tenant_id, sent_by) REFERENCES users (tenant_id, id)
        )
    """)
    _force_rls("email_messages")

    op.execute("""
        CREATE TABLE invitations (
          id uuid PRIMARY KEY DEFAULT uuidv7(),
          tenant_id uuid NOT NULL REFERENCES tenants (id),
          email citext NOT NULL,
          role text NOT NULL CHECK (role IN ('COMPANY_ADMIN', 'RECRUITER', 'REVIEWER')),
          token_hash text NOT NULL UNIQUE,
          invited_by uuid NOT NULL,
          email_id uuid NOT NULL,
          expires_at timestamptz NOT NULL,
          accepted_at timestamptz,
          revoked_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (tenant_id, id),
          FOREIGN KEY (tenant_id, invited_by) REFERENCES users (tenant_id, id),
          FOREIGN KEY (tenant_id, email_id) REFERENCES email_messages (tenant_id, id)
        )
    """)
    # Pending invitations of an email, which a new one revokes.
    op.execute("CREATE INDEX ON invitations (tenant_id, email)")
    _force_rls("invitations")

    # The invitee has no Tenant context yet (ERD §8). Like auth_find_user (0002), it tries each
    # Tenant's context in turn and restores the caller's; the caller sets the returned Tenant's.
    # The UPDATE locks the row, so of two concurrent accepts of one token only the first wins.
    op.execute("""
        CREATE FUNCTION accept_invitation(p_token_hash text)
        RETURNS TABLE (tenant_id uuid, email citext, role text)
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
              UPDATE invitations i SET accepted_at = now()
              WHERE i.token_hash = p_token_hash AND i.accepted_at IS NULL
                AND i.revoked_at IS NULL AND i.expires_at > now()
              RETURNING i.tenant_id, i.email, i.role;
            EXIT WHEN FOUND;
          END LOOP;
          PERFORM set_config('app.current_tenant_id', coalesce(caller_tenant, ''), true);
        END
        $$
    """)
    op.execute("REVOKE EXECUTE ON FUNCTION accept_invitation(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION accept_invitation(text) TO ats_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION accept_invitation(text)")
    op.execute("DROP TABLE invitations")
    op.execute("DROP TABLE email_messages")
