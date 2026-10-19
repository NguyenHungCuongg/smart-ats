import inspect
import os
from collections.abc import Callable
from typing import Any
from uuid import UUID

from celery import Celery
from kombu import Queue

from app.db import tenant_session

# include: the modules that define tasks; the worker imports them at startup.
celery_app = Celery(
    "smart_ats",
    broker=os.environ["REDIS_URL"],
    include=["app.jobs", "app.scoring_runs", "app.sweep", "app.uploads"],
)
celery_app.conf.update(
    task_queues=[Queue(name) for name in ("llm", "default", "agent", "email")],
    task_default_queue="default",
    # Celery Beat: retention jobs land here in later tickets.
    beat_schedule={
        # Every minute, so a stuck row waits little past STUCK_AFTER (SAD §6).
        "sweep-stuck-rows": {"task": "sweep.stuck_rows", "schedule": 60.0},
    },
)

# Tasks that touch no tenant data and so skip @tenant_task (ADR-0002). Adding a name here is the
# explicit declaration the CI check (untenanted_tasks) asks for.
# sweep.stuck_rows reads only the ids of ACTIVE Tenants and sweeps each in a @tenant_task.
NON_TENANT_TASKS = frozenset(
    {"demo.llm", "demo.default", "demo.agent", "demo.email", "sweep.stuck_rows"}
)

# The wrappers @tenant_task built. The check matches a task's body against these rather than a
# flag on the task, which any task could set without the decorator.
_tenant_task_wrappers: set[Callable[..., Any]] = set()


def tenant_task(**options: Any) -> Callable[[Callable[..., Any]], Any]:
    """Register a Celery task that runs in one tenant's RLS context (ADR-0002, SAD §4).

    The function takes (tenant_id: UUID, session: Session, *args); callers send only
    (tenant_id, *args). The task acks late and is rejected (so requeued) if its worker process
    dies, so a task cut off mid-run is redelivered: write idempotently (SAD §6).
    """
    if options.get("bind"):
        raise TypeError("@tenant_task does not take bind: Celery would pass the task as tenant_id")

    def decorate(fn: Callable[..., Any]) -> Any:
        if list(inspect.signature(fn).parameters)[:2] != ["tenant_id", "session"]:
            raise TypeError(f"{fn.__name__} must take (tenant_id, session, ...) first")

        def run(tenant_id: str | UUID, *args: Any, **kwargs: Any) -> Any:
            tid = UUID(str(tenant_id))
            with tenant_session(tid) as session:
                return fn(tid, session, *args, **kwargs)

        # Not functools.wraps: its __wrapped__ would make Celery check callers' args against fn's
        # signature, which has the extra `session`.
        run.__name__, run.__module__, run.__doc__ = fn.__name__, fn.__module__, fn.__doc__
        _tenant_task_wrappers.add(run)
        return celery_app.task(acks_late=True, reject_on_worker_lost=True, **options)(run)

    return decorate


def untenanted_tasks(app: Celery) -> list[str]:
    """Names of registered tasks that neither use @tenant_task nor are in NON_TENANT_TASKS.

    Imports the app's task modules first, as a worker does at startup, so no task escapes the
    check by living in a module nothing else imported.
    """
    app.loader.import_default_modules()
    return sorted(
        name
        for name, task in app.tasks.items()
        if not name.startswith("celery.")  # Celery's own built-ins
        # autoretry_for swaps task.run for a retrying wrapper and keeps the body in _orig_run.
        and getattr(task, "_orig_run", task.run) not in _tenant_task_wrappers
        and name not in NON_TENANT_TASKS
    )


@celery_app.task(name="demo.llm", queue="llm")
def demo_llm() -> str:
    return "llm"


@celery_app.task(name="demo.default", queue="default")
def demo_default() -> str:
    return "default"


@celery_app.task(name="demo.agent", queue="agent")
def demo_agent() -> str:
    return "agent"


@celery_app.task(name="demo.email", queue="email")
def demo_email() -> str:
    return "email"
