"""Public Apply: anonymous application submission via /apply/{slug} (FR-A3.4).

Public endpoints look up the Job via `public_job_by_slug` (SECURITY DEFINER) before knowing
the Tenant, then operate within that Tenant's context (SAD §4.2). Candidates submit CV, contact info
and mandatory consent. Duplicate applications for the same Job and email are idempotently accepted
without creating duplicate records.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Cookie,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import emails, outbox, storage, usage
from app.auth import _redis
from app.db import async_engine, async_tenant_session
from app.jobs import MAX_DOCUMENT_BYTES, WorkMode
from app.worker import tenant_task
from smart_ats_scoring import parsing
from smart_ats_scoring.extraction import document_type, extract_text
from smart_ats_scoring.llm import llm_from_env

log = logging.getLogger(__name__)

MIME_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

# NFR-SEC-06: Public Apply 5 requests / hour / IP
RATE_LIMIT_PER_HOUR = 5
RATE_LIMIT_TTL_SECONDS = 3600

_APPLY_RATE_LIMIT_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
if current > tonumber(ARGV[2]) then
    return 0
end
return 1
"""

_RECEIPT_EMAIL = {
    "vi": (
        "Xác nhận nhận hồ sơ ứng tuyển: {job_title}",
        "Xin chào {full_name},\n\n"
        "Cảm ơn bạn đã nộp hồ sơ ứng tuyển vị trí {job_title} tại {tenant_name}.\n\n"
        "Chúng tôi đã nhận được hồ sơ của bạn và sẽ xem xét trong thời gian sớm nhất.\n\n"
        "Trân trọng,\n"
        "{tenant_name}\n",
    ),
    "en": (
        "Application received: {job_title}",
        "Dear {full_name},\n\n"
        "Thank you for applying for the {job_title} position at {tenant_name}.\n\n"
        "We have received your application and will review it shortly.\n\n"
        "Best regards,\n"
        "{tenant_name}\n",
    ),
}

router = APIRouter(prefix="/api/apply")


async def _check_rate_limit(ip: str) -> bool:
    script = _redis().register_script(_APPLY_RATE_LIMIT_LUA)
    allowed = await script(
        keys=[f"apply_limit:{ip}"], args=[RATE_LIMIT_TTL_SECONDS, RATE_LIMIT_PER_HOUR]
    )
    return bool(allowed)


class PublicJob(BaseModel):
    job_id: uuid.UUID
    title: str
    status: str
    public_apply_enabled: bool
    apply_deadline: date | None
    location: str | None
    work_mode: WorkMode | None
    criteria: dict[str, Any] | None
    tenant_name: str
    tenant_logo_url: str | None
    tenant_privacy_notice_url: str | None
    is_closed: bool


class ApplyResult(BaseModel):
    status: Literal["ok"]
    message: str


