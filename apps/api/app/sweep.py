"""beat's sweep of stuck outbox-style rows (SAD §6).

A PENDING row last enqueued over STUCK_AFTER ago that no task holds locked has lost its task:
the enqueue after commit never reached the broker, or the task rolled back. The sweep enqueues
it again, up to MAX_ATTEMPTS enqueues in all, then fails it with error code STUCK. A task that
is running holds its row locked however long it runs, so the sweep skips the row.
"""

import uuid
from collections.abc import Callable
from datetime import timedelta
from functools import partial
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app import jobs, scoring_runs, uploads
from app.db import sync_engine
from app.worker import celery_app, tenant_task

# SAD §6.
STUCK_AFTER = timedelta(minutes=10)
MAX_ATTEMPTS = 4  # the first enqueue and three more

# ponytail: a row merely waiting in a long queue looks stuck too; it is enqueued again (the task
# is idempotent) and fails as STUCK after 40 minutes. Raise STUCK_AFTER if queues get that long.


@celery_app.task(name="sweep.stuck_rows")
def stuck_rows() -> None:
    """Sweep each ACTIVE Tenant in a task of its own, in that Tenant's context (ADR-0002)."""
    with sync_engine().connect() as conn:
        tenant_ids = conn.scalars(text("SELECT active_tenant_ids()")).all()
    for tenant_id in tenant_ids:
        tenant.delay(str(tenant_id))


@tenant_task(name="sweep.tenant")
def tenant(tenant_id: uuid.UUID, session: Session) -> None:
    """Enqueue again or fail the Tenant's stuck Job parses, upload items and score results."""
    tid = str(tenant_id)
    sends: list[Callable[[], Any]] = []

    for job in _stuck(
        session,
        "jobs",
        "parse_attempts",
        "parse_enqueued_at",
        "SELECT id, created_by, parse_attempts AS attempts FROM jobs"
        " WHERE parse_status = 'PENDING' AND parse_enqueued_at < now() - :after"
        " FOR NO KEY UPDATE SKIP LOCKED",
    ):
        if job.attempts >= MAX_ATTEMPTS:
            jobs.fail_parse(session, job.id, job.created_by, "STUCK")
        else:
            sends.append(partial(jobs.parse.delay, tid, str(job.id), str(job.created_by)))

    for item in _stuck(
        session,
        "upload_batch_items",
        "attempts",
        "enqueued_at",
        "SELECT i.id, i.batch_id, b.job_id, b.created_by, i.attempts"
        " FROM upload_batch_items i JOIN upload_batches b ON b.id = i.batch_id"
        " WHERE i.status = 'PENDING' AND i.enqueued_at < now() - :after"
        " FOR NO KEY UPDATE OF i SKIP LOCKED",
    ):
        if item.attempts >= MAX_ATTEMPTS:
            uploads.finish_item(
                session, item, "FAILED", error=("STUCK", "the CV was never processed")
            )
        else:
            sends.append(partial(uploads.parse_cv.delay, tid, str(item.id)))

    for result in _stuck(
        session,
        "score_results",
        "attempts",
        "enqueued_at",
        "SELECT s.id, s.scoring_run_id AS run_id, s.application_id, r.job_id, r.created_by,"
        "  s.attempts"
        " FROM score_results s JOIN scoring_runs r ON r.id = s.scoring_run_id"
        " WHERE s.status = 'PENDING' AND s.enqueued_at < now() - :after"
        " FOR NO KEY UPDATE OF s SKIP LOCKED",
    ):
        args = (str(result.run_id), str(result.application_id))
        if result.attempts >= MAX_ATTEMPTS:
            scoring_runs.fail_result(
                session, result.id, result.created_by, result.job_id, *args, "STUCK"
            )
        else:
            sends.append(partial(scoring_runs.score_application.delay, tid, *args))

    # After commit (SAD §5.1), as the API enqueues.
    event.listen(session, "after_commit", lambda _: [send() for send in sends], once=True)


def _stuck(session: Session, table: str, attempts: str, enqueued_at: str, select: str) -> Any:
    """The rows select finds, locked; those to enqueue again are counted as enqueued now."""
    rows = session.execute(text(select), {"after": STUCK_AFTER}).all()
    again = [row.id for row in rows if row.attempts < MAX_ATTEMPTS]
    session.execute(
        text(
            f"UPDATE {table} SET {attempts} = {attempts} + 1, {enqueued_at} = now()"
            " WHERE id = ANY(:ids)"
        ),
        {"ids": again},
    )
    return rows
