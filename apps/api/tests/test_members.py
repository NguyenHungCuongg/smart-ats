"""Invite Members through the email outbox, change their role, revoke them (FR-C1.2, SAD §5.4).

The broker and SMTP are faked; the API, the send task and PostgreSQL are real.
"""

import asyncio
import hashlib
import re
import secrets
import smtplib
import uuid
from collections.abc import AsyncIterator
from email.message import EmailMessage
from typing import Any

import jwt
import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text

from app import emails
from app.db import sync_engine, tenant_session
from app.main import app
from tests.test_jobs import User, make_user

pytestmark = pytest.mark.usefixtures("database")

PASSWORD = "correct horse battery staple"
SECRET = "test-secret-at-least-32-bytes-long!"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv("WEB_BASE_URL", "https://ats.example")
    monkeypatch.setenv("EMAIL_FROM", "Smart ATS <no-reply@ats.example>")


@pytest.fixture(autouse=True)
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """send_email tasks sent to the broker, as their arguments."""
    sent: list[tuple[str, ...]] = []
    monkeypatch.setattr(emails.send_email, "delay", lambda *args: sent.append(args))
    return sent


@pytest.fixture(autouse=True)
def sent_mail(monkeypatch: pytest.MonkeyPatch) -> list[EmailMessage]:
    """Messages handed to the SMTP server."""
    delivered: list[EmailMessage] = []
    monkeypatch.setattr(emails, "deliver", delivered.append)
    return delivered


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    # https: the refresh cookie is Secure, so the client only sends it back over https.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


@pytest.fixture
def admin() -> User:
    return make_user("COMPANY_ADMIN")


def email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


async def invite(client: AsyncClient, admin: User, to: str, role: str = "REVIEWER") -> Response:
    return await client.post(
        "/api/invitations", headers=admin.headers, json={"email": to, "role": role}
    )


def send_all(enqueued: list[tuple[str, ...]]) -> None:
    """Run every send_email task enqueued so far, as the email worker would."""
    while enqueued:
        emails.send_email.apply(args=enqueued.pop(0)).get()


def token_in(message: EmailMessage) -> str:
    body = message.get_content()
    match = re.search(r"https://ats\.example/invitations/accept\?token=([\w-]+)", body)
    assert match, body
    return match.group(1)


async def invited_token(
    client: AsyncClient,
    admin: User,
    enqueued: list[tuple[str, ...]],
    sent_mail: list[EmailMessage],
    to: str,
    role: str = "REVIEWER",
) -> str:
    assert (await invite(client, admin, to, role)).status_code == 201
    send_all(enqueued)
    return token_in(sent_mail[-1])


async def accept(client: AsyncClient, token: str, full_name: str = "Lê Thị Hoa") -> Response:
    return await client.post(
        "/api/invitations/accept",
        json={"token": token, "full_name": full_name, "password": PASSWORD},
    )


async def members(client: AsyncClient, admin: User) -> dict[str, Any]:
    response = await client.get("/api/members", headers=admin.headers)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def claims(response: Response) -> dict[str, Any]:
    decoded: dict[str, Any] = jwt.decode(
        response.json()["access_token"], SECRET, algorithms=["HS256"]
    )
    return decoded


async def test_invitation_is_queued_then_sent_with_a_one_time_link(
    client: AsyncClient,
    admin: User,
    enqueued: list[tuple[str, ...]],
    sent_mail: list[EmailMessage],
) -> None:
    to = email()

    response = await invite(client, admin, to)

    assert response.status_code == 201
    [pending] = (await members(client, admin))["invitations"]
    assert (pending["email"], pending["role"], pending["email_status"]) == (
        to,
        "REVIEWER",
        "QUEUED",
    )
    assert [args[0] for args in enqueued] == [str(admin.tenant_id)]
    assert sent_mail == []  # nothing is sent before the worker runs

    send_all(enqueued)

    [message] = sent_mail
    assert message["To"] == to
    assert token_in(message)
    [pending] = (await members(client, admin))["invitations"]
    assert pending["email_status"] == "SENT"


