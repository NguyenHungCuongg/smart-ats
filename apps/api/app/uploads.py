"""Upload a CV into a Job; its parse creates the Candidate, CV Document and Application (FR-A1.2).

Each upload is an Upload Batch of one item (SAD §5.1). The API stores the file and enqueues
`uploads.parse_cv` once that commits; the task dedupes, parses, writes the result on the item
and tells the Recruiter over SSE.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app import events, outbox, storage, usage
from app.jobs import MAX_DOCUMENT_BYTES, Recruiter
from app.worker import tenant_task
from smart_ats_scoring import parsing
from smart_ats_scoring.extraction import ExtractionError, document_type, extract_text
from smart_ats_scoring.llm import UnusableResponse, llm_from_env

log = logging.getLogger(__name__)

MIME_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
# ponytail: shape only; a CV whose email fails it simply gets a Candidate of its own.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

Dedupe = Literal["EXISTING_CANDIDATE", "CV_REPLACED", "ALREADY_APPLIED"]

router = APIRouter(prefix="/api/jobs")


class UploadCreated(BaseModel):
    batch_id: uuid.UUID
    item_id: uuid.UUID


class UploadItem(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    file_name: str
    status: Literal["PENDING", "SUCCEEDED", "FAILED"]
    dedupe: Dedupe | None
    error_code: str | None
    error_message: str | None
    created_at: datetime


class Application(BaseModel):
    id: uuid.UUID
    candidate_id: uuid.UUID
    full_name: str | None
    email: str | None
    stage: str
    file_name: str
    updated_at: datetime


async def _require_job(db: AsyncSession, job_id: uuid.UUID) -> None:
    # Another Tenant's Job is hidden by RLS, so it is a 404 like a missing one (SAD §4.3).
    if await db.scalar(text("SELECT 1 FROM jobs WHERE id = :id"), {"id": job_id}) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")


@router.post("/{job_id}/uploads", status_code=status.HTTP_202_ACCEPTED)
async def create(
    job_id: uuid.UUID,
    auth: Recruiter,
    file: UploadFile,
    consent_confirmed: Annotated[bool, Form()],
) -> UploadCreated:
    """One CV into a Job, as an Upload Batch of one item; the parse runs on queue llm."""
    if not consent_confirmed:
        # FR-A1.2: the Recruiter attests the Candidate's consent or another lawful basis.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Confirm the lawful basis for processing the Candidate's personal data",
        )
    await _require_job(auth.db, job_id)
    # Caddy cuts a body off a little past the limit, as in jobs.create.
    data = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The CV exceeds 10 MB")
    kind = document_type(data)
    if kind not in MIME_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "The CV must be PDF or DOCX")

    # ponytail: an object stays behind if the inserts below fail; a sweep can collect those.
    key = f"t/{auth.tenant_id}/cv/{uuid.uuid4()}.{kind}"
    await asyncio.to_thread(storage.put, key, data)
    batch_id: uuid.UUID = (
        await auth.db.execute(
            text(
                "INSERT INTO upload_batches (tenant_id, job_id, created_by, total_count, status)"
                " VALUES (:tenant_id, :job_id, :user_id, 1, 'PROCESSING') RETURNING id"
            ),
            {"tenant_id": auth.tenant_id, "job_id": job_id, "user_id": auth.user_id},
        )
    ).scalar_one()
    item_id: uuid.UUID = (
        await auth.db.execute(
            text(
                "INSERT INTO upload_batch_items (tenant_id, batch_id, file_name, storage_key,"
                "  status, attempts, enqueued_at)"
                " VALUES (:tenant_id, :batch_id, :file_name, :key, 'PENDING', 1, now())"
                " RETURNING id"
            ),
            {
                "tenant_id": auth.tenant_id,
                "batch_id": batch_id,
                "file_name": file.filename or "CV",
                "key": key,
            },
        )
    ).scalar_one()
    outbox.enqueue_after_commit(auth.db, parse_cv, (str(auth.tenant_id), str(item_id)))
    return UploadCreated(batch_id=batch_id, item_id=item_id)


@router.get("/{job_id}/uploads")
async def list_items(job_id: uuid.UUID, auth: Recruiter) -> list[UploadItem]:
    """The Job's upload items, newest first, with their failure or dedupe outcome."""
    await _require_job(auth.db, job_id)
    rows = await auth.db.execute(
        text(
            "SELECT i.id, i.batch_id, i.file_name, i.status, i.dedupe, i.error_code,"
            "  i.error_message, b.created_at"
            " FROM upload_batch_items i JOIN upload_batches b ON b.id = i.batch_id"
            " WHERE b.job_id = :job_id ORDER BY b.created_at DESC, i.id DESC"
        ),
        {"job_id": job_id},
    )
    return [UploadItem(**row._mapping) for row in rows]


