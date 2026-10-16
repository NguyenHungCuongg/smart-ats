"""Upload a CV into a Job; its parse creates the Candidate, CV Document and Application (FR-A1.2).

Object storage, the LLM and the broker are faked; the API, the parse task and PostgreSQL
are real.
"""

import copy
import io
import json
import threading
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any

import pytest
from docx import Document
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text

from app import events, storage, uploads, usage
from app.auth import _redis
from app.db import tenant_session
from app.main import app
from tests.test_jobs import MALFORMED_ZIPS, FakeLlm, User, docx_bomb, make_user

pytestmark = pytest.mark.usefixtures("database")


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
    monkeypatch.setattr(uploads.parse_cv, "delay", lambda *args: sent.append(args))
    return sent


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def recruiter() -> User:
    return make_user()


def make_job(user: User) -> str:
    with tenant_session(user.tenant_id) as session:
        job_id: uuid.UUID = session.execute(
            text(
                "INSERT INTO jobs (tenant_id, title, level, status, parse_status, created_by,"
                "  weight_technical, weight_soft_skills, weight_experience)"
                " VALUES (:tenant_id, 'Backend Developer', 'MID', 'DRAFT', 'SUCCEEDED', :user_id,"
                "  0.55, 0.15, 0.30) RETURNING id"
            ),
            {"tenant_id": user.tenant_id, "user_id": user.id},
        ).scalar_one()
    return str(job_id)


@pytest.fixture
def job(recruiter: User) -> str:
    return make_job(recruiter)


def docx(body: str) -> bytes:
    document = Document()
    document.add_paragraph(body)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


CV = docx("Nguyễn Văn An - Backend Developer")


async def upload(
    client: AsyncClient,
    user: User,
    job_id: str,
    data: bytes = CV,
    filename: str = "an.docx",
    consent: str | None = "true",
) -> Response:
    form = {} if consent is None else {"consent_confirmed": consent}
    return await client.post(
        f"/api/jobs/{job_id}/uploads",
        headers=user.headers,
        files={"file": (filename, data)},
        data=form,
    )


async def items(client: AsyncClient, user: User, job_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"/api/jobs/{job_id}/uploads", headers=user.headers)
    assert response.status_code == 200
    result: list[dict[str, Any]] = response.json()
    return result


async def applications(client: AsyncClient, user: User, job_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"/api/jobs/{job_id}/applications", headers=user.headers)
    assert response.status_code == 200
    result: list[dict[str, Any]] = response.json()
    return result


async def test_upload_stores_the_file_and_enqueues_its_parse(
    client: AsyncClient,
    recruiter: User,
    job: str,
    objects: dict[str, bytes],
    enqueued: list[tuple[str, ...]],
) -> None:
    response = await upload(client, recruiter, job)

    assert response.status_code == 202
    item_id = response.json()["item_id"]
    assert enqueued == [(str(recruiter.tenant_id), item_id)]
    # Object keys carry the Tenant (SAD §4.3).
    [(key, data)] = objects.items()
    assert key.startswith(f"t/{recruiter.tenant_id}/") and data == CV
    [item] = await items(client, recruiter, job)
    assert item | {"created_at": None} == {
        "id": item_id,
        "batch_id": response.json()["batch_id"],
        "file_name": "an.docx",
        "status": "PENDING",
        "dedupe": None,
        "error_code": None,
        "error_message": None,
        "created_at": None,
    }


@pytest.mark.parametrize("consent", [None, "false"], ids=["missing", "false"])
async def test_upload_needs_the_recruiters_attestation(
    client: AsyncClient,
    recruiter: User,
    job: str,
    objects: dict[str, bytes],
    enqueued: list[tuple[str, ...]],
    consent: str | None,
) -> None:
    response = await upload(client, recruiter, job, consent=consent)

    assert response.status_code == 422
    assert objects == {} and enqueued == []


@pytest.mark.parametrize(
    ("filename", "data"),
    [("cv.txt", b"Nguyen Van An, Python"), ("cv.pdf", b"\x89PNG\r\n\x1a\n\x00\x00")],
    ids=["text", "png named pdf"],
)
async def test_only_pdf_and_docx_are_accepted_by_magic_bytes(
    client: AsyncClient,
    recruiter: User,
    job: str,
    objects: dict[str, bytes],
    filename: str,
    data: bytes,
) -> None:
    response = await upload(client, recruiter, job, data, filename)

    assert response.status_code == 415
    assert objects == {}