async def test_invitee_accepts_and_is_signed_in_with_the_invited_role(
    client: AsyncClient,
    admin: User,
    enqueued: list[tuple[str, ...]],
    sent_mail: list[EmailMessage],
) -> None:
    to = email()
    token = await invited_token(client, admin, enqueued, sent_mail, to)

    response = await accept(client, token)

    assert response.status_code == 200
    assert claims(response)["role"] == "REVIEWER"
    assert claims(response)["tid"] == str(admin.tenant_id)
    assert "refresh_token=" in response.headers["set-cookie"]
    me = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
    )
    assert (me.json()["email"], me.json()["full_name"]) == (to, "Lê Thị Hoa")
    listed = await members(client, admin)
    assert listed["invitations"] == []
    [member] = [m for m in listed["members"] if m["email"] == to]
    assert (member["role"], member["is_active"]) == ("REVIEWER", True)
    assert member["last_login_at"] is not None


def expire(tenant_id: uuid.UUID) -> None:
    with tenant_session(tenant_id) as session:
        session.execute(text("UPDATE invitations SET expires_at = now() - interval '1 second'"))


async def revoke_pending(client: AsyncClient, admin: User) -> None:
    [pending] = (await members(client, admin))["invitations"]
    response = await client.delete(f"/api/invitations/{pending['id']}", headers=admin.headers)
    assert response.status_code == 204


@pytest.mark.parametrize("spoil", ["used", "expired", "revoked", "unknown"])
async def test_spoiled_token_gets_the_one_generic_error(
    client: AsyncClient,
    admin: User,
    enqueued: list[tuple[str, ...]],
    sent_mail: list[EmailMessage],
    spoil: str,
) -> None:
    token = await invited_token(client, admin, enqueued, sent_mail, email())
    if spoil == "used":
        assert (await accept(client, token)).status_code == 200
    elif spoil == "expired":
        expire(admin.tenant_id)
    elif spoil == "revoked":
        await revoke_pending(client, admin)
    else:
        token = secrets.token_urlsafe(32)

    response = await accept(client, token)

    assert response.status_code == 400
    assert response.json() == {"detail": "This invitation is invalid or has expired"}
    assert "set-cookie" not in response.headers


@pytest.mark.cross_tenant
async def test_email_with_an_account_elsewhere_is_refused_and_the_invitation_kept(
    client: AsyncClient,
    admin: User,
    enqueued: list[tuple[str, ...]],
    sent_mail: list[EmailMessage],
) -> None:
    to = email()
    token = await invited_token(client, admin, enqueued, sent_mail, to)
    elsewhere = make_user()
    with tenant_session(elsewhere.tenant_id) as session:
        session.execute(text("UPDATE users SET email = :email"), {"email": to})

    response = await accept(client, token)

    assert response.json() == {"detail": "This invitation is invalid or has expired"}
    # Creating the User failed, so the invitation was not used up.
    with tenant_session(elsewhere.tenant_id) as session:
        session.execute(text("UPDATE users SET email = :email"), {"email": email()})
    assert (await accept(client, token)).status_code == 200


async def test_inviting_again_leaves_only_the_newest_link_working(
    client: AsyncClient,
    admin: User,
    enqueued: list[tuple[str, ...]],
    sent_mail: list[EmailMessage],
) -> None:
    to = email()
    first = await invited_token(client, admin, enqueued, sent_mail, to)
    second = await invited_token(client, admin, enqueued, sent_mail, to, "RECRUITER")

    assert len((await members(client, admin))["invitations"]) == 1
    assert (await accept(client, first)).status_code == 400
    assert claims(await accept(client, second))["role"] == "RECRUITER"


async def test_concurrent_invitations_of_one_email_leave_one_pending(
    client: AsyncClient, admin: User
) -> None:
    to = email()

    responses = await asyncio.gather(*(invite(client, admin, to) for _ in range(4)))

    assert [r.status_code for r in responses] == [201] * 4
    assert len((await members(client, admin))["invitations"]) == 1


async def test_a_member_cannot_be_invited_again(
    client: AsyncClient,
    admin: User,
    enqueued: list[tuple[str, ...]],
    sent_mail: list[EmailMessage],
) -> None:
    to = email()
    await accept(client, await invited_token(client, admin, enqueued, sent_mail, to))

    assert (await invite(client, admin, to)).status_code == 409


def email_body(tenant_id: uuid.UUID) -> str:
    with tenant_session(tenant_id) as session:
        body: str = session.execute(text("SELECT body FROM email_messages")).scalar_one()
    return body


