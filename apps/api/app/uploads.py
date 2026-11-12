"""Upload CVs into a Job; each parse creates a Candidate, CV Document and Application (FR-A1.2).

Each upload is an Upload Batch of up to MAX_BATCH_FILES items (SAD §5.1). The API checks every
file before it stores any, then enqueues `uploads.parse_cv` per item once that commits; the task
dedupes, parses, writes the result on the item and tells the Recruiter over SSE.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, NoReturn

from celery.exceptions import TaskPredicate
from fastapi import APIRouter, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import ai, events, outbox, storage, usage
from app.jobs import MANAGERS, MAX_DOCUMENT_BYTES, JobManager, JobReader, JobWriter
from app.worker import tenant_task
from smart_ats_scoring import parsing
from smart_ats_scoring.extraction import ExtractionError, document_type, extract_text
from smart_ats_scoring.llm import UnusableResponse, is_transient_error, llm_from_env

log = logging.getLogger(__name__)

MIME_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
# ponytail: shape only; a CV whose email fails it simply gets a Candidate of its own.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

# FR-A1.2; with MAX_DOCUMENT_BYTES it sizes Caddy's body limit on this route (Caddyfile).
MAX_BATCH_FILES = 50

Dedupe = Literal["EXISTING_CANDIDATE", "CV_REPLACED", "ALREADY_APPLIED"]
RejectReason = Literal["TOO_LARGE", "UNSUPPORTED_TYPE"]

router = APIRouter(prefix="/api/jobs")


class UploadCreated(BaseModel):
    batch_id: uuid.UUID
    item_ids: list[uuid.UUID]


class UploadItem(BaseModel):
    id: uuid.UUID
    file_name: str
    status: Literal["PENDING", "SUCCEEDED", "FAILED"]
    dedupe: Dedupe | None
    error_code: str | None
    error_message: str | None


class UploadBatch(BaseModel):
    id: uuid.UUID
    status: Literal["PROCESSING", "COMPLETED"]
    total: int
    # Counted from the items (SAD §5.1); processed includes failed.
    processed: int
    failed: int
    created_at: datetime
    items: list[UploadItem]


class Application(BaseModel):
    """As a Reviewer sees it: without the Candidate's contact details (SRS §2.1)."""

    id: uuid.UUID
    candidate_id: uuid.UUID
    full_name: str | None
    stage: str
    rejected_reason: str | None
    # Sent back with a Stage change (optimistic locking, FR-A3.2).
    version: int
    source: Literal["UPLOAD", "PUBLIC_APPLY", "REDISCOVERY"]
    # Of the newest Scoring Run that scored it, so a run in progress keeps the last one shown.
    total_score: float | None
    file_name: str
    updated_at: datetime


class ApplicationWithContact(Application):
    email: str | None