@pytest.mark.parametrize("data", MALFORMED_ZIPS)
async def test_a_malformed_zip_is_rejected(
    client: AsyncClient, recruiter: User, job: str, objects: dict[str, bytes], data: bytes
) -> None:
    response = await upload(client, recruiter, job, data)

    assert response.status_code == 415
    assert objects == {}


async def test_cv_over_10_mb_is_rejected(
    client: AsyncClient, recruiter: User, job: str, objects: dict[str, bytes]
) -> None:
    response = await upload(client, recruiter, job, b"%PDF" + b"0" * (10 * 1024 * 1024))

    assert response.status_code == 413
    assert objects == {}


@pytest.mark.cross_tenant
async def test_other_tenants_job_is_not_found_on_every_endpoint(
    client: AsyncClient, job: str, objects: dict[str, bytes]
) -> None:
    other = make_user()

    assert (await upload(client, other, job)).status_code == 404
    for path in ("uploads", "applications"):
        response = await client.get(f"/api/jobs/{job}/{path}", headers=other.headers)
        assert response.status_code == 404
    assert objects == {}


async def test_reviewer_cannot_upload_or_list(
    client: AsyncClient, recruiter: User, job: str
) -> None:
    reviewer = make_user("REVIEWER", recruiter.tenant_id)

    assert (await upload(client, reviewer, job)).status_code == 403
    for path in ("uploads", "applications"):
        response = await client.get(f"/api/jobs/{job}/{path}", headers=reviewer.headers)
        assert response.status_code == 403


# The parse task, run in-process as a worker would run what the API enqueued.

PROFILE: dict[str, Any] = {
    "contact": {
        "full_name": "Nguyễn Văn An",
        "email": "an.nguyen@example.com",
        "phone": "0901234567",
        "links": ["https://github.com/annguyen"],
    },
    "work_history": [
        {
            "company": "Acme",
            "title": "Backend Developer",
            "start": "03/2021",
            "end": "nay",
            "responsibilities": ["Xây dựng API bằng Python"],
            # Contact details quoted outside `contact` are hidden too (FR-C2.4).
            "achievements": ["Nguyễn Văn An được khen thưởng; xem https://github.com/annguyen"],
        }
    ],
    "skills": {"hard": ["Python"], "soft": [], "tools": ["Docker"], "languages": []},
    "education": [],
    "certifications": [],
    "anomalies": [],
}


def profile(**contact: Any) -> dict[str, Any]:
    data = copy.deepcopy(PROFILE)
    data["contact"] |= contact
    return data


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> FakeLlm:
    fake = FakeLlm(PROFILE)
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "test-model")
    monkeypatch.setattr(uploads, "llm_from_env", lambda model: fake)
    monkeypatch.setitem(
        usage.PRICES, "test-model", usage.Price(Decimal("2"), Decimal("0.5"), Decimal("8"))
    )
    return fake


def run_parse(enqueued: list[tuple[str, ...]]) -> None:
    while enqueued:
        uploads.parse_cv.apply(args=enqueued.pop(0)).get()


def query(user: User, sql: str, **params: Any) -> list[dict[str, Any]]:
    with tenant_session(user.tenant_id) as session:
        return [dict(row._mapping) for row in session.execute(text(sql), params)]


async def uploaded(
    client: AsyncClient,
    user: User,
    job_id: str,
    enqueued: list[tuple[str, ...]],
    data: bytes = CV,
) -> dict[str, Any]:
    """Upload, run the parse, and return the item as listed."""
    item_id = (await upload(client, user, job_id, data)).json()["item_id"]
    run_parse(enqueued)
    return next(item for item in await items(client, user, job_id) if item["id"] == item_id)


