"""Smoke tests for the postgres service (Infra 02, ADR-0001, ADR-0005).

Run against the Compose stack from the host: see README "Infrastructure".
"""

import os
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest


def connect(role: str) -> psycopg.Connection[tuple[Any, ...]]:
    return psycopg.connect(
        host="127.0.0.1",  # the address Compose publishes on
        port=int(os.environ.get("POSTGRES_HOST_PORT", "5432")),
        dbname=os.environ["POSTGRES_DB"],
        user=role,
        password=os.environ[f"{role.upper()}_PASSWORD"],
        autocommit=True,
    )


@pytest.mark.parametrize("role", ["ats_owner", "ats_app"])
def test_role_can_connect(role: str) -> None:
    with connect(role) as conn:
        assert conn.execute("SELECT current_user").fetchone() == (role,)


def test_cosine_distance_on_1536_dim_vectors() -> None:
    x = "[" + ",".join(["1"] + ["0"] * 1535) + "]"
    y = "[" + ",".join(["0", "1"] + ["0"] * 1534) + "]"
    with connect("ats_app") as conn:
        row = conn.execute(
            "SELECT %s::vector(1536) <=> %s::vector(1536), %s::vector(1536) <=> %s::vector(1536)",
            (x, y, x, x),
        ).fetchone()
    assert row == (1.0, 0.0)


def test_app_role_is_restricted() -> None:
    with connect("ats_app") as conn:
        row = conn.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolbypassrls"
            " FROM pg_roles WHERE rolname = 'ats_app'"
        ).fetchone()
    assert row == (False, False, False, False, False)


@pytest.fixture
def owner_table() -> Iterator[str]:
    """A table created by ats_owner after init, as a migration would."""
    name = f"smoke_{uuid.uuid4().hex}"
    with connect("ats_owner") as conn:
        conn.execute(f"CREATE TABLE {name} (id uuid PRIMARY KEY DEFAULT uuidv7(), n serial)")
        try:
            yield name
        finally:
            conn.execute(f"DROP TABLE {name}")


def test_app_role_has_dml_on_owner_tables(owner_table: str) -> None:
    with connect("ats_app") as conn:
        conn.execute(f"INSERT INTO {owner_table} DEFAULT VALUES")
        conn.execute(f"UPDATE {owner_table} SET n = n + 1")
        assert conn.execute(f"SELECT count(*) FROM {owner_table}").fetchone() == (1,)
        conn.execute(f"DELETE FROM {owner_table}")


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE smoke_forbidden (id int)",
        "CREATE TEMP TABLE smoke_forbidden (id int)",
        "DROP TABLE {table}",
        "ALTER TABLE {table} ADD x int",
    ],
)
def test_app_role_cannot_run_ddl(owner_table: str, ddl: str) -> None:
    with connect("ats_app") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(ddl.format(table=owner_table))
