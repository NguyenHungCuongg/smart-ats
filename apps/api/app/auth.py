"""Password login with rotating refresh tokens (FR-C1.1, ADR-0003, SAD §4.2)."""

import hashlib
import os
import secrets
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Annotated, Literal

import jwt
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from pydantic import BaseModel, Field
from redis.asyncio import BlockingConnectionPool, Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.db import async_engine, async_tenant_session

# Lifetimes: FR-C1.1.
ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=7)
REFRESH_COOKIE = "refresh_token"
REFRESH_PATH = "/api/auth/refresh"
# Lockout after consecutive failures, per account and per IP: FR-C1.1.
MAX_FAILURES = 5
LOCK_FOR = timedelta(minutes=15)
_LOCKED_DETAIL = "Too many failed logins, try again later"
# SAD §4.3.
MAX_REDIS_CONNECTIONS = 50

# Counts a login attempt unless the account is locked; returns no row if it is. Reaching
# max_failures locks it, and the count starts again for after the lock; a success resets both.
_COUNT_ATTEMPT = text("""
    UPDATE users SET
      failed_login_count =
        CASE WHEN failed_login_count + 1 >= :max_failures THEN 0 ELSE failed_login_count + 1 END,
      locked_until =
        CASE WHEN failed_login_count + 1 >= :max_failures THEN now() + :lock_for END
    WHERE id = :id AND (locked_until IS NULL OR locked_until <= now())
    RETURNING id
""")
# The same rule in Redis, for IPs and for emails without an account, so an unknown email locks
# exactly like a real one. The lock lasts lock_for from the failure that set it: attempts while
# locked are not counted and do not extend it.
# ponytail: the counter forgets after a day without attempts, unlike users.failed_login_count;
# five guesses spread over days could tell an unknown email apart. Fine below NFR-SEC-06.
_COUNT_ATTEMPT_LUA = """
if redis.call('EXISTS', KEYS[2]) == 1 then return 0 end
local n = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], 86400)
if n >= tonumber(ARGV[1]) then
  redis.call('DEL', KEYS[1])
  redis.call('SET', KEYS[2], 1, 'PX', ARGV[2])
end
return 1
"""
# Refresh, reuse detection and logout of one family run one at a time: a revoke running
# alongside a rotation would miss the token the rotation was minting. The lock is taken in its
# own statement, so every later statement sees what the previous holder committed.
_LOCK_FAMILY = text(
    "SELECT family_id, pg_advisory_xact_lock(hashtextextended(family_id::text, 0))"
    " FROM refresh_tokens WHERE token_hash = :token_hash"
)
_REVOKE_FAMILY = text(
    "UPDATE refresh_tokens SET revoked_at = now()"
    " WHERE family_id = :family_id AND revoked_at IS NULL"
)

router = APIRouter(prefix="/api/auth")


@cache
def _redis() -> Redis:
    # Capped (SAD §4.3): a burst of requests waits for a free connection rather than opening more.
    pool = BlockingConnectionPool.from_url(
        os.environ["REDIS_URL"], max_connections=MAX_REDIS_CONNECTIONS
    )
    return Redis(connection_pool=pool)


async def _count_attempt(key: str) -> bool:
    """Counts a login attempt against key, as _COUNT_ATTEMPT_LUA; False if key is locked."""
    count = _redis().register_script(_COUNT_ATTEMPT_LUA)
    lock_ms = int(LOCK_FOR.total_seconds() * 1000)
    keys = [f"login_attempts:{key}", f"login_locked:{key}"]
    return bool(await count(keys=keys, args=[MAX_FAILURES, lock_ms]))


password_hash = PasswordHash.recommended()
_DUMMY_HASH = password_hash.hash(secrets.token_urlsafe())


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = int(ACCESS_TTL.total_seconds())


