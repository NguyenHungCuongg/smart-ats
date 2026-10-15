import inspect
import os
from collections.abc import Callable
from typing import Any
from uuid import UUID

from celery import Celery
from kombu import Queue

from app.db import tenant_session

# include: the modules that define tasks; the worker imports them at startup.
celery_app = Celery("smart_ats", broker=os.environ["REDIS_URL"], include=["app.jobs"])
celery_app.conf.update(
    task_queues=[Queue(name) for name in ("llm", "default", "agent", "email")],
    task_default_queue="default",
    # Celery Beat: retention jobs land here in later tickets.
    beat_schedule={},
)

# Tasks that touch no tenant data and so skip @tenant_task (ADR-0002). Adding a name here is the
# explicit declaration the CI check (untenanted_tasks) asks for.
NON_TENANT_TASKS = frozenset({"demo.llm", "demo.default", "demo.agent", "demo.email"})


def tenant_task(**options: Any) -> Callable[[Callable[..., Any]], Any]:
    """Register a Celery task that runs in one tenant's RLS context (ADR-0002, SAD §4).

    The function takes (tenant_id: UUID, session: Session, *args); callers send only
    (tenant_id, *args). The task acks late, so a worker that dies mid-task is redelivered:
    write idempotently.
    """

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
        return celery_app.task(acks_late=True, tenant_scoped=True, **options)(run)

    return decorate


def untenanted_tasks(app: Celery) -> list[str]:
    """Names of registered tasks that neither use @tenant_task nor are in NON_TENANT_TASKS."""
    return sorted(
        name
        for name, task in app.tasks.items()
        if not name.startswith("celery.")  # Celery's own built-ins
        and not getattr(task, "tenant_scoped", False)
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