@router.get("/{job_id}/applications")
async def list_applications(job_id: uuid.UUID, auth: Recruiter) -> list[Application]:
    await _require_job(auth.db, job_id)
    rows = await auth.db.execute(
        text(
            "SELECT a.id, a.candidate_id, c.full_name, c.email, a.stage, d.file_name,"
            "  a.updated_at"
            " FROM applications a JOIN candidates c ON c.id = a.candidate_id"
            "  JOIN cv_documents d ON d.id = a.cv_document_id"
            " WHERE a.job_id = :job_id ORDER BY a.created_at DESC"
        ),
        {"job_id": job_id},
    )
    return [Application(**row._mapping) for row in rows]


@tenant_task(name="uploads.parse_cv", queue="llm")
def parse_cv(tenant_id: uuid.UUID, session: Session, item_id: str) -> None:
    """Dedupe and parse one uploaded CV into a Candidate, CV Document and Application."""
    # ponytail: the locks and the transaction stay open through the LLM call, as in jobs.parse.
    item = session.execute(
        text(
            "SELECT i.id, i.batch_id, i.file_name, i.storage_key, b.job_id, b.created_by"
            " FROM upload_batch_items i JOIN upload_batches b ON b.id = i.batch_id"
            " WHERE i.id = :id AND i.status = 'PENDING' FOR UPDATE OF i"
        ),
        {"id": item_id},
    ).one_or_none()
    if item is None:
        return  # redelivered (acks_late) after it finished
    try:
        data = storage.get(item.storage_key)
    except Exception:
        log.exception("reading CV upload item %s from object storage failed", item_id)
        finish_item(session, item, "FAILED", error=("PARSE_FAILED", "the CV could not be read"))
        return
    sha256 = hashlib.sha256(data).hexdigest()
    # Parses of the same file wait for each other, so the later one finds the CV Document the
    # earlier one committed instead of parsing the file again.
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"cv:{tenant_id}:{sha256}"},
    )
    cv = session.execute(
        text("SELECT id, candidate_id FROM cv_documents WHERE sha256 = :sha256"),
        {"sha256": sha256},
    ).one_or_none()

    if cv is None:
        parsed = _parse(session, item, data)
        if isinstance(parsed, tuple):
            finish_item(session, item, "FAILED", error=parsed)
            return
        contact = parsed.data["contact"]
        email = (contact["email"] or "").strip()
        # ON CONFLICT: a parse running alongside with the same email finds this Candidate, and
        # one already there keeps its name, contact details and consent (FR-A1.2).
        candidate = session.execute(
            text(
                "INSERT INTO candidates (tenant_id, full_name, email, phone, links,"
                "  consent_source, consent_at, last_activity_at)"
                " VALUES (:tenant_id, :full_name, :email, :phone, CAST(:links AS jsonb),"
                "  'RECRUITER_ATTESTED', now(), now())"
                " ON CONFLICT (tenant_id, email) DO UPDATE SET last_activity_at = now()"
                " RETURNING id, old.id IS NOT NULL AS existed"
            ),
            {
                "tenant_id": tenant_id,
                "full_name": contact["full_name"],
                "email": email if _EMAIL.fullmatch(email) else None,
                "phone": contact["phone"],
                "links": json.dumps(contact["links"]),
            },
        ).one()
        candidate_id, existing_candidate = candidate.id, candidate.existed
        cv_id = session.execute(
            text(
                "INSERT INTO cv_documents (tenant_id, candidate_id, storage_key, file_name,"
                "  mime_type, sha256, parse_status, parsed_profile, blind_profile,"
                "  field_verification, parser_model, parsed_at)"
                " VALUES (:tenant_id, :candidate_id, :key, :file_name, :mime_type, :sha256,"
                "  'PARSED', CAST(:parsed AS jsonb), CAST(:blind AS jsonb),"
                "  CAST(:verification AS jsonb), :model, now()) RETURNING id"
            ),
            {
                "tenant_id": tenant_id,
                "candidate_id": candidate_id,
                "key": item.storage_key,
                "file_name": item.file_name,
                # The API named the object after the type it checked.
                "mime_type": MIME_TYPES[item.storage_key.rsplit(".", 1)[1]],
                "sha256": sha256,
                "parsed": json.dumps(parsed.data),
                "blind": json.dumps(parsing.blind_profile(parsed.data)),
                "verification": json.dumps(parsed.verification),
                "model": parsed.usage.model,
            },
        ).scalar_one()
        usage.record(session, item.created_by, "CV_PARSE", parsed.usage, "cv_document", cv_id)
    else:
        # ponytail: this item's copy of the file stays in storage; the retention sweep must
        # delete upload_batch_items.storage_key objects too, not only CV Documents'.
        cv_id, candidate_id, existing_candidate = cv.id, cv.candidate_id, True
        session.execute(
            text("UPDATE candidates SET last_activity_at = now() WHERE id = :id"),
            {"id": candidate_id},
        )

    # An Application already there moves to this CV and keeps its stage; with this same CV,
    # nothing changes and no row comes back.
    application = session.execute(
        text(
            "INSERT INTO applications (tenant_id, job_id, candidate_id, cv_document_id, source,"
            "  stage) VALUES (:tenant_id, :job_id, :candidate_id, :cv_id, 'UPLOAD', 'APPLIED')"
            " ON CONFLICT (job_id, candidate_id) DO UPDATE"
            "  SET cv_document_id = EXCLUDED.cv_document_id, updated_at = now()"
            "  WHERE applications.cv_document_id <> EXCLUDED.cv_document_id"
            " RETURNING old.id IS NOT NULL AS existed"
        ),
        {
            "tenant_id": tenant_id,
            "job_id": item.job_id,
            "candidate_id": candidate_id,
            "cv_id": cv_id,
        },
    ).one_or_none()
    dedupe: Dedupe | None
    if application is None:
        dedupe = "ALREADY_APPLIED"
    elif application.existed:
        dedupe = "CV_REPLACED"
    else:
        dedupe = "EXISTING_CANDIDATE" if existing_candidate else None
    finish_item(session, item, "SUCCEEDED", cv_id=cv_id, dedupe=dedupe)


