"""Create a Job from a JD Document and confirm its criteria (FR-A1.1).

Object storage, the LLM and the broker are faked; the API, the parse task and PostgreSQL
are real.
"""

import asyncio
import io
import json
import threading
import uuid
import zipfile
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import events, jobs, storage, uploads
from app.auth import _access_token, _redis
from app.db import tenant_session
from app.main import app
from smart_ats_scoring import pricing
from smart_ats_scoring.extraction import MAX_DOCX_UNZIPPED_BYTES
from smart_ats_scoring.llm import LlmResult, UnusableResponse, Usage
from tests.test_tenancy import make_tenant

pytestmark = pytest.mark.usefixtures("database")

PDF = b"%PDF-1.7\n fake body: the parse task's extraction is not reached in API tests"


def _malformed_zips() -> list[Any]:
    """DOCX-named ZIPs that zipfile rejects with something other than BadZipFile."""
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    data = bytearray(archive.getvalue())
    central = data.index(b"PK\x01\x02")  # the central directory entry
    newer = data.copy()
    newer[central + 6] = 99  # needs ZIP version 9.9: NotImplementedError
    bad_name = data.copy()
    bad_name[central + 9] |= 0x08  # flag bit 11: the name is UTF-8
    bad_name[central + 46] = 0xFF  # which it is not: UnicodeDecodeError
    return [
        pytest.param(bytes(newer), id="unsupported zip version"),
        pytest.param(bytes(bad_name), id="name not utf-8"),
    ]


MALFORMED_ZIPS = _malformed_zips()


def docx_bomb() -> bytes:
    """Tens of KiB that unzip past the DOCX limit of Document Extraction."""
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b" " * (MAX_DOCX_UNZIPPED_BYTES + 1))
    return bomb.getvalue()


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!")


