"""Company Admin connects and manages Facebook Page (FR-A3.5, SAD §5.6).

The Meta Graph API is faked via the adapter seam; PostgreSQL, RLS, Redis, token encryption,
Audit Log, FastAPI routing and CSRF state verification are real.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app import channels
from app.channels import FacebookPage, FacebookPostResult, FacebookTokenError
from app.db import tenant_session
from app.main import app
from tests.test_jobs import User, make_user
from tests.test_scoring_runs import query

pytestmark = pytest.mark.usefixtures("database", "redis")

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
        if code == "no-role-code":
            raise channels.FacebookGraphError("App not active: developer role required", code=10)
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
    # https: channel cookies are Secure, so the client sends them back over https like a browser.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test", follow_redirects=False
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


def _channel_audit_rows(user: User) -> list[dict[str, Any]]:
    return query(
        user,
        "SELECT action, actor_type, actor_user_id, entity_type, entity_id, before, after"
        " FROM audit_logs WHERE entity_type = 'channel_connection' ORDER BY created_at, id",
    )


# --- Tests ---


async def test_connect_single_page_connects_immediately_and_records_audit(
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

    state = auth_resp.cookies.get(channels.OAUTH_STATE_COOKIE)
    assert state is not None

    # 2. Browser redirect callback from Facebook (no Authorization header)
    callback_resp = await client.get(
        f"/api/channels/facebook/callback?code=oauth-code-1&state={state}"
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

    # Crucially: no token string or ciphertext in response or Audit Log!
    assert "token" not in conn
    assert "token_ciphertext" not in conn
    assert "access_token" not in conn
    assert "page-token-secret-999" not in str(conn)

    audit_rows = _channel_audit_rows(admin)
    assert len(audit_rows) == 1
    assert audit_rows[0]["action"] == "channel_connection.connected"
    assert audit_rows[0]["actor_type"] == "USER"
    assert audit_rows[0]["actor_user_id"] == admin.id
    assert str(audit_rows[0]["entity_id"]) == conn["id"]
    assert audit_rows[0]["before"] is None
    assert audit_rows[0]["after"] == {"channel": "FACEBOOK_PAGE", "external_id": "page-1"}
    assert "page-token-secret-999" not in str(audit_rows)


async def test_connect_multiple_pages_keeps_tokens_server_side_and_allows_admin_to_select(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    fake_adapter.pages = [
        FacebookPage("page-alpha", "Alpha Careers", "alpha-token"),
        FacebookPage("page-beta", "Beta Jobs", "beta-token"),
    ]

    auth_resp = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    assert auth_resp.status_code == 200
    state = auth_resp.cookies[channels.OAUTH_STATE_COOKIE]

    # Callback with multiple pages (no Authorization header, like a real browser)
    callback_resp = await client.get(
        f"/api/channels/facebook/callback?code=multi-code&state={state}"
    )
    assert callback_resp.status_code == 302
    assert (
        callback_resp.headers["location"] == "https://ats.example/settings/channels?select_page=1"
    )
    selection_cookie = callback_resp.cookies.get(channels.PAGE_SELECTION_COOKIE)
    assert selection_cookie is not None
    # Cookie carries only a compact opaque id; encrypted Page tokens stay server-side in Redis.
    assert len(selection_cookie) < 64
    assert "alpha-token" not in selection_cookie
    assert "beta-token" not in selection_cookie

    # List candidate pages
    pages_resp = await client.get("/api/channels/facebook/pages", headers=admin.headers)
    assert pages_resp.status_code == 200
    candidates = pages_resp.json()
    assert candidates == [
        {"id": "page-alpha", "name": "Alpha Careers"},
        {"id": "page-beta", "name": "Beta Jobs"},
    ]
    assert "alpha-token" not in str(candidates)
    assert "beta-token" not in str(candidates)

    # Another user cannot use this selection id even if they somehow obtain the cookie
    other_admin = make_user("COMPANY_ADMIN", admin.tenant_id)
    hijack_resp = await client.get("/api/channels/facebook/pages", headers=other_admin.headers)
    assert hijack_resp.status_code == 400

    # Admin selects Beta Jobs
    select_resp = await client.post(
        "/api/channels/facebook/select",
        headers=admin.headers,
        json={"page_id": "page-beta"},
    )
    assert select_resp.status_code == 200
    selected = select_resp.json()
    assert selected["external_id"] == "page-beta"
    assert selected["name"] == "Beta Jobs"
    assert "beta-token" not in str(selected)

    # Redis selection key is deleted after selection (cannot replay)
    replay_resp = await client.post(
        "/api/channels/facebook/select",
        headers={
            **admin.headers,
            "Cookie": f"{channels.PAGE_SELECTION_COOKIE}={selection_cookie}",
        },
        json={"page_id": "page-alpha"},
    )
    assert replay_resp.status_code == 400

    # Active connection reflects Beta Jobs + Audit Log recorded
    active_resp = await client.get("/api/channels/facebook", headers=admin.headers)
    assert active_resp.status_code == 200
    active = active_resp.json()
    assert active["external_id"] == "page-beta"
    assert active["name"] == "Beta Jobs"

    audit_rows = _channel_audit_rows(admin)
    assert len(audit_rows) == 1
    assert audit_rows[0]["action"] == "channel_connection.connected"
    assert audit_rows[0]["after"] == {"channel": "FACEBOOK_PAGE", "external_id": "page-beta"}


async def test_tampered_state_rejected(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    fake_adapter.pages = [FacebookPage("p-1", "Page", "tok")]
    auth_resp = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    state = auth_resp.cookies[channels.OAUTH_STATE_COOKIE]

    tampered = state[:-4] + "xxxx"
    res = await client.get(f"/api/channels/facebook/callback?code=c1&state={tampered}")
    assert res.status_code == 400
    assert "invalid oauth state" in res.json()["detail"].lower()


async def test_expired_state_rejected(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    fake_adapter.pages = [FacebookPage("p-1", "Page", "tok")]
    past = datetime.now(UTC) - timedelta(minutes=15)
    claims = {
        "sub": str(admin.id),
        "tid": str(admin.tenant_id),
        "role": "COMPANY_ADMIN",
        "purpose": "facebook_oauth",
        "nonce": "expired-nonce",
        "iat": int(past.timestamp()),
        "exp": int((past + timedelta(minutes=5)).timestamp()),
    }
    expired_state = jwt.encode(claims, "test-secret-at-least-32-bytes-long!", algorithm="HS256")

    res = await client.get(
        f"/api/channels/facebook/callback?code=c1&state={expired_state}",
        headers={"Cookie": f"{channels.OAUTH_STATE_COOKIE}={expired_state}"},
    )
    assert res.status_code == 400
    assert "expired" in res.json()["detail"].lower()


async def test_state_of_another_user_or_replayed_or_after_logout_rejected(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    fake_adapter.pages = [FacebookPage("p-1", "Page", "tok")]
    other_admin = make_user("COMPANY_ADMIN")

    # 1. Missing state cookie (attacker sends their own state to a browser without the cookie)
    other_state = channels.create_oauth_state(
        other_admin.id, other_admin.tenant_id, "COMPANY_ADMIN"
    )
    res_no_cookie = await client.get(f"/api/channels/facebook/callback?code=c1&state={other_state}")
    assert res_no_cookie.status_code == 400

    # 2. Browser holds admin's cookie, but query state belongs to other_admin
    auth_resp = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    admin_state = auth_resp.cookies[channels.OAUTH_STATE_COOKIE]
    res_mismatch = await client.get(f"/api/channels/facebook/callback?code=c1&state={other_state}")
    assert res_mismatch.status_code == 400
    assert "another user" in res_mismatch.json()["detail"].lower()

    # 3. Valid callback succeeds once, then replaying the same state is rejected (single-use nonce)
    ok_resp = await client.get(f"/api/channels/facebook/callback?code=c1&state={admin_state}")
    assert ok_resp.status_code == 302
    replay_resp = await client.get(
        f"/api/channels/facebook/callback?code=c1&state={admin_state}",
        headers={"Cookie": f"{channels.OAUTH_STATE_COOKIE}={admin_state}"},
    )
    assert replay_resp.status_code == 400

    # 4. Logging out clears fb_oauth_state so a pending callback cannot complete after logout
    auth_resp2 = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    pending_state = auth_resp2.cookies[channels.OAUTH_STATE_COOKIE]
    logout_resp = await client.delete("/api/auth/refresh", headers={"X-Requested-With": "fetch"})
    assert logout_resp.status_code == 204
    after_logout = await client.get(
        f"/api/channels/facebook/callback?code=c2&state={pending_state}"
    )
    assert after_logout.status_code == 400


async def test_demoted_admin_rejected_on_callback(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    fake_adapter.pages = [FacebookPage("p-1", "Page", "tok")]
    auth_resp = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    state = auth_resp.cookies[channels.OAUTH_STATE_COOKIE]

    with tenant_session(admin.tenant_id) as session:
        session.execute(
            text("UPDATE users SET role = 'RECRUITER' WHERE id = :id"), {"id": admin.id}
        )

    res = await client.get(f"/api/channels/facebook/callback?code=c1&state={state}")
    assert res.status_code == 403


async def test_reconnect_replaces_old_page_and_records_before_after(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    # First connection
    fake_adapter.pages = [FacebookPage("p-1", "Page 1", "tok-1")]
    auth1 = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    await client.get(
        f"/api/channels/facebook/callback?code=c1&state={auth1.cookies[channels.OAUTH_STATE_COOKIE]}"
    )
    conn1 = (await client.get("/api/channels/facebook", headers=admin.headers)).json()
    assert conn1["external_id"] == "p-1"

    # Reconnect with Page 2
    fake_adapter.pages = [FacebookPage("p-2", "Page 2", "tok-2")]
    auth2 = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    await client.get(
        f"/api/channels/facebook/callback?code=c2&state={auth2.cookies[channels.OAUTH_STATE_COOKIE]}"
    )
    conn2 = (await client.get("/api/channels/facebook", headers=admin.headers)).json()
    assert conn2["external_id"] == "p-2"
    assert conn2["name"] == "Page 2"

    audit_rows = _channel_audit_rows(admin)
    assert [row["action"] for row in audit_rows] == [
        "channel_connection.connected",
        "channel_connection.connected",
    ]
    assert audit_rows[1]["before"] == {"channel": "FACEBOOK_PAGE", "external_id": "p-1"}
    assert audit_rows[1]["after"] == {"channel": "FACEBOOK_PAGE", "external_id": "p-2"}


async def test_disconnect_deletes_row_and_records_audit(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    fake_adapter.pages = [FacebookPage("p-1", "Page 1", "tok-1")]
    auth = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    await client.get(
        f"/api/channels/facebook/callback?code=c1&state={auth.cookies[channels.OAUTH_STATE_COOKIE]}"
    )

    assert (await client.get("/api/channels/facebook", headers=admin.headers)).json() is not None

    del_resp = await client.delete("/api/channels/facebook", headers=admin.headers)
    assert del_resp.status_code == 204

    # Second disconnect is a no-op (no duplicate audit row)
    assert (await client.delete("/api/channels/facebook", headers=admin.headers)).status_code == 204

    get_resp = await client.get("/api/channels/facebook", headers=admin.headers)
    assert get_resp.status_code == 200
    assert get_resp.json() is None

    audit_rows = _channel_audit_rows(admin)
    assert [row["action"] for row in audit_rows] == [
        "channel_connection.connected",
        "channel_connection.disconnected",
    ]
    assert audit_rows[1]["before"] == {"channel": "FACEBOOK_PAGE", "external_id": "p-1"}
    assert audit_rows[1]["after"] is None


async def test_recruiter_and_reviewer_forbidden(
    client: AsyncClient, recruiter: User, reviewer: User
) -> None:
    for user in (recruiter, reviewer):
        assert (await client.get("/api/channels/facebook", headers=user.headers)).status_code == 403
        assert (
            await client.get("/api/channels/facebook/auth-url", headers=user.headers)
        ).status_code == 403
        assert (
            await client.get("/api/channels/facebook/pages", headers=user.headers)
        ).status_code == 403
        assert (
            await client.post(
                "/api/channels/facebook/select", headers=user.headers, json={"page_id": "p"}
            )
        ).status_code == 403
        assert (
            await client.delete("/api/channels/facebook", headers=user.headers)
        ).status_code == 403


async def test_missing_or_invalid_config_returns_503(
    client: AsyncClient, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FACEBOOK_APP_ID", raising=False)
    res = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    assert res.status_code == 503
    assert "not configured" in res.json()["detail"].lower()

    monkeypatch.setenv("FACEBOOK_APP_ID", "test-fb-app-123")
    monkeypatch.setenv("CHANNEL_TOKEN_KEY", "not-a-fernet-key")
    res_bad_key = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    assert res_bad_key.status_code == 503
    assert "channel_token_key" in res_bad_key.json()["detail"].lower()


@pytest.mark.cross_tenant
async def test_other_tenant_does_not_see_connection(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    fake_adapter.pages = [FacebookPage("p-1", "Tenant A Page", "tok-a")]
    auth = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    await client.get(
        f"/api/channels/facebook/callback?code=c1&state={auth.cookies[channels.OAUTH_STATE_COOKIE]}"
    )

    other_admin = make_user("COMPANY_ADMIN")
    resp = await client.get("/api/channels/facebook", headers=other_admin.headers)
    assert resp.status_code == 200
    assert resp.json() is None


async def test_meta_and_graph_errors_redirect_to_catalog_codes(
    client: AsyncClient, admin: User, fake_adapter: FakeFacebookAdapter
) -> None:
    # 1. User cancelled on Facebook
    res_cancel = await client.get(
        "/api/channels/facebook/callback?error=access_denied&error_reason=user_denied"
    )
    assert res_cancel.status_code == 302
    assert res_cancel.headers["location"] == "https://ats.example/settings/channels?error=cancelled"

    # 2. Account has no role on Meta app in dev mode
    res_no_role = await client.get(
        "/api/channels/facebook/callback?error=no_role&error_description=Developer+role+required"
    )
    assert res_no_role.status_code == 302
    assert res_no_role.headers["location"] == "https://ats.example/settings/channels?error=no_role"

    # 3. Account manages no Facebook Pages
    fake_adapter.pages = []
    auth = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    res_no_pages = await client.get(
        f"/api/channels/facebook/callback?code=empty-code&state={auth.cookies[channels.OAUTH_STATE_COOKIE]}"
    )
    assert res_no_pages.status_code == 302
    assert (
        res_no_pages.headers["location"] == "https://ats.example/settings/channels?error=no_pages"
    )

    # 4. Graph API error redirects cleanly instead of exposing raw English JSON
    auth_bad = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    res_graph_err = await client.get(
        f"/api/channels/facebook/callback?code=bad-code&state={auth_bad.cookies[channels.OAUTH_STATE_COOKIE]}"
    )
    assert res_graph_err.status_code == 302
    assert (
        res_graph_err.headers["location"]
        == "https://ats.example/settings/channels?error=oauth_failed"
    )

    # 5. Graph API token error (code 190) redirects cleanly
    auth_tok = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    res_tok_err = await client.get(
        f"/api/channels/facebook/callback?code=token-expired&state={auth_tok.cookies[channels.OAUTH_STATE_COOKIE]}"
    )
    assert res_tok_err.status_code == 302
    assert (
        res_tok_err.headers["location"]
        == "https://ats.example/settings/channels?error=oauth_failed"
    )

    # 6. Graph API role error redirects to no_role
    auth_role = await client.get("/api/channels/facebook/auth-url", headers=admin.headers)
    res_role_err = await client.get(
        f"/api/channels/facebook/callback?code=no-role-code&state={auth_role.cookies[channels.OAUTH_STATE_COOKIE]}"
    )
    assert res_role_err.status_code == 302
    assert res_role_err.headers["location"] == "https://ats.example/settings/channels?error=no_role"