def _access_token(user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> str:
    now = datetime.now(UTC)
    claims = {"sub": str(user_id), "tid": str(tenant_id), "role": role, "iat": now}
    return jwt.encode(claims | {"exp": now + ACCESS_TTL}, os.environ["JWT_SECRET"], "HS256")


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response) -> TokenResponse:
    # Attempts are counted before the slow password check and the count is cleared on success,
    # so concurrent guesses cannot all slip in under the limit.
    ip = f"ip:{request.client.host if request.client else 'unknown'}"
    if not await _count_attempt(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, _LOCKED_DETAIL)

    async with async_engine().begin() as conn:
        user = (
            await conn.execute(text("SELECT * FROM auth_find_user(:email)"), {"email": body.email})
        ).one_or_none()
    # tenant_id is NULL for a System Admin, whose login is not built yet.
    if user is None or user.tenant_id is None or user.password_hash is None:
        user = None
        email = hashlib.sha256(body.email.lower().encode()).hexdigest()
        if not await _count_attempt(f"email:{email}"):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, _LOCKED_DETAIL)
    else:
        async with async_tenant_session(user.tenant_id) as db:
            counted = await db.scalar(
                _COUNT_ATTEMPT,
                {"id": user.id, "max_failures": MAX_FAILURES, "lock_for": LOCK_FOR},
            )
        if counted is None:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, _LOCKED_DETAIL)

    # Verify even without an account, so response time does not reveal which emails exist.
    valid = await run_in_threadpool(
        password_hash.verify, body.password, user.password_hash if user else _DUMMY_HASH
    )
    if user is None or not valid or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    await _redis().delete(f"login_attempts:{ip}", f"login_locked:{ip}")
    async with async_tenant_session(user.tenant_id) as db:
        await db.execute(
            text(
                "UPDATE users SET failed_login_count = 0, locked_until = NULL,"
                " last_login_at = now() WHERE id = :id"
            ),
            {"id": user.id},
        )
        tokens, _ = await issue_tokens(
            db,
            response,
            user.id,
            user.tenant_id,
            user.role,
            family_id=uuid.uuid4(),
            expires_at=datetime.now(UTC) + REFRESH_TTL,
        )
    return tokens


def _require_csrf_header(x_requested_with: Annotated[str | None, Header()] = None) -> None:
    # The cookie endpoints need a custom header, which a cross-site form cannot send (ADR-0003).
    if not x_requested_with:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing X-Requested-With header")


@router.post("/refresh", dependencies=[Depends(_require_csrf_header)])
async def refresh(
    response: Response, refresh_token: Annotated[str, Cookie()] = ""
) -> TokenResponse:
    tenant_id = _tenant_of(refresh_token)
    if tenant_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    tokens = None
    token_hash = _hash_refresh_token(refresh_token)
    async with async_tenant_session(tenant_id) as db:
        await db.execute(_LOCK_FAMILY, {"token_hash": token_hash})
        token = (
            await db.execute(
                text(
                    "SELECT t.id, t.user_id, t.family_id, t.expires_at, t.revoked_at,"
                    "  u.role, u.is_active"
                    " FROM refresh_tokens t"
                    " JOIN users u ON u.tenant_id = t.tenant_id AND u.id = t.user_id"
                    " WHERE t.token_hash = :token_hash"
                ),
                {"token_hash": token_hash},
            )
        ).one_or_none()
        if token is not None and (token.revoked_at is not None or not token.is_active):
            # A rotated or logged-out token came back, expired or not: assume it was stolen
            # (FR-C1.1). Committed by leaving the block normally; raising would roll it back.
            await db.execute(_REVOKE_FAMILY, {"family_id": token.family_id})
        elif token is not None and token.expires_at > datetime.now(UTC):
            # Rotation keeps the family's expiry, set once at login (FR-C1.1).
            tokens, new_id = await issue_tokens(
                db,
                response,
                token.user_id,
                tenant_id,
                token.role,
                family_id=token.family_id,
                expires_at=token.expires_at,
            )
            await db.execute(
                text(
                    "UPDATE refresh_tokens SET revoked_at = now(), replaced_by_id = :new_id"
                    " WHERE id = :id"
                ),
                {"id": token.id, "new_id": new_id},
            )
    if tokens is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    return tokens


