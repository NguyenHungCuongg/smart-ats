"""Score a Job's Applications in a Scoring Run and read their Fit-Gap Reports (FR-A1.3).

The API freezes the Job into a run with one PENDING score_results row per Application, then
enqueues `scoring_runs.score_application` for each once that commits (SAD §5.2). Each task
scores its row, finishes the run when no row is left PENDING and tells the Recruiter over SSE.
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app import events, storage, usage
from app.jobs import Recruiter, Weights
from app.worker import tenant_task
from smart_ats_scoring.extraction import ExtractionError, extract_text
from smart_ats_scoring.llm import llm_from_env
from smart_ats_scoring.scoring import PROMPT_VERSION, RUBRIC_VERSION, score
from smart_ats_scoring.scoring import Weights as ScoringWeights

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs")

# ponytail: a run stuck RUNNING (enqueue lost, task rolled back) stops counting after 30
# minutes, so it cannot lock its Job forever; replace with beat's sweep of stuck PENDING rows
# (SAD §6). The one definition of a running run: POST and GET latest both use it.
_RUNNING = "(r.status = 'RUNNING' AND r.created_at > now() - interval '30 minutes')"


class RunCreated(BaseModel):
    run_id: uuid.UUID


class ScoreResult(BaseModel):
    application_id: uuid.UUID
    full_name: str | None
    status: Literal["PENDING", "SCORED", "FAILED"]
    # The CV scored, and the Application's CV now: they differ once a new CV replaced it.
    cv_document_id: uuid.UUID
    current_cv_document_id: uuid.UUID
    technical_score: float | None
    soft_skills_score: float | None
    experience_score: float | None
    total_score: float | None
    must_have_coverage: float | None
    must_have_detail: dict[str, list[str]] | None
    rubric_grades: dict[str, Any] | None
    fit_gap_report: dict[str, Any] | None
    grounding_rate: float | None
    error_code: str | None


class ScoringRun(BaseModel):
    id: uuid.UUID
    status: Literal["RUNNING", "COMPLETED", "PARTIAL"]
    # Whether the run still blocks a new one, by the rule POST applies.
    running: bool
    weights: Weights
    model: str
    prompt_version: str
    rubric_version: str
    created_at: datetime
    completed_at: datetime | None
    results: list[ScoreResult]


@router.post("/{job_id}/scoring-runs", status_code=status.HTTP_202_ACCEPTED)
async def create(job_id: uuid.UUID, auth: Recruiter) -> RunCreated:
    """Score every Application the Job has now; the scoring runs on queue llm."""
    # The row lock makes concurrent requests take turns, so only one passes the running check.
    # Not a partial unique index: whether a run counts as running depends on the time.
    confirmed = await auth.db.scalar(
        text("SELECT criteria_confirmed_at IS NOT NULL FROM jobs WHERE id = :id FOR UPDATE"),
        {"id": job_id},
    )
    if confirmed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    # A statement of its own, so its snapshot is taken after the lock and sees the run that
    # the request it waited for committed.
    checks = (
        await auth.db.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM applications WHERE job_id = :id) AS has_applications,"
                f"  EXISTS (SELECT 1 FROM scoring_runs r WHERE job_id = :id AND {_RUNNING})"
                "    AS running"
            ),
            {"id": job_id},
        )
    ).one()
    if not confirmed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Confirm the Job's criteria first")
    if not checks.has_applications:
        raise HTTPException(status.HTTP_409_CONFLICT, "The Job has no Applications to score")
    if checks.running:
        raise HTTPException(status.HTTP_409_CONFLICT, "The Job is already being scored")
    model = os.environ["LLM_REASONING_MODEL"]
    if usage.price(model) is None:
        # Tokens the ledger cannot price must not be spent: a server configuration error.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The AI model has no price in the ledger"
        )

    run_id: uuid.UUID = (
        await auth.db.execute(
            text(
                "INSERT INTO scoring_runs (tenant_id, job_id, trigger_mode, weights,"
                "  criteria_snapshot, model, prompt_version, rubric_version, status, created_by)"
                " SELECT tenant_id, id, 'MANUAL',"
                "  jsonb_build_object('technical', weight_technical,"
                "    'soft_skills', weight_soft_skills, 'experience', weight_experience),"
                # Title and level too: the Experience rubric weighs the level.
                "  criteria || jsonb_build_object('title', title, 'level', level),"
                "  :model, :prompt_version, :rubric_version, 'RUNNING', :user_id"
                " FROM jobs WHERE id = :id RETURNING id"
            ),
            {
                "id": job_id,
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "rubric_version": RUBRIC_VERSION,
                "user_id": auth.user_id,
            },
        )
    ).scalar_one()
    application_ids = (
        await auth.db.scalars(
            text(
                "INSERT INTO score_results (tenant_id, scoring_run_id, application_id,"
                "  cv_document_id, status)"
                " SELECT tenant_id, :run_id, id, cv_document_id, 'PENDING'"
                " FROM applications WHERE job_id = :job_id RETURNING application_id"
            ),
            {"run_id": run_id, "job_id": job_id},
        )
    ).all()

    def enqueue(_: Any) -> None:
        for application_id in application_ids:
            score_application.delay(str(auth.tenant_id), str(run_id), str(application_id))

    # After commit (SAD §5.1): a task sent earlier could run before its row is visible.
    event.listen(auth.db.sync_session, "after_commit", enqueue, once=True)
    return RunCreated(run_id=run_id)


@router.get("/{job_id}/scoring-runs/latest")
async def latest(job_id: uuid.UUID, auth: Recruiter) -> ScoringRun:
    """The Job's newest run with its results; 404 for a Job never scored."""
    run = (
        await auth.db.execute(
            text(
                "SELECT r.id, r.status, r.weights, r.model, r.prompt_version, r.rubric_version,"
                f"  r.created_at, r.completed_at, {_RUNNING} AS running"
                " FROM scoring_runs r WHERE r.job_id = :job_id"
                " ORDER BY r.created_at DESC, r.id DESC LIMIT 1"
            ),
            {"job_id": job_id},
        )
    ).one_or_none()
    # Another Tenant's Job is hidden by RLS, so it is a 404 like a missing one (SAD §4.3).
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The Job has no Scoring Run")
    results = await auth.db.execute(
        text(
            "SELECT s.application_id, c.full_name, s.status, s.cv_document_id,"
            "  a.cv_document_id AS current_cv_document_id, s.technical_score,"
            "  s.soft_skills_score, s.experience_score, s.total_score, s.must_have_coverage,"
            "  s.must_have_detail, s.rubric_grades, s.fit_gap_report, s.grounding_rate,"
            "  s.error_code"
            " FROM score_results s JOIN applications a ON a.id = s.application_id"
            "  JOIN candidates c ON c.id = a.candidate_id"
            " WHERE s.scoring_run_id = :run_id ORDER BY a.created_at DESC"
        ),
        {"run_id": run.id},
    )
    fields = dict(run._mapping)
    # Stored as fractions, sent in whole percent like a Job's weights.
    weights = Weights(**{axis: round(share * 100) for axis, share in fields.pop("weights").items()})
    return ScoringRun(
        **fields, weights=weights, results=[ScoreResult(**row._mapping) for row in results]
    )


