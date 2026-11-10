"""Facebook Page channel connection and Meta Graph API adapter (FR-A3.5, SAD §5.6, ERD §6).

Company Admin connects a Facebook Page for the Workspace via OAuth 2.0.
The Page access token is encrypted at rest using Fernet with CHANNEL_TOKEN_KEY
and never leaves the server. Recruiters and Reviewers cannot manage connections.
"""

import json
import os
import secrets
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Protocol

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth import Auth, Authenticated
from app.db import async_tenant_session

router = APIRouter(prefix="/api/channels/facebook")

OAUTH_STATE_TTL = timedelta(minutes=10)
PAGE_SELECTION_COOKIE = "fb_page_selection"
PAGE_SELECTION_TTL = timedelta(minutes=5)


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
    """Raised on other Graph API errors."""


# --- Adapter Protocol and Concrete Implementation ---


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
    """Thin adapter for Meta Graph API calls."""

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def _graph_version(self) -> str:
        return os.environ.get("FACEBOOK_GRAPH_VERSION", "v26.0")

    def _app_credentials(self) -> tuple[str, str]:
        app_id = os.environ.get("FACEBOOK_APP_ID")
        app_secret = os.environ.get("FACEBOOK_APP_SECRET")
        if not app_id or not app_secret:
            raise FacebookGraphError("Facebook app ID or secret is not configured")
        return app_id, app_secret

    def _handle_error(self, data: dict[str, Any], default_message: str) -> None:
        err = data.get("error", {})
        code = err.get("code")
        subcode = err.get("error_subcode")
        msg = err.get("message", default_message)
        if code == 190:
            raise FacebookTokenError(msg, code=code, subcode=subcode)
        raise FacebookGraphError(msg, code=code, subcode=subcode)

    def exchange_code_for_user_token(self, code: str, redirect_uri: str) -> str:
        app_id, app_secret = self._app_credentials()
        version = self._graph_version()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                f"https://graph.facebook.com/{version}/oauth/access_token",
                params={
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
            )
            data = resp.json()
            if resp.status_code != 200:
                self._handle_error(data, "Failed to exchange authorization code")
            short_token = data.get("access_token")
            if not short_token:
                raise FacebookGraphError("No access token in response")

            resp_long = client.get(
                f"https://graph.facebook.com/{version}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "fb_exchange_token": short_token,
                },
            )
            data_long = resp_long.json()
            if resp_long.status_code != 200:
                self._handle_error(data_long, "Failed to obtain long-lived user token")
            long_token = data_long.get("access_token")
            if not long_token:
                raise FacebookGraphError("No long-lived access token in response")
            return str(long_token)

    def list_pages(self, user_access_token: str) -> list[FacebookPage]:
        version = self._graph_version()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                f"https://graph.facebook.com/{version}/me/accounts",
                params={"access_token": user_access_token},
            )
            data = resp.json()
            if resp.status_code != 200:
                self._handle_error(data, "Failed to list Facebook pages")
            pages_data = data.get("data", [])
            return [
                FacebookPage(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    access_token=str(item["access_token"]),
                )
                for item in pages_data
            ]

    def publish_feed_post(
        self,
        page_id: str,
        page_access_token: str,
        message: str,
        link: str | None = None,
    ) -> FacebookPostResult:
        version = self._graph_version()
        with httpx.Client(timeout=self.timeout) as client:
            payload: dict[str, Any] = {
                "message": message,
                "access_token": page_access_token,
            }
            if link:
                payload["link"] = link
            resp = client.post(
                f"https://graph.facebook.com/{version}/{page_id}/feed",
                json=payload,
            )
            data = resp.json()
            if resp.status_code != 200:
                self._handle_error(data, "Failed to publish feed post")
            post_id = str(data["id"])
            return FacebookPostResult(
                external_post_id=post_id,
                url=f"https://www.facebook.com/{post_id}",
            )


# Default adapter seam, monkeypatchable in tests.
adapter: FacebookAdapter = GraphAPIAdapter()


# --- Token Encryption & Configuration Helpers ---