@router.get("/{slug}")
async def get_public_job(slug: str) -> PublicJob:
    """Retrieve public job and tenant details by slug without authentication."""
    async with async_engine().begin() as conn:
        row = (
            await conn.execute(text("SELECT * FROM public_job_by_slug(:slug)"), {"slug": slug})
        ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    is_closed = (
        row.status != "PUBLISHED"
        or not row.public_apply_enabled
        or (row.apply_deadline is not None and row.apply_deadline < date.today())
    )
    return PublicJob(
        job_id=row.job_id,
        title=row.title,
        status=row.status,
        public_apply_enabled=row.public_apply_enabled,
        apply_deadline=row.apply_deadline,
        location=row.location,
        work_mode=row.work_mode,
        criteria=row.criteria,
        tenant_name=row.tenant_name,
        tenant_logo_url=row.tenant_logo_url,
        tenant_privacy_notice_url=row.tenant_privacy_notice_url,
        is_closed=is_closed,
    )


@router.post("/{slug}", status_code=status.HTTP_200_OK)
async def submit_application(
    slug: str,
    request: Request,
    file: Annotated[UploadFile, File()],
    full_name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    consent: Annotated[bool, Form()],
    phone: Annotated[str | None, Form()] = None,
    next_locale: Annotated[str | None, Cookie(alias="NEXT_LOCALE")] = None,
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> ApplyResult:
    """Submit an application to a Job with Public Apply Link enabled (FR-A3.4)."""
    ip = f"ip:{request.client.host if request.client else 'unknown'}"
    if not await _check_rate_limit(ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests. Please try again later."
        )

    if not consent:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "You must consent to personal data processing to apply.",
        )

    clean_name = full_name.strip()
    clean_email = email.strip().lower()
    clean_phone = phone.strip() if phone and phone.strip() else None

    if not clean_name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Full name is required.")
    if not _EMAIL.fullmatch(clean_email):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid email address.")

    async with async_engine().begin() as conn:
        job = (
            await conn.execute(text("SELECT * FROM public_job_by_slug(:slug)"), {"slug": slug})
        ).one_or_none()
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

    if (
        job.status != "PUBLISHED"
        or not job.public_apply_enabled
        or (job.apply_deadline is not None and job.apply_deadline < date.today())
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This job is closed and no longer accepting applications."
        )

    data = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The CV exceeds 10 MB")

    ext = document_type(data)
    if ext not in MIME_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF and DOCX documents are accepted"
        )
    mime_type = MIME_TYPES[ext]
    sha256 = hashlib.sha256(data).hexdigest()

    async with async_tenant_session(job.tenant_id) as db:
        # Check duplicate application (same email for same Job)
        existing_candidate_id = await db.scalar(
            text("SELECT id FROM candidates WHERE email = :email"),
            {"email": clean_email},
        )
        if existing_candidate_id is not None:
            already_applied = await db.scalar(
                text(
                    "SELECT 1 FROM applications WHERE job_id = :job_id AND candidate_id = :cand_id"
                ),
                {"job_id": job.job_id, "cand_id": existing_candidate_id},
            )
            if already_applied:
                # AC 6: do not create second application, return same confirmation message
                return ApplyResult(status="ok", message="Application received")

        # Create or update candidate with consent details (FR-C1.5)
        candidate_id: uuid.UUID = (
            await db.execute(
                text(
                    "INSERT INTO candidates (tenant_id, full_name, email, phone,"
                    "  consent_source, consent_at, consent_notice_version, last_activity_at)"
                    " VALUES (:tenant_id, :full_name, :email, :phone,"
                    "  'PUBLIC_APPLY_CONSENT', now(), '1.0', now())"
                    " ON CONFLICT (tenant_id, email) DO UPDATE"
                    "  SET last_activity_at = now(),"
                    "      consent_source = 'PUBLIC_APPLY_CONSENT',"
                    "      consent_at = now(),"
                    "      full_name = coalesce(candidates.full_name, EXCLUDED.full_name),"
                    "      phone = coalesce(candidates.phone, EXCLUDED.phone)"
                    " RETURNING id"
                ),
                {
                    "tenant_id": job.tenant_id,
                    "full_name": clean_name,
                    "email": clean_email,
                    "phone": clean_phone,
                },
            )
        ).scalar_one()

        # Deduplicate CV document by sha256 (FR-A1.2)
        existing_cv = (
            await db.execute(
                text("SELECT id, parse_status FROM cv_documents WHERE sha256 = :sha256"),
                {"sha256": sha256},
            )
        ).one_or_none()

        needs_parse = False
        if existing_cv is not None:
            cv_document_id = existing_cv.id
            if existing_cv.parse_status == "PENDING":
                needs_parse = True
        else:
            storage_key = f"t/{job.tenant_id}/cv/{uuid.uuid4()}.{ext}"
            await asyncio.to_thread(storage.put, storage_key, data)
            cv_document_id = (
                await db.execute(
                    text(
                        "INSERT INTO cv_documents (tenant_id, candidate_id, storage_key,"
                        "  file_name, mime_type, sha256, parse_status)"
                        " VALUES (:tenant_id, :candidate_id, :key, :file_name, :mime_type,"
                        "  :sha256, 'PENDING') RETURNING id"
                    ),
                    {
                        "tenant_id": job.tenant_id,
                        "candidate_id": candidate_id,
                        "key": storage_key,
                        "file_name": file.filename or "CV",
                        "mime_type": mime_type,
                        "sha256": sha256,
                    },
                )
            ).scalar_one()
            needs_parse = True

        # Create application with source = PUBLIC_APPLY at stage APPLIED
        application_id: uuid.UUID = (
            await db.execute(
                text(
                    "INSERT INTO applications (tenant_id, job_id, candidate_id,"
                    "  cv_document_id, source, stage)"
                    " VALUES (:tenant_id, :job_id, :candidate_id, :cv_id,"
                    "  'PUBLIC_APPLY', 'APPLIED')"
                    " ON CONFLICT (job_id, candidate_id) DO NOTHING"
                    " RETURNING id"
                ),
                {
                    "tenant_id": job.tenant_id,
                    "job_id": job.job_id,
                    "candidate_id": candidate_id,
                    "cv_id": cv_document_id,
                },
            )
        ).scalar_one()

        # Application stage history (changed_by is NULL for public apply, ERD §3)
        await db.execute(
            text(
                "INSERT INTO application_stage_history"
                "  (tenant_id, application_id, to_stage, changed_by)"
                " VALUES (:tenant_id, :app_id, 'APPLIED', NULL)"
            ),
            {"tenant_id": job.tenant_id, "app_id": application_id},
        )

        # Enqueue confirmation email (APPLY_RECEIPT) rendered in candidate's locale
        lang = emails.locale(next_locale, accept_language, is_public=True)
        subject_template, body_template = _RECEIPT_EMAIL[lang]
        subject = subject_template.format(job_title=job.title, tenant_name=job.tenant_name)
        body = body_template.format(
            full_name=clean_name, job_title=job.title, tenant_name=job.tenant_name
        )

        email_id = (
            await db.execute(
                text(
                    "INSERT INTO email_messages (tenant_id, application_id, kind, to_address,"
                    "  subject, body, status, attempts, enqueued_at)"
                    " VALUES (:tenant_id, :app_id, 'APPLY_RECEIPT', :to, :subject, :body,"
                    "  'QUEUED', 1, now()) RETURNING id"
                ),
                {
                    "tenant_id": job.tenant_id,
                    "app_id": application_id,
                    "to": clean_email,
                    "subject": subject,
                    "body": body,
                },
            )
        ).scalar_one()

        outbox.enqueue_after_commit(db, emails.send_email, (str(job.tenant_id), str(email_id)))
        if needs_parse:
            outbox.enqueue_after_commit(db, parse_cv, (str(job.tenant_id), str(cv_document_id)))

    return ApplyResult(status="ok", message="Application received")


