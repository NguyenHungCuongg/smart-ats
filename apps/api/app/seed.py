"""Create the demo Tenant, its Company Admin and its Recruiter for dev and demo; rerunning
changes nothing.

Usage: SEED_PASSWORD=... python -m app.seed  (see README "Development")

Runs as ats_owner (DATABASE_MIGRATION_URL): ats_app can read only its own Tenant and write none.
"""

import os

from pwdlib import PasswordHash
from sqlalchemy import create_engine, text

DEMO_SLUG = "demo"
DEMO_USERS = {
    "admin@demo.local": ("Demo Admin", "COMPANY_ADMIN"),
    "recruiter@demo.local": ("Demo Recruiter", "RECRUITER"),
}


def seed(password: str) -> None:
    # Forced RLS binds the owner on users too, so the Users go in under the Tenant's context.
    with create_engine(os.environ["DATABASE_MIGRATION_URL"]).begin() as conn:
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
        conn.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        for email, (full_name, role) in DEMO_USERS.items():
            conn.execute(
                text(
                    "INSERT INTO users (tenant_id, email, password_hash, full_name, role,"
                    "  is_active)"
                    " VALUES (:tenant_id, :email, :password_hash, :full_name, :role, true)"
                    " ON CONFLICT (email) DO NOTHING"
                ),
                {
                    "tenant_id": tenant_id,
                    "email": email,
                    # Argon2id with pwdlib's recommended parameters (SRS FR-C1.1).
                    "password_hash": PasswordHash.recommended().hash(password),
                    "full_name": full_name,
                    "role": role,
                },
            )


if __name__ == "__main__":
    seed(os.environ["SEED_PASSWORD"])
    print(f"Seeded tenant '{DEMO_SLUG}' with {', '.join(DEMO_USERS)}")
