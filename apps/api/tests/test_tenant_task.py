"""@tenant_task and the CI check that every registered task uses it (ADR-0002, FR-C1.3)."""

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from celery import Celery
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.db import tenant_session
from tests.test_tenancy import COUNT_USERS, insert_user, make_tenant


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> Iterator[Celery]:
    """app.worker with a throwaway broker URL (importing it needs REDIS_URL, never connects).

    Tasks a test registers on the shared app are dropped afterwards, so the registry check
    below only ever sees the real ones.
    """
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from app import worker

    before = set(worker.celery_app.tasks)
    yield worker.celery_app
    for name in set(worker.celery_app.tasks) - before:
        worker.celery_app.tasks.pop(name)


def test_every_registered_task_uses_tenant_task_or_is_a_declared_exception(
    worker: Celery,
) -> None:
    from app.worker import untenanted_tasks

    assert untenanted_tasks(worker) == []


def test_check_flags_a_task_registered_without_tenant_task() -> None:
    from app.worker import untenanted_tasks

    app = Celery("violator", broker="memory://")

    @app.task(name="violator.plain")
    def plain() -> None: ...

    assert untenanted_tasks(app) == ["violator.plain"]


def test_tenant_task_requires_tenant_id_then_session(worker: Celery) -> None:
    from app.worker import tenant_task

    with pytest.raises(TypeError, match="tenant_id"):

        @tenant_task(name="bad.no_tenant")
        def no_tenant(session: Session) -> None: ...

    with pytest.raises(TypeError, match="session"):

        @tenant_task(name="bad.no_session")
        def no_session(tenant_id: uuid.UUID) -> None: ...


def test_tenant_task_acks_late_and_passes_the_check(worker: Celery) -> None:
    from app.worker import tenant_task, untenanted_tasks

    @tenant_task(name="test.noop")
    def noop(tenant_id: uuid.UUID, session: Session) -> None: ...

    assert noop.acks_late is True
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
