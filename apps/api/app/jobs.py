"""Create a Job from a JD Document, parse it in the background, confirm its criteria (FR-A1.1).

The API inserts a DRAFT Job with placeholders and enqueues `jobs.parse` once that commits; the
task overwrites the placeholders with the parsed criteria and tells the Recruiter over SSE.
Scoring takes only Jobs whose criteria a Recruiter has confirmed (criteria_confirmed_at).

A Job then moves through the lifecycle of FR-A3.1 and is read by the Reviewers assigned to it.
The dependencies here decide who reads and who writes a Job for every router under /api/jobs.
"""

import asyncio
import json
import logging
import os
import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import PurePath
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app import events, outbox, storage, usage
from app.auth import Auth, Authenticated
from app.worker import tenant_task
from smart_ats_scoring.extraction import ExtractionError, document_type, extract_text
from smart_ats_scoring.llm import UnusableResponse, llm_from_env
from smart_ats_scoring.parsing import parse_job

log = logging.getLogger(__name__)

# The per-file limit of FR-A1.2, for JD Documents too.
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024

Level = Literal["INTERN", "JUNIOR", "MID", "SENIOR", "LEAD", "MANAGER"]
WorkMode = Literal["REMOTE", "HYBRID", "ONSITE"]
JobStatus = Literal["DRAFT", "PUBLISHED", "PAUSED", "CLOSED", "ARCHIVED"]
Action = Literal["publish", "pause", "resume", "close", "archive", "reopen"]

# The edges of FR-A3.1's diagram; any other (status, action) is refused.
TRANSITIONS: dict[tuple[JobStatus, Action], JobStatus] = {
    ("DRAFT", "publish"): "PUBLISHED",
    ("PUBLISHED", "pause"): "PAUSED",
    ("PAUSED", "resume"): "PUBLISHED",
    ("PUBLISHED", "close"): "CLOSED",
    ("PAUSED", "close"): "CLOSED",
    ("CLOSED", "archive"): "ARCHIVED",
    ("CLOSED", "reopen"): "PUBLISHED",
}

router = APIRouter(prefix="/api/jobs")


MANAGERS = ("COMPANY_ADMIN", "RECRUITER")


def _recruiter(auth: Authenticated) -> Auth:
    # SRS §2: creating Jobs and configuring criteria is for Company Admins and Recruiters.
    if auth.role not in MANAGERS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only Recruiters manage Jobs")
    return auth


Recruiter = Annotated[Auth, Depends(_recruiter)]


# The one definition of the Jobs a user may read, for one Job and for the list (SRS §2.1).
_VISIBLE = (
    "(:all OR EXISTS ("
    "  SELECT 1 FROM job_reviewers r WHERE r.job_id = j.id AND r.user_id = :user_id))"
)


def _visible_to(auth: Auth) -> dict[str, Any]:
    return {"all": auth.role in MANAGERS, "user_id": auth.user_id}


async def job_reader(job_id: uuid.UUID, auth: Authenticated) -> Auth:
    """Any Job of the Tenant for Company Admins and Recruiters, only an assigned one for a
    Reviewer (SRS §2.1). An unassigned Job is a 404 like another Tenant's (SAD §4.3)."""
    visible = await auth.db.scalar(
        text(f"SELECT 1 FROM jobs j WHERE id = :id AND {_VISIBLE}"),
        {"id": job_id, **_visible_to(auth)},
    )
    if visible is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return auth


async def _job_manager(job_id: uuid.UUID, auth: Recruiter) -> Auth:
    return await job_reader(job_id, auth)


# Every endpoint that reads a Job or its Applications takes one of these: JobReader where
# assigned Reviewers read too, JobManager where only Company Admins and Recruiters do.
JobReader = Annotated[Auth, Depends(job_reader)]
JobManager = Annotated[Auth, Depends(_job_manager)]


def _job_writer(lock: Literal["FOR KEY SHARE", "FOR UPDATE"]) -> Callable[..., Awaitable[Auth]]:
    async def dependency(job_id: uuid.UUID, auth: Recruiter) -> Auth:
        # Checked under the row lock, which waits for a transition that is archiving the Job.
        job_status = await auth.db.scalar(
            text(f"SELECT status FROM jobs WHERE id = :id {lock}"), {"id": job_id}
        )
        if job_status is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
        if job_status == "ARCHIVED":
            raise HTTPException(status.HTTP_409_CONFLICT, "An archived Job is read-only")
        return auth

    return dependency


