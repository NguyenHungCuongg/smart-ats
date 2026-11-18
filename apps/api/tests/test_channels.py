"""Company Admin connects and manages Facebook Page (FR-A3.5, SAD §5.6).

The Meta Graph API is faked via the adapter seam; PostgreSQL, RLS, token encryption,
FastAPI routing and CSRF state verification are real.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from app import channels
from app.channels import FacebookPage, FacebookPostResult, FacebookTokenError
from app.main import app
from tests.test_jobs import User, make_user

pytestmark = pytest.mark.usefixtures("database")

FERNET_KEY = Fernet.generate_key().decode()


class FakeFacebookAdapter:
    def __init__(self, pages: list[FacebookPage] | None = None) -> None:
        self.pages = pages if pages is not None else []
        self.exchanged_codes: list[str] = []
        self.posts: list[dict[str, str | None]] = []

    def exchange_code_for_user_token(self, code: str, redirect_uri: str) -> str:
        self.exchanged_codes.append(code)
        if code == "bad-code":
            raise channels.FacebookGraphError("Invalid verification code", code=100)
        if code == "token-expired":
            raise channels.FacebookTokenError("Token expired", code=190)
        return f"long-lived-user-token-{code}"

    def list_pages(self, user_access_token: str) -> list[FacebookPage]:
        if "token-expired" in user_access_token:
            raise channels.FacebookTokenError("Token expired", code=190)
        return self.pages

    def publish_feed_post(
        self,
        page_id: str,
        page_access_token: str,
        message: str,
        link: str | None = None,
    ) -> FacebookPostResult:
        if page_access_token == "invalid-token":
            raise FacebookTokenError("Page token invalid", code=190)
        post_id = f"{page_id}_{len(self.posts) + 1}"
        self.posts.append(
            {"page_id": page_id, "token": page_access_token, "message": message, "link": link}
        )
        return FacebookPostResult(
            external_post_id=post_id, url=f"https://www.facebook.com/{post_id}"
        )


@pytest.fixture(autouse=True)
def facebook_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!")
    monkeypatch.setenv("CHANNEL_TOKEN_KEY", FERNET_KEY)
    monkeypatch.setenv("FACEBOOK_APP_ID", "test-fb-app-123")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "test-fb-secret-456")
    monkeypatch.setenv("FACEBOOK_REDIRECT_URI", "https://localhost/api/channels/facebook/callback")
    monkeypatch.setenv("FACEBOOK_GRAPH_VERSION", "v26.0")
    monkeypatch.setenv("WEB_BASE_URL", "https://ats.example")


@pytest.fixture
def fake_adapter(monkeypatch: pytest.MonkeyPatch) -> FakeFacebookAdapter:
    fake = FakeFacebookAdapter()
    monkeypatch.setattr(channels, "adapter", fake)
    return fake


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        yield client


@pytest.fixture
def admin() -> User:
    return make_user("COMPANY_ADMIN")


@pytest.fixture
def recruiter(admin: User) -> User:
    return make_user("RECRUITER", admin.tenant_id)


@pytest.fixture
def reviewer(admin: User) -> User:
    return make_user("REVIEWER", admin.tenant_id)


# --- Tests ---


async def test_connect_single_page_connects_immediately(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    fake_adapter.pages = [FacebookPage("page-1", "Tech Corp Fanpage", "page-token-secret-999")]

    # 1. Company Admin initiates connection
    auth_resp = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    assert auth_resp.status_code == 200
    auth_url = auth_resp.json()["auth_url"]
    assert "https://www.facebook.com/v26.0/dialog/oauth" in auth_url
    assert "scope=pages_manage_posts%2Cpages_read_engagement%2Cpages_show_list" in auth_url
    assert "state=" in auth_url

    # Extract state parameter and cookie
    state = auth_resp.cookies.get("fb_oauth_state")
    assert state is not None

    # 2. Callback from Facebook
    callback_resp = await client.get(
        f"/api/channels/facebook/callback?code=oauth-code-1&state={state}",
        headers=admin.headers,
    )
    assert callback_resp.status_code == 302
    assert callback_resp.headers["location"] == "https://ats.example/settings/channels?connected=1"
    assert "oauth-code-1" in fake_adapter.exchanged_codes

    # 3. Read connection
    conn_resp = await client.get("/api/channels/facebook", headers=admin.headers)
    assert conn_resp.status_code == 200
    conn = conn_resp.json()
    assert conn["channel"] == "FACEBOOK_PAGE"
    assert conn["external_id"] == "page-1"
    assert conn["name"] == "Tech Corp Fanpage"
    assert conn["connected_by"] == str(admin.id)
    assert conn["connected_by_name"] == "Test User"
    assert conn["connected_at"] is not None

    # Crucially: no token string or ciphertext in response!
    assert "token" not in conn
    assert "token_ciphertext" not in conn
    assert "access_token" not in conn
    assert "page-token-secret-999" not in str(conn)


async def test_connect_multiple_pages_allows_admin_to_select(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    fake_adapter.pages = [
        FacebookPage("page-alpha", "Alpha Careers", "alpha-token"),
        FacebookPage("page-beta", "Beta Jobs", "beta-token"),
    ]

    # Get auth URL
    auth_resp = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    assert auth_resp.status_code == 200
    state = auth_resp.cookies["fb_oauth_state"]

    # Callback with multiple pages
    callback_resp = await client.get(
        f"/api/channels/facebook/callback?code=multi-code&state={state}",
        headers=admin.headers,
    )
    assert callback_resp.status_code == 302
    assert (
        callback_resp.headers["location"] == "https://ats.example/settings/channels?select_page=1"
    )
    selection_cookie = callback_resp.cookies.get(channels.PAGE_SELECTION_COOKIE)
    assert selection_cookie is not None

    # List candidate pages
    pages_resp = await client.get(
        "/api/channels/facebook/pages",
        headers=admin.headers,
        cookies={channels.PAGE_SELECTION_COOKIE: selection_cookie},
    )
    assert pages_resp.status_code == 200
    candidates = pages_resp.json()
    assert candidates == [
        {"id": "page-alpha", "name": "Alpha Careers"},
        {"id": "page-beta", "name": "Beta Jobs"},
    ]
    # No tokens in candidate response
    assert "alpha-token" not in str(candidates)
    assert "beta-token" not in str(candidates)

    # Admin selects Beta Jobs
    select_resp = await client.post(
        "/api/channels/facebook/select",
        headers=admin.headers,
        cookies={channels.PAGE_SELECTION_COOKIE: selection_cookie},
        json={"page_id": "page-beta"},
    )
    assert select_resp.status_code == 200
    selected = select_resp.json()
    assert selected["external_id"] == "page-beta"
    assert selected["name"] == "Beta Jobs"
    assert "beta-token" not in str(selected)

    # Active connection reflects Beta Jobs
    active_resp = await client.get("/api/channels/facebook", headers=admin.headers)
    assert active_resp.status_code == 200
    active = active_resp.json()
    assert active["external_id"] == "page-beta"
    assert active["name"] == "Beta Jobs"


async def test_tampered_state_rejected(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    fake_adapter.pages = [FacebookPage("p-1", "Page", "tok")]
    auth_resp = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    state = auth_resp.cookies["fb_oauth_state"]

    # Tampered signature
    tampered = state[:-4] + "xxxx"
    res = await client.get(
        f"/api/channels/facebook/callback?code=c1&state={tampered}",
        headers=admin.headers,
    )
    assert res.status_code == 400
    assert "Invalid OAuth state" in res.json()["detail"]


async def test_expired_state_rejected(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    fake_adapter.pages = [FacebookPage("p-1", "Page", "tok")]
    # Create expired state token
    past = datetime.now(UTC) - timedelta(minutes=15)
    claims = {
        "sub": str(admin.id),
        "tid": str(admin.tenant_id),
        "role": "COMPANY_ADMIN",
        "purpose": "facebook_oauth",
        "iat": int(past.timestamp()),
        "exp": int((past + timedelta(minutes=5)).timestamp()),
    }
    expired_state = jwt.encode(claims, "test-secret-at-least-32-bytes-long!", algorithm="HS256")

    res = await client.get(
        f"/api/channels/facebook/callback?code=c1&state={expired_state}",
        headers=admin.headers,
    )
    assert res.status_code == 400
    assert "expired" in res.json()["detail"].lower()


async def test_state_of_another_user_rejected(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    fake_adapter.pages = [FacebookPage("p-1", "Page", "tok")]
    other_admin = make_user("COMPANY_ADMIN")

    # State belongs to other_admin
    state = channels.create_oauth_state(other_admin.id, other_admin.tenant_id, "COMPANY_ADMIN")

    # Current caller is admin (different user)
    res = await client.get(
        f"/api/channels/facebook/callback?code=c1&state={state}",
        headers=admin.headers,
    )
    assert res.status_code == 400
    assert "another user" in res.json()["detail"].lower()


async def test_reconnect_replaces_old_page(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    # First connection
    fake_adapter.pages = [FacebookPage("p-1", "Page 1", "tok-1")]
    auth1 = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    await client.get(
        f"/api/channels/facebook/callback?code=c1&state={auth1.cookies['fb_oauth_state']}",
        headers=admin.headers,
    )
    conn1 = (await client.get("/api/channels/facebook", headers=admin.headers)).json()
    assert conn1["external_id"] == "p-1"

    # Reconnect with Page 2
    fake_adapter.pages = [FacebookPage("p-2", "Page 2", "tok-2")]
    auth2 = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    await client.get(
        f"/api/channels/facebook/callback?code=c2&state={auth2.cookies['fb_oauth_state']}",
        headers=admin.headers,
    )
    conn2 = (await client.get("/api/channels/facebook", headers=admin.headers)).json()
    assert conn2["external_id"] == "p-2"
    assert conn2["name"] == "Page 2"


async def test_disconnect_deletes_row(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    fake_adapter.pages = [FacebookPage("p-1", "Page 1", "tok-1")]
    auth = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    await client.get(
        f"/api/channels/facebook/callback?code=c1&state={auth.cookies['fb_oauth_state']}",
        headers=admin.headers,
    )

    # Verify connected
    assert (await client.get("/api/channels/facebook", headers=admin.headers)).json() is not None

    # Disconnect
    del_resp = await client.delete("/api/channels/facebook", headers=admin.headers)
    assert del_resp.status_code == 204

    # Verify connection is now null
    get_resp = await client.get("/api/channels/facebook", headers=admin.headers)
    assert get_resp.status_code == 200
    assert get_resp.json() is None


async def test_recruiter_and_reviewer_forbidden(
    client: AsyncClient, recruiter: User, reviewer: User
) -> None:
    # Recruiter cannot manage connection
    assert (
        await client.get("/api/channels/facebook/auth-url", headers=recruiter.headers)
    ).status_code == 403
    assert (
        await client.get("/api/channels/facebook/pages", headers=recruiter.headers)
    ).status_code == 403
    assert (
        await client.post(
            "/api/channels/facebook/select", headers=recruiter.headers, json={"page_id": "p"}
        )
    ).status_code == 403
    assert (
        await client.delete("/api/channels/facebook", headers=recruiter.headers)
    ).status_code == 403

    # Recruiter CAN read the connection (for Job Ad posting in #99)
    get_res = await client.get("/api/channels/facebook", headers=recruiter.headers)
    assert get_res.status_code == 200

    # Reviewer cannot do anything with channels (403 on everything)
    assert (
        await client.get("/api/channels/facebook/auth-url", headers=reviewer.headers)
    ).status_code == 403
    assert (await client.get("/api/channels/facebook", headers=reviewer.headers)).status_code == 403
    assert (
        await client.delete("/api/channels/facebook", headers=reviewer.headers)
    ).status_code == 403


async def test_missing_config_returns_503(
    client: AsyncClient, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FACEBOOK_APP_ID", raising=False)
    res = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    assert res.status_code == 503
    assert "not configured" in res.json()["detail"].lower()


@pytest.mark.cross_tenant
async def test_other_tenant_does_not_see_connection(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    fake_adapter.pages = [FacebookPage("p-1", "Tenant A Page", "tok-a")]
    auth = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    await client.get(
        f"/api/channels/facebook/callback?code=c1&state={auth.cookies['fb_oauth_state']}",
        headers=admin.headers,
    )

    other_admin = make_user("COMPANY_ADMIN")
    resp = await client.get("/api/channels/facebook", headers=other_admin.headers)
    assert resp.status_code == 200
    assert resp.json() is None


async def test_meta_error_cancelled_and_no_role_and_no_pages(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    # 1. User cancelled on Facebook
    res_cancel = await client.get(
        "/api/channels/facebook/callback?error=access_denied&error_reason=user_denied",
        headers=admin.headers,
    )
    assert res_cancel.status_code == 302
    assert res_cancel.headers["location"] == "https://ats.example/settings/channels?error=cancelled"

    # 2. Account has no role on Meta app in dev mode
    res_no_role = await client.get(
        "/api/channels/facebook/callback?error=no_role&error_description=Developer+role+required",
        headers=admin.headers,
    )
    assert res_no_role.status_code == 302
    assert res_no_role.headers["location"] == "https://ats.example/settings/channels?error=no_role"

    # 3. Account manages no Facebook Pages
    fake_adapter.pages = []
    auth = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    res_no_pages = await client.get(
        f"/api/channels/facebook/callback?code=empty-code&state={auth.cookies['fb_oauth_state']}",
        headers=admin.headers,
    )
    assert res_no_pages.status_code == 302
    assert (
        res_no_pages.headers["location"] == "https://ats.example/settings/channels?error=no_pages"
    )
