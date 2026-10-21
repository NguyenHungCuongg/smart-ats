"""Move Applications through the Stages of FR-A3.2 and read each one's Stage history.

Every move names the version of each Application the client saw: one that changed since is a
409 and the board reloads (optimistic locking, SAD §6). A move of several Applications runs in
the request's one transaction, so it applies to all of them or to none, and appends one
application_stage_history row for each.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth import Auth, Authenticated
from app.jobs import JobWriter, Recruiter, job_reader, job_writer

Stage = Literal["APPLIED", "SCREENING", "SHORTLISTED", "INTERVIEW", "OFFER", "HIRED", "REJECTED"]
# HIRED and REJECTED end the pipeline; between these an Application moves either way.
ACTIVE: tuple[Stage, ...] = ("APPLIED", "SCREENING", "SHORTLISTED", "INTERVIEW", "OFFER")

Text = Annotated[str, Field(max_length=2000)]

router = APIRouter(prefix="/api")


class Move(BaseModel):
    to_stage: Stage
    version: int
    note: Text | None = None
    rejected_reason: Text | None = None


class Seen(BaseModel):
    """An Application as the client saw it."""

    id: uuid.UUID
    version: int


class BulkMove(BaseModel):
    applications: list[Seen] = Field(min_length=1, max_length=1000)
    to_stage: Stage


class Moved(BaseModel):
    id: uuid.UUID
    stage: Stage
    version: int


class StageChange(BaseModel):
    from_stage: Stage | None
    to_stage: Stage
    # NULL only for an Application created through Public Apply (ERD §3).
    changed_by: uuid.UUID | None
    note: str | None
    changed_at: datetime


def _refusal(from_stage: Stage, to_stage: Stage, note: str | None) -> HTTPException | None:
    if from_stage == "HIRED":
        return HTTPException(status.HTTP_409_CONFLICT, "A HIRED Application cannot move")
    if from_stage == to_stage:
        return HTTPException(status.HTTP_409_CONFLICT, f"The Application is already {to_stage}")
    if from_stage == "REJECTED":
        if to_stage not in ACTIVE:
            return HTTPException(
                status.HTTP_409_CONFLICT, "A REJECTED Application reopens to an active Stage"
            )
        if not (note or "").strip():
            return HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Reopening an Application needs a reason"
            )
    return None


async def _move(
    auth: Auth,
    job_id: uuid.UUID,
    seen: list[Seen],
    to_stage: Stage,
    note: str | None = None,
    rejected_reason: str | None = None,
) -> list[Moved]:
    versions = {s.id: s.version for s in seen}
    # The row locks make a concurrent move of the same Application wait, then see its version.
    rows = (
        await auth.db.execute(
            text(
                "SELECT id, stage, version FROM applications"
                " WHERE id = ANY(CAST(:ids AS uuid[])) AND job_id = :job_id"
                " ORDER BY id FOR UPDATE"
            ),
            {"ids": list(versions), "job_id": job_id},
        )
    ).all()
    if len(rows) != len(versions):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    if any(row.version != versions[row.id] for row in rows):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An Application changed since it was loaded; reload"
        )
    for row in rows:
        if refusal := _refusal(row.stage, to_stage, note):
            raise refusal
    moved = await auth.db.execute(
        text(
            "WITH moved AS ("
            "  UPDATE applications SET stage = :to_stage, version = version + 1,"
            "    updated_at = now(),"
            # Only a REJECTED Application has a reason; a reopened one drops it.
            "    rejected_reason = CASE WHEN :to_stage = 'REJECTED'"
            "      THEN CAST(:rejected_reason AS text) END"
            "  WHERE id = ANY(CAST(:ids AS uuid[]))"
            "  RETURNING id, old.stage AS from_stage, stage, version),"
            " logged AS ("
            "  INSERT INTO application_stage_history (tenant_id, application_id, from_stage,"
            "    to_stage, changed_by, note)"
            "  SELECT :tenant_id, id, from_stage, stage, :user_id, :note FROM moved)"
            " SELECT id, stage, version FROM moved ORDER BY id"
        ),
        {
            "ids": list(versions),
            "to_stage": to_stage,
            "rejected_reason": rejected_reason,
            "tenant_id": auth.tenant_id,
            "user_id": auth.user_id,
            "note": note,
        },
    )
    return [Moved.model_validate(row._mapping) for row in moved]


async def _job_of(auth: Auth, application_id: uuid.UUID) -> uuid.UUID:
    # Another Tenant's Application is hidden by RLS, so it is a 404 like a missing one.
    job_id: uuid.UUID | None = await auth.db.scalar(
        text("SELECT job_id FROM applications WHERE id = :id"), {"id": application_id}
    )
    if job_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return job_id


@router.patch("/applications/{application_id}/stage")
async def move(application_id: uuid.UUID, body: Move, auth: Recruiter) -> Moved:
    """Move one Application, from a drag on the Kanban Board or its Stage menu."""
    job_id = await _job_of(auth, application_id)
    await job_writer(job_id, auth)
    [moved] = await _move(
        auth,
        job_id,
        [Seen(id=application_id, version=body.version)],
        body.to_stage,
        body.note,
        body.rejected_reason,
    )
    return moved


@router.post("/jobs/{job_id}/applications/stage")
async def move_many(job_id: uuid.UUID, body: BulkMove, auth: JobWriter) -> list[Moved]:
    """Move the Applications selected on the Kanban Board, all or none."""
    return await _move(auth, job_id, body.applications, body.to_stage)


@router.get("/applications/{application_id}/stage-history")
async def history(application_id: uuid.UUID, auth: Authenticated) -> list[StageChange]:
    """Oldest first, for whoever may read the Application's Job."""
    await job_reader(await _job_of(auth, application_id), auth)
    rows = await auth.db.execute(
        text(
            "SELECT from_stage, to_stage, changed_by, note, changed_at"
            " FROM application_stage_history WHERE application_id = :id"
            " ORDER BY changed_at, id"
        ),
        {"id": application_id},
    )
    return [StageChange.model_validate(row._mapping) for row in rows]