def check_facebook_config() -> dict[str, str]:
    required = [
        "FACEBOOK_APP_ID",
        "FACEBOOK_APP_SECRET",
        "FACEBOOK_REDIRECT_URI",
        "CHANNEL_TOKEN_KEY",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Facebook integration is not configured (missing {', '.join(missing)})",
        )
    return {
        "app_id": os.environ["FACEBOOK_APP_ID"],
        "app_secret": os.environ["FACEBOOK_APP_SECRET"],
        "redirect_uri": os.environ["FACEBOOK_REDIRECT_URI"],
        "graph_version": os.environ.get("FACEBOOK_GRAPH_VERSION", "v26.0"),
        "token_key": os.environ["CHANNEL_TOKEN_KEY"],
    }


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
        "nonce": secrets.token_hex(8),
    }
    return jwt.encode(claims, os.environ["JWT_SECRET"], algorithm="HS256")


def verify_oauth_state(state: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(
            state,
            os.environ["JWT_SECRET"],
            algorithms=["HS256"],
            options={"require": ["sub", "tid", "role", "purpose", "exp"]},
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


async def _upsert_connection(
    session: Any,
    tenant_id: uuid.UUID,
    external_id: str,
    name: str,
    token_ciphertext: bytes,
    connected_by: uuid.UUID,
) -> tuple[uuid.UUID, datetime]:
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
    return row.id, row.created_at


def _verify_page_selection(
    raw: str | None,
    token_key: str,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No page selection in progress")
    payload = decrypt_selection(raw, token_key)
    if uuid.UUID(payload["sub"]) != user_id or uuid.UUID(payload["tid"]) != tenant_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Page selection belongs to another user")
    return payload


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
    response.set_cookie(
        "fb_oauth_state",
        state,
        max_age=int(OAUTH_STATE_TTL.total_seconds()),
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    scope = "pages_manage_posts,pages_read_engagement,pages_show_list"
    params = urllib.parse.urlencode(
        {
            "client_id": config["app_id"],
            "redirect_uri": config["redirect_uri"],
            "scope": scope,
            "state": state,
            "response_type": "code",
        }
    )
    auth_url = f"https://www.facebook.com/{config['graph_version']}/dialog/oauth?{params}"
    return {"auth_url": auth_url}


@router.get("/callback")
async def facebook_callback(
    request: Request,
    response: Response,
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
        if error == "access_denied" or error_reason == "user_denied":
            return RedirectResponse(
                f"{web_base}/settings/channels?error=cancelled", status_code=302
            )
        desc_lower = (error_description or "").lower()
        if (
            "role" in desc_lower
            or "developer" in desc_lower
            or "not active" in desc_lower
            or error == "no_role"
        ):
            return RedirectResponse(f"{web_base}/settings/channels?error=no_role", status_code=302)
        return RedirectResponse(f"{web_base}/settings/channels?error=oauth_failed", status_code=302)

    if not code or not state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing code or state")

    config = check_facebook_config()
    claims = verify_oauth_state(state)
    state_user_id = uuid.UUID(claims["sub"])
    state_tenant_id = uuid.UUID(claims["tid"])

    # Authenticate and verify user context matches the state
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        bearer_token = auth_header[7:].strip()
        try:
            bearer_claims = jwt.decode(
                bearer_token,
                os.environ["JWT_SECRET"],
                algorithms=["HS256"],
                options={"require": ["sub", "tid", "role"]},
            )
            bearer_user_id = uuid.UUID(bearer_claims["sub"])
            bearer_tenant_id = uuid.UUID(bearer_claims["tid"])
            bearer_role = bearer_claims["role"]
        except Exception as e:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authorization token") from e

        if bearer_role != "COMPANY_ADMIN":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Only Company Admins manage Facebook Page connection"
            )
        if bearer_user_id != state_user_id or bearer_tenant_id != state_tenant_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "OAuth state belongs to another user")
    elif fb_oauth_state:
        try:
            cookie_claims = verify_oauth_state(fb_oauth_state)
            cookie_user_id = uuid.UUID(cookie_claims["sub"])
            cookie_tenant_id = uuid.UUID(cookie_claims["tid"])
            cookie_role = cookie_claims["role"]
        except Exception as e:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Invalid or expired state cookie"
            ) from e

        if cookie_role != "COMPANY_ADMIN":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Only Company Admins manage Facebook Page connection"
            )
        if cookie_user_id != state_user_id or cookie_tenant_id != state_tenant_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "OAuth state belongs to another user")
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing OAuth authentication context")

    if claims.get("role") != "COMPANY_ADMIN":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only Company Admins manage Facebook Page connection"
        )

    # Exchange code for long-lived user token
    try:
        user_token = adapter.exchange_code_for_user_token(code, config["redirect_uri"])
    except FacebookTokenError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Facebook token error: {e}") from e
    except FacebookGraphError as e:
        msg_lower = str(e).lower()
        if "role" in msg_lower or "developer" in msg_lower or "not active" in msg_lower:
            return RedirectResponse(f"{web_base}/settings/channels?error=no_role", status_code=302)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Facebook API error: {e}") from e

    # List pages
    try:
        pages = adapter.list_pages(user_token)
    except FacebookTokenError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Facebook token error: {e}") from e
    except FacebookGraphError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Facebook API error: {e}") from e

    # Drop user token immediately (never stored in DB or cookie)
    del user_token

    if len(pages) == 0:
        redirect = RedirectResponse(f"{web_base}/settings/channels?error=no_pages", status_code=302)
        redirect.delete_cookie("fb_oauth_state", path="/")
        return redirect

    if len(pages) == 1:
        page = pages[0]
        ciphertext = encrypt_token(page.access_token, config["token_key"])
        async with async_tenant_session(state_tenant_id) as session:
            await _upsert_connection(
                session,
                state_tenant_id,
                page.id,
                page.name,
                ciphertext,
                state_user_id,
            )
        redirect = RedirectResponse(f"{web_base}/settings/channels?connected=1", status_code=302)
        redirect.delete_cookie("fb_oauth_state", path="/")
        redirect.delete_cookie(PAGE_SELECTION_COOKIE, path="/")
        return redirect

    # Multiple pages: store encrypted candidate pages with short TTL in HttpOnly cookie
    selection_str = encrypt_selection(state_user_id, state_tenant_id, pages, config["token_key"])
    redirect = RedirectResponse(f"{web_base}/settings/channels?select_page=1", status_code=302)
    redirect.set_cookie(
        PAGE_SELECTION_COOKIE,
        selection_str,
        max_age=int(PAGE_SELECTION_TTL.total_seconds()),
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    redirect.delete_cookie("fb_oauth_state", path="/")
    return redirect


@router.get("/pages")
async def list_candidate_pages(
    admin: CompanyAdmin,
    fb_page_selection: Annotated[str | None, Cookie()] = None,
) -> list[FacebookPageCandidate]:
    config = check_facebook_config()
    payload = _verify_page_selection(
        fb_page_selection, config["token_key"], admin.user_id, admin.tenant_id
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
    payload = _verify_page_selection(
        fb_page_selection, config["token_key"], admin.user_id, admin.tenant_id
    )

    matched = next((p for p in payload["pages"] if p["id"] == body.page_id), None)
    if not matched:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Selected page not found in candidates")

    ciphertext = encrypt_token(matched["access_token"], config["token_key"])
    conn_id, created_at = await _upsert_connection(
        admin.db,
        admin.tenant_id,
        matched["id"],
        matched["name"],
        ciphertext,
        admin.user_id,
    )

    user_name = (
        await admin.db.execute(
            text("SELECT full_name FROM users WHERE id = :id"),
            {"id": admin.user_id},
        )
    ).scalar_one()

    response.delete_cookie(PAGE_SELECTION_COOKIE, path="/")
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
    auth: Authenticated,
) -> FacebookConnectionResponse | None:
    if auth.role not in ("COMPANY_ADMIN", "RECRUITER"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only Company Admins and Recruiters view channel connections",
        )

    row = (
        await auth.db.execute(
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
    await admin.db.execute(text("DELETE FROM channel_connections WHERE channel = 'FACEBOOK_PAGE'"))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