@router.delete(
    "/refresh", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(_require_csrf_header)]
)
async def logout(response: Response, refresh_token: Annotated[str, Cookie()] = "") -> None:
    """Revoke the refresh token's whole family (FR-C1.1); a missing or unknown token is a no-op."""
    tenant_id = _tenant_of(refresh_token)
    if tenant_id is not None:
        async with async_tenant_session(tenant_id) as db:
            family_id = await db.scalar(
                _LOCK_FAMILY, {"token_hash": _hash_refresh_token(refresh_token)}
            )
            await db.execute(_REVOKE_FAMILY, {"family_id": family_id})
    response.delete_cookie(
        REFRESH_COOKIE, path=REFRESH_PATH, secure=True, httponly=True, samesite="strict"
    )


def _hash_refresh_token(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode()).hexdigest()


def _tenant_of(refresh_token: str) -> uuid.UUID | None:
    """The Tenant a refresh token claims; RLS then hides its row if the claim is false."""
    try:
        return uuid.UUID(refresh_token.partition(".")[0])
    except ValueError:
        return None


async def issue_tokens(
    db: AsyncSession,
    response: Response,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role: str,
    *,
    family_id: uuid.UUID,
    expires_at: datetime,
) -> tuple[TokenResponse, uuid.UUID]:
    """Issue an access token and set a new refresh token of family_id as the cookie.

    Returns the access token and the refresh token's row id.
    """
    # The tenant id travels inside the refresh token: refresh finds its row under RLS.
    refresh_token = f"{tenant_id}.{secrets.token_urlsafe(32)}"
    token_id: uuid.UUID = (
        await db.execute(
            text(
                "INSERT INTO refresh_tokens (tenant_id, user_id, family_id, token_hash, expires_at)"
                " VALUES (:tenant_id, :user_id, :family_id, :token_hash, :expires_at) RETURNING id"
            ),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "family_id": family_id,
                "token_hash": _hash_refresh_token(refresh_token),
                "expires_at": expires_at,
            },
        )
    ).scalar_one()
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=round((expires_at - datetime.now(UTC)).total_seconds()),
        path=REFRESH_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return TokenResponse(access_token=_access_token(user_id, tenant_id, role)), token_id


@dataclass(frozen=True)
class Auth:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    db: AsyncSession


def _unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not authenticated", {"WWW-Authenticate": "Bearer"}
    )


async def _authenticate(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
    ],
) -> AsyncIterator[Auth]:
    """Every authenticated request runs in one transaction scoped to its JWT's tid (SAD §4.2)."""
    if credentials is None:
        raise _unauthorized()
    try:
        claims = jwt.decode(
            credentials.credentials,
            os.environ["JWT_SECRET"],
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "tid", "role"]},
        )
        user_id, tenant_id = uuid.UUID(claims["sub"]), uuid.UUID(claims["tid"])
    except (jwt.PyJWTError, ValueError) as e:
        raise _unauthorized() from e
    async with async_tenant_session(tenant_id) as db:
        yield Auth(user_id, tenant_id, claims["role"], db)


# scope="function": the transaction commits before the response is sent, not after.
Authenticated = Annotated[Auth, Depends(_authenticate, scope="function")]


class Me(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str


@router.get("/me")
async def me(auth: Authenticated) -> Me:
    user = (
        await auth.db.execute(
            text("SELECT id, email, full_name, role FROM users WHERE id = :id"),
            {"id": auth.user_id},
        )
    ).one_or_none()
    if user is None:
        raise _unauthorized()
    return Me.model_validate(user._mapping)