@pytest.mark.usefixtures("redis")
async def test_parse_creates_the_candidate_cv_document_and_application(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    item = await uploaded(client, recruiter, job, enqueued)

    assert (item["status"], item["dedupe"], item["error_code"]) == ("SUCCEEDED", None, None)
    [candidate] = query(
        recruiter,
        "SELECT full_name, email, phone, links, consent_source,"
        "  consent_at > now() - interval '1 minute' AS consented_now,"
        "  last_activity_at > now() - interval '1 minute' AS active_now"
        " FROM candidates",
    )
    assert candidate == {
        "full_name": "Nguyễn Văn An",
        "email": "an.nguyen@example.com",
        "phone": "0901234567",
        "links": ["https://github.com/annguyen"],
        "consent_source": "RECRUITER_ATTESTED",
        "consented_now": True,
        "active_now": True,
    }
    [cv] = query(
        recruiter,
        "SELECT file_name, mime_type, parse_status, parsed_profile, parser_model, sha256"
        " FROM cv_documents",
    )
    assert cv["file_name"] == "an.docx" and cv["parse_status"] == "PARSED"
    assert cv["mime_type"].endswith("wordprocessingml.document")
    assert cv["parsed_profile"] == PROFILE and cv["parser_model"] == "test-model"
    [application] = await applications(client, recruiter, job)
    assert {k: application[k] for k in ("full_name", "email", "stage", "file_name")} == {
        "full_name": "Nguyễn Văn An",
        "email": "an.nguyen@example.com",
        "stage": "APPLIED",
        "file_name": "an.docx",
    }
    [batch] = query(
        recruiter, "SELECT status, completed_at IS NOT NULL AS done FROM upload_batches"
    )
    assert batch == {"status": "COMPLETED", "done": True}
    [entry] = query(recruiter, "SELECT user_id, feature, ref_type FROM ai_usage_entries")
    assert entry == {"user_id": recruiter.id, "feature": "CV_PARSE", "ref_type": "cv_document"}


@pytest.mark.usefixtures("redis")
async def test_blind_profile_in_the_database_holds_no_name_or_contact_details(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    await uploaded(client, recruiter, job, enqueued)

    [row] = query(recruiter, "SELECT blind_profile FROM cv_documents")
    stored = json.dumps(row["blind_profile"], ensure_ascii=False)
    for detail in ("Nguyễn Văn An", "an.nguyen@example.com", "0901234567", "github.com/annguyen"):
        assert detail not in stored
    assert "Xây dựng API bằng Python" in stored


@pytest.mark.usefixtures("redis")
async def test_parse_announces_the_item_to_the_recruiter(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    item_id = (await upload(client, recruiter, job)).json()["item_id"]
    async with _redis().pubsub() as sub:
        await sub.subscribe(events.channel(recruiter.tenant_id, recruiter.id))
        assert (await sub.get_message(timeout=5) or {})["type"] == "subscribe"

        run_parse(enqueued)

        message = await sub.get_message(timeout=5)
    assert message is not None
    assert json.loads(message["data"]) == {
        "event": "upload.item",
        "data": {"job_id": job, "item_id": item_id, "status": "SUCCEEDED"},
    }


# Dedupe (FR-A1.2).


@pytest.mark.usefixtures("redis")
async def test_same_file_in_the_same_job_changes_nothing(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    await uploaded(client, recruiter, job, enqueued)

    again = await uploaded(client, recruiter, job, enqueued)

    assert (again["status"], again["dedupe"]) == ("SUCCEEDED", "ALREADY_APPLIED")
    # The CV Document is reused, so the file is not parsed twice.
    assert llm.calls == 1
    assert len(query(recruiter, "SELECT id FROM cv_documents")) == 1
    assert len(await applications(client, recruiter, job)) == 1


@pytest.mark.usefixtures("redis")
async def test_same_file_in_another_job_reuses_the_cv_document(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    await uploaded(client, recruiter, job, enqueued)
    other_job = make_job(recruiter)

    item = await uploaded(client, recruiter, other_job, enqueued)

    assert item["dedupe"] == "EXISTING_CANDIDATE"
    assert llm.calls == 1
    [cv] = query(recruiter, "SELECT id FROM cv_documents")
    assert [a["stage"] for a in await applications(client, recruiter, other_job)] == ["APPLIED"]
    assert len(query(recruiter, "SELECT id FROM candidates")) == 1
    assert {r["cv_document_id"] for r in query(recruiter, "SELECT * FROM applications")} == {
        cv["id"]
    }


@pytest.mark.usefixtures("redis")
async def test_same_email_attaches_to_the_existing_candidate_without_editing_it(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    await uploaded(client, recruiter, job, enqueued)
    with tenant_session(recruiter.tenant_id) as session:
        # As if the Candidate had come through Public Apply, a month ago.
        session.execute(
            text(
                "UPDATE candidates SET consent_source = 'PUBLIC_APPLY_CONSENT',"
                "  consent_at = now() - interval '30 days',"
                "  last_activity_at = now() - interval '30 days'"
            )
        )
    llm.data = profile(
        full_name="An Nguyen", email="  AN.Nguyen@Example.com ", phone="0999", links=[]
    )

    item = await uploaded(client, recruiter, make_job(recruiter), enqueued, docx("An Nguyen CV"))

    assert item["dedupe"] == "EXISTING_CANDIDATE"
    [candidate] = query(
        recruiter,
        "SELECT full_name, email, phone, links, consent_source,"
        "  consent_at < now() - interval '1 day' AS consent_kept,"
        "  last_activity_at > now() - interval '1 day' AS active"
        " FROM candidates",
    )
    assert candidate == {
        "full_name": "Nguyễn Văn An",
        "email": "an.nguyen@example.com",
        "phone": "0901234567",
        "links": ["https://github.com/annguyen"],
        "consent_source": "PUBLIC_APPLY_CONSENT",
        "consent_kept": True,
        "active": True,
    }
    assert len(query(recruiter, "SELECT id FROM cv_documents")) == 2


@pytest.mark.usefixtures("redis")
async def test_new_cv_of_an_applicant_replaces_the_applications_cv_and_keeps_its_stage(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    await uploaded(client, recruiter, job, enqueued)
    with tenant_session(recruiter.tenant_id) as session:
        session.execute(text("UPDATE applications SET stage = 'SCREENING'"))

    item = await uploaded(client, recruiter, job, enqueued, docx("Nguyễn Văn An - CV 2026"))

    assert item["dedupe"] == "CV_REPLACED"
    [application] = await applications(client, recruiter, job)
    assert application["stage"] == "SCREENING"
    [row] = query(
        recruiter,
        "SELECT a.cv_document_id = i.cv_document_id AS replaced"
        " FROM applications a, upload_batch_items i WHERE i.id = :id",
        id=item["id"],
    )
    assert row["replaced"]


@pytest.mark.parametrize("email", [None, "   ", "not an email"], ids=["none", "blank", "invalid"])
@pytest.mark.usefixtures("redis")
async def test_cv_without_a_valid_email_creates_a_new_candidate(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
    email: str | None,
) -> None:
    llm.data = profile(email=email)
    await uploaded(client, recruiter, job, enqueued)

    item = await uploaded(client, recruiter, job, enqueued, docx("Nguyễn Văn An - CV 2026"))

    assert item["dedupe"] is None
    candidates = query(recruiter, "SELECT email FROM candidates")
    assert candidates == [{"email": None}, {"email": None}]
    assert len(await applications(client, recruiter, job)) == 2


@pytest.mark.usefixtures("redis")
@pytest.mark.cross_tenant
async def test_dedupe_never_crosses_tenants(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    await uploaded(client, recruiter, job, enqueued)
    other = make_user()

    item = await uploaded(client, other, make_job(other), enqueued)

    assert item["dedupe"] is None
    assert llm.calls == 2
    for user in (recruiter, other):
        assert len(query(user, "SELECT id FROM candidates")) == 1


# Concurrent parses: INSERT … ON CONFLICT and the per-file lock keep them from duplicating.


def run_concurrently(enqueued: list[tuple[str, ...]]) -> None:
    with ThreadPoolExecutor(len(enqueued)) as pool:
        for future in [
            pool.submit(lambda args: uploads.parse_cv.apply(args=args).get(), args)
            for args in enqueued
        ]:
            future.result()
    enqueued.clear()


class BarrierLlm(FakeLlm):
    """Holds each call until every task is past its dedupe checks and inside the LLM call."""

    def __init__(self, data: dict[str, Any], parties: int) -> None:
        super().__init__(data)
        self.barrier = threading.Barrier(parties, timeout=10)

    def structured(self, *args: Any, **kwargs: Any) -> Any:
        self.barrier.wait()
        return super().structured(*args, **kwargs)


@pytest.mark.usefixtures("redis", "llm")
async def test_concurrent_cvs_with_the_same_email_make_one_candidate_and_application(
    client: AsyncClient,
    recruiter: User,
    job: str,
    enqueued: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = BarrierLlm(PROFILE, 2)
    monkeypatch.setattr(uploads, "llm_from_env", lambda model: llm)
    for body in ("CV một", "CV hai"):
        await upload(client, recruiter, job, docx(body))

    run_concurrently(enqueued)

    assert sorted(str(i["dedupe"]) for i in await items(client, recruiter, job)) == [
        "CV_REPLACED",
        "None",
    ]
    assert len(query(recruiter, "SELECT id FROM candidates")) == 1
    assert len(await applications(client, recruiter, job)) == 1


@pytest.mark.usefixtures("redis")
async def test_concurrent_uploads_of_the_same_file_parse_it_once(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    llm.data = profile(email=None)  # nothing but the file to dedupe on
    for _ in range(2):
        await upload(client, recruiter, job)

    run_concurrently(enqueued)

    assert llm.calls == 1
    assert len(query(recruiter, "SELECT id FROM cv_documents")) == 1
    assert len(query(recruiter, "SELECT id FROM candidates")) == 1
    assert sorted(str(i["dedupe"]) for i in await items(client, recruiter, job)) == [
        "ALREADY_APPLIED",
        "None",
    ]


# Failures and redelivery.


@pytest.mark.usefixtures("redis")
async def test_unreadable_file_fails_its_item_with_a_code_and_reason(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    item = await uploaded(client, recruiter, job, enqueued, b"%PDF-1.7\n damaged")

    assert (item["status"], item["error_code"]) == ("FAILED", "UNREADABLE")
    assert item["error_message"]
    assert llm.calls == 0
    assert query(recruiter, "SELECT id FROM candidates") == []
    [batch] = query(recruiter, "SELECT status FROM upload_batches")
    assert batch == {"status": "COMPLETED"}


@pytest.mark.usefixtures("redis")
async def test_docx_bomb_fails_its_item_with_its_extraction_code(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    item = await uploaded(client, recruiter, job, enqueued, docx_bomb())

    assert (item["status"], item["error_code"]) == ("FAILED", "DOCX_TOO_LARGE")
    assert llm.calls == 0


@pytest.mark.usefixtures("redis")
async def test_model_without_a_price_fails_the_item_before_calling_it(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "unpriced-model")

    item = await uploaded(client, recruiter, job, enqueued)

    assert (item["status"], item["error_code"]) == ("FAILED", "UNPRICED_MODEL")
    assert llm.calls == 0


@pytest.mark.usefixtures("redis")
async def test_redelivered_parse_does_nothing(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    await upload(client, recruiter, job)
    args = enqueued[0]
    run_parse(enqueued)

    uploads.parse_cv.apply(args=args).get()

    assert llm.calls == 1
    assert len(query(recruiter, "SELECT id FROM ai_usage_entries")) == 1


@pytest.mark.cross_tenant
async def test_parse_cannot_reach_another_tenants_item(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    await upload(client, recruiter, job)
    [(_, item_id)] = enqueued

    uploads.parse_cv.apply(args=(str(make_user().tenant_id), item_id)).get()

    assert llm.calls == 0
    assert [i["status"] for i in await items(client, recruiter, job)] == ["PENDING"]


@pytest.mark.usefixtures("redis")
async def test_file_missing_from_storage_fails_its_item_rather_than_leave_it_pending(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
    objects: dict[str, bytes],
) -> None:
    await upload(client, recruiter, job)
    objects.clear()

    run_parse(enqueued)

    [item] = await items(client, recruiter, job)
    assert (item["status"], item["error_code"]) == ("FAILED", "PARSE_FAILED")
    [batch] = query(recruiter, "SELECT status FROM upload_batches")
    assert batch == {"status": "COMPLETED"}
