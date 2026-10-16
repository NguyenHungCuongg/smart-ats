"""Create a Job from a JD Document, parse it in the background, confirm its criteria (FR-A1.1).

The API inserts a DRAFT Job with placeholders and enqueues `jobs.parse` once that commits; the
task overwrites the placeholders with the parsed criteria and tells the Recruiter over SSE.
Scoring takes only Jobs whose criteria a Recruiter has confirmed (criteria_confirmed_at).
"""

import asyncio
import io
import json
import logging
import os
import uuid
import zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import PurePath
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app import events, storage, usage
from app.auth import Auth, Authenticated
from app.worker import tenant_task
from smart_ats_scoring.extraction import ExtractionError, extract_text
from smart_ats_scoring.llm import llm_from_env
from smart_ats_scoring.parsing import parse_job

log = logging.getLogger(__name__)

# The per-file limit of FR-A1.2, for JD Documents too.
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024

Level = Literal["INTERN", "JUNIOR", "MID", "SENIOR", "LEAD", "MANAGER"]
WorkMode = Literal["REMOTE", "HYBRID", "ONSITE"]

router = APIRouter(prefix="/api/jobs")


def _recruiter(auth: Authenticated) -> Auth:
    # SRS §2: creating Jobs and configuring criteria is for Company Admins and Recruiters.
    if auth.role not in ("COMPANY_ADMIN", "RECRUITER"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only Recruiters manage Jobs")
    return auth


Recruiter = Annotated[Auth, Depends(_recruiter)]


class Weights(BaseModel):
    """The three axes in whole percent (FR-A1.3); the database stores them as fractions."""

    technical: int = Field(ge=0, le=100)
    soft_skills: int = Field(ge=0, le=100)
    experience: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _make_100_percent(self) -> Self:
        if self.technical + self.soft_skills + self.experience != 100:
            raise ValueError("weights must add up to 100%")
        return self


class Skill(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    must_have: bool


class Criteria(BaseModel):
    """The `criteria` column (ERD §3): the parsed fields that have no column of their own."""

    skills: list[Skill] = Field(max_length=200)
    min_years_experience: float | None = Field(ge=0, le=60)
    education: str | None = Field(max_length=2000)
    responsibilities: list[Annotated[str, Field(max_length=2000)]] = Field(max_length=100)
    salary_range: str | None = Field(max_length=200)


class Job(BaseModel):
    id: uuid.UUID
    title: str
    level: Level
    department: str | None
    location: str | None
    work_mode: WorkMode | None
    status: str
    parse_status: Literal["PENDING", "SUCCEEDED", "FAILED"]
    parse_error: str | None
    # As parsed until confirmed: the LLM's output is not held to the limits of Criteria.
    criteria: dict[str, Any] | None
    # VERIFIED or NEEDS_REVIEW per parsed field (FR-A1.1).
    verification: dict[str, Literal["VERIFIED", "NEEDS_REVIEW"]] | None
    weights: Weights
    criteria_confirmed_at: datetime | None


class JobCreated(BaseModel):
    id: uuid.UUID


class CriteriaConfirmation(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    level: Level
    department: str | None = Field(max_length=200)
    location: str | None = Field(max_length=200)
    work_mode: WorkMode | None
    criteria: Criteria
    weights: Weights


def _document_type(data: bytes) -> str | None:
    """pdf, docx or txt, told by magic bytes as extract_text does (NFR-SEC-07), never by the
    file name or Content-Type."""
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        # Any ZIP starts so (XLSX, JAR…): a DOCX is one holding a Word document.
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except Exception:
            # A malformed archive raises BadZipFile, NotImplementedError, UnicodeDecodeError…
            return None
        return "docx" if "word/document.xml" in names else None
    try:
        decoded = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    return None if "\x00" in decoded else "txt"


def _placeholder_title(name: str) -> str:
    return name.strip()[:200] or "JD"


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create(
    auth: Recruiter,
    file: UploadFile | None = None,
    jd_text: Annotated[str | None, Form(alias="text")] = None,
) -> JobCreated:
    """A DRAFT Job from an uploaded JD Document or pasted text; the parse runs on queue llm."""
    if file is not None and jd_text is None:
        # Caddy cuts a body off a little past the limit, so Starlette spools no more (Caddyfile).
        data = await file.read(MAX_DOCUMENT_BYTES + 1)
        title = _placeholder_title(PurePath(file.filename or "").stem)
    elif file is None and jd_text is not None and jd_text.strip():
        data = jd_text.encode()
        title = _placeholder_title(next(line for line in jd_text.splitlines() if line.strip()))
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Send either a JD Document or its text"
        )
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The JD Document exceeds 10 MB")
    document_type = _document_type(data)
    if document_type is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "The JD Document must be PDF, DOCX or text"
        )

    # Pasted text is stored too, so the task reads every JD the same way.
    # ponytail: an object stays behind if the insert below fails; a sweep can collect those.
    key = f"t/{auth.tenant_id}/jd/{uuid.uuid4()}.{document_type}"
    await asyncio.to_thread(storage.put, key, data)
    job_id: uuid.UUID = (
        await auth.db.execute(
            # Placeholders for the NOT NULL columns, and the default weights of FR-A1.3.
            text(
                "INSERT INTO jobs (tenant_id, title, level, status, jd_document_key, parse_status,"
                "  weight_technical, weight_soft_skills, weight_experience, created_by)"
                " VALUES (:tenant_id, :title, 'MID', 'DRAFT', :key, 'PENDING',"
                "  0.55, 0.15, 0.30, :user_id) RETURNING id"
            ),
            {"tenant_id": auth.tenant_id, "title": title, "key": key, "user_id": auth.user_id},
        )
    ).scalar_one()
    # After commit (SAD §5.1): a task sent earlier could run before its Job is visible.
    event.listen(
        auth.db.sync_session,
        "after_commit",
        lambda _: parse.delay(str(auth.tenant_id), str(job_id), str(auth.user_id)),
        once=True,
    )
    return JobCreated(id=job_id)


_SELECT_JOB = text("""
    SELECT id, title, level, department, location, work_mode, status, parse_status, parse_error,
      criteria, criteria_verification AS verification, criteria_confirmed_at,
      (weight_technical * 100)::int AS technical,
      (weight_soft_skills * 100)::int AS soft_skills,
      (weight_experience * 100)::int AS experience
    FROM jobs WHERE id = :id
""")


async def _job(db: AsyncSession, job_id: uuid.UUID) -> Job:
    # Another Tenant's Job is hidden by RLS, so it is a 404 like a missing one (SAD §4.3).
    row = (await db.execute(_SELECT_JOB, {"id": job_id})).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    job = dict(row._mapping)
    weights = Weights(**{axis: job.pop(axis) for axis in Weights.model_fields})
    return Job(**job, weights=weights)


@router.get("/{job_id}")
async def get(job_id: uuid.UUID, auth: Recruiter) -> Job:
    return await _job(auth.db, job_id)


@router.put("/{job_id}/criteria")
async def confirm_criteria(job_id: uuid.UUID, body: CriteriaConfirmation, auth: Recruiter) -> Job:
    """Save the Recruiter's edits and confirm the criteria, which makes the Job scorable."""
    parse_status = await auth.db.scalar(
        text("SELECT parse_status FROM jobs WHERE id = :id FOR UPDATE"), {"id": job_id}
    )
    if parse_status is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if parse_status == "PENDING":
        # The parse would overwrite the confirmed criteria.
        raise HTTPException(status.HTTP_409_CONFLICT, "The JD Document is still being parsed")
    await auth.db.execute(
        text(
            "UPDATE jobs SET title = :title, level = :level, department = :department,"
            "  location = :location, work_mode = :work_mode, criteria = CAST(:criteria AS jsonb),"
            "  weight_technical = :technical, weight_soft_skills = :soft_skills,"
            "  weight_experience = :experience, criteria_confirmed_at = now(), updated_at = now(),"
            # The Recruiter has reviewed every field, so nothing stays flagged Needs review.
            "  criteria_verification = NULL"
            " WHERE id = :id"
        ),
        {
            "id": job_id,
            **body.model_dump(include={"title", "level", "department", "location", "work_mode"}),
            "criteria": body.criteria.model_dump_json(),
            **{axis: Decimal(percent) / 100 for axis, percent in body.weights},
        },
    )
    return await _job(auth.db, job_id)


@tenant_task(name="jobs.parse", queue="llm")
def parse(tenant_id: uuid.UUID, session: Session, job_id: str, user_id: str) -> None:
    """Parse the Job's JD Document into criteria for the Recruiter to confirm (FR-A1.1)."""
    # ponytail: the row lock and the transaction stay open through the LLM call (NFR-PERF-02);
    # split into claim / call / write transactions if connections run short.
    key = session.scalar(
        text(
            "SELECT jd_document_key FROM jobs WHERE id = :id AND parse_status = 'PENDING'"
            " FOR UPDATE"
        ),
        {"id": job_id},
    )
    if key is None:
        return  # redelivered (acks_late) after it finished
    model = os.environ["LLM_EXTRACTION_MODEL"]
    error = None
    if usage.price(model) is None:
        # Checked before the call: tokens the ledger cannot price must not be spent.
        log.error("no price for model %s in app.usage.PRICES", model)
        error = "UNPRICED_MODEL"
    else:
        try:
            parsed = parse_job(extract_text(storage.get(key)), llm_from_env(model))
            usage.record(
                session, uuid.UUID(user_id), "JOB_PARSE", parsed.usage, "job", uuid.UUID(job_id)
            )
        except ExtractionError as e:
            error = e.code
        except Exception:
            # The traceback may hold provider details: it goes to the log, the Job gets a code.
            log.exception("parsing the JD Document of job %s failed", job_id)
            error = "PARSE_FAILED"

    if error is None:
        data = parsed.data
        # A field the JD does not state keeps its placeholder, which nobody has verified.
        verification = parsed.verification | {
            field: "NEEDS_REVIEW" for field in ("title", "level") if data[field] is None
        }
        session.execute(
            text(
                "UPDATE jobs SET title = coalesce(:title, title), level = coalesce(:level, level),"
                "  department = :department, location = :location, work_mode = :work_mode,"
                "  criteria = CAST(:criteria AS jsonb),"
                "  criteria_verification = CAST(:verification AS jsonb),"
                "  parse_status = 'SUCCEEDED', updated_at = now()"
                " WHERE id = :id"
            ),
            {
                "id": job_id,
                **{f: data[f] for f in ("title", "level", "department", "location", "work_mode")},
                "criteria": json.dumps({f: data[f] for f in Criteria.model_fields}),
                "verification": json.dumps(verification),
            },
        )
    else:
        session.execute(
            text(
                "UPDATE jobs SET parse_status = 'FAILED', parse_error = :error, updated_at = now()"
                " WHERE id = :id"
            ),
            {"id": job_id, "error": error},
        )
    events.publish(
        session,
        uuid.UUID(user_id),
        "job.parsed",
        {"job_id": job_id, "parse_status": "FAILED" if error else "SUCCEEDED"},
    )