def _parse(session: Session, item: Any, data: bytes) -> parsing.Parsed | tuple[str, str]:
    """The parsed CV, or the item's (error_code, error_message)."""
    try:
        cv_text = extract_text(data)
    except ExtractionError as e:
        return e.code, e.reason
    model = os.environ["LLM_EXTRACTION_MODEL"]
    if not usage.priced(model):
        return "UNPRICED_MODEL", "the AI model has no price in the AI Usage Ledger"
    try:
        return parsing.parse_cv(cv_text, llm_from_env(model))
    except Exception as e:
        # The traceback may hold provider details: it goes to the log, the item gets a code.
        log.exception("parsing CV upload item failed")
        if isinstance(e, UnusableResponse):
            # Billed all the same (FR-C1.4); no CV Document exists to refer to.
            usage.record(
                session, item.created_by, "CV_PARSE", e.usage, "upload_batch_item", item.id
            )
        return "PARSE_FAILED", "the CV could not be parsed"


def finish_item(
    session: Session,
    item: Any,
    status: Literal["SUCCEEDED", "FAILED"],
    cv_id: uuid.UUID | None = None,
    dedupe: Dedupe | None = None,
    error: tuple[str, str] | None = None,
) -> None:
    code, message = error or (None, None)
    session.execute(
        text(
            "UPDATE upload_batch_items SET status = :status, cv_document_id = :cv_id,"
            "  dedupe = :dedupe, error_code = :code, error_message = :message WHERE id = :id"
        ),
        {
            "id": item.id,
            "status": status,
            "cv_id": cv_id,
            "dedupe": dedupe,
            "code": code,
            "message": message,
        },
    )
    outbox.complete_parent(
        session,
        "upload_batches",
        item.batch_id,
        "upload_batch_items",
        "batch_id",
        "status = 'COMPLETED', completed_at = now()",
    )
    events.publish(
        session,
        item.created_by,
        "upload.item",
        {"job_id": str(item.job_id), "item_id": str(item.id), "status": status},
    )
