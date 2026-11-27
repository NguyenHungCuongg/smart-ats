"""Company Admins invite, list, re-role and revoke the Members of their Workspace (FR-C1.2).

An invitation's token goes out only inside its email (app.emails); the database keeps its
SHA-256. Accepting needs no login: accept_invitation (ERD §8) finds the Tenant, and the new
User is created and signed in within the same transaction, so a failure leaves the invitation
usable.
"""

import hashlib
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app import audit, emails, outbox
from app.auth import (
    REFRESH_TTL,
    Auth,
    Authenticated,
    TokenResponse,
    clear_session_bound_cookies,
    issue_tokens,
    password_hash,
)
from app.db import async_engine, set_tenant

# FR-C1.2.
INVITATION_TTL = timedelta(hours=48)

TenantRole = Literal["COMPANY_ADMIN", "RECRUITER", "REVIEWER"]
ROLE_NAMES = {"COMPANY_ADMIN": "Company Admin", "RECRUITER": "Recruiter", "REVIEWER": "Reviewer"}

# Subject and body of the invitation email in each language (NFR-USE-03).
_INVITATION_EMAIL: dict[emails.Locale, tuple[str, str]] = {
    "vi": (
        "Lời mời tham gia {workspace} trên Smart ATS",
        "{workspace} mời bạn tham gia Smart ATS với vai trò {role}.\n\n"
        "Mở liên kết sau để tạo tài khoản. Liên kết chỉ dùng được một lần và hết hạn"
        " sau {hours} giờ:\n{link}\n",
    ),
    "en": (
        "Join {workspace} on Smart ATS",
        "{workspace} invited you to Smart ATS as {role}.\n\n"
        "Open this link to create your account. The link works once and expires"
        " in {hours} hours:\n{link}\n",
    ),
}

# Wrong, expired, used or revoked token, or an email that already has an account elsewhere:
# one answer, so it reveals nothing about which (FR-C1.2).
_INVALID_INVITATION = "This invitation is invalid or has expired"

router = APIRouter(prefix="/api")


def _company_admin(auth: Authenticated) -> Auth:
    # SRS §2.2: managing the Workspace and its Members is for Company Admins only.
    if auth.role != "COMPANY_ADMIN":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only Company Admins manage Members")
    return auth


CompanyAdmin = Annotated[Auth, Depends(_company_admin)]


class Member(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: TenantRole
    is_active: bool
    last_login_at: datetime | None


class PendingInvitation(BaseModel):
    id: uuid.UUID
    email: str
    role: TenantRole
    created_at: datetime
    expires_at: datetime
    # FAILED: the Company Admin invites again, which makes a new token.
    email_status: Literal["QUEUED", "SENT", "FAILED"]


class Members(BaseModel):
    members: list[Member]
    invitations: list[PendingInvitation]


class InvitationRequest(BaseModel):
    # ponytail: shape only; the email bouncing is what really tells.
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: TenantRole


class InvitationCreated(BaseModel):
    id: uuid.UUID


class RoleChange(BaseModel):
    role: TenantRole


class Acceptance(BaseModel):
    token: str = Field(max_length=100)
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=256)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _record_invitation_revoked(auth: Auth, invitation_id: uuid.UUID, role: str) -> None:
    await audit.arecord(
        auth.db,
        actor_type="USER",
        actor_user_id=auth.user_id,
        action="invitation.revoked",
        entity_id=invitation_id,
        before={"role": role, "status": "PENDING"},
        after={"invitation_id": str(invitation_id), "status": "REVOKED"},
        ip=auth.ip,
    )


@router.get("/members")
async def list_members(auth: CompanyAdmin) -> Members:
    users = await auth.db.execute(
        text(
            "SELECT id, email, full_name, role, is_active, last_login_at FROM users"
            " ORDER BY created_at"
        )
    )
    invitations = await auth.db.execute(
        text(
            "SELECT i.id, i.email, i.role, i.created_at, i.expires_at, e.status AS email_status"
            " FROM invitations i JOIN email_messages e ON e.id = i.email_id"
            " WHERE i.accepted_at IS NULL AND i.revoked_at IS NULL AND i.expires_at > now()"
            " ORDER BY i.created_at"
        )
    )
    return Members(
        members=[Member.model_validate(row._mapping) for row in users],
        invitations=[PendingInvitation.model_validate(row._mapping) for row in invitations],
    )


