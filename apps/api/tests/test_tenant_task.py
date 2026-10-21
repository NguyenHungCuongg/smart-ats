"""@tenant_task and the CI check that every registered task uses it (ADR-0002, FR-C1.3)."""

import subprocess
import sys
import uuid

import psycopg
import pytest
from celery import Celery
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.db import tenant_session
from tests.conftest import API_DIR
from tests.test_tenancy import COUNT_USERS, insert_user, make_tenant


def test_every_registered_task_uses_tenant_task_or_is_a_declared_exception(
    worker: Celery,
) -> None:
    from app.worker import untenanted_tasks

    assert untenanted_tasks(worker) == []


def test_check_loads_every_task_module_itself() -> None:
    # A fresh interpreter: here the worker fixture and other tests have already imported them.
    script = (
        "from app.worker import celery_app, untenanted_tasks\n"
        "untenanted_tasks(celery_app)\n"
        "print(sorted(n for n in celery_app.tasks if not n.startswith(('celery.', 'demo.'))))"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=API_DIR, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == str(
        [
            "apply.parse_cv",
            "emails.send_email",
            "jobs.parse",
            "scoring_runs.score_application",
            "sweep.stuck_rows",
            "sweep.tenant",
            "uploads.parse_cv",
        ]
    )


def test_every_tenant_task_is_redelivered_if_its_worker_dies(worker: Celery) -> None:
    for name in (
        "apply.parse_cv",
        "jobs.parse",
        "uploads.parse_cv",
        "scoring_runs.score_application",
        "sweep.tenant",
    ):
        task = worker.tasks[name]
        assert task.acks_late is True
        assert task.reject_on_worker_lost is True


def test_check_flags_a_task_registered_without_tenant_task() -> None:
    from app.worker import untenanted_tasks

    app = Celery("violator", broker="memory://")

    @app.task(name="violator.plain")
    def plain() -> None: ...

    assert untenanted_tasks(app) == ["violator.plain"]


def test_check_flags_a_task_that_claims_tenant_scope_without_tenant_task(worker: Celery) -> None:
    from app.worker import untenanted_tasks

    # tenant_scoped was the flag the check once trusted; setting it must not pass.
    @worker.task(name="violator.self_declared", tenant_scoped=True)
    def self_declared(tenant_id: str) -> None: ...

    assert untenanted_tasks(worker) == ["violator.self_declared"]


def test_tenant_task_requires_tenant_id_then_session(worker: Celery) -> None:
    from app.worker import tenant_task

    with pytest.raises(TypeError, match="tenant_id"):

        @tenant_task(name="bad.no_tenant")
        def no_tenant(session: Session) -> None: ...

    with pytest.raises(TypeError, match="session"):

        @tenant_task(name="bad.no_session")
        def no_session(tenant_id: uuid.UUID) -> None: ...


def test_tenant_task_refuses_bind_which_would_put_the_task_where_tenant_id_goes(
    worker: Celery,
) -> None:
    from app.worker import tenant_task

    with pytest.raises(TypeError, match="bind"):

        @tenant_task(name="bad.bound", bind=True)
        def bound(tenant_id: uuid.UUID, session: Session) -> None: ...


def test_tenant_task_acks_late_and_passes_the_check(worker: Celery) -> None:
    from app.worker import tenant_task, untenanted_tasks

    @tenant_task(name="test.noop")
    def noop(tenant_id: uuid.UUID, session: Session) -> None: ...

    assert noop.acks_late is True
    assert untenanted_tasks(worker) == []


def test_tenant_task_that_autoretries_still_passes_the_check(worker: Celery) -> None:
    from app.worker import tenant_task, untenanted_tasks

    # autoretry_for makes Celery swap task.run for a retrying wrapper.
    @tenant_task(name="test.retrying", autoretry_for=(ValueError,))
    def retrying(tenant_id: uuid.UUID, session: Session) -> None: ...

    assert untenanted_tasks(worker) == []


@pytest.mark.usefixtures("database")
@pytest.mark.cross_tenant
def test_task_for_tenant_a_cannot_read_or_write_tenant_b(worker: Celery) -> None:
    from app.worker import tenant_task

    @tenant_task(name="test.count_users")
    def count_users(tenant_id: uuid.UUID, session: Session) -> int:
        return int(session.scalar(COUNT_USERS) or 0)

    @tenant_task(name="test.add_user_for")
    def add_user_for(tenant_id: uuid.UUID, session: Session, victim: str) -> None:
        insert_user(session, uuid.UUID(victim))

    a, b = make_tenant(), make_tenant()
    with tenant_session(b) as session:
        insert_user(session, b)

    # Read: A's task sees none of B's rows; B's task sees its own.
    assert count_users.apply(args=[str(a)]).get() == 0
    assert count_users.apply(args=[str(b)]).get() == 1

    # Write: A's task inserting a row for B is rejected by RLS, and nothing lands.
    result = add_user_for.apply(args=[str(a), str(b)])
    assert isinstance(result.result, ProgrammingError)
    assert isinstance(result.result.orig, psycopg.errors.InsufficientPrivilege)
    assert count_users.apply(args=[str(b)]).get() == 1
