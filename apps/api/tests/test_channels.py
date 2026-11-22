"""Company Admin connects and manages Facebook Page (FR-A3.5, SAD §5.6).

The Meta Graph API is faked via the adapter seam; PostgreSQL, RLS, Redis, token encryption,
Audit Log, FastAPI routing and CSRF state verification are real.
"""

import uuid
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
        if page_access_token == "timeout-token":
            raise channels.FacebookGraphError("Facebook Graph API request timed out")
        if page_access_token == "error-token":
            raise channels.FacebookGraphError("Unknown Graph error", code=500)
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


# --- Channel 03: Post Job Ad to Facebook Page Tests (FR-A3.5) ---


def _connect_page(
    user: User,
    page_id: str = "page-1",
    page_name: str = "Tech Corp Fanpage",
    token: str = "page-token-secret-999",
) -> None:
    ciphertext = channels.encrypt_token(token, FERNET_KEY)
    with tenant_session(user.tenant_id) as session:
        session.execute(
            text("""
                INSERT INTO channel_connections (
                    id, tenant_id, channel, external_id, name,
                    token_ciphertext, connected_by, created_at
                ) VALUES (
                    uuidv7(), :tenant_id, 'FACEBOOK_PAGE', :external_id, :name,
                    :ciphertext, :user_id, now()
                )
                ON CONFLICT (tenant_id, channel) DO UPDATE SET
                    external_id = EXCLUDED.external_id,
                    name = EXCLUDED.name,
                    token_ciphertext = EXCLUDED.token_ciphertext,
                    connected_by = EXCLUDED.connected_by
            """),
            {
                "tenant_id": user.tenant_id,
                "external_id": page_id,
                "name": page_name,
                "ciphertext": ciphertext,
                "user_id": user.id,
            },
        )


def _make_job(
    user: User,
    *,
    status: str = "PUBLISHED",
    public_apply_enabled: bool = True,
) -> tuple[str, str]:
    slug = f"job-{uuid.uuid4().hex[:12]}"
    with tenant_session(user.tenant_id) as session:
        job_id = session.scalar(
            text("""
                INSERT INTO jobs (
                    tenant_id, title, level, status, parse_status, created_by,
                    weight_technical, weight_soft_skills, weight_experience,
                    public_apply_enabled, public_slug, location, work_mode, published_at
                ) VALUES (
                    :tenant_id, 'Senior Python Dev', 'SENIOR', :status, 'SUCCEEDED',
                    :user_id, 0.50, 0.25, 0.25, :enabled, :slug, 'Hà Nội', 'HYBRID',
                    CASE WHEN :status = 'PUBLISHED' THEN now() ELSE NULL END
                )
                RETURNING id
            """),
            {
                "tenant_id": user.tenant_id,
                "user_id": user.id,
                "status": status,
                "enabled": public_apply_enabled,
                "slug": slug,
            },
        )
    return str(job_id), slug


