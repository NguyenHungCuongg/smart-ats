"""Facebook Page channel connection and Meta Graph API adapter (FR-A3.5, SAD §5.6, ERD §6).

Company Admin connects a Facebook Page for the Workspace via OAuth 2.0.
The Page access token is encrypted at rest using Fernet with CHANNEL_TOKEN_KEY
and never leaves the API. Recruiters and Reviewers cannot manage connections.
"""

import json
import os
import secrets
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Protocol

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app import audit
from app.auth import Auth, Authenticated, _redis
from app.db import async_tenant_session
from app.jobs import JobManager, LockedJob

router = APIRouter(prefix="/api/channels/facebook")
jobs_router = APIRouter(prefix="/api/jobs", tags=["channels"])

OAUTH_STATE_COOKIE = "fb_oauth_state"
OAUTH_STATE_TTL = timedelta(minutes=10)
PAGE_SELECTION_COOKIE = "fb_page_selection"
PAGE_SELECTION_TTL = timedelta(minutes=5)
CHANNEL_COOKIE_PATH = "/api/channels/facebook"
DEFAULT_GRAPH_VERSION = "v26.0"


# --- Exceptions ---


class FacebookError(Exception):
    """Base exception for Facebook Graph API errors."""

    def __init__(self, message: str, code: int | None = None, subcode: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.subcode = subcode


class FacebookTokenError(FacebookError):
    """Raised when Facebook access token is invalid, expired or revoked (code 190)."""


class FacebookGraphError(FacebookError):
    """Raised on other Graph API or transport errors."""


# --- Configuration & Adapter ---


@dataclass(frozen=True)
class FacebookConfig:
    app_id: str
    app_secret: str
    redirect_uri: str
    graph_version: str
    token_key: str


def _graph_version() -> str:
    return os.environ.get("FACEBOOK_GRAPH_VERSION", "").strip() or DEFAULT_GRAPH_VERSION


def _app_credentials() -> tuple[str, str]:
    app_id = os.environ.get("FACEBOOK_APP_ID", "").strip()
    app_secret = os.environ.get("FACEBOOK_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise FacebookGraphError("Facebook app ID or secret is not configured")
    return app_id, app_secret


@dataclass(frozen=True)
class FacebookPage:
    id: str
    name: str
    access_token: str


@dataclass(frozen=True)
class FacebookPostResult:
    external_post_id: str
    url: str


class FacebookAdapter(Protocol):
    def exchange_code_for_user_token(self, code: str, redirect_uri: str) -> str: ...

    def list_pages(self, user_access_token: str) -> list[FacebookPage]: ...

    def publish_feed_post(
        self,
        page_id: str,
        page_access_token: str,
        message: str,
        link: str | None = None,
    ) -> FacebookPostResult: ...


class GraphAPIAdapter:
    """Thin adapter for Meta Graph API calls (the only module that calls Facebook)."""

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def _handle_error(self, data: dict[str, Any], default_message: str) -> None:
        err = data.get("error")
        err_dict = err if isinstance(err, dict) else {}
        code = err_dict.get("code")
        subcode = err_dict.get("error_subcode")
        msg = err_dict.get("message") or default_message
        if code == 190:
            raise FacebookTokenError(str(msg), code=code, subcode=subcode)
        raise FacebookGraphError(str(msg), code=code, subcode=subcode)

    def _request(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        default_error: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            resp = client.request(method, url, **kwargs)
        except httpx.TimeoutException as e:
            raise FacebookGraphError("Facebook Graph API request timed out") from e
        except httpx.HTTPError as e:
            # Never include str(e): httpx error text can echo query params containing secrets.
            raise FacebookGraphError("Facebook Graph API request failed") from e

        try:
            data: Any = resp.json()
        except ValueError as e:
            raise FacebookGraphError(f"{default_error} (HTTP {resp.status_code})") from e

        if not isinstance(data, dict):
            raise FacebookGraphError(default_error)
        if resp.status_code != 200:
            self._handle_error(data, default_error)
        return data

    def exchange_code_for_user_token(self, code: str, redirect_uri: str) -> str:
        app_id, app_secret = _app_credentials()
        version = _graph_version()
        with httpx.Client(timeout=self.timeout) as client:
            data = self._request(
                client,
                "GET",
                f"https://graph.facebook.com/{version}/oauth/access_token",
                default_error="Failed to exchange authorization code",
                params={
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
            )
            short_token = data.get("access_token")
            if not short_token:
                raise FacebookGraphError("No access token in response")

            data_long = self._request(
                client,
                "GET",
                f"https://graph.facebook.com/{version}/oauth/access_token",
                default_error="Failed to obtain long-lived user token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "fb_exchange_token": short_token,
                },
            )
            long_token = data_long.get("access_token")
            if not long_token:
                raise FacebookGraphError("No long-lived access token in response")
            return str(long_token)

    def list_pages(self, user_access_token: str) -> list[FacebookPage]:
        version = _graph_version()
        with httpx.Client(timeout=self.timeout) as client:
            data = self._request(
                client,
                "GET",
                f"https://graph.facebook.com/{version}/me/accounts",
                default_error="Failed to list Facebook pages",
                headers={"Authorization": f"Bearer {user_access_token}"},
            )
            pages_data = data.get("data", [])
            if not isinstance(pages_data, list):
                raise FacebookGraphError("Unexpected response format from Facebook pages endpoint")
            try:
                return [
                    FacebookPage(
                        id=str(item["id"]),
                        name=str(item["name"]),
                        access_token=str(item["access_token"]),
                    )
                    for item in pages_data
                ]
            except (KeyError, TypeError) as e:
                raise FacebookGraphError("Missing page fields in Facebook response") from e

    def publish_feed_post(
        self,
        page_id: str,
        page_access_token: str,
        message: str,
        link: str | None = None,
    ) -> FacebookPostResult:
        version = _graph_version()
        payload: dict[str, Any] = {"message": message}
        if link:
            payload["link"] = link
        with httpx.Client(timeout=self.timeout) as client:
            data = self._request(
                client,
                "POST",
                f"https://graph.facebook.com/{version}/{page_id}/feed",
                default_error="Failed to publish feed post",
                headers={"Authorization": f"Bearer {page_access_token}"},
                json=payload,
            )
            post_id = data.get("id")
            if not post_id:
                raise FacebookGraphError("No post id in response")
            post_id_str = str(post_id)
            return FacebookPostResult(
                external_post_id=post_id_str,
                url=f"https://www.facebook.com/{post_id_str}",
            )


# Default adapter seam, monkeypatchable in tests.
adapter: FacebookAdapter = GraphAPIAdapter()


# --- Token Encryption, State & Cookie Helpers ---


def check_facebook_config() -> FacebookConfig:
    required = (
        "FACEBOOK_APP_ID",
        "FACEBOOK_APP_SECRET",
        "FACEBOOK_REDIRECT_URI",
        "CHANNEL_TOKEN_KEY",
    )
    missing = [k for k in required if not os.environ.get(k, "").strip()]
    if missing:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Facebook integration is not configured (missing {', '.join(missing)})",
        )
    token_key = os.environ["CHANNEL_TOKEN_KEY"].strip()
    try:
        Fernet(token_key.encode())
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Facebook integration is not configured (invalid CHANNEL_TOKEN_KEY)",
        ) from e
    return FacebookConfig(
        app_id=os.environ["FACEBOOK_APP_ID"].strip(),
        app_secret=os.environ["FACEBOOK_APP_SECRET"].strip(),
        redirect_uri=os.environ["FACEBOOK_REDIRECT_URI"].strip(),
        graph_version=_graph_version(),
        token_key=token_key,
    )


def encrypt_token(token: str, key: str | None = None) -> bytes:
    token_key = key or os.environ["CHANNEL_TOKEN_KEY"]
    return Fernet(token_key.encode()).encrypt(token.encode())


def decrypt_token(ciphertext: bytes, key: str | None = None) -> str:
    token_key = key or os.environ["CHANNEL_TOKEN_KEY"]
    return Fernet(token_key.encode()).decrypt(ciphertext).decode()


def create_oauth_state(user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "role": role,
        "purpose": "facebook_oauth",
        "iat": int(now.timestamp()),
        "exp": int((now + OAUTH_STATE_TTL).timestamp()),
        "nonce": secrets.token_hex(16),
    }
    return jwt.encode(claims, os.environ["JWT_SECRET"], algorithm="HS256")


def verify_oauth_state(state: str) -> dict[str, Any]:
    try:
        claims: dict[str, Any] = jwt.decode(
            state,
            os.environ["JWT_SECRET"],
            algorithms=["HS256"],
            options={"require": ["sub", "tid", "role", "purpose", "nonce", "exp"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "OAuth state has expired") from e
    except (jwt.PyJWTError, ValueError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid OAuth state") from e

    if claims.get("purpose") != "facebook_oauth":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid OAuth state purpose")
    return claims


def encrypt_selection(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    pages: list[FacebookPage],
    token_key: str,
) -> str:
    payload = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "exp": int((datetime.now(UTC) + PAGE_SELECTION_TTL).timestamp()),
        "pages": [{"id": p.id, "name": p.name, "access_token": p.access_token} for p in pages],
    }
    encoded = json.dumps(payload).encode()
    return Fernet(token_key.encode()).encrypt(encoded).decode("ascii")


def decrypt_selection(token_str: str, token_key: str) -> dict[str, Any]:
    try:
        decrypted = Fernet(token_key.encode()).decrypt(token_str.encode("ascii"))
        payload: dict[str, Any] = json.loads(decrypted.decode())
    except (InvalidToken, json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid page selection state") from e

    if payload.get("exp", 0) < int(datetime.now(UTC).timestamp()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Page selection has expired")
    return payload


def _oauth_nonce_key(nonce: str) -> str:
    return f"fb_oauth_nonce:{nonce}"


def _selection_key(selection_id: str) -> str:
    return f"fb_page_selection:{selection_id}"


def _set_channel_cookie(response: Response, name: str, value: str, ttl: timedelta) -> None:
    response.set_cookie(
        name,
        value,
        max_age=int(ttl.total_seconds()),
        path=CHANNEL_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="lax",
    )


def _delete_channel_cookie(response: Response, name: str) -> None:
    response.delete_cookie(
        name,
        path=CHANNEL_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="lax",
    )


def _is_meta_role_error(text_value: str | None) -> bool:
    lower = (text_value or "").lower()
    return "role" in lower or "developer" in lower or "not active" in lower


def _callback_error_redirect(web_base: str, error_code: str) -> RedirectResponse:
    redirect = RedirectResponse(f"{web_base}/settings/channels?error={error_code}", status_code=302)
    _delete_channel_cookie(redirect, OAUTH_STATE_COOKIE)
    return redirect


async def _load_page_selection(
    selection_id: str | None,
    token_key: str,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    if not selection_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No page selection in progress")
    raw: bytes | None = await _redis().get(_selection_key(selection_id))
    if raw is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Page selection has expired")
    payload = decrypt_selection(raw.decode("ascii"), token_key)
    if uuid.UUID(payload["sub"]) != user_id or uuid.UUID(payload["tid"]) != tenant_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Page selection belongs to another user")
    return payload


async def _upsert_connection(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    external_id: str,
    name: str,
    token_ciphertext: bytes,
    connected_by: uuid.UUID,
    ip: str | None,
) -> tuple[uuid.UUID, datetime]:
    existing = (
        await session.execute(
            text(
                "SELECT channel, external_id FROM channel_connections"
                " WHERE channel = 'FACEBOOK_PAGE' FOR UPDATE"
            )
        )
    ).one_or_none()
    before = (
        {"channel": existing.channel, "external_id": existing.external_id}
        if existing is not None
        else None
    )
    row = (
        await session.execute(
            text("""
                INSERT INTO channel_connections (
                  id, tenant_id, channel, external_id, name,
                  token_ciphertext, connected_by, created_at
                ) VALUES (
                  uuidv7(), :tenant_id, 'FACEBOOK_PAGE', :external_id, :name,
                  :token_ciphertext, :connected_by, now()
                )
                ON CONFLICT (tenant_id, channel) DO UPDATE SET
                  external_id = EXCLUDED.external_id,
                  name = EXCLUDED.name,
                  token_ciphertext = EXCLUDED.token_ciphertext,
                  connected_by = EXCLUDED.connected_by,
                  created_at = EXCLUDED.created_at
                RETURNING id, created_at
            """),
            {
                "tenant_id": tenant_id,
                "external_id": external_id,
                "name": name,
                "token_ciphertext": token_ciphertext,
                "connected_by": connected_by,
            },
        )
    ).one()
    await audit.arecord(
        session,
        actor_type="USER",
        actor_user_id=connected_by,
        action="channel_connection.connected",
        entity_id=row.id,
        before=before,
        after={"channel": "FACEBOOK_PAGE", "external_id": external_id},
        ip=ip,
    )
    return row.id, row.created_at


# --- Dependencies & Pydantic Models ---


def _company_admin(auth: Authenticated) -> Auth:
    if auth.role != "COMPANY_ADMIN":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only Company Admins manage Facebook Page connection"
        )
    return auth


CompanyAdmin = Annotated[Auth, Depends(_company_admin)]


class FacebookPageCandidate(BaseModel):
    id: str
    name: str


class FacebookConnectionResponse(BaseModel):
    id: uuid.UUID
    channel: str = "FACEBOOK_PAGE"
    external_id: str
    name: str
    connected_by: uuid.UUID
    connected_by_name: str
    connected_at: datetime


class SelectPageRequest(BaseModel):
    page_id: str = Field(min_length=1)


# --- Endpoints ---


@router.get("/auth-url")
async def get_auth_url(
    admin: CompanyAdmin,
    response: Response,
) -> dict[str, str]:
    config = check_facebook_config()
    state = create_oauth_state(admin.user_id, admin.tenant_id, admin.role)
    nonce = verify_oauth_state(state)["nonce"]
    await _redis().set(
        _oauth_nonce_key(nonce), f"{admin.tenant_id}:{admin.user_id}", px=OAUTH_STATE_TTL
    )
    _set_channel_cookie(response, OAUTH_STATE_COOKIE, state, OAUTH_STATE_TTL)
    scope = "pages_manage_posts,pages_read_engagement,pages_show_list"
    params = urllib.parse.urlencode(
        {
            "client_id": config.app_id,
            "redirect_uri": config.redirect_uri,
            "scope": scope,
            "state": state,
            "response_type": "code",
        }
    )
    auth_url = f"https://www.facebook.com/{config.graph_version}/dialog/oauth?{params}"
    return {"auth_url": auth_url}


@router.get("/callback")
async def facebook_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_reason: str | None = None,
    error_description: str | None = None,
    fb_oauth_state: Annotated[str | None, Cookie()] = None,
) -> Response:
    web_base = os.environ.get("WEB_BASE_URL", "")

    # Meta-returned OAuth cancellation or refusal
    if error is not None:
        if fb_oauth_state:
            try:
                cookie_nonce = verify_oauth_state(fb_oauth_state)["nonce"]
            except HTTPException:
                cookie_nonce = None
            if cookie_nonce:
                await _redis().delete(_oauth_nonce_key(cookie_nonce))
        if error == "access_denied" or error_reason == "user_denied":
            return _callback_error_redirect(web_base, "cancelled")
        if error == "no_role" or _is_meta_role_error(error_description):
            return _callback_error_redirect(web_base, "no_role")
        return _callback_error_redirect(web_base, "oauth_failed")

    if not code or not state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing code or state")

    config = check_facebook_config()
    claims = verify_oauth_state(state)

    if not fb_oauth_state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing OAuth authentication context")
    if not secrets.compare_digest(fb_oauth_state, state):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "OAuth state belongs to another user")

    if claims.get("role") != "COMPANY_ADMIN":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only Company Admins manage Facebook Page connection"
        )

    state_user_id = uuid.UUID(claims["sub"])
    state_tenant_id = uuid.UUID(claims["tid"])

    # Single-use nonce bound to the admin who initiated OAuth.
    expected_owner = f"{state_tenant_id}:{state_user_id}".encode()
    stored_owner: bytes | None = await _redis().getdel(_oauth_nonce_key(claims["nonce"]))
    if stored_owner != expected_owner:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or already used OAuth state")

    # Confirm the user is still an active Company Admin before calling Graph API.
    async with async_tenant_session(state_tenant_id) as session:
        is_admin = await session.scalar(
            text("SELECT 1 FROM users WHERE id = :id AND is_active AND role = 'COMPANY_ADMIN'"),
            {"id": state_user_id},
        )
    if is_admin is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only Company Admins manage Facebook Page connection"
        )

    # Exchange code for long-lived user token, then list Pages.
    try:
        user_token = await run_in_threadpool(
            adapter.exchange_code_for_user_token, code, config.redirect_uri
        )
        pages = await run_in_threadpool(adapter.list_pages, user_token)
    except FacebookGraphError as e:
        if _is_meta_role_error(str(e)):
            return _callback_error_redirect(web_base, "no_role")
        return _callback_error_redirect(web_base, "oauth_failed")
    except FacebookTokenError:
        return _callback_error_redirect(web_base, "oauth_failed")
    finally:
        user_token = ""

    if len(pages) == 0:
        return _callback_error_redirect(web_base, "no_pages")

    if len(pages) == 1:
        page = pages[0]
        ciphertext = encrypt_token(page.access_token, config.token_key)
        async with async_tenant_session(state_tenant_id) as session:
            await _upsert_connection(
                session,
                state_tenant_id,
                page.id,
                page.name,
                ciphertext,
                state_user_id,
                audit.client_ip(request),
            )
        redirect = RedirectResponse(f"{web_base}/settings/channels?connected=1", status_code=302)
        _delete_channel_cookie(redirect, OAUTH_STATE_COOKIE)
        _delete_channel_cookie(redirect, PAGE_SELECTION_COOKIE)
        return redirect

    # Multiple pages: keep encrypted tokens server-side in Redis with a short TTL;
    # the browser cookie holds only an opaque random selection id.
    selection_id = secrets.token_urlsafe(32)
    encrypted_selection = encrypt_selection(state_user_id, state_tenant_id, pages, config.token_key)
    await _redis().set(_selection_key(selection_id), encrypted_selection, px=PAGE_SELECTION_TTL)
    redirect = RedirectResponse(f"{web_base}/settings/channels?select_page=1", status_code=302)
    _set_channel_cookie(redirect, PAGE_SELECTION_COOKIE, selection_id, PAGE_SELECTION_TTL)
    _delete_channel_cookie(redirect, OAUTH_STATE_COOKIE)
    return redirect


@router.get("/pages")
async def list_candidate_pages(
    admin: CompanyAdmin,
    fb_page_selection: Annotated[str | None, Cookie()] = None,
) -> list[FacebookPageCandidate]:
    config = check_facebook_config()
    payload = await _load_page_selection(
        fb_page_selection, config.token_key, admin.user_id, admin.tenant_id
    )
    return [FacebookPageCandidate(id=p["id"], name=p["name"]) for p in payload["pages"]]


@router.post("/select")
async def select_page(
    body: SelectPageRequest,
    admin: CompanyAdmin,
    response: Response,
    fb_page_selection: Annotated[str | None, Cookie()] = None,
) -> FacebookConnectionResponse:
    config = check_facebook_config()
    payload = await _load_page_selection(
        fb_page_selection, config.token_key, admin.user_id, admin.tenant_id
    )

    matched = next((p for p in payload["pages"] if p["id"] == body.page_id), None)
    if not matched:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Selected page not found in candidates")

    ciphertext = encrypt_token(matched["access_token"], config.token_key)
    conn_id, created_at = await _upsert_connection(
        admin.db,
        admin.tenant_id,
        matched["id"],
        matched["name"],
        ciphertext,
        admin.user_id,
        admin.ip,
    )

    user_name = (
        await admin.db.execute(
            text("SELECT full_name FROM users WHERE id = :id"),
            {"id": admin.user_id},
        )
    ).scalar_one()

    if fb_page_selection:
        await _redis().delete(_selection_key(fb_page_selection))
    _delete_channel_cookie(response, PAGE_SELECTION_COOKIE)
    return FacebookConnectionResponse(
        id=conn_id,
        channel="FACEBOOK_PAGE",
        external_id=matched["id"],
        name=matched["name"],
        connected_by=admin.user_id,
        connected_by_name=user_name,
        connected_at=created_at,
    )


@router.get("")
async def get_facebook_connection(
    admin: CompanyAdmin,
) -> FacebookConnectionResponse | None:
    row = (
        await admin.db.execute(
            text("""
                SELECT c.id, c.channel, c.external_id, c.name, c.connected_by,
                       u.full_name AS connected_by_name, c.created_at
                FROM channel_connections c
                JOIN users u ON u.tenant_id = c.tenant_id AND u.id = c.connected_by
                WHERE c.channel = 'FACEBOOK_PAGE'
            """)
        )
    ).one_or_none()

    if row is None:
        return None

    return FacebookConnectionResponse(
        id=row.id,
        channel=row.channel,
        external_id=row.external_id,
        name=row.name,
        connected_by=row.connected_by,
        connected_by_name=row.connected_by_name,
        connected_at=row.created_at,
    )


@router.delete("")
async def disconnect_facebook_page(
    admin: CompanyAdmin,
) -> Response:
    deleted = (
        await admin.db.execute(
            text(
                "DELETE FROM channel_connections WHERE channel = 'FACEBOOK_PAGE'"
                " RETURNING id, channel, external_id"
            )
        )
    ).one_or_none()
    if deleted is not None:
        await audit.arecord(
            admin.db,
            actor_type="USER",
            actor_user_id=admin.user_id,
            action="channel_connection.disconnected",
            entity_id=deleted.id,
            before={"channel": deleted.channel, "external_id": deleted.external_id},
            after=None,
            ip=admin.ip,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Channel 03: Channel Posts (FR-A3.5, ERD §6, SAD §5.6) ---


class ChannelPostResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    channel: Literal["FACEBOOK_PAGE"] = "FACEBOOK_PAGE"
    target_id: str
    external_post_id: str
    url: str
    body: str
    posted_by: uuid.UUID
    posted_by_name: str
    posted_at: datetime


class PublishFacebookPostRequest(BaseModel):
    message: str = Field(min_length=1)


class FacebookJobChannelStatus(BaseModel):
    connected: bool
    page_name: str | None = None
    page_id: str | None = None
    posts: list[ChannelPostResponse] = []


def _row_to_channel_post(row: Any) -> ChannelPostResponse:
    return ChannelPostResponse(
        id=row.id,
        job_id=row.job_id,
        channel=row.channel,
        target_id=row.target_id,
        external_post_id=row.external_post_id,
        url=row.url,
        body=row.body,
        posted_by=row.posted_by,
        posted_by_name=row.posted_by_name,
        posted_at=row.posted_at,
    )


@jobs_router.get("/{job_id}/channel-posts")
async def list_channel_posts(
    job_id: uuid.UUID,
    auth: JobManager,
) -> list[ChannelPostResponse]:
    rows = (
        await auth.db.execute(
            text("""
                SELECT p.id, p.job_id, p.channel, p.target_id, p.external_post_id,
                       p.url, p.body, p.posted_by, u.full_name AS posted_by_name, p.posted_at
                FROM channel_posts p
                JOIN users u ON u.tenant_id = p.tenant_id AND u.id = p.posted_by
                WHERE p.job_id = :job_id
                ORDER BY p.posted_at DESC
            """),
            {"job_id": job_id},
        )
    ).all()
    return [_row_to_channel_post(r) for r in rows]


@jobs_router.get("/{job_id}/channels/facebook")
async def get_job_facebook_channel(
    job_id: uuid.UUID,
    auth: JobManager,
) -> FacebookJobChannelStatus:
    conn = (
        await auth.db.execute(
            text(
                "SELECT external_id, name FROM channel_connections WHERE channel = 'FACEBOOK_PAGE'"
            )
        )
    ).one_or_none()
    posts = await list_channel_posts(job_id, auth)
    return FacebookJobChannelStatus(
        connected=conn is not None,
        page_name=conn.name if conn is not None else None,
        page_id=conn.external_id if conn is not None else None,
        posts=posts,
    )


@jobs_router.post("/{job_id}/channel-posts", status_code=status.HTTP_201_CREATED)
async def publish_facebook_post(
    job_id: uuid.UUID,
    body: PublishFacebookPostRequest,
    auth: LockedJob,
    response: Response,
) -> ChannelPostResponse:
    # 1. Verify Job status & public apply preconditions (row locked FOR UPDATE by LockedJob)
    job_row = (
        await auth.db.execute(
            text("""
                SELECT status, public_apply_enabled, public_slug
                FROM jobs
                WHERE id = :id
            """),
            {"id": job_id},
        )
    ).one_or_none()

    if job_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

    if job_row.status != "PUBLISHED":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "JOB_NOT_PUBLISHED",
                "message": "Job must be published to publish to Facebook Page",
            },
        )

    if not job_row.public_apply_enabled or not job_row.public_slug:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "PUBLIC_APPLY_DISABLED",
                "message": "Public apply link must be enabled to publish to Facebook Page",
            },
        )

    # 2. Check Facebook Page connection
    conn_row = (
        await auth.db.execute(
            text("""
                SELECT external_id, name, token_ciphertext
                FROM channel_connections
                WHERE channel = 'FACEBOOK_PAGE'
            """)
        )
    ).one_or_none()

    if conn_row is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "NOT_CONNECTED",
                "message": "Facebook Page is not connected for this Workspace",
            },
        )

    # 3. Check if already posted for this job and page
    existing_post = (
        await auth.db.execute(
            text("""
                SELECT p.id, p.job_id, p.channel, p.target_id, p.external_post_id,
                       p.url, p.body, p.posted_by, u.full_name AS posted_by_name, p.posted_at
                FROM channel_posts p
                JOIN users u ON u.tenant_id = p.tenant_id AND u.id = p.posted_by
                WHERE p.job_id = :job_id
                  AND p.channel = 'FACEBOOK_PAGE'
                  AND p.target_id = :target_id
            """),
            {"job_id": job_id, "target_id": conn_row.external_id},
        )
    ).one_or_none()

    if existing_post is not None:
        response.status_code = status.HTTP_200_OK
        return _row_to_channel_post(existing_post)

    # 4. Decrypt token and call Facebook adapter
    token_key = os.environ.get("CHANNEL_TOKEN_KEY", "").strip()
    try:
        page_token = decrypt_token(conn_row.token_ciphertext, token_key)
    except Exception as e:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CONFIG_ERROR", "message": "Failed to decrypt Facebook access token"},
        ) from e

    web_base = os.environ.get("WEB_BASE_URL", "").rstrip("/")
    apply_url = f"{web_base}/apply/{job_row.public_slug}"

    try:
        post_result = await run_in_threadpool(
            adapter.publish_feed_post,
            page_id=conn_row.external_id,
            page_access_token=page_token,
            message=body.message,
            link=apply_url,
        )
    except FacebookTokenError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "TOKEN_EXPIRED",
                "message": str(e) or "Facebook token is invalid or expired",
            },
        ) from e
    except FacebookGraphError as e:
        if "timed out" in str(e).lower():
            raise HTTPException(
                status.HTTP_504_GATEWAY_TIMEOUT,
                detail={"code": "TIMEOUT", "message": str(e)},
            ) from e
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={"code": "GRAPH_ERROR", "message": str(e)},
        ) from e

    # 5. Insert Channel Post in the same transaction
    inserted = (
        await auth.db.execute(
            text("""
                INSERT INTO channel_posts (
                  id, tenant_id, job_id, channel, target_id,
                  external_post_id, url, body, posted_by, posted_at
                ) VALUES (
                  uuidv7(), :tenant_id, :job_id, 'FACEBOOK_PAGE', :target_id,
                  :external_post_id, :url, :body, :posted_by, now()
                )
                RETURNING id, posted_at
            """),
            {
                "tenant_id": auth.tenant_id,
                "job_id": job_id,
                "target_id": conn_row.external_id,
                "external_post_id": post_result.external_post_id,
                "url": post_result.url,
                "body": body.message,
                "posted_by": auth.user_id,
            },
        )
    ).one()

    poster_name = (
        await auth.db.execute(
            text("SELECT full_name FROM users WHERE id = :id"),
            {"id": auth.user_id},
        )
    ).scalar_one()

    response.status_code = status.HTTP_201_CREATED
    return ChannelPostResponse(
        id=inserted.id,
        job_id=job_id,
        channel="FACEBOOK_PAGE",
        target_id=conn_row.external_id,
        external_post_id=post_result.external_post_id,
        url=post_result.url,
        body=body.message,
        posted_by=auth.user_id,
        posted_by_name=poster_name,
        posted_at=inserted.posted_at,
    )