@router.post("/{job_id}/uploads", status_code=status.HTTP_202_ACCEPTED)
async def create(
    job_id: uuid.UUID,
    auth: JobWriter,
    files: list[UploadFile],
    consent_confirmed: Annotated[bool, Form()],
) -> UploadCreated:
    """CVs into a Job as one Upload Batch; each file's parse runs on queue llm."""
    if not consent_confirmed:
        # FR-A1.2: the Recruiter attests the Candidate's consent or another lawful basis.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Confirm the lawful basis for processing the Candidate's personal data",
        )
    if len(files) > MAX_BATCH_FILES:
        _reject(status.HTTP_413_CONTENT_TOO_LARGE, f"At most {MAX_BATCH_FILES} CVs per upload", [])

    # Every file is checked before any is stored, so a rejected batch leaves nothing to clean
    # up. Starlette has spooled them to disk; each is read once here and once to store it.
    kinds: list[str | None] = []
    rejected: list[tuple[UploadFile, RejectReason]] = []
    for file in files:
        # Reading one byte past the limit is enough to tell the file is over it.
        data = await file.read(MAX_DOCUMENT_BYTES + 1)
        kind = document_type(data)
        kinds.append(kind)
        if len(data) > MAX_DOCUMENT_BYTES:
            rejected.append((file, "TOO_LARGE"))
        elif kind not in MIME_TYPES:
            rejected.append((file, "UNSUPPORTED_TYPE"))
    if rejected:
        too_large = any(reason == "TOO_LARGE" for _, reason in rejected)
        _reject(
            status.HTTP_413_CONTENT_TOO_LARGE
            if too_large
            else status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Each CV must be a PDF or DOCX of at most {MAX_DOCUMENT_BYTES // 2**20} MB",
            rejected,
        )
    await usage.check_budget(auth.db, {"CV_PARSE": len(files)})

    batch_id: uuid.UUID = (
        await auth.db.execute(
            text(
                "INSERT INTO upload_batches (tenant_id, job_id, created_by, total_count, status)"
                " VALUES (:tenant_id, :job_id, :user_id, :total, 'PROCESSING') RETURNING id"
            ),
            {
                "tenant_id": auth.tenant_id,
                "job_id": job_id,
                "user_id": auth.user_id,
                "total": len(files),
            },
        )
    ).scalar_one()
    item_ids: list[uuid.UUID] = []
    for file, extension in zip(files, kinds, strict=True):
        await file.seek(0)
        # ponytail: objects stay behind if a later put or insert fails; a sweep can collect them.
        key = f"t/{auth.tenant_id}/cv/{uuid.uuid4()}.{extension}"
        await asyncio.to_thread(storage.put, key, await file.read())
        item_ids.append(
            (
                await auth.db.execute(
                    text(
                        "INSERT INTO upload_batch_items (tenant_id, batch_id, file_name,"
                        "  storage_key, status, attempts, enqueued_at)"
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
        )
    outbox.enqueue_after_commit(
        auth.db, parse_cv, *[(str(auth.tenant_id), str(item_id)) for item_id in item_ids]
    )
    return UploadCreated(batch_id=batch_id, item_ids=item_ids)


def _reject(code: int, message: str, files: list[tuple[UploadFile, RejectReason]]) -> NoReturn:
    """Refuse the whole batch, naming each file at fault and why."""
    raise HTTPException(
        code,
        {
            "message": message,
            "files": [{"file_name": f.filename, "reason": reason} for f, reason in files],
        },
    )


@router.post("/{job_id}/uploads/items/{item_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_item(job_id: uuid.UUID, item_id: uuid.UUID, auth: JobWriter) -> UploadItem:
    """Re-enqueue one failed upload item whose failure was a transient AI outage."""
    item = (
        await auth.db.execute(
            text(
                "SELECT i.id, i.batch_id, i.status, i.error_code"
                " FROM upload_batch_items i JOIN upload_batches b ON b.id = i.batch_id"
                " WHERE i.id = :item_id AND b.job_id = :job_id FOR UPDATE OF i"
            ),
            {"item_id": item_id, "job_id": job_id},
        )
    ).one_or_none()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload item not found")
    if item.status != "FAILED" or item.error_code not in ai.RETRYABLE_ERRORS:
        raise HTTPException(status.HTTP_409_CONFLICT, "The upload item cannot be retried")
    await usage.check_budget(auth.db, {"CV_PARSE": 1})
    updated = (
        await auth.db.execute(
            text(
                "UPDATE upload_batch_items SET status = 'PENDING', error_code = NULL,"
                "  error_message = NULL, attempts = 1, enqueued_at = now()"
                " WHERE id = :id"
                " RETURNING id, file_name, status, dedupe, error_code, error_message"
            ),
            {"id": item_id},
        )
    ).one()
    await auth.db.execute(
        text(
            "UPDATE upload_batches SET status = 'PROCESSING', completed_at = NULL"
            " WHERE id = :batch_id"
        ),
        {"batch_id": item.batch_id},
    )
    outbox.enqueue_after_commit(auth.db, parse_cv, (str(auth.tenant_id), str(item_id)))
    return UploadItem(**updated._mapping)


@router.get("/{job_id}/uploads")
async def list_batches(job_id: uuid.UUID, auth: JobManager) -> list[UploadBatch]:
    """The Job's Upload Batches, newest first, with their progress and their items in the order
    sent, each with its failure or dedupe outcome."""
    rows = await auth.db.execute(
        text(
            "SELECT b.id, b.status, b.created_at, count(*) AS total,"
            "  count(*) FILTER (WHERE i.status <> 'PENDING') AS processed,"
            "  count(*) FILTER (WHERE i.status = 'FAILED') AS failed,"
            "  json_agg(json_build_object('id', i.id, 'file_name', i.file_name,"
            "    'status', i.status, 'dedupe', i.dedupe, 'error_code', i.error_code,"
            "    'error_message', i.error_message) ORDER BY i.id) AS items"
            " FROM upload_batches b JOIN upload_batch_items i ON i.batch_id = b.id"
            " WHERE b.job_id = :job_id GROUP BY b.id ORDER BY b.created_at DESC, b.id DESC"
        ),
        {"job_id": job_id},
    )
    return [UploadBatch(**row._mapping) for row in rows]


@router.get("/{job_id}/applications")
async def list_applications(
    job_id: uuid.UUID, auth: JobReader
) -> list[ApplicationWithContact] | list[Application]:
    rows = await auth.db.execute(
        text(
            "SELECT a.id, a.candidate_id, c.full_name, c.email, a.stage, a.rejected_reason,"
            "  a.version, a.source, d.file_name, a.updated_at,"
            "  (SELECT s.total_score FROM score_results s"
            "    JOIN scoring_runs r ON r.id = s.scoring_run_id"
            "    WHERE s.application_id = a.id AND s.status = 'SCORED'"
            "    ORDER BY r.created_at DESC, r.id DESC LIMIT 1) AS total_score"
            " FROM applications a JOIN candidates c ON c.id = a.candidate_id"
            "  JOIN cv_documents d ON d.id = a.cv_document_id"
            " WHERE a.job_id = :job_id ORDER BY a.created_at DESC"
        ),
        {"job_id": job_id},
    )
    if auth.role in MANAGERS:
        return [ApplicationWithContact(**row._mapping) for row in rows]
    return [Application(**row._mapping) for row in rows]


@tenant_task(name="uploads.parse_cv", queue="llm", max_retries=len(ai.RETRY_BACKOFF_SECONDS))
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
        parsed = _parse(tenant_id, session, item, data)
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
            " RETURNING id, old.id IS NOT NULL AS existed"
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
        # Its creation opens its Stage history (FR-A3.2), by whoever uploaded the CV.
        session.execute(
            text(
                "INSERT INTO application_stage_history (tenant_id, application_id, to_stage,"
                "  changed_by) VALUES (:tenant_id, :id, 'APPLIED', :user_id)"
            ),
            {"tenant_id": tenant_id, "id": application.id, "user_id": item.created_by},
        )
    finish_item(session, item, "SUCCEEDED", cv_id=cv_id, dedupe=dedupe)


def _parse(
    tenant_id: uuid.UUID, session: Session, item: Any, data: bytes
) -> parsing.Parsed | tuple[str, str]:
    """The parsed CV, or the item's (error_code, error_message)."""
    try:
        cv_text = extract_text(data)
    except ExtractionError as e:
        return e.code, e.reason
    model = os.environ["LLM_EXTRACTION_MODEL"]
    if not usage.priced(model):
        return "UNPRICED_MODEL", "the AI model has no price in the AI Usage Ledger"
    try:
        llm = llm_from_env(model, max_retries=0)
        with ai.llm_call(session, tenant_id):
            return parsing.parse_cv(cv_text, llm)
    except TaskPredicate:
        raise
    except Exception as e:
        if is_transient_error(e):
            log.warning("transient error parsing CV upload item %s: %s", item.id, type(e).__name__)
            return ai.retry_transient_error(e), "the AI service is temporarily unavailable"
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
