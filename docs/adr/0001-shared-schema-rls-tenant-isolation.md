# Shared schema with forced Row-Level Security for tenant isolation

All Tenants share one PostgreSQL schema. Every tenant-owned table carries a non-null `tenant_id` and has RLS **enabled and forced**, with one policy `USING` / `WITH CHECK` `tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid`. We chose this over schema-per-tenant and database-per-tenant because it keeps one migration path while pushing isolation into the database engine, which is also a thesis contribution we can test.

## Consequences

- The app connects as `ats_app`, a role that neither owns tables nor has `BYPASSRLS`. Migrations run as `ats_owner`. Table owners bypass RLS unless it is forced, so tests that pass as the owner prove nothing.
- Tenant context is set per transaction with `SELECT set_config('app.current_tenant_id', :tid, true)`. `SET LOCAL` cannot take bind parameters, and a session-level `SET` leaks across pooled connections.
- `NULLIF(..., '')` is required: once a pooled connection has used the setting, it reads back as `''` rather than `NULL`, and `''::uuid` raises an error instead of returning no rows.
- Child tables (for example `score_results`) repeat `tenant_id` rather than relying on a join inside the policy. This keeps policies trivial and indexable.
- Lookups that happen before a Tenant is known (login by email, Public Apply Link by slug, accepting an invitation) go through narrow `SECURITY DEFINER` functions owned by `ats_owner`, never through a bypass role.
- LangGraph checkpoint tables sit outside RLS. Only the agent runner reads them, keyed by a Campaign id it has already loaded under RLS.
