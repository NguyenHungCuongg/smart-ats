"""Password login with rotating refresh tokens (FR-C1.1, ADR-0003), through the HTTP API."""

import asyncio
import hashlib
import itertools
import os
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import ASGITransport, AsyncClient, Response
from pwdlib import PasswordHash
from sqlalchemy import text

from app.db import sync_engine, tenant_session
from app.main import app
from tests.test_tenancy import make_tenant

pytestmark = pytest.mark.usefixtures("database", "redis")

PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!")


# Each client gets its own IP, so per-IP lockouts never leak between tests.
_client_numbers = itertools.count(1)


def other_ip_client() -> AsyncClient:
    n = next(_client_numbers)
    transport = ASGITransport(app=app, client=(f"10.0.{n // 250}.{n % 250 + 1}", 4000))
    # https: the refresh cookie is Secure, so the client only sends it back over https.
    return AsyncClient(transport=transport, base_url="https://test")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with other_ip_client() as client:
        yield client


async def login(client: AsyncClient, email: str, password: str = PASSWORD) -> Response:
    return await client.post("/api/auth/login", json={"email": email, "password": password})


def make_user(*, is_active: bool = True) -> str:
    """A new Tenant with one Recruiter; returns the email."""
    email = f"{uuid.uuid4().hex}@example.com"
    tenant_id = make_tenant()
    with tenant_session(tenant_id) as session:
        session.execute(
            text(
                "INSERT INTO users (tenant_id, email, password_hash, full_name, role, is_active)"
                " VALUES (:tenant_id, :email, :password_hash, 'Test User', 'RECRUITER', :is_active)"
            ),
            {
                "tenant_id": tenant_id,
                "email": email,
                "password_hash": PasswordHash.recommended().hash(PASSWORD),
                "is_active": is_active,
            },
        )
    return email


async def test_login_returns_access_token_and_sets_refresh_cookie(client: AsyncClient) -> None:
    response = await login(client, make_user())

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60
    assert body["access_token"]
    cookie = response.headers["set-cookie"].lower()
    for attribute in ("httponly", "secure", "samesite=strict", "path=/api/auth/refresh"):
        assert attribute in cookie
    assert "max-age=604800" in cookie


async def test_login_is_case_insensitive_on_email(client: AsyncClient) -> None:
    assert (await login(client, make_user().upper())).status_code == 200


@pytest.mark.parametrize(
    "credentials",
    [
        pytest.param(lambda: (make_user(), "wrong password"), id="wrong password"),
        pytest.param(lambda: ("nobody@example.com", PASSWORD), id="unknown email"),
        pytest.param(lambda: (make_user(is_active=False), PASSWORD), id="inactive user"),
    ],
)
async def test_failed_login_is_401_and_reveals_nothing(
    client: AsyncClient, credentials: Callable[[], tuple[str, str]]
) -> None:
    response = await login(client, *credentials())

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}
    assert "set-cookie" not in response.headers


async def test_account_is_locked_after_five_consecutive_failures(client: AsyncClient) -> None:
    email = make_user()
    for _ in range(4):
        await login(client, email, "wrong password")
    assert (await login(client, email)).status_code == 200  # success resets the count

    for _ in range(5):
        assert (await login(client, email, "wrong password")).status_code == 401
    # From another IP too: the lock is on the account.
    async with other_ip_client() as elsewhere:
        response = await login(elsewhere, email)
    assert response.status_code == 429


async def test_ip_is_locked_after_five_consecutive_failures(client: AsyncClient) -> None:
    email = make_user()
    for _ in range(5):
        await login(client, f"{uuid.uuid4().hex}@example.com", "guess")

    assert (await login(client, email)).status_code == 429
    async with other_ip_client() as elsewhere:
        assert (await login(elsewhere, email)).status_code == 200


async def test_access_token_authenticates_within_its_tenant(client: AsyncClient) -> None:
    email = make_user()
    token = (await login(client, email)).json()["access_token"]

    response = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() | {"id": None} == {
        "id": None,
        "email": email,
        "full_name": "Test User",
        "role": "RECRUITER",
    }


def forged_token(**claims: object) -> str:
    now = datetime.now(UTC)
    base = {"sub": str(uuid.uuid4()), "tid": str(uuid.uuid4()), "role": "RECRUITER", "iat": now}
    return jwt.encode(
        base | {"exp": now + timedelta(minutes=15)} | claims, os.environ["JWT_SECRET"], "HS256"
    )