@pytest.fixture(autouse=True)
def objects(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Object storage as a dict."""
    stored: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "put", lambda key, data: stored.__setitem__(key, data))
    monkeypatch.setattr(storage, "get", lambda key: stored[key])
    return stored


@pytest.fixture(autouse=True)
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Parse tasks sent to the broker, as their arguments."""
    sent: list[tuple[str, ...]] = []
    monkeypatch.setattr(jobs.parse, "delay", lambda *args: sent.append(args))
    return sent


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


class User:
    def __init__(self, tenant_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None:
        self.tenant_id, self.id = tenant_id, user_id
        self.headers = {"Authorization": f"Bearer {_access_token(user_id, tenant_id, role)}"}


def make_user(role: str = "RECRUITER", tenant_id: uuid.UUID | None = None) -> User:
    tenant_id = tenant_id or make_tenant()
    with tenant_session(tenant_id) as session:
        user_id: uuid.UUID = session.execute(
            text(
                "INSERT INTO users (tenant_id, email, full_name, role, is_active)"
                " VALUES (:tenant_id, :email, 'Test User', :role, true) RETURNING id"
            ),
            {"tenant_id": tenant_id, "email": f"{uuid.uuid4().hex}@example.com", "role": role},
        ).scalar_one()
    return User(tenant_id, user_id, role)


@pytest.fixture
def recruiter() -> User:
    return make_user()


async def upload(
    client: AsyncClient, user: User, filename: str = "Backend Developer.pdf", data: bytes = PDF
) -> Response:
    return await client.post("/api/jobs", headers=user.headers, files={"file": (filename, data)})


async def paste(client: AsyncClient, user: User, jd: str) -> Response:
    return await client.post("/api/jobs", headers=user.headers, data={"text": jd})


async def get_job(client: AsyncClient, user: User, job_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/jobs/{job_id}", headers=user.headers)
    assert response.status_code == 200
    job: dict[str, Any] = response.json()
    return job


async def test_upload_creates_a_draft_job_and_enqueues_its_parse(
    client: AsyncClient,
    recruiter: User,
    objects: dict[str, bytes],
    enqueued: list[tuple[str, ...]],
) -> None:
    response = await upload(client, recruiter)

    assert response.status_code == 202
    job_id = response.json()["id"]
    assert enqueued == [(str(recruiter.tenant_id), job_id, str(recruiter.id))]
    # Object keys carry the Tenant (SAD §4.3).
    [(key, data)] = objects.items()
    assert key.startswith(f"t/{recruiter.tenant_id}/") and data == PDF
    # Placeholders until the parse overwrites them; FR-A1.3 default weights.
    assert await get_job(client, recruiter, job_id) == {
        "id": job_id,
        "title": "Backend Developer",
        "level": "MID",
        "department": None,
        "location": None,
        "work_mode": None,
        "status": "DRAFT",
        "parse_status": "PENDING",
        "parse_error": None,
        "criteria": None,
        "verification": None,
        "weights": {"technical": 55, "soft_skills": 15, "experience": 30},
        "criteria_confirmed_at": None,
        "apply_deadline": None,
        "published_at": None,
        "public_apply_enabled": False,
        "public_slug": None,
    }


async def test_pasted_text_is_stored_as_a_text_document(
    client: AsyncClient, recruiter: User, objects: dict[str, bytes]
) -> None:
    response = await paste(client, recruiter, "\n  Senior Backend Developer  \nPython, 3 năm")

    assert response.status_code == 202
    [(key, data)] = objects.items()
    assert key.endswith(".txt") and data.decode() == "\n  Senior Backend Developer  \nPython, 3 năm"
    job = await get_job(client, recruiter, response.json()["id"])
    assert job["title"] == "Senior Backend Developer"


async def test_document_type_is_told_by_magic_bytes_not_the_name(
    client: AsyncClient, recruiter: User, objects: dict[str, bytes]
) -> None:
    # A PNG named .pdf.
    response = await upload(client, recruiter, "jd.pdf", b"\x89PNG\r\n\x1a\n\x00\x00")

    assert response.status_code == 415
    assert objects == {}


async def test_a_zip_that_is_not_a_docx_is_rejected(
    client: AsyncClient, recruiter: User, objects: dict[str, bytes]
) -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("xl/workbook.xml", "<workbook/>")

    response = await upload(client, recruiter, "jd.docx", archive.getvalue())

    assert response.status_code == 415
    assert objects == {}


@pytest.mark.parametrize("data", MALFORMED_ZIPS)
async def test_a_malformed_zip_is_rejected(
    client: AsyncClient, recruiter: User, objects: dict[str, bytes], data: bytes
) -> None:
    response = await upload(client, recruiter, "jd.docx", data)

    assert response.status_code == 415
    assert objects == {}


async def test_document_over_10_mb_is_rejected(
    client: AsyncClient, recruiter: User, objects: dict[str, bytes]
) -> None:
    response = await upload(client, recruiter, data=b"%PDF" + b"0" * (10 * 1024 * 1024))

    assert response.status_code == 413
    assert objects == {}


@pytest.mark.parametrize(
    "send",
    [
        {},
        {"data": {"text": "   "}},
        {"data": {"text": "JD"}, "files": {"file": ("jd.pdf", PDF)}},
    ],
    ids=["nothing", "blank text", "file and text"],
)
async def test_job_needs_exactly_one_document_or_text(
    client: AsyncClient, recruiter: User, send: dict[str, Any]
) -> None:
    response = await client.post("/api/jobs", headers=recruiter.headers, **send)

    assert response.status_code == 422


async def test_reviewer_cannot_create_a_job(client: AsyncClient) -> None:
    assert (await upload(client, make_user("REVIEWER"))).status_code == 403


async def test_creating_a_job_needs_authentication(client: AsyncClient) -> None:
    assert (await client.post("/api/jobs", files={"file": ("jd.pdf", PDF)})).status_code == 401


# The parse task, run in-process as a worker would run what the API enqueued.

JD = """Senior Backend Developer
Phòng ban: Engineering. Làm việc Hybrid tại Hà Nội.
Yêu cầu: 3 năm kinh nghiệm Python, PostgreSQL. Ưu tiên: Docker.
"""

PARSED = {
    "title": "Senior Backend Developer",
    "level": "SENIOR",
    "skills": [
        {"name": "Python", "must_have": True},
        {"name": "PostgreSQL", "must_have": True},
        {"name": "Docker", "must_have": False},
    ],
    "min_years_experience": 3,
    "education": "Đại học CNTT",  # not in the JD
    "responsibilities": [],
    "work_mode": "HYBRID",
    "salary_range": None,
    "department": "Engineering",
    "location": "Hà Nội",
}


class FakeLlm:
    def __init__(self, data: dict[str, Any], model: str = "test-model") -> None:
        self.data, self.model = data, model
        self.calls = 0

    def structured(self, *args: Any, **kwargs: Any) -> LlmResult:
        self.calls += 1
        return LlmResult(self.data, Usage(self.model, 1000, 500, 400))


class UnusableLlm(FakeLlm):
    """Bills the call but returns nothing usable, as on hitting the token limit."""

    def structured(self, *args: Any, **kwargs: Any) -> LlmResult:
        self.calls += 1
        raise UnusableResponse("cut off", Usage(self.model, 1000, 500, 400))


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> FakeLlm:
    fake = FakeLlm(PARSED)
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "test-model")
    monkeypatch.setattr(jobs, "llm_from_env", lambda model, **_: fake)
    monkeypatch.setitem(
        pricing.PRICES, "test-model", pricing.Price(Decimal("2"), Decimal("0.5"), Decimal("8"))
    )
    return fake


def run_parse(enqueued: list[tuple[str, ...]]) -> None:
    for args in enqueued:
        jobs.parse.apply(args=args).get()


def usage_entries(user: User) -> list[tuple[Any, ...]]:
    with tenant_session(user.tenant_id) as session:
        rows = session.execute(
            text(
                "SELECT user_id, feature, model, input_tokens, output_tokens, cached_tokens,"
                "  cost_usd, ref_type, ref_id FROM ai_usage_entries"
            )
        ).all()
    return [tuple(row) for row in rows]


@pytest.mark.usefixtures("redis")
async def test_parse_overwrites_the_placeholders_and_records_its_usage(
    client: AsyncClient, recruiter: User, llm: FakeLlm, enqueued: list[tuple[str, ...]]
) -> None:
    job_id = (await paste(client, recruiter, JD)).json()["id"]

    run_parse(enqueued)

    job = await get_job(client, recruiter, job_id)
    assert job | {"criteria_confirmed_at": None} == job
    assert {k: job[k] for k in ("title", "level", "department", "location", "work_mode")} == {
        "title": "Senior Backend Developer",
        "level": "SENIOR",
        "department": "Engineering",
        "location": "Hà Nội",
        "work_mode": "HYBRID",
    }
    assert (job["parse_status"], job["parse_error"]) == ("SUCCEEDED", None)
    assert job["criteria"] == {
        "skills": PARSED["skills"],
        "min_years_experience": 3,
        "education": "Đại học CNTT",
        "responsibilities": [],
        "salary_range": None,
    }
    assert {field for field, v in job["verification"].items() if v == "NEEDS_REVIEW"} == {
        "education"
    }
    # 600 uncached x $2 + 400 cached x $0.5 + 500 output x $8, per 1M tokens.
    assert usage_entries(recruiter) == [
        (
            recruiter.id,
            "JOB_PARSE",
            "test-model",
            1000,
            500,
            400,
            Decimal("0.005400"),
            "job",
            uuid.UUID(job_id),
        )
    ]


@pytest.mark.usefixtures("redis")
async def test_fields_the_jd_does_not_state_keep_their_placeholder_marked_needs_review(
    client: AsyncClient, recruiter: User, llm: FakeLlm, enqueued: list[tuple[str, ...]]
) -> None:
    llm.data = PARSED | {"title": None, "level": None}
    job_id = (await paste(client, recruiter, JD)).json()["id"]

    run_parse(enqueued)

    job = await get_job(client, recruiter, job_id)
    assert (job["title"], job["level"]) == ("Senior Backend Developer", "MID")
    assert job["verification"]["title"] == job["verification"]["level"] == "NEEDS_REVIEW"


@pytest.mark.usefixtures("redis")
async def test_parse_announces_its_result_to_the_recruiter(
    client: AsyncClient, recruiter: User, llm: FakeLlm, enqueued: list[tuple[str, ...]]
) -> None:
    job_id = (await paste(client, recruiter, JD)).json()["id"]
    async with _redis().pubsub() as sub:
        await sub.subscribe(events.channel(recruiter.tenant_id, recruiter.id))
        # Subscribed before the task runs, so its publish cannot race the subscription.
        assert (await sub.get_message(timeout=5) or {})["type"] == "subscribe"

        run_parse(enqueued)

        message = await sub.get_message(timeout=5)
    assert message is not None
    assert json.loads(message["data"]) == {
        "event": "job.parsed",
        "data": {"job_id": job_id, "parse_status": "SUCCEEDED"},
    }


@pytest.mark.usefixtures("redis")
async def test_unreadable_document_fails_with_its_extraction_code(
    client: AsyncClient, recruiter: User, llm: FakeLlm, enqueued: list[tuple[str, ...]]
) -> None:
    job_id = (await upload(client, recruiter)).json()["id"]

    run_parse(enqueued)

    job = await get_job(client, recruiter, job_id)
    assert (job["parse_status"], job["parse_error"], job["criteria"]) == (
        "FAILED",
        "UNREADABLE",
        None,
    )
    assert llm.calls == 0
    assert usage_entries(recruiter) == []


@pytest.mark.usefixtures("redis")
async def test_docx_bomb_fails_with_its_extraction_code(
    client: AsyncClient, recruiter: User, llm: FakeLlm, enqueued: list[tuple[str, ...]]
) -> None:
    job_id = (await upload(client, recruiter, "jd.docx", docx_bomb())).json()["id"]

    run_parse(enqueued)

    job = await get_job(client, recruiter, job_id)
    assert (job["parse_status"], job["parse_error"]) == ("FAILED", "DOCX_TOO_LARGE")
    assert llm.calls == 0


@pytest.mark.usefixtures("redis")
async def test_model_without_a_price_fails_the_parse_before_calling_it(
    client: AsyncClient,
    recruiter: User,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "unpriced-model")
    job_id = (await paste(client, recruiter, JD)).json()["id"]

    run_parse(enqueued)

    job = await get_job(client, recruiter, job_id)
    assert (job["parse_status"], job["parse_error"]) == ("FAILED", "UNPRICED_MODEL")
    # No tokens spent that the ledger could not record.
    assert llm.calls == 0


@pytest.mark.usefixtures("redis")
async def test_redelivered_parse_does_nothing(
    client: AsyncClient, recruiter: User, llm: FakeLlm, enqueued: list[tuple[str, ...]]
) -> None:
    await paste(client, recruiter, JD)

    run_parse(enqueued)
    run_parse(enqueued)

    assert llm.calls == 1
    assert len(usage_entries(recruiter)) == 1


@pytest.mark.usefixtures("redis", "llm")
async def test_billed_response_it_cannot_use_fails_the_parse_and_is_recorded_once(
    client: AsyncClient,
    recruiter: User,
    enqueued: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jobs, "llm_from_env", lambda model, **_: UnusableLlm({}))
    job_id = (await paste(client, recruiter, JD)).json()["id"]

    run_parse(enqueued)
    run_parse(enqueued)  # redelivered

    job = await get_job(client, recruiter, job_id)
    assert (job["parse_status"], job["parse_error"]) == ("FAILED", "PARSE_FAILED")
    assert [(e[1], e[3], e[7], e[8]) for e in usage_entries(recruiter)] == [
        ("JOB_PARSE", 1000, "job", uuid.UUID(job_id))
    ]


class BlockingLlm(FakeLlm):
    """Holds the call open until released, so the test acts while the parse is mid-call."""

    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(data)
        self.calling, self.release = threading.Event(), threading.Event()

    def structured(self, *args: Any, **kwargs: Any) -> LlmResult:
        self.calling.set()
        self.release.wait(10)
        return super().structured(*args, **kwargs)


@pytest.mark.usefixtures("redis", "llm")
async def test_cv_upload_into_a_job_being_parsed_does_not_wait_for_the_parse(
    client: AsyncClient,
    recruiter: User,
    enqueued: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = BlockingLlm(PARSED)
    monkeypatch.setattr(jobs, "llm_from_env", lambda model, **_: llm)
    monkeypatch.setattr(uploads.parse_cv, "delay", lambda *args: None)
    job_id = (await paste(client, recruiter, JD)).json()["id"]
    parse = asyncio.create_task(asyncio.to_thread(run_parse, enqueued))
    assert await asyncio.to_thread(llm.calling.wait, 10)

    try:
        # Inserting the Upload Batch checks its foreign key to the Job the parse holds.
        response = await asyncio.wait_for(
            client.post(
                f"/api/jobs/{job_id}/uploads",
                headers=recruiter.headers,
                files={"files": ("cv.pdf", PDF)},
                data={"consent_confirmed": "true"},
            ),
            5,
        )
    finally:
        llm.release.set()
        await parse

    assert response.status_code == 202
    assert (await get_job(client, recruiter, job_id))["parse_status"] == "SUCCEEDED"


# Confirming the criteria.

CONFIRMATION = {
    "title": "Backend Developer",
    "level": "MID",
    "department": "Engineering",
    "location": None,
    "work_mode": "REMOTE",
    "criteria": {
        "skills": [{"name": "Python", "must_have": True}, {"name": "Go", "must_have": False}],
        "min_years_experience": 2,
        "education": None,
        "responsibilities": ["Build APIs"],
        "salary_range": None,
    },
    "weights": {"technical": 60, "soft_skills": 10, "experience": 30},
}


@pytest.fixture
async def parsed_job(
    client: AsyncClient, recruiter: User, llm: FakeLlm, enqueued: list[tuple[str, ...]]
) -> str:
    job_id: str = (await paste(client, recruiter, JD)).json()["id"]
    run_parse(enqueued)
    return job_id


async def confirm(
    client: AsyncClient, user: User, job_id: str, body: dict[str, Any] = CONFIRMATION
) -> Response:
    return await client.put(f"/api/jobs/{job_id}/criteria", headers=user.headers, json=body)


@pytest.mark.usefixtures("redis")
async def test_confirming_saves_the_recruiters_edits(
    client: AsyncClient, recruiter: User, parsed_job: str
) -> None:
    response = await confirm(client, recruiter, parsed_job)

    assert response.status_code == 200
    job = response.json()
    assert job == await get_job(client, recruiter, parsed_job)
    assert job["criteria_confirmed_at"] is not None
    assert {k: job[k] for k in CONFIRMATION} == CONFIRMATION
    # The Recruiter has reviewed every field: nothing is left to flag.
    assert job["verification"] is None


@pytest.mark.usefixtures("redis")
async def test_weights_that_do_not_make_100_percent_are_not_saved(
    client: AsyncClient, recruiter: User, parsed_job: str
) -> None:
    weights = {"technical": 60, "soft_skills": 10, "experience": 31}

    response = await confirm(client, recruiter, parsed_job, CONFIRMATION | {"weights": weights})

    assert response.status_code == 422
    job = await get_job(client, recruiter, parsed_job)
    assert (job["weights"]["technical"], job["criteria_confirmed_at"]) == (55, None)


async def test_criteria_cannot_be_confirmed_while_the_parse_is_pending(
    client: AsyncClient, recruiter: User
) -> None:
    job_id = (await paste(client, recruiter, JD)).json()["id"]

    assert (await confirm(client, recruiter, job_id)).status_code == 409


@pytest.mark.usefixtures("redis")
@pytest.mark.cross_tenant
async def test_other_tenants_job_is_not_found_on_every_endpoint(
    client: AsyncClient, recruiter: User, parsed_job: str
) -> None:
    other = make_user()

    assert (await client.get(f"/api/jobs/{parsed_job}", headers=other.headers)).status_code == 404
    assert (await confirm(client, other, parsed_job)).status_code == 404
    assert (await get_job(client, recruiter, parsed_job))["criteria_confirmed_at"] is None


# The database alone holds the weights to 100%, whatever the caller.


def insert_job(session: Session, user_id: uuid.UUID, weights: tuple[str, str, str]) -> None:
    session.execute(
        text(
            "INSERT INTO jobs (tenant_id, title, level, status, parse_status, created_by,"
            "  weight_technical, weight_soft_skills, weight_experience)"
            " VALUES (:tenant_id, 'Dev', 'MID', 'DRAFT', 'PENDING', :user_id, :t, :s, :e)"
        ),
        {
            "tenant_id": session.info["tenant_id"],
            "user_id": user_id,
            "t": weights[0],
            "s": weights[1],
            "e": weights[2],
        },
    )


@pytest.mark.parametrize("weights", [("0.55", "0.15", "0.31"), ("1.20", "-0.20", "0.00")])
def test_database_rejects_weights_that_do_not_make_100_percent(
    recruiter: User, weights: tuple[str, str, str]
) -> None:
    with pytest.raises(IntegrityError) as exc, tenant_session(recruiter.tenant_id) as session:
        insert_job(session, recruiter.id, weights)
    assert isinstance(exc.value.orig, psycopg.errors.CheckViolation)


def test_database_accepts_weights_that_make_100_percent(recruiter: User) -> None:
    with tenant_session(recruiter.tenant_id) as session:
        insert_job(session, recruiter.id, ("0.55", "0.15", "0.30"))


async def test_toggle_public_apply(client: AsyncClient, recruiter: User, parsed_job: str) -> None:
    # Initially false and slug is None
    job = await get_job(client, recruiter, parsed_job)
    assert job["public_apply_enabled"] is False
    assert job["public_slug"] is None

    # Enable public apply -> generates random unguessable slug
    res = await client.patch(
        f"/api/jobs/{parsed_job}/public-apply",
        json={"enabled": True},
        headers=recruiter.headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["public_apply_enabled"] is True
    assert data["public_slug"] is not None
    slug = data["public_slug"]
    assert len(slug) >= 16

    # Disable public apply -> keeps the slug
    res_off = await client.patch(
        f"/api/jobs/{parsed_job}/public-apply",
        json={"enabled": False},
        headers=recruiter.headers,
    )
    assert res_off.status_code == 200
    assert res_off.json()["public_apply_enabled"] is False
    assert res_off.json()["public_slug"] == slug

    # Enable again -> keeps the same slug
    res_on = await client.patch(
        f"/api/jobs/{parsed_job}/public-apply",
        json={"enabled": True},
        headers=recruiter.headers,
    )
    assert res_on.status_code == 200
    assert res_on.json()["public_apply_enabled"] is True
    assert res_on.json()["public_slug"] == slug


async def test_toggle_public_apply_rbac_and_cross_tenant(
    client: AsyncClient, recruiter: User, parsed_job: str
) -> None:
    # Reviewer is forbidden (403)
    reviewer = make_user("REVIEWER", recruiter.tenant_id)
    res_rev = await client.patch(
        f"/api/jobs/{parsed_job}/public-apply",
        json={"enabled": True},
        headers=reviewer.headers,
    )
    assert res_rev.status_code == 403

    # Other tenant is 404
    other = make_user()
    res_other = await client.patch(
        f"/api/jobs/{parsed_job}/public-apply",
        json={"enabled": True},
        headers=other.headers,
    )
    assert res_other.status_code == 404
