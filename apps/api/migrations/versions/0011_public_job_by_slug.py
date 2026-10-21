"""public_job_by_slug SECURITY DEFINER lookup (ERD §8)

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Look up a Job by public_slug before knowing the Tenant (ERD §8, SAD §4.2). Like auth_find_user
    # (0002) and accept_invitation (0008), it tries each active Tenant's context in turn and
    # restores the caller's context. Returns only public columns, with criteria minus salary_range.
    op.execute("""
        CREATE FUNCTION public_job_by_slug(p_slug text)
        RETURNS TABLE (
          tenant_id uuid,
          job_id uuid,
          title text,
          status text,
          public_apply_enabled boolean,
          apply_deadline date,
          location text,
          work_mode text,
          criteria jsonb,
          tenant_name text,
          tenant_logo_url text,
          tenant_privacy_notice_url text
        )
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
        #variable_conflict use_column
        DECLARE
          caller_tenant text := current_setting('app.current_tenant_id', true);
          t uuid;
        BEGIN
          IF p_slug IS NULL OR trim(p_slug) = '' THEN
            RETURN;
          END IF;
          FOR t IN SELECT tenants.id FROM tenants WHERE tenants.status = 'ACTIVE' LOOP
            PERFORM set_config('app.current_tenant_id', t::text, true);
            RETURN QUERY
              SELECT
                j.tenant_id,
                j.id AS job_id,
                j.title,
                j.status,
                j.public_apply_enabled,
                j.apply_deadline,
                j.location,
                j.work_mode,
                CASE
                  WHEN j.criteria IS NOT NULL THEN (j.criteria - 'salary_range')
                  ELSE NULL
                END AS criteria,
                t_row.name AS tenant_name,
                t_row.logo_url AS tenant_logo_url,
                t_row.privacy_notice_url AS tenant_privacy_notice_url
              FROM jobs j
              JOIN tenants t_row ON t_row.id = j.tenant_id
              WHERE j.public_slug = p_slug;
            EXIT WHEN FOUND;
          END LOOP;
          PERFORM set_config('app.current_tenant_id', coalesce(caller_tenant, ''), true);
        END
        $$
    """)
    op.execute("REVOKE EXECUTE ON FUNCTION public_job_by_slug(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public_job_by_slug(text) TO ats_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION public_job_by_slug(text)")