@tenant_task(name="apply.parse_cv", queue="llm")
def parse_cv(tenant_id: uuid.UUID, session: Session, cv_document_id: str) -> None:
    """Parse a CV Document uploaded via Public Apply into structured profile and blind profile."""
    doc = session.execute(
        text(
            "SELECT id, storage_key, file_name FROM cv_documents"
            " WHERE id = :id AND parse_status = 'PENDING' FOR UPDATE"
        ),
        {"id": cv_document_id},
    ).one_or_none()
    if doc is None:
        return
    try:
        data = storage.get(doc.storage_key)
        cv_text = extract_text(data)
        model = os.environ["LLM_EXTRACTION_MODEL"]
        if not usage.priced(model):
            session.execute(
                text("UPDATE cv_documents SET parse_status = 'FAILED' WHERE id = :id"),
                {"id": cv_document_id},
            )
            return
        parsed = parsing.parse_cv(cv_text, llm_from_env(model))
        blind = parsing.blind_profile(parsed.data)
        session.execute(
            text(
                "UPDATE cv_documents SET parse_status = 'PARSED',"
                "  parsed_profile = CAST(:parsed AS jsonb),"
                "  blind_profile = CAST(:blind AS jsonb),"
                "  field_verification = CAST(:verification AS jsonb),"
                "  parser_model = :model, parsed_at = now()"
                " WHERE id = :id"
            ),
            {
                "id": cv_document_id,
                "parsed": json.dumps(parsed.data),
                "blind": json.dumps(blind),
                "verification": json.dumps(parsed.verification),
                "model": parsed.usage.model,
            },
        )
        usage.record(session, None, "CV_PARSE", parsed.usage, "cv_document", doc.id)
    except Exception:
        log.exception("parsing public apply CV document %s failed", cv_document_id)
        session.execute(
            text("UPDATE cv_documents SET parse_status = 'FAILED' WHERE id = :id"),
            {"id": cv_document_id},
        )