async def test_publish_job_post_to_facebook_page_success_and_idempotent(
    client: AsyncClient, admin: User, recruiter: User, fake_adapter: FakeFacebookAdapter
) -> None:
    _connect_page(admin, page_id="page-tech", page_name="Tech Fanpage")
    job_id, slug = _make_job(recruiter)

    # 1. First publish call succeeds with 201 Created
    post_res = await client.post(
        f"/api/jobs/{job_id}/channel-posts",
        headers=recruiter.headers,
        json={"message": "Join us as a Senior Python Dev!"},
    )
    assert post_res.status_code == 201
    post_data = post_res.json()
    assert post_data["job_id"] == job_id
    assert post_data["channel"] == "FACEBOOK_PAGE"
    assert post_data["target_id"] == "page-tech"
    assert post_data["url"] == "https://www.facebook.com/page-tech_1"
    assert post_data["body"] == "Join us as a Senior Python Dev!"
    assert post_data["posted_by"] == str(recruiter.id)
    assert post_data["posted_by_name"] == "Test User"
    assert "token" not in post_data
    assert "token_ciphertext" not in post_data
    assert "access_token" not in post_data
    assert "page-token-secret-999" not in str(post_data)
    assert "page-token-secret-999" not in post_res.text

    # Verify fake_adapter was called once with the right link and token
    assert len(fake_adapter.posts) == 1
    assert fake_adapter.posts[0]["page_id"] == "page-tech"
    assert fake_adapter.posts[0]["link"] == f"https://ats.example/apply/{slug}"
    assert fake_adapter.posts[0]["message"] == "Join us as a Senior Python Dev!"

    # 2. Second publish call returns existing post with 200 OK without calling Facebook again
    second_res = await client.post(
        f"/api/jobs/{job_id}/channel-posts",
        headers=recruiter.headers,
        json={"message": "Different text that will be ignored"},
    )
    assert second_res.status_code == 200
    second_data = second_res.json()
    assert second_data["id"] == post_data["id"]
    assert second_data["url"] == post_data["url"]
    assert "page-token-secret-999" not in str(second_data)
    assert "page-token-secret-999" not in second_res.text
    # Adapter was NOT called again
    assert len(fake_adapter.posts) == 1

    # 3. List channel posts returns the post
    list_res = await client.get(f"/api/jobs/{job_id}/channel-posts", headers=recruiter.headers)
    assert list_res.status_code == 200
    posts = list_res.json()
    assert len(posts) == 1
    assert posts[0]["id"] == post_data["id"]
    assert "page-token-secret-999" not in str(posts)
    assert "page-token-secret-999" not in list_res.text

    # 4. Job Facebook status returns connected and the post
    status_res = await client.get(
        f"/api/jobs/{job_id}/channels/facebook", headers=recruiter.headers
    )
    assert status_res.status_code == 200
    fb_status = status_res.json()
    assert fb_status["connected"] is True
    assert fb_status["page_name"] == "Tech Fanpage"
    assert len(fb_status["posts"]) == 1
    assert "page-token-secret-999" not in str(fb_status)
    assert "page-token-secret-999" not in status_res.text

    # 5. Audit Log recorded once in the same transaction; idempotent call adds no duplicate
    audit_rows = query(
        recruiter,
        "SELECT action, actor_type, actor_user_id, entity_type, entity_id, before, after"
        " FROM audit_logs WHERE entity_type = 'channel_post' ORDER BY created_at, id",
    )
    assert len(audit_rows) == 1
    assert audit_rows[0]["action"] == "channel_post.created"
    assert audit_rows[0]["actor_type"] == "USER"
    assert audit_rows[0]["actor_user_id"] == recruiter.id
    assert str(audit_rows[0]["entity_id"]) == str(post_data["id"])
    assert audit_rows[0]["before"] is None
    assert audit_rows[0]["after"] == {
        "channel_post_id": str(post_data["id"]),
        "channel": "FACEBOOK_PAGE",
        "target_id": "page-tech",
        "external_post_id": "page-tech_1",
    }
    assert "page-token-secret-999" not in str(audit_rows)
    assert "Join us as a Senior Python Dev!" not in str(audit_rows)