async def test_sent_email_is_not_sent_again_and_its_token_is_masked(
    client: AsyncClient,
    admin: User,
    enqueued: list[tuple[str, ...]],
    sent_mail: list[EmailMessage],
) -> None:
    await invite(client, admin, email())
    [args] = enqueued

    emails.send_email.apply(args=args).get()
    emails.send_email.apply(args=args).get()  # redelivered

    assert len(sent_mail) == 1
    body = email_body(admin.tenant_id)
    assert token_in(sent_mail[0]) not in body
    assert "token=[redacted]" in body


async def test_failed_send_shows_on_the_invitation_and_masks_its_token(
    client: AsyncClient,
    admin: User,
    enqueued: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(message: EmailMessage) -> None:
        raise smtplib.SMTPRecipientsRefused({message["To"]: (550, b"no such user")})

    monkeypatch.setattr(emails, "deliver", refuse)
    await invite(client, admin, email())

    send_all(enqueued)

    [pending] = (await members(client, admin))["invitations"]
    assert pending["email_status"] == "FAILED"
    assert "token=[redacted]" in email_body(admin.tenant_id)


@pytest.fixture
async def member() -> AsyncIterator[AsyncClient]:
    """A client of the invited Member's own, which holds their refresh cookie."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


async def invited_member(
    member: AsyncClient,
    admin: User,
    enqueued: list[tuple[str, ...]],
    sent_mail: list[EmailMessage],
    role: str,
) -> str:
    """Invite a Member and sign them in on member; returns their id."""
    to = email()
    token = await invited_token(member, admin, enqueued, sent_mail, to, role)
    assert (await accept(member, token)).status_code == 200
    [member_id] = [m["id"] for m in (await members(member, admin))["members"] if m["email"] == to]
    return str(member_id)


async def refresh(client: AsyncClient) -> Response:
    return await client.post("/api/auth/refresh", headers={"X-Requested-With": "fetch"})


async def test_revoked_member_cannot_refresh(
    client: AsyncClient,
    member: AsyncClient,
    admin: User,
    enqueued: list[tuple[str, ...]],
    sent_mail: list[EmailMessage],
) -> None:
    member_id = await invited_member(member, admin, enqueued, sent_mail, "RECRUITER")

    response = await client.delete(f"/api/members/{member_id}", headers=admin.headers)

    assert response.status_code == 204
    assert (await refresh(member)).status_code == 401
    [listed] = [m for m in (await members(client, admin))["members"] if m["id"] == member_id]
    assert listed["is_active"] is False


async def test_new_role_takes_effect_at_the_next_refresh(
    client: AsyncClient,
    member: AsyncClient,
    admin: User,
    enqueued: list[tuple[str, ...]],
    sent_mail: list[EmailMessage],
) -> None:
    member_id = await invited_member(member, admin, enqueued, sent_mail, "REVIEWER")

    response = await client.patch(
        f"/api/members/{member_id}", headers=admin.headers, json={"role": "RECRUITER"}
    )

    assert response.status_code == 200
    assert response.json()["role"] == "RECRUITER"
    assert claims(await refresh(member))["role"] == "RECRUITER"


async def test_last_company_admin_cannot_be_demoted_or_revoked(
    client: AsyncClient, admin: User
) -> None:
    path = f"/api/members/{admin.id}"

    demoted = await client.patch(path, headers=admin.headers, json={"role": "RECRUITER"})
    revoked = await client.delete(path, headers=admin.headers)

    assert (demoted.status_code, revoked.status_code) == (409, 409)


async def test_admin_cannot_revoke_themselves_even_with_another_admin(
    client: AsyncClient, admin: User
) -> None:
    make_user("COMPANY_ADMIN", admin.tenant_id)

    response = await client.delete(f"/api/members/{admin.id}", headers=admin.headers)

    assert response.status_code == 409


@pytest.mark.parametrize(("change", "done"), [("demote", 200), ("revoke", 204)])
async def test_two_admins_removing_each_other_at_once_leave_one(
    client: AsyncClient, admin: User, change: str, done: int
) -> None:
    other = make_user("COMPANY_ADMIN", admin.tenant_id)

    async def remove(by: User, target: User) -> int:
        path = f"/api/members/{target.id}"
        if change == "demote":
            response = await client.patch(path, headers=by.headers, json={"role": "REVIEWER"})
        else:
            response = await client.delete(path, headers=by.headers)
        return response.status_code

    statuses = await asyncio.gather(remove(admin, other), remove(other, admin))

    assert sorted(statuses) == sorted([done, 409])


ADMIN_ONLY = [
    ("GET", "/api/members", None),
    ("POST", "/api/invitations", {"email": "a@example.com", "role": "RECRUITER"}),
    ("DELETE", f"/api/invitations/{uuid.uuid4()}", None),
    ("PATCH", f"/api/members/{uuid.uuid4()}", {"role": "RECRUITER"}),
    ("DELETE", f"/api/members/{uuid.uuid4()}", None),
]


# SRS §2.2, row "Quản lý Workspace & Member": no access for Recruiters and Reviewers.
@pytest.mark.parametrize("role", ["RECRUITER", "REVIEWER"])
@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ONLY)
async def test_only_company_admins_manage_members(
    client: AsyncClient, role: str, method: str, path: str, body: dict[str, str] | None
) -> None:
    user = make_user(role)

    response = await client.request(method, path, headers=user.headers, json=body)

    assert response.status_code == 403


@pytest.mark.cross_tenant
async def test_other_tenants_members_and_invitations_are_404(
    client: AsyncClient,
    member: AsyncClient,
    admin: User,
    enqueued: list[tuple[str, ...]],
    sent_mail: list[EmailMessage],
) -> None:
    member_id = await invited_member(member, admin, enqueued, sent_mail, "RECRUITER")
    await invite(client, admin, email())
    [invitation] = (await members(client, admin))["invitations"]
    other = make_user("COMPANY_ADMIN")

    listed = await members(client, other)
    responses = [
        await client.delete(f"/api/invitations/{invitation['id']}", headers=other.headers),
        await client.patch(
            f"/api/members/{member_id}", headers=other.headers, json={"role": "REVIEWER"}
        ),
        await client.delete(f"/api/members/{member_id}", headers=other.headers),
    ]

    assert [m["id"] for m in listed["members"]] == [str(other.id)]
    assert listed["invitations"] == []
    assert [r.status_code for r in responses] == [404, 404, 404]
    after = await members(client, admin)
    assert [i["id"] for i in after["invitations"]] == [invitation["id"]]
    assert [(m["role"], m["is_active"]) for m in after["members"] if m["id"] == member_id] == [
        ("RECRUITER", True)
    ]


@pytest.mark.cross_tenant
async def test_send_email_in_another_tenant_finds_nothing(
    client: AsyncClient,
    admin: User,
    enqueued: list[tuple[str, ...]],
    sent_mail: list[EmailMessage],
) -> None:
    await invite(client, admin, email())
    [(_, email_id)] = enqueued

    emails.send_email.apply(args=(str(make_user().tenant_id), email_id)).get()

    assert sent_mail == []
    [pending] = (await members(client, admin))["invitations"]
    assert pending["email_status"] == "QUEUED"


@pytest.mark.cross_tenant
async def test_accept_invitation_finds_any_tenant_and_restores_the_callers_context(
    client: AsyncClient,
    admin: User,
    enqueued: list[tuple[str, ...]],
    sent_mail: list[EmailMessage],
) -> None:
    token = await invited_token(client, admin, enqueued, sent_mail, email(), "RECRUITER")
    caller = make_user().tenant_id

    with tenant_session(caller) as session:
        found = session.execute(
            text("SELECT tenant_id, role FROM accept_invitation(:hash)"),
            {"hash": hashlib.sha256(token.encode()).hexdigest()},
        ).one()
        context = session.scalar(text("SELECT current_setting('app.current_tenant_id')"))

    assert tuple(found) == (admin.tenant_id, "RECRUITER")
    assert context == str(caller)


def test_accept_invitation_is_a_narrow_security_definer() -> None:
    with sync_engine().connect() as conn:
        grants = conn.execute(
            text(
                "SELECT p.prosecdef, pg_get_userbyid(p.proowner),"
                "  has_function_privilege('ats_app', p.oid, 'EXECUTE'),"
                "  has_function_privilege('public', p.oid, 'EXECUTE')"
                " FROM pg_proc p WHERE p.proname = 'accept_invitation'"
            )
        ).one()
    assert tuple(grants) == (True, "ats_owner", True, False)