@router.post("/invitations", status_code=status.HTTP_201_CREATED)
async def invite(
    body: InvitationRequest,
    auth: CompanyAdmin,
    next_locale: Annotated[str | None, Cookie(alias="NEXT_LOCALE")] = None,
) -> InvitationCreated:
    """Invite email as role; its email is QUEUED with it and sent once both commit (SAD §5.4)."""
    db = auth.db
    # Invitations of one email run one at a time, so the revoke below sees every pending one.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(lower(:email), 0))"),
        {"email": body.email},
    )
    # Only this Tenant's Users are visible; one elsewhere surfaces when the invitee accepts.
    if await db.scalar(text("SELECT 1 FROM users WHERE email = :email"), {"email": body.email}):
        raise HTTPException(status.HTTP_409_CONFLICT, "This email is already a Member")
    # Inviting again replaces the pending invitation: only the newest link works.
    revoked_rows = (
        await db.execute(
            text(
                "UPDATE invitations SET revoked_at = now()"
                " WHERE email = :email AND accepted_at IS NULL AND revoked_at IS NULL"
                "   AND expires_at > now()"
                " RETURNING id, role"
            ),
            {"email": body.email},
        )
    ).all()
    for revoked in revoked_rows:
        await _record_invitation_revoked(auth, revoked.id, revoked.role)
    workspace = await db.scalar(text("SELECT name FROM tenants"))
    token = secrets.token_urlsafe(32)
    # emails.finish masks the token once sent by its "token=" parameter: keep that name.
    link = f"{os.environ['WEB_BASE_URL']}/invitations/accept?token={token}"
    hours = INVITATION_TTL // timedelta(hours=1)
    subject, message = _INVITATION_EMAIL[emails.locale(next_locale)]
    email_id = await db.scalar(
        text(
            "INSERT INTO email_messages (tenant_id, kind, to_address, subject, body, status,"
            "  attempts, enqueued_at, sent_by)"
            " VALUES (:tenant_id, 'MEMBER_INVITATION', :to, :subject, :body, 'QUEUED', 1, now(),"
            "  :user_id) RETURNING id"
        ),
        {
            "tenant_id": auth.tenant_id,
            "to": body.email,
            "subject": subject.format(workspace=workspace),
            "body": message.format(
                workspace=workspace, role=ROLE_NAMES[body.role], hours=hours, link=link
            ),
            "user_id": auth.user_id,
        },
    )
    invitation_id: uuid.UUID = (
        await db.execute(
            text(
                "INSERT INTO invitations (tenant_id, email, role, token_hash, invited_by, email_id,"
                "  expires_at)"
                " VALUES (:tenant_id, :email, :role, :token_hash, :user_id, :email_id,"
                "  now() + :ttl) RETURNING id"
            ),
            {
                "tenant_id": auth.tenant_id,
                "email": body.email,
                "role": body.role,
                "token_hash": _hash_token(token),
                "user_id": auth.user_id,
                "email_id": email_id,
                "ttl": INVITATION_TTL,
            },
        )
    ).scalar_one()
    await audit.arecord(
        db,
        actor_type="USER",
        actor_user_id=auth.user_id,
        action="invitation.created",
        entity_id=invitation_id,
        after={"invitation_id": str(invitation_id), "role": body.role},
        ip=auth.ip,
    )
    outbox.enqueue_after_commit(db, emails.send_email, (str(auth.tenant_id), str(email_id)))
    return InvitationCreated(id=invitation_id)


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(invitation_id: uuid.UUID, auth: CompanyAdmin) -> None:
    revoked = (
        await auth.db.execute(
            text(
                "UPDATE invitations SET revoked_at = now()"
                " WHERE id = :id AND accepted_at IS NULL AND revoked_at IS NULL"
                "   AND expires_at > now()"
                " RETURNING id, role"
            ),
            {"id": invitation_id},
        )
    ).one_or_none()
    if revoked is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No pending invitation")
    await _record_invitation_revoked(auth, revoked.id, revoked.role)


