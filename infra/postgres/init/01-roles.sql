-- Runs once, as the bootstrap superuser, when the data volume is empty (ADR-0001, ADR-0005).
-- Passwords come from the container environment; see .env.example.
\getenv owner_password ATS_OWNER_PASSWORD
\getenv app_password ATS_APP_PASSWORD

CREATE EXTENSION vector;

-- Owns the schema and every table in it; Alembic migrations run as this role.
CREATE ROLE ats_owner LOGIN PASSWORD :'owner_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
ALTER SCHEMA public OWNER TO ats_owner;

-- API and workers: DML only. Owning no table and lacking BYPASSRLS keeps it under forced RLS.
CREATE ROLE ats_app LOGIN PASSWORD :'app_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
GRANT USAGE ON SCHEMA public TO ats_app;

-- No tables exist yet, so grant on the ones ats_owner creates later.
ALTER DEFAULT PRIVILEGES FOR ROLE ats_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ats_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ats_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO ats_app;