# Every endpoint that writes to a Job or its Applications takes one of these, so none forgets
# that ARCHIVED is read-only (FR-A3.1). KEY SHARE does not wait for a JD parse, which holds
# NO KEY UPDATE through its LLM call; FOR UPDATE does, and makes writers take turns.
# job_writer is also called directly by a write that finds its Job through an Application.
job_writer = _job_writer("FOR KEY SHARE")
JobWriter = Annotated[Auth, Depends(job_writer)]
LockedJob = Annotated[Auth, Depends(_job_writer("FOR UPDATE"))]


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
    status: JobStatus
    parse_status: Literal["PENDING", "SUCCEEDED", "FAILED"]
    parse_error: str | None
    # As parsed until confirmed: the LLM's output is not held to the limits of Criteria.
    criteria: dict[str, Any] | None
    # VERIFIED or NEEDS_REVIEW per parsed field (FR-A1.1).
    verification: dict[str, Literal["VERIFIED", "NEEDS_REVIEW"]] | None
    weights: Weights
    criteria_confirmed_at: datetime | None
    apply_deadline: date | None
    published_at: datetime | None = None
    public_apply_enabled: bool
    public_slug: str | None


class JobCreated(BaseModel):
    id: uuid.UUID


class JobSummary(BaseModel):
    id: uuid.UUID
    title: str
    level: Level
    department: str | None
    location: str | None
    status: JobStatus
    application_count: int
    created_at: datetime


class Transition(BaseModel):
    action: Action


class MetadataChange(BaseModel):
    """The fields sent change; one left out stays."""

    title: str | None = Field(None, min_length=1, max_length=200)
    level: Level | None = None
    department: str | None = Field(None, max_length=200)
    location: str | None = Field(None, max_length=200)
    work_mode: WorkMode | None = None
    apply_deadline: date | None = None

    @model_validator(mode="after")
    def _title_and_level_are_not_null(self) -> Self:
        if any(
            getattr(self, field) is None for field in {"title", "level"} & self.model_fields_set
        ):
            raise ValueError("title and level cannot be null")
        return self


class CriteriaConfirmation(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    level: Level
    department: str | None = Field(max_length=200)
    location: str | None = Field(max_length=200)
    work_mode: WorkMode | None
    criteria: Criteria
    weights: Weights


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
    kind = document_type(data)
    if kind is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "The JD Document must be PDF, DOCX or text"
        )

    # Pasted text is stored too, so the task reads every JD the same way.
    # ponytail: an object stays behind if the insert below fails; a sweep can collect those.
    key = f"t/{auth.tenant_id}/jd/{uuid.uuid4()}.{kind}"
    await asyncio.to_thread(storage.put, key, data)
    job_id: uuid.UUID = (
        await auth.db.execute(
            # Placeholders for the NOT NULL columns, and the default weights of FR-A1.3.
            text(
                "INSERT INTO jobs (tenant_id, title, level, status, jd_document_key, parse_status,"
                "  parse_attempts, parse_enqueued_at,"
                "  weight_technical, weight_soft_skills, weight_experience, created_by)"
                " VALUES (:tenant_id, :title, 'MID', 'DRAFT', :key, 'PENDING', 1, now(),"
                "  0.55, 0.15, 0.30, :user_id) RETURNING id"
            ),
            {"tenant_id": auth.tenant_id, "title": title, "key": key, "user_id": auth.user_id},
        )
    ).scalar_one()
    outbox.enqueue_after_commit(
        auth.db, parse, (str(auth.tenant_id), str(job_id), str(auth.user_id))
    )
    return JobCreated(id=job_id)


@router.get("")
async def list_jobs(
    auth: Authenticated, job_status: Annotated[JobStatus | None, Query(alias="status")] = None
) -> list[JobSummary]:
    """The Jobs the user may read, as job_reader decides, newest first."""
    rows = await auth.db.execute(
        text(
            "SELECT j.id, j.title, j.level, j.department, j.location, j.status, j.created_at,"
            "  (SELECT count(*) FROM applications a WHERE a.job_id = j.id) AS application_count"
            " FROM jobs j"
            f" WHERE {_VISIBLE} AND (CAST(:status AS text) IS NULL OR j.status = :status)"
            " ORDER BY j.created_at DESC, j.id DESC"
        ),
        {"status": job_status, **_visible_to(auth)},
    )
    return [JobSummary.model_validate(row._mapping) for row in rows]


