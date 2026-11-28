"""Workspace Dashboard summary for daily recruiting operations (SRS §2.1, ADR-0001).

Aggregates Job status counts, Pipeline Stage distribution, actionable backlog items, newest Jobs,
and recent Audit Log entries within the signed-in user's tenant and RBAC scope.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth import Authenticated
from app.jobs import _VISIBLE, MANAGERS, JobStatus, Level, _visible_to
from app.pipeline import Stage

router = APIRouter(prefix="/api")

JOB_STATUSES: tuple[JobStatus, ...] = ("DRAFT", "PUBLISHED", "PAUSED", "CLOSED", "ARCHIVED")
STAGES: tuple[Stage, ...] = (
    "APPLIED",
    "SCREENING",
    "SHORTLISTED",
    "INTERVIEW",
    "OFFER",
    "HIRED",
    "REJECTED",
)

_UNSCORED_CONDITION = """
    j.criteria_confirmed_at IS NOT NULL
    AND j.status <> 'ARCHIVED'
    AND EXISTS (
      SELECT 1 FROM applications a
      LEFT JOIN LATERAL (
        SELECT r.id FROM scoring_runs r
        WHERE r.job_id = j.id
        ORDER BY r.created_at DESC, r.id DESC
        LIMIT 1
      ) lr ON true
      LEFT JOIN score_results sr
        ON sr.scoring_run_id = lr.id
       AND sr.application_id = a.id
       AND sr.status = 'SCORED'
       AND sr.cv_document_id = a.cv_document_id
      WHERE a.job_id = j.id AND sr.id IS NULL
    )
