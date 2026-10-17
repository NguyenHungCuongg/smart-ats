import pytest
from pwdlib import PasswordHash
from sqlalchemy import text

from app.db import tenant_session
from app.seed import DEMO_SLUG, seed
from tests.test_tenancy import owner_engine

pytestmark = pytest.mark.usefixtures("database")


def test_seed_creates_one_tenant_and_recruiter_however_often_it_runs() -> None:
    seed("demo-password")
    seed("demo-password")

    with owner_engine().connect() as conn:
        tenant_ids = conn.scalars(
            text("SELECT id FROM tenants WHERE slug = :slug"), {"slug": DEMO_SLUG}
        ).all()
    assert len(tenant_ids) == 1

    with tenant_session(tenant_ids[0]) as session:
        users = session.execute(text("SELECT role, password_hash FROM users")).all()
    assert [role for role, _ in users] == ["RECRUITER"]
    password_hash = users[0][1]
    assert password_hash.startswith("$argon2id$")
    assert PasswordHash.recommended().verify("demo-password", password_hash)