_SELECT_JOB = text("""
    SELECT id, title, level, department, location, work_mode, status, parse_status, parse_error,
      criteria, criteria_verification AS verification, criteria_confirmed_at, apply_deadline,
      published_at, public_apply_enabled, public_slug,
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
async def get(job_id: uuid.UUID, auth: JobReader) -> Job:
    return await _job(auth.db, job_id)


async def _refuse_while_parsing(db: AsyncSession, job_id: uuid.UUID) -> None:
    parse_status = await db.scalar(
        text("SELECT parse_status FROM jobs WHERE id = :id"), {"id": job_id}
    )
    if parse_status == "PENDING":
        # The parse would overwrite what is saved now.
        raise HTTPException(status.HTTP_409_CONFLICT, "The JD Document is still being parsed")


@router.put("/{job_id}/criteria")
async def confirm_criteria(job_id: uuid.UUID, body: CriteriaConfirmation, auth: LockedJob) -> Job:
    """Save the Recruiter's edits and confirm the criteria, which makes the Job scorable."""
    await _refuse_while_parsing(auth.db, job_id)
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


@router.post("/{job_id}/transitions")
async def transition(job_id: uuid.UUID, body: Transition, auth: LockedJob) -> Job:
    """Move the Job along one edge of FR-A3.1. LockedJob's row lock makes concurrent
    transitions take turns, so each checks its edge against what the one before it left."""
    current = await auth.db.scalar(text("SELECT status FROM jobs WHERE id = :id"), {"id": job_id})
    to = TRANSITIONS.get((current, body.action))
    if to is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A {current} Job cannot {body.action}")
    await auth.db.execute(
        text(
            "UPDATE jobs SET status = :to, "
            "published_at = CASE WHEN :to = 'PUBLISHED' AND published_at IS NULL THEN now() "
            "ELSE published_at END, updated_at = now() WHERE id = :id"
        ),
        {"id": job_id, "to": to},
    )
    return await _job(auth.db, job_id)


@router.patch("/{job_id}")
async def change_metadata(job_id: uuid.UUID, body: MetadataChange, auth: LockedJob) -> Job:
    """Edit the Job's metadata (FR-A3.1); its Reviewers have an endpoint of their own."""
    await _refuse_while_parsing(auth.db, job_id)
    changes = body.model_dump(exclude_unset=True)
    if changes:
        # The column names are MetadataChange's own fields, never the client's text.
        assignments = ", ".join(f"{column} = :{column}" for column in changes)
        await auth.db.execute(
            text(f"UPDATE jobs SET {assignments}, updated_at = now() WHERE id = :id"),
            {"id": job_id, **changes},
        )
    return await _job(auth.db, job_id)


class PublicApplyToggle(BaseModel):
    enabled: bool


@router.patch("/{job_id}/public-apply")
async def toggle_public_apply(job_id: uuid.UUID, body: PublicApplyToggle, auth: LockedJob) -> Job:
    """Enable or disable the Job's Public Apply Link (FR-A3.4).

    Enabling for the first time generates a random, unguessable public_slug.
    Company Admins and Recruiters only; Reviewers are rejected by LockedJob (403).
    """
    await _refuse_while_parsing(auth.db, job_id)
    if body.enabled:
        slug = secrets.token_urlsafe(16)
        await auth.db.execute(
            text(
                "UPDATE jobs SET public_apply_enabled = true,"
                "  public_slug = coalesce(public_slug, :slug),"
                "  updated_at = now()"
                " WHERE id = :id"
            ),
            {"id": job_id, "slug": slug},
        )
    else:
        await auth.db.execute(
            text("UPDATE jobs SET public_apply_enabled = false, updated_at = now() WHERE id = :id"),
            {"id": job_id},
        )
    return await _job(auth.db, job_id)


class Reviewer(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    assigned: bool


class ReviewerAssignment(BaseModel):
    user_ids: list[uuid.UUID]


async def _reviewers(db: AsyncSession, job_id: uuid.UUID) -> list[Reviewer]:
    rows = await db.execute(
        text(
            "SELECT u.id, u.full_name, u.email, r.user_id IS NOT NULL AS assigned FROM users u"
            " LEFT JOIN job_reviewers r ON r.user_id = u.id AND r.job_id = :job_id"
            " WHERE u.role = 'REVIEWER' AND u.is_active ORDER BY u.full_name, u.id"
        ),
        {"job_id": job_id},
    )
    return [Reviewer.model_validate(row._mapping) for row in rows]


@router.get("/{job_id}/reviewers")
async def list_reviewers(job_id: uuid.UUID, auth: JobManager) -> list[Reviewer]:
    """The Workspace's active Reviewers, each marked whether the Job is assigned to them."""
    return await _reviewers(auth.db, job_id)


@router.put("/{job_id}/reviewers")
async def assign_reviewers(
    job_id: uuid.UUID, body: ReviewerAssignment, auth: LockedJob
) -> list[Reviewer]:
    """Replace the Job's Reviewer Assignments with user_ids; the lock makes two replacements
    take turns, so neither keeps what the other removed."""
    ids = list(set(body.user_ids))
    reviewers = set(
        await auth.db.scalars(
            text(
                "SELECT id FROM users"
                " WHERE id = ANY(CAST(:ids AS uuid[])) AND role = 'REVIEWER' AND is_active"
            ),
            {"ids": ids},
        )
    )
    if invalid := [str(id) for id in ids if id not in reviewers]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "message": "Only active Reviewers of the Workspace can be assigned",
                "user_ids": invalid,
            },
        )
    await auth.db.execute(
        text(
            "DELETE FROM job_reviewers"
            " WHERE job_id = :job_id AND user_id <> ALL(CAST(:ids AS uuid[]))"
        ),
        {"job_id": job_id, "ids": ids},
    )
    # One already assigned keeps who assigned them and when.
    await auth.db.execute(
        text(
            "INSERT INTO job_reviewers (tenant_id, job_id, user_id, assigned_by)"
            " SELECT :tenant_id, :job_id, unnest(CAST(:ids AS uuid[])), :user_id"
            " ON CONFLICT DO NOTHING"
        ),
        {"tenant_id": auth.tenant_id, "job_id": job_id, "ids": ids, "user_id": auth.user_id},
    )
    return await _reviewers(auth.db, job_id)


