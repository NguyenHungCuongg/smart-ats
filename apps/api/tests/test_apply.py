"""Tests for Public Apply Link (FR-A3.4, NFR-SEC-06, SAD §4.2, §5.4, §5.7)."""

import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app import apply, emails, storage
from app.auth import _redis
from app.db import tenant_session
from app.main import app
from smart_ats_scoring import pricing
from tests.test_jobs import FakeLlm, User, make_user

pytestmark = [pytest.mark.usefixtures("database"), pytest.mark.usefixtures("redis")]

PDF_SAMPLE = b"%PDF-1.7\n1 0 obj\n<<\n>>\nendobj\ntrailer\n<<\n>>\n%%EOF"


@pytest.fixture(autouse=True)
async def clear_rate_limits() -> None:
    await _redis().flushdb()


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!")
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "gpt-4o-mini")


@pytest.fixture(autouse=True)
def objects(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Object storage as a dict."""
    stored: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "put", lambda key, data: stored.__setitem__(key, data))
    monkeypatch.setattr(storage, "get", lambda key: stored[key])
    return stored


@pytest.fixture(autouse=True)
def enqueued_emails(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    sent: list[tuple[str, ...]] = []
    monkeypatch.setattr(emails.send_email, "delay", lambda *args: sent.append(args))
    return sent


@pytest.fixture(autouse=True)
def enqueued_parses(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    sent: list[tuple[str, ...]] = []
    monkeypatch.setattr(apply.parse_cv, "delay", lambda *args: sent.append(args))
    return sent


@pytest.fixture
def recruiter() -> User:
    return make_user()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


def make_published_job(
    user: User,
    *,
    public_apply_enabled: bool = True,
    apply_deadline: date | None = None,
    status: str = "PUBLISHED",
    criteria: dict[str, Any] | None = None,
    location: str | None = "Hà Nội",
    work_mode: str | None = "HYBRID",
) -> tuple[str, str]:
    """Create a Job and set public_slug, returning (job_id, public_slug)."""
    slug = f"job-{uuid.uuid4().hex[:12]}"
    with tenant_session(user.tenant_id) as session:
        job_id = session.scalar(
            text(
                "INSERT INTO jobs (tenant_id, title, level, status, parse_status, created_by,"
                "  weight_technical, weight_soft_skills, weight_experience,"
                "  public_apply_enabled, public_slug, apply_deadline, criteria,"
                "  location, work_mode, published_at)"
                " VALUES (:tenant_id, 'Senior Python Dev', 'SENIOR', :status, 'SUCCEEDED',"
                "  :user_id, 0.50, 0.25, 0.25, :enabled, :slug, :deadline,"
                "  CAST(:criteria AS jsonb), :location, :work_mode,"
                "  CASE WHEN :status = 'PUBLISHED' THEN now() ELSE NULL END)"
                " RETURNING id"
            ),
            {
                "tenant_id": user.tenant_id,
                "user_id": user.id,
                "status": status,
                "enabled": public_apply_enabled,
                "slug": slug,
                "deadline": apply_deadline,
                "location": location,
                "work_mode": work_mode,
                "criteria": (
                    json_str(criteria)
                    if criteria is not None
                    else json_str(
                        {
                            "skills": [{"name": "Python", "must_have": True}],
                            "salary_range": "2000-3000 USD",
                        }
                    )
                ),
            },
        )
    return str(job_id), slug


def json_str(val: dict[str, Any]) -> str:
    import json

    return json.dumps(val)


async def test_get_public_job(client: AsyncClient, recruiter: User) -> None:
    job_id, slug = make_published_job(recruiter)

    res = await client.get(f"/api/apply/{slug}")
    assert res.status_code == 200
    data = res.json()
    assert data["job_id"] == job_id
    assert data["title"] == "Senior Python Dev"
    assert data["status"] == "PUBLISHED"
    assert data["public_apply_enabled"] is True
    assert data["is_closed"] is False
    assert data["tenant_name"] is not None
    assert data["location"] == "Hà Nội"
    assert data["work_mode"] == "HYBRID"
    assert data["published_at"] is not None
    # Criteria must NOT contain salary_range (ERD §8)
    assert data["criteria"] is not None
    assert "salary_range" not in data["criteria"]


async def test_get_public_job_closed_cases(client: AsyncClient, recruiter: User) -> None:
    # 1. public_apply_enabled is false
    _, slug1 = make_published_job(recruiter, public_apply_enabled=False)
    res1 = await client.get(f"/api/apply/{slug1}")
    assert res1.status_code == 200
    assert res1.json()["is_closed"] is True

    # 2. status is not PUBLISHED (e.g. CLOSED)
    _, slug2 = make_published_job(recruiter, status="CLOSED")
    res2 = await client.get(f"/api/apply/{slug2}")
    assert res2.status_code == 200
    assert res2.json()["is_closed"] is True

    # 3. deadline is expired
    past_date = date.today() - timedelta(days=2)
    _, slug3 = make_published_job(recruiter, apply_deadline=past_date)
    res3 = await client.get(f"/api/apply/{slug3}")
    assert res3.status_code == 200
    assert res3.json()["is_closed"] is True

    # 4. Unknown slug -> 404
    res_unknown = await client.get("/api/apply/does-not-exist")
    assert res_unknown.status_code == 404


async def test_submit_application_success(
    client: AsyncClient,
    recruiter: User,
    enqueued_emails: list[tuple[str, ...]],
    enqueued_parses: list[tuple[str, ...]],
) -> None:
    job_id, slug = make_published_job(recruiter)

    response = await client.post(
        f"/api/apply/{slug}",
        data={
            "full_name": "Tran Van B",
            "email": "b.tran@example.com",
            "phone": "0912345678",
            "consent": "true",
        },
        files={"file": ("my_cv.pdf", PDF_SAMPLE, "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "Application received"}

    with tenant_session(recruiter.tenant_id) as session:
        # Check Candidate
        cand = session.execute(
            text(
                "SELECT id, full_name, email, phone, consent_source, consent_notice_version"
                " FROM candidates WHERE email = 'b.tran@example.com'"
            )
        ).one()
        assert cand.full_name == "Tran Van B"
        assert cand.phone == "0912345678"
        assert cand.consent_source == "PUBLIC_APPLY_CONSENT"
        assert cand.consent_notice_version == "1.0"

        # Check Application
        app_row = session.execute(
            text(
                "SELECT id, job_id, candidate_id, source, stage FROM applications"
                " WHERE job_id = :job_id AND candidate_id = :cand_id"
            ),
            {"job_id": job_id, "cand_id": cand.id},
        ).one()
        assert app_row.source == "PUBLIC_APPLY"
        assert app_row.stage == "APPLIED"

        # Check Stage History
        history = session.execute(
            text(
                "SELECT to_stage, changed_by FROM application_stage_history"
                " WHERE application_id = :id"
            ),
            {"id": app_row.id},
        ).one()
        assert history.to_stage == "APPLIED"
        assert history.changed_by is None

        # Check Email outbox
        email_row = session.execute(
            text(
                "SELECT kind, to_address, subject, body, status FROM email_messages"
                " WHERE application_id = :app_id"
            ),
            {"app_id": app_row.id},
        ).one()
        assert email_row.kind == "APPLY_RECEIPT"
        assert email_row.to_address == "b.tran@example.com"
        assert email_row.status == "QUEUED"

    # Tasks enqueued
    assert len(enqueued_emails) == 1
    assert len(enqueued_parses) == 1


async def test_submit_application_duplicate_is_idempotent(
    client: AsyncClient,
    recruiter: User,
    enqueued_emails: list[tuple[str, ...]],
) -> None:
    job_id, slug = make_published_job(recruiter)

    # First submit
    res1 = await client.post(
        f"/api/apply/{slug}",
        data={"full_name": "Nguyen A", "email": "nguyen.a@example.com", "consent": "true"},
        files={"file": ("cv.pdf", PDF_SAMPLE, "application/pdf")},
    )
    assert res1.status_code == 200
    assert len(enqueued_emails) == 1

    # Second submit with same email for same job
    res2 = await client.post(
        f"/api/apply/{slug}",
        data={"full_name": "Nguyen A", "email": "nguyen.a@example.com", "consent": "true"},
        files={"file": ("cv.pdf", PDF_SAMPLE, "application/pdf")},
    )
    assert res2.status_code == 200
    assert res2.json() == {"status": "ok", "message": "Application received"}

    # No second application created, no second email queued
    assert len(enqueued_emails) == 1
    with tenant_session(recruiter.tenant_id) as session:
        count = session.scalar(
            text(
                "SELECT count(*) FROM applications a JOIN candidates c ON c.id = a.candidate_id"
                " WHERE a.job_id = :job_id AND c.email = 'nguyen.a@example.com'"
            ),
            {"job_id": job_id},
        )
        assert count == 1


async def test_submit_application_closed_rejected(client: AsyncClient, recruiter: User) -> None:
    # Disabled public apply link
    _, slug_disabled = make_published_job(recruiter, public_apply_enabled=False)
    res = await client.post(
        f"/api/apply/{slug_disabled}",
        data={"full_name": "Test", "email": "test@example.com", "consent": "true"},
        files={"file": ("cv.pdf", PDF_SAMPLE, "application/pdf")},
    )
    assert res.status_code == 409

    # Expired deadline
    _, slug_expired = make_published_job(recruiter, apply_deadline=date.today() - timedelta(days=1))
    res_expired = await client.post(
        f"/api/apply/{slug_expired}",
        data={"full_name": "Test", "email": "test@example.com", "consent": "true"},
        files={"file": ("cv.pdf", PDF_SAMPLE, "application/pdf")},
    )
    assert res_expired.status_code == 409


async def test_submit_application_validation(client: AsyncClient, recruiter: User) -> None:
    _, slug = make_published_job(recruiter)

    # Missing consent
    res = await client.post(
        f"/api/apply/{slug}",
        data={"full_name": "Test", "email": "test@example.com", "consent": "false"},
        files={"file": ("cv.pdf", PDF_SAMPLE, "application/pdf")},
    )
    assert res.status_code == 422

    # Invalid email
    res_email = await client.post(
        f"/api/apply/{slug}",
        data={"full_name": "Test", "email": "not-an-email", "consent": "true"},
        files={"file": ("cv.pdf", PDF_SAMPLE, "application/pdf")},
    )
    assert res_email.status_code == 422

    # Empty full name
    res_name = await client.post(
        f"/api/apply/{slug}",
        data={"full_name": "   ", "email": "test@example.com", "consent": "true"},
        files={"file": ("cv.pdf", PDF_SAMPLE, "application/pdf")},
    )
    assert res_name.status_code == 422

    # Invalid MIME type
    res_mime = await client.post(
        f"/api/apply/{slug}",
        data={"full_name": "Test", "email": "test@example.com", "consent": "true"},
        files={"file": ("script.sh", b"#!/bin/bash\necho 1", "application/x-sh")},
    )
    assert res_mime.status_code == 415

    # File exceeding 10MB
    large_pdf = b"%PDF-1.7" + b"0" * (10 * 1024 * 1024 + 1)
    res_size = await client.post(
        f"/api/apply/{slug}",
        data={"full_name": "Test", "email": "test@example.com", "consent": "true"},
        files={"file": ("large.pdf", large_pdf, "application/pdf")},
    )
    assert res_size.status_code == 413


async def test_submit_application_rate_limiting(client: AsyncClient, recruiter: User) -> None:
    _, slug = make_published_job(recruiter)
    # Clear any rate limit key
    await _redis().delete("apply_limit:ip:127.0.0.1", "apply_limit:ip:testclient")

    for i in range(5):
        res = await client.post(
            f"/api/apply/{slug}",
            data={"full_name": f"User {i}", "email": f"user{i}@example.com", "consent": "true"},
            files={"file": ("cv.pdf", PDF_SAMPLE, "application/pdf")},
        )
        assert res.status_code == 200

    # 6th request from same IP must be 429
    res6 = await client.post(
        f"/api/apply/{slug}",
        data={"full_name": "User 6", "email": "user6@example.com", "consent": "true"},
        files={"file": ("cv.pdf", PDF_SAMPLE, "application/pdf")},
    )
    assert res6.status_code == 429


@pytest.mark.parametrize(
    ("cookie", "accept_lang", "expected_lang"),
    [
        ("NEXT_LOCALE=en", None, "en"),
        (None, "en-US,en;q=0.9,vi;q=0.8", "en"),
        ("NEXT_LOCALE=vi", "en-US,en;q=0.9", "vi"),
        (None, None, "vi"),
    ],
)
async def test_receipt_email_language(
    client: AsyncClient,
    recruiter: User,
    cookie: str | None,
    accept_lang: str | None,
    expected_lang: str,
) -> None:
    _, slug = make_published_job(recruiter)
    headers = {}
    if cookie:
        headers["Cookie"] = cookie
    if accept_lang:
        headers["Accept-Language"] = accept_lang

    res = await client.post(
        f"/api/apply/{slug}",
        data={
            "full_name": "Candidate",
            "email": f"cand-{uuid.uuid4().hex[:6]}@example.com",
            "consent": "true",
        },
        files={"file": ("cv.pdf", PDF_SAMPLE, "application/pdf")},
        headers=headers,
    )
    assert res.status_code == 200

    with tenant_session(recruiter.tenant_id) as session:
        msg = session.execute(
            text(
                "SELECT subject, body FROM email_messages WHERE kind = 'APPLY_RECEIPT'"
                " ORDER BY created_at DESC LIMIT 1"
            )
        ).one()
        if expected_lang == "en":
            assert "Application received" in msg.subject
        else:
            assert "Xác nhận nhận hồ sơ" in msg.subject


async def test_cross_tenant_isolation(client: AsyncClient, recruiter: User) -> None:
    # Experiment 4: Slug of tenant A cannot read or write data of tenant B
    other_user = make_user()
    job_id_b, slug_b = make_published_job(other_user)

    # Public apply to tenant B using slug B
    res = await client.post(
        f"/api/apply/{slug_b}",
        data={"full_name": "Cross Tenant Test", "email": "cross@example.com", "consent": "true"},
        files={"file": ("cv.pdf", PDF_SAMPLE, "application/pdf")},
    )
    assert res.status_code == 200

    # Tenant A context cannot see the candidate or application
    with tenant_session(recruiter.tenant_id) as session_a:
        assert (
            session_a.scalar(
                text("SELECT count(*) FROM candidates WHERE email = 'cross@example.com'")
            )
            == 0
        )
        assert (
            session_a.scalar(
                text("SELECT count(*) FROM applications WHERE job_id = :id"), {"id": job_id_b}
            )
            == 0
        )

    # Tenant B context has the candidate and application
    with tenant_session(other_user.tenant_id) as session_b:
        assert (
            session_b.scalar(
                text("SELECT count(*) FROM candidates WHERE email = 'cross@example.com'")
            )
            == 1
        )
        assert (
            session_b.scalar(
                text("SELECT count(*) FROM applications WHERE job_id = :id"), {"id": job_id_b}
            )
            == 1
        )


def test_apply_parse_cv_task(recruiter: User, monkeypatch: pytest.MonkeyPatch) -> None:
    llm = FakeLlm(
        {
            "contact": {
                "full_name": "Nguyen Van B",
                "email": "b@example.com",
                "phone": "0123",
                "links": [],
            },
            "skills": [{"name": "Python", "category": "TECHNICAL", "proficiency": "ADVANCED"}],
            "experience": [],
            "education": [],
            "summary": "Dev",
        }
    )
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "test-model")
    monkeypatch.setattr(apply, "llm_from_env", lambda model: llm)
    monkeypatch.setattr(apply, "extract_text", lambda data: "Parsed CV text")
    monkeypatch.setitem(
        pricing.PRICES, "test-model", pricing.Price(Decimal("2"), Decimal("0.5"), Decimal("8"))
    )

    # Insert CV document with PENDING status
    with tenant_session(recruiter.tenant_id) as session:
        cand_id = session.scalar(
            text(
                "INSERT INTO candidates (tenant_id, full_name, email, consent_source,"
                "  consent_at, last_activity_at)"
                " VALUES (:tenant_id, 'Nguyen B', 'b@example.com', 'PUBLIC_APPLY_CONSENT',"
                "  now(), now()) RETURNING id"
            ),
            {"tenant_id": recruiter.tenant_id},
        )
        storage_key = f"t/{recruiter.tenant_id}/cv/test.pdf"
        storage.put(storage_key, PDF_SAMPLE)
        doc_id = session.scalar(
            text(
                "INSERT INTO cv_documents (tenant_id, candidate_id, storage_key, file_name,"
                "  mime_type, sha256, parse_status)"
                " VALUES (:tenant_id, :cand_id, :key, 'cv.pdf', 'application/pdf',"
                "  'dummy-sha-test', 'PENDING') RETURNING id"
            ),
            {"tenant_id": recruiter.tenant_id, "cand_id": cand_id, "key": storage_key},
        )

    # Run parse_cv task
    apply.parse_cv.apply(args=(str(recruiter.tenant_id), str(doc_id))).get()

    with tenant_session(recruiter.tenant_id) as session:
        doc = session.execute(
            text(
                "SELECT parse_status, parsed_profile, blind_profile"
                " FROM cv_documents WHERE id = :id"
            ),
            {"id": doc_id},
        ).one()
        assert doc.parse_status == "PARSED"
        assert doc.parsed_profile is not None
        assert doc.blind_profile is not None

        # Check AI usage recorded with user_id = None
        entry = session.execute(
            text(
                "SELECT feature, user_id, ref_type, ref_id FROM ai_usage_entries WHERE ref_id = :id"
            ),
            {"id": doc_id},
        ).one()
        assert entry.feature == "CV_PARSE"
        assert entry.user_id is None
        assert str(entry.ref_id) == str(doc_id)