"""


class ActionJob(BaseModel):
    id: uuid.UUID
    title: str
    level: Level
    status: JobStatus
    application_count: int


class ActionJobGroup(BaseModel):
    count: int
    items: list[ActionJob]


class ActionItems(BaseModel):
    pending_criteria_jobs: ActionJobGroup
    failed_parse_jobs: ActionJobGroup
    unscored_jobs: ActionJobGroup
    new_applications_count: int


class RecentJob(BaseModel):
    id: uuid.UUID
    title: str
    level: Level
    department: str | None
    location: str | None
    status: JobStatus
    parse_status: Literal["PENDING", "SUCCEEDED", "FAILED"]
    criteria_confirmed: bool
    application_count: int
    created_at: datetime


class DashboardSummary(BaseModel):
    total_jobs: int
    jobs_by_status: dict[JobStatus, int]
    total_applications: int
    pipeline_by_stage: dict[Stage, int]
    action_items: ActionItems
    recent_jobs: list[RecentJob]
    recent_activity: list[audit.ActivityEntry]


async def _action_group(db: AsyncSession, condition: str) -> ActionJobGroup:
    rows = (
        await db.execute(
            text(
                "SELECT j.id, j.title, j.level, j.status,"
                "  (SELECT count(*) FROM applications a WHERE a.job_id = j.id)"
                "    AS application_count,"
                "  count(*) OVER () AS total_count"
                " FROM jobs j"
                f" WHERE {condition}"
                " ORDER BY j.created_at DESC, j.id DESC"
                " LIMIT 5"
            )
        )
    ).all()
    if not rows:
        return ActionJobGroup(count=0, items=[])
    total = int(rows[0].total_count)
    items = [
        ActionJob(
            id=row.id,
            title=row.title,
            level=row.level,
            status=row.status,
            application_count=int(row.application_count),
        )
        for row in rows
    ]
    return ActionJobGroup(count=total, items=items)


async def _recent_activity(
    db: AsyncSession, role: str, user_id: uuid.UUID
) -> list[audit.ActivityEntry]:
    params: dict[str, Any] = {}
    if role == "COMPANY_ADMIN":
        where_scope = "true"
    elif role == "RECRUITER":
        where_scope = "l.entity_type IN ('job', 'application', 'channel_post')"
    else:
        where_scope = (
            "("
            "  (l.entity_type = 'job' AND EXISTS ("
            "    SELECT 1 FROM job_reviewers r"
            "    WHERE r.job_id = l.entity_id AND r.user_id = :user_id"
            "  ))"
            "  OR"
            "  (l.entity_type = 'application' AND EXISTS ("
            "    SELECT 1 FROM applications a"
            "    JOIN job_reviewers r ON r.job_id = a.job_id"
            "    WHERE a.id = l.entity_id AND r.user_id = :user_id"
            "  ))"
            ")"
        )
        params["user_id"] = user_id

    rows = (
        await db.execute(
            text(
                "SELECT l.id, l.action, l.actor_type, l.actor_user_id,"
                "  u.full_name AS actor_full_name, l.before, l.after, l.created_at"
                " FROM audit_logs l"
                " LEFT JOIN users u ON u.tenant_id = l.tenant_id AND u.id = l.actor_user_id"
                f" WHERE {where_scope}"
                " ORDER BY l.created_at DESC, l.id DESC"
                " LIMIT 10"
            ),
            params,
        )
    ).all()
    return [
        audit.ActivityEntry(
            id=row.id,
            action=row.action,
            actor_type=row.actor_type,
            actor=(
                audit.Actor(id=row.actor_user_id, full_name=row.actor_full_name)
                if row.actor_user_id is not None and row.actor_full_name is not None
                else None
            ),
            before=row.before,
            after=row.after,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/dashboard")
async def get_dashboard(auth: Authenticated) -> DashboardSummary:
    """Aggregate Workspace overview metrics, action items, recent Jobs, and Activity."""
    vis = _visible_to(auth)

    status_rows = (
        await auth.db.execute(
            text(
                f"SELECT j.status, count(*) AS cnt FROM jobs j WHERE {_VISIBLE} GROUP BY j.status"
            ),
            vis,
        )
    ).all()
    jobs_by_status: dict[JobStatus, int] = dict.fromkeys(JOB_STATUSES, 0)
    for row in status_rows:
        jobs_by_status[row.status] = int(row.cnt)
    total_jobs = sum(jobs_by_status.values())

    stage_rows = (
        await auth.db.execute(
            text(
                "SELECT a.stage, count(*) AS cnt"
                " FROM applications a"
                " JOIN jobs j ON j.id = a.job_id"
                f" WHERE {_VISIBLE}"
                " GROUP BY a.stage"
            ),
            vis,
        )
    ).all()
    pipeline_by_stage: dict[Stage, int] = dict.fromkeys(STAGES, 0)
    for row in stage_rows:
        pipeline_by_stage[row.stage] = int(row.cnt)
    total_applications = sum(pipeline_by_stage.values())

    if auth.role in MANAGERS:
        pending_criteria = await _action_group(
            auth.db,
            "j.status = 'DRAFT' AND j.parse_status = 'SUCCEEDED'"
            " AND j.criteria_confirmed_at IS NULL",
        )
        failed_parse = await _action_group(
            auth.db,
            "j.parse_status = 'FAILED' AND j.status <> 'ARCHIVED'",
        )
        unscored = await _action_group(auth.db, _UNSCORED_CONDITION)
    else:
        empty_group = ActionJobGroup(count=0, items=[])
        pending_criteria = empty_group
        failed_parse = empty_group
        unscored = empty_group

    recent_job_rows = (
        await auth.db.execute(
            text(
                "SELECT j.id, j.title, j.level, j.department, j.location, j.status,"
                "  j.parse_status, (j.criteria_confirmed_at IS NOT NULL) AS criteria_confirmed,"
                "  (SELECT count(*) FROM applications a WHERE a.job_id = j.id)"
                "    AS application_count,"
                "  j.created_at"
                " FROM jobs j"
                f" WHERE {_VISIBLE}"
                " ORDER BY j.created_at DESC, j.id DESC"
                " LIMIT 5"
            ),
            vis,
        )
    ).all()
    recent_jobs = [RecentJob.model_validate(row._mapping) for row in recent_job_rows]
    recent_activity = await _recent_activity(auth.db, auth.role, auth.user_id)

    return DashboardSummary(
        total_jobs=total_jobs,
        jobs_by_status=jobs_by_status,
        total_applications=total_applications,
        pipeline_by_stage=pipeline_by_stage,
        action_items=ActionItems(
            pending_criteria_jobs=pending_criteria,
            failed_parse_jobs=failed_parse,
            unscored_jobs=unscored,
            new_applications_count=pipeline_by_stage["APPLIED"],
        ),
        recent_jobs=recent_jobs,
        recent_activity=recent_activity,
    )