@tenant_task(name="jobs.parse", queue="llm")
def parse(tenant_id: uuid.UUID, session: Session, job_id: str, user_id: str) -> None:
    """Parse the Job's JD Document into criteria for the Recruiter to confirm (FR-A1.1)."""
    # ponytail: the row lock and the transaction stay open through the LLM call (NFR-PERF-02);
    # split into claim / call / write transactions if connections run short. A worker that dies
    # after the call rolls back its AI Usage Entry too, so the redelivered call bills uncounted.
    # NO KEY UPDATE: rows inserted with a foreign key to the Job (an upload into it) take
    # KEY SHARE on it, which FOR UPDATE would make wait for the whole LLM call.
    key = session.scalar(
        text(
            "SELECT jd_document_key FROM jobs WHERE id = :id AND parse_status = 'PENDING'"
            " FOR NO KEY UPDATE"
        ),
        {"id": job_id},
    )
    if key is None:
        return  # redelivered (acks_late) after it finished
    model = os.environ["LLM_EXTRACTION_MODEL"]
    error = None
    if not usage.priced(model):
        error = "UNPRICED_MODEL"
    else:
        try:
            parsed = parse_job(extract_text(storage.get(key)), llm_from_env(model))
            usage.record(
                session, uuid.UUID(user_id), "JOB_PARSE", parsed.usage, "job", uuid.UUID(job_id)
            )
        except ExtractionError as e:
            error = e.code
        except Exception as e:
            # The traceback may hold provider details: it goes to the log, the Job gets a code.
            log.exception("parsing the JD Document of job %s failed", job_id)
            error = "PARSE_FAILED"
            if isinstance(e, UnusableResponse):
                # Billed all the same (FR-C1.4).
                usage.record(
                    session, uuid.UUID(user_id), "JOB_PARSE", e.usage, "job", uuid.UUID(job_id)
                )

    if error is not None:
        fail_parse(session, uuid.UUID(job_id), uuid.UUID(user_id), error)
        return
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
    events.publish(
        session, uuid.UUID(user_id), "job.parsed", {"job_id": job_id, "parse_status": "SUCCEEDED"}
    )


def fail_parse(session: Session, job_id: uuid.UUID, user_id: uuid.UUID, error: str) -> None:
    """End the Job's parse as FAILED with error, and tell the Recruiter."""
    session.execute(
        text(
            "UPDATE jobs SET parse_status = 'FAILED', parse_error = :error, updated_at = now()"
            " WHERE id = :id"
        ),
        {"id": job_id, "error": error},
    )
    events.publish(
        session, user_id, "job.parsed", {"job_id": str(job_id), "parse_status": "FAILED"}
    )