async def test_publish_token_error_records_nothing_and_returns_error(
    client: AsyncClient, admin: User, recruiter: User, fake_adapter: FakeFacebookAdapter
) -> None:
    # Connect with invalid-token so FakeFacebookAdapter raises FacebookTokenError(code=190)
    _connect_page(admin, page_id="page-bad", token="invalid-token")
    job_id, _ = _make_job(recruiter)

    res = await client.post(
        f"/api/jobs/{job_id}/channel-posts",
        headers=recruiter.headers,
        json={"message": "Job text"},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "TOKEN_EXPIRED"

    # Verify no row was inserted into channel_posts
    with tenant_session(admin.tenant_id) as session:
        count = session.scalar(
            text("SELECT count(*) FROM channel_posts WHERE job_id = :job_id"), {"job_id": job_id}
        )
        assert count == 0


async def test_publish_timeout_and_graph_error_records_nothing_and_returns_error(
    client: AsyncClient, admin: User, recruiter: User, fake_adapter: FakeFacebookAdapter
) -> None:
    # 1. Timeout returns 504 with TIMEOUT code
    _connect_page(admin, page_id="page-to", token="timeout-token")
    job_id_1, _ = _make_job(recruiter)

    res_to = await client.post(
        f"/api/jobs/{job_id_1}/channel-posts",
        headers=recruiter.headers,
        json={"message": "Job text"},
    )
    assert res_to.status_code == 504
    assert res_to.json()["detail"]["code"] == "TIMEOUT"

    # 2. Generic Graph error returns 502 with GRAPH_ERROR code
    _connect_page(admin, page_id="page-err", token="error-token")
    job_id_2, _ = _make_job(recruiter)

    res_err = await client.post(
        f"/api/jobs/{job_id_2}/channel-posts",
        headers=recruiter.headers,
        json={"message": "Job text"},
    )
    assert res_err.status_code == 502
    assert res_err.json()["detail"]["code"] == "GRAPH_ERROR"

    # Verify no row was inserted for either job
    with tenant_session(admin.tenant_id) as session:
        count = session.scalar(
            text("SELECT count(*) FROM channel_posts WHERE job_id IN (:j1, :j2)"),
            {"j1": job_id_1, "j2": job_id_2},
        )
        assert count == 0


async def test_publish_rejected_when_not_published_or_link_disabled(
    client: AsyncClient, admin: User, recruiter: User
) -> None:
    _connect_page(admin)

    # 1. Job is in DRAFT
    job_draft, _ = _make_job(recruiter, status="DRAFT", public_apply_enabled=True)
    res_draft = await client.post(
        f"/api/jobs/{job_draft}/channel-posts",
        headers=recruiter.headers,
        json={"message": "Draft job"},
    )
    assert res_draft.status_code == 409
    assert res_draft.json()["detail"]["code"] == "JOB_NOT_PUBLISHED"

    # 2. Public Apply link is disabled
    job_disabled, _ = _make_job(recruiter, status="PUBLISHED", public_apply_enabled=False)
    res_disabled = await client.post(
        f"/api/jobs/{job_disabled}/channel-posts",
        headers=recruiter.headers,
        json={"message": "Disabled apply link"},
    )
    assert res_disabled.status_code == 409
    assert res_disabled.json()["detail"]["code"] == "PUBLIC_APPLY_DISABLED"


async def test_publish_rejected_when_page_not_connected(
    client: AsyncClient, admin: User, recruiter: User
) -> None:
    # Ensure no channel connection
    with tenant_session(admin.tenant_id) as session:
        session.execute(text("DELETE FROM channel_connections WHERE channel = 'FACEBOOK_PAGE'"))

    job_id, _ = _make_job(recruiter)
    res = await client.post(
        f"/api/jobs/{job_id}/channel-posts",
        headers=recruiter.headers,
        json={"message": "Job text"},
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "NOT_CONNECTED"


@pytest.mark.cross_tenant
async def test_publish_and_list_rbac_and_cross_tenant(
    client: AsyncClient, admin: User, recruiter: User, reviewer: User
) -> None:
    _connect_page(admin)
    job_id, _ = _make_job(recruiter)

    # 1. Reviewer is forbidden (403)
    res_rev_post = await client.post(
        f"/api/jobs/{job_id}/channel-posts",
        headers=reviewer.headers,
        json={"message": "Job text"},
    )
    assert res_rev_post.status_code == 403

    res_rev_get = await client.get(
        f"/api/jobs/{job_id}/channel-posts",
        headers=reviewer.headers,
    )
    assert res_rev_get.status_code == 403

    res_rev_status = await client.get(
        f"/api/jobs/{job_id}/channels/facebook",
        headers=reviewer.headers,
    )
    assert res_rev_status.status_code == 403

    # 2. Other tenant is 404
    other_admin = make_user("COMPANY_ADMIN")
    res_other_post = await client.post(
        f"/api/jobs/{job_id}/channel-posts",
        headers=other_admin.headers,
        json={"message": "Job text"},
    )
    assert res_other_post.status_code == 404

    res_other_get = await client.get(
        f"/api/jobs/{job_id}/channel-posts",
        headers=other_admin.headers,
    )
    assert res_other_get.status_code == 404

    res_other_status = await client.get(
        f"/api/jobs/{job_id}/channels/facebook",
        headers=other_admin.headers,
    )
    assert res_other_status.status_code == 404


async def test_publish_rejected_when_web_base_url_missing(
    client: AsyncClient, admin: User, recruiter: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _connect_page(admin)
    job_id, _ = _make_job(recruiter)
    monkeypatch.setenv("WEB_BASE_URL", "")

    res = await client.post(
        f"/api/jobs/{job_id}/channel-posts",
        headers=recruiter.headers,
        json={"message": "Valid job ad"},
    )
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "CONFIG_ERROR"


async def test_publish_rejected_when_message_whitespace_only(
    client: AsyncClient, admin: User, recruiter: User
) -> None:
    _connect_page(admin)
    job_id, _ = _make_job(recruiter)

    res = await client.post(
        f"/api/jobs/{job_id}/channel-posts",
        headers=recruiter.headers,
        json={"message": "   \n\t  "},
    )
    assert res.status_code == 422


async def test_disconnect_retains_channel_posts(
    client: AsyncClient, admin: User, recruiter: User, fake_adapter: FakeFacebookAdapter
) -> None:
    _connect_page(admin, page_id="page-persist")
    job_id, _ = _make_job(recruiter)

    # 1. Publish successfully
    res = await client.post(
        f"/api/jobs/{job_id}/channel-posts",
        headers=recruiter.headers,
        json={"message": "Permanent post"},
    )
    assert res.status_code == 201
    assert "page-token-secret-999" not in res.text

    # 2. Company Admin disconnects Facebook Page
    del_res = await client.delete("/api/channels/facebook", headers=admin.headers)
    assert del_res.status_code == 204

    # 3. Channel Post is still preserved
    list_res = await client.get(f"/api/jobs/{job_id}/channel-posts", headers=recruiter.headers)
    assert list_res.status_code == 200
    posts = list_res.json()
    assert len(posts) == 1
    assert posts[0]["body"] == "Permanent post"
    assert posts[0]["target_id"] == "page-persist"
    assert "page-token-secret-999" not in list_res.text

    # Status shows connected=False but posts are still returned
    status_res = await client.get(
        f"/api/jobs/{job_id}/channels/facebook", headers=recruiter.headers
    )
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["connected"] is False
    assert len(status_data["posts"]) == 1
    assert "page-token-secret-999" not in status_res.text