@tenant_task(name="scoring_runs.score_application", queue="llm")
def score_application(
    tenant_id: uuid.UUID, session: Session, run_id: str, application_id: str
) -> None:
    """Score one Application on the CV and Job frozen into its run (FR-A1.3, SAD §5.2)."""
    # ponytail: the row lock and the transaction stay open through the LLM call, as in
    # jobs.parse; split into claim / call / write transactions if connections run short.
    row = session.execute(
        text(
            "SELECT s.id, r.job_id, r.criteria_snapshot, r.weights, r.model, r.created_by,"
            "  d.parsed_profile, d.storage_key AS cv_key, j.jd_document_key AS jd_key"
            " FROM score_results s JOIN scoring_runs r ON r.id = s.scoring_run_id"
            "  JOIN cv_documents d ON d.id = s.cv_document_id JOIN jobs j ON j.id = r.job_id"
            " WHERE s.scoring_run_id = :run_id AND s.application_id = :application_id"
            "  AND s.status = 'PENDING' FOR UPDATE OF s"
        ),
        {"run_id": run_id, "application_id": application_id},
    ).one_or_none()
    if row is None:
        return  # redelivered (acks_late) after it finished
    error = None
    try:
        # The source texts are not stored: extract_text is deterministic and calls no LLM,
        # so reading the files again gives the texts the parses saw.
        cv_text = extract_text(storage.get(row.cv_key))
        jd_text = extract_text(storage.get(row.jd_key)) if row.jd_key else ""
    except ExtractionError as e:
        error = e.code
    except Exception:
        log.exception("reading the documents of score result %s failed", row.id)
        error = "READ_FAILED"
    if error is None:
        try:
            result = score(
                row.criteria_snapshot,
                row.parsed_profile,
                cv_text,
                jd_text,
                llm_from_env(row.model),
                ScoringWeights(**row.weights),
            )
        except Exception:
            # The traceback may hold provider details: it goes to the log, the row gets a code.
            log.exception("scoring score result %s failed", row.id)
            error = "SCORING_FAILED"

    if error is None:
        usage.record(session, row.created_by, "SCORING", result.usage, "score_result", row.id)
        coverage = result.coverage
        session.execute(
            text(
                "UPDATE score_results SET status = 'SCORED', technical_score = :technical,"
                "  soft_skills_score = :soft_skills, experience_score = :experience,"
                "  total_score = :total, must_have_coverage = :coverage,"
                "  must_have_detail = CAST(:detail AS jsonb),"
                "  rubric_grades = CAST(:rubric AS jsonb),"
                "  fit_gap_report = CAST(:report AS jsonb), grounding_rate = :grounding"
                " WHERE id = :id"
            ),
            {
                "id": row.id,
                "technical": result.technical,
                "soft_skills": result.soft_skills,
                "experience": result.experience,
                "total": result.total,
                "coverage": coverage.ratio,
                "detail": json.dumps({"matched": coverage.matched, "missing": coverage.missing}),
                "rubric": json.dumps(result.rubric),
                "report": json.dumps(result.fit_gap_report),
                "grounding": result.grounding_rate,
            },
        )
    else:
        session.execute(
            text("UPDATE score_results SET status = 'FAILED', error_code = :code WHERE id = :id"),
            {"id": row.id, "code": error},
        )
    # Tasks finishing together each lock the run first, so the last one to commit sees every
    # other row done and finishes it (counts come from the rows, SAD §5.1).
    session.execute(text("SELECT 1 FROM scoring_runs WHERE id = :id FOR UPDATE"), {"id": run_id})
    session.execute(
        text(
            "UPDATE scoring_runs SET completed_at = now(), status = CASE WHEN EXISTS ("
            "  SELECT 1 FROM score_results WHERE scoring_run_id = :id AND status = 'FAILED')"
            "  THEN 'PARTIAL' ELSE 'COMPLETED' END"
            " WHERE id = :id AND NOT EXISTS ("
            "  SELECT 1 FROM score_results WHERE scoring_run_id = :id AND status = 'PENDING')"
        ),
        {"id": run_id},
    )
    events.publish(
        session,
        row.created_by,
        "scoring.result",
        {
            "job_id": str(row.job_id),
            "run_id": run_id,
            "application_id": application_id,
            "status": "FAILED" if error else "SCORED",
        },
    )
