import os

from celery import Celery
from kombu import Queue

celery_app = Celery("smart_ats", broker=os.environ["REDIS_URL"])
celery_app.conf.update(
    task_queues=[Queue(name) for name in ("llm", "default", "agent", "email")],
    task_default_queue="default",
    # Celery Beat: retention jobs land here in later tickets.
    beat_schedule={},
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
