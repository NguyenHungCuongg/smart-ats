import asyncio
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

API_DIR = Path(__file__).parents[1]
REPO_DIR = API_DIR.parents[1]

# psycopg's async mode cannot run on the Proactor loop that Windows uses by default.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def database() -> Iterator[None]:
    """Real PostgreSQL bootstrapped like Compose: same image, same init script, then Alembic.

    Migrations run as ats_owner; the tests run as ats_app, the role RLS actually binds (ADR-0001).
    """
    # Keep in sync with the postgres service in docker-compose.yml.
    container = (
        PostgresContainer("pgvector/pgvector:0.8.7-pg18-trixie")
        .with_env("ATS_OWNER_PASSWORD", "owner")
        .with_env("ATS_APP_PASSWORD", "app")
        .with_volume_mapping(
            str(REPO_DIR / "infra/postgres/init"), "/docker-entrypoint-initdb.d", "ro"
        )
    )
    with container, pytest.MonkeyPatch.context() as env:
        host, port = container.get_container_host_ip(), container.get_exposed_port(5432)
        base = f"@{host}:{port}/{container.dbname}"
        env.setenv("DATABASE_MIGRATION_URL", f"postgresql+psycopg://ats_owner:owner{base}")
        env.setenv("DATABASE_URL", f"postgresql+psycopg://ats_app:app{base}")
        command.upgrade(Config(API_DIR / "alembic.ini"), "head")
        yield