@pytest.mark.parametrize(
    "authorization",
    [
        pytest.param(lambda: None, id="missing"),
        pytest.param(lambda: "Bearer not-a-jwt", id="garbage"),
        pytest.param(
            lambda: "Bearer " + forged_token(exp=datetime.now(UTC) - timedelta(seconds=1)),
            id="expired",
        ),
        pytest.param(
            lambda: (
                "Bearer "
                + jwt.encode(
                    {"sub": "x", "tid": str(uuid.uuid4())}, "another-secret-32-bytes-long!!!!"
                )
            ),
            id="wrong signature",
        ),
        # Signed correctly, but no such User in that Tenant.
        pytest.param(lambda: "Bearer " + forged_token(), id="unknown user"),
    ],
)
async def test_bad_access_token_is_401(
    client: AsyncClient, authorization: Callable[[], str | None]
) -> None:
    value = authorization()
    headers = {"Authorization": value} if value else {}

    response = await client.get("/api/auth/me", headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def refresh(client: AsyncClient, token: str, *, csrf: bool = True) -> Response:
    """POST /api/auth/refresh with exactly this refresh token, whatever the client's cookie jar."""
    client.cookies.clear()
    headers = {"Cookie": f"refresh_token={token}"}
    if csrf:
        headers["X-Requested-With"] = "fetch"
    return await client.post("/api/auth/refresh", headers=headers)


async def me_status(client: AsyncClient, response: Response) -> int:
    token = response.json()["access_token"]
    return (
        await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    ).status_code


async def test_refresh_rotates_the_token(client: AsyncClient) -> None:
    first = (await login(client, make_user())).cookies["refresh_token"]

    response = await refresh(client, first)

    assert response.status_code == 200
    assert await me_status(client, response) == 200
    second = response.cookies["refresh_token"]
    assert second != first
    assert (await refresh(client, second)).status_code == 200


async def test_reusing_a_rotated_token_revokes_its_whole_family(client: AsyncClient) -> None:
    first = (await login(client, make_user())).cookies["refresh_token"]
    second = (await refresh(client, first)).cookies["refresh_token"]

    assert (await refresh(client, first)).status_code == 401
    assert (await refresh(client, second)).status_code == 401


async def test_refresh_requires_the_csrf_header(client: AsyncClient) -> None:
    token = (await login(client, make_user())).cookies["refresh_token"]

    assert (await refresh(client, token, csrf=False)).status_code == 403
    assert (await refresh(client, token)).status_code == 200  # not consumed by the rejected call


async def test_refresh_without_a_valid_token_is_401(client: AsyncClient) -> None:
    token = (await login(client, make_user())).cookies["refresh_token"]
    _, secret = token.split(".")

    client.cookies.clear()
    no_cookie = await client.post("/api/auth/refresh", headers={"X-Requested-With": "fetch"})
    assert no_cookie.status_code == 401
    assert (await refresh(client, "garbage")).status_code == 401
    # Same secret presented under another Tenant: RLS hides the row.
    assert (await refresh(client, f"{uuid.uuid4()}.{secret}")).status_code == 401


async def test_logout_revokes_the_token_family(client: AsyncClient) -> None:
    first = (await login(client, make_user())).cookies["refresh_token"]
    second = (await refresh(client, first)).cookies["refresh_token"]

    client.cookies.clear()
    response = await client.delete(
        "/api/auth/refresh",
        headers={"Cookie": f"refresh_token={second}", "X-Requested-With": "fetch"},
    )

    assert response.status_code == 204
    assert 'refresh_token=""' in response.headers["set-cookie"]
    assert (await refresh(client, second)).status_code == 401


@pytest.mark.cross_tenant
async def test_refresh_tokens_of_one_tenant_are_invisible_to_another(client: AsyncClient) -> None:
    tenants = []
    for _ in range(2):
        token = (await login(client, make_user())).json()["access_token"]
        claims = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
        tenants.append(uuid.UUID(claims["tid"]))

    for tenant_id in tenants:
        with tenant_session(tenant_id) as session:
            visible = session.scalars(text("SELECT tenant_id FROM refresh_tokens")).all()
        assert visible == [tenant_id]


@pytest.mark.cross_tenant
def test_auth_find_user_leaves_the_callers_tenant_context() -> None:
    own, other = make_user(), make_user()
    find = text("SELECT tenant_id FROM auth_find_user(:email)")
    with sync_engine().connect() as conn:
        own_tenant = conn.execute(find, {"email": own}).scalar_one()

    with tenant_session(own_tenant) as session:
        assert session.execute(find, {"email": other}).scalar_one() != own_tenant
        assert session.scalars(text("SELECT email FROM users")).all() == [own]


async def test_concurrent_guesses_cannot_outrun_the_account_lock() -> None:
    email = make_user()
    clients = [other_ip_client() for _ in range(10)]

    responses = await asyncio.gather(*(login(c, email, "wrong password") for c in clients))

    assert sorted(r.status_code for r in responses) == [401] * 5 + [429] * 5
    assert (await login(clients[0], email)).status_code == 429
    for c in clients:
        await c.aclose()


async def test_concurrent_guesses_cannot_outrun_the_ip_lock(client: AsyncClient) -> None:
    emails = [f"{uuid.uuid4().hex}@example.com" for _ in range(10)]

    responses = await asyncio.gather(*(login(client, email, "guess") for email in emails))

    assert sorted(r.status_code for r in responses) == [401] * 5 + [429] * 5


async def test_reusing_an_expired_rotated_token_still_revokes_the_family(
    client: AsyncClient,
) -> None:
    first = (await login(client, make_user())).cookies["refresh_token"]
    second = (await refresh(client, first)).cookies["refresh_token"]
    with tenant_session(uuid.UUID(first.partition(".")[0])) as session:
        session.execute(
            text(
                "UPDATE refresh_tokens SET expires_at = now() - interval '1 second'"
                " WHERE token_hash = :token_hash"
            ),
            {"token_hash": hashlib.sha256(first.encode()).hexdigest()},
        )

    assert (await refresh(client, first)).status_code == 401
    assert (await refresh(client, second)).status_code == 401