@router.post("/invitations/accept")
async def accept(body: Acceptance, request: Request, response: Response) -> TokenResponse:
    """Create the invited User and sign them in, as /api/auth/login does."""
    # Not tenant_session: the Tenant is known only once accept_invitation has found it, and
    # the User must be created in the transaction that accepted (ERD §8).
    token_hash = _hash_token(body.token)
    async with AsyncSession(async_engine()) as db, db.begin():
        invitation = (
            await db.execute(
                text("SELECT * FROM accept_invitation(:token_hash)"),
                {"token_hash": token_hash},
            )
        ).one_or_none()
        if invitation is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, _INVALID_INVITATION)
        await set_tenant(db, invitation.tenant_id)
        invitation_id: uuid.UUID = (
            await db.execute(
                text("SELECT id FROM invitations WHERE token_hash = :token_hash"),
                {"token_hash": token_hash},
            )
        ).scalar_one()
        # Hashed only for a valid token: anyone may call this, and Argon2 is slow on purpose.
        hashed = await run_in_threadpool(password_hash.hash, body.password)
        try:
            user_id: uuid.UUID = (
                await db.execute(
                    text(
                        "INSERT INTO users (tenant_id, email, password_hash, full_name, role,"
                        "  is_active, last_login_at)"
                        " VALUES (:tenant_id, :email, :password_hash, :full_name, :role,"
                        "  true, now())"
                        " RETURNING id"
                    ),
                    {
                        "tenant_id": invitation.tenant_id,
                        "email": invitation.email,
                        "password_hash": hashed,
                        "full_name": body.full_name,
                        "role": invitation.role,
                    },
                )
            ).scalar_one()
        except IntegrityError:
            # users.email is unique platform-wide: the email has an account in another Tenant.
            # Raising rolls back the acceptance too.
            raise HTTPException(status.HTTP_400_BAD_REQUEST, _INVALID_INVITATION) from None
        await audit.arecord(
            db,
            actor_type="USER",
            actor_user_id=user_id,
            action="invitation.accepted",
            entity_id=invitation_id,
            before={"status": "PENDING"},
            after={
                "invitation_id": str(invitation_id),
                "role": invitation.role,
                "status": "ACCEPTED",
            },
            ip=audit.client_ip(request),
        )
        tokens, _ = await issue_tokens(
            db,
            response,
            user_id,
            invitation.tenant_id,
            invitation.role,
            family_id=uuid.uuid4(),
            expires_at=datetime.now(UTC) + REFRESH_TTL,
        )
    clear_session_bound_cookies(response)
    return tokens


async def _lock_admins(db: AsyncSession) -> set[uuid.UUID]:
    """The active Company Admins, locked in one order before any change to a Member.

    Two Admins demoting or revoking each other at once then run one after the other, and the
    second sees that the first left only itself.
    """
    return set(
        await db.scalars(
            text(
                "SELECT id FROM users WHERE role = 'COMPANY_ADMIN' AND is_active"
                " ORDER BY id FOR UPDATE"
            )
        )
    )


def _last_admin() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "The Workspace needs a Company Admin")


@router.patch("/members/{member_id}")
async def change_role(member_id: uuid.UUID, body: RoleChange, auth: CompanyAdmin) -> Member:
    """Takes effect at the Member's next refresh, which reads the role again (FR-C1.1)."""
    admins = await _lock_admins(auth.db)
    if admins == {member_id} and body.role != "COMPANY_ADMIN":
        raise _last_admin()
    member = (
        await auth.db.execute(
            text(
                "UPDATE users SET role = :role WHERE id = :id"
                " RETURNING id, email, full_name, role, is_active, last_login_at,"
                "   old.role AS previous_role"
            ),
            {"id": member_id, "role": body.role},
        )
    ).one_or_none()
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    if member.previous_role != member.role:
        await audit.arecord(
            auth.db,
            actor_type="USER",
            actor_user_id=auth.user_id,
            action="member.role_changed",
            entity_id=member_id,
            before={"role": member.previous_role},
            after={"role": member.role},
            ip=auth.ip,
        )
    return Member.model_validate(member._mapping)


@router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_member(member_id: uuid.UUID, auth: CompanyAdmin) -> None:
    """Deactivate the Member and revoke every refresh token family of theirs (FR-C1.2).

    An access token already issued works until it expires (FR-C1.1).
    """
    if member_id == auth.user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot revoke yourself")
    if await _lock_admins(auth.db) == {member_id}:
        raise _last_admin()
    revoked = (
        await auth.db.execute(
            text(
                "UPDATE users SET is_active = false WHERE id = :id"
                " RETURNING id, role, old.is_active AS was_active"
            ),
            {"id": member_id},
        )
    ).one_or_none()
    if revoked is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    await auth.db.execute(
        text(
            "UPDATE refresh_tokens SET revoked_at = now()"
            " WHERE user_id = :id AND revoked_at IS NULL"
        ),
        {"id": member_id},
    )
    if revoked.was_active:
        await audit.arecord(
            auth.db,
            actor_type="USER",
            actor_user_id=auth.user_id,
            action="member.revoked",
            entity_id=member_id,
            before={"is_active": True, "role": revoked.role},
            after={"is_active": False},
            ip=auth.ip,
        )
