"""Create the demo Tenant and its Recruiter for dev and demo; rerunning changes nothing.

Usage: SEED_PASSWORD=... python -m app.seed  (see README "Development")
"""

import os

from pwdlib import PasswordHash
from sqlalchemy import text

from app.db import sync_engine, tenant_session

DEMO_SLUG = "demo"
DEMO_EMAIL = "recruiter@demo.local"


def seed(password: str) -> None:
    # tenants has no RLS; users does, so the Recruiter is inserted inside the tenant's context.
    with sync_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenants (name, slug, plan_type, ai_budget_monthly_usd, status)"
                " VALUES ('Demo Company', :slug, 'FREE', 10, 'ACTIVE')"
                " ON CONFLICT (slug) DO NOTHING"
            ),
            {"slug": DEMO_SLUG},
        )
        tenant_id = conn.scalar(
            text("SELECT id FROM tenants WHERE slug = :slug"), {"slug": DEMO_SLUG}
        )

    with tenant_session(tenant_id) as session:
        session.execute(
            text(
                "INSERT INTO users (tenant_id, email, password_hash, full_name, role, is_active)"
                " VALUES (:tenant_id, :email, :password_hash, 'Demo Recruiter', 'RECRUITER', true)"
                " ON CONFLICT (email) DO NOTHING"
            ),
            {
                "tenant_id": tenant_id,
                "email": DEMO_EMAIL,
                # Argon2id with pwdlib's recommended parameters (SRS FR-C1.1).
                "password_hash": PasswordHash.recommended().hash(password),
            },
        )


if __name__ == "__main__":
    seed(os.environ["SEED_PASSWORD"])
    print(f"Seeded tenant '{DEMO_SLUG}' with Recruiter {DEMO_EMAIL}")
