import os

from celery import Celery
from kombu import Queue

QUEUES = ("llm", "default", "agent", "email")

celery_app = Celery("smart_ats", broker=os.environ["REDIS_URL"])
celery_app.conf.update(
    task_queues=[Queue(queue) for queue in QUEUES],
    task_default_queue="default",
    task_routes={f"demo.{queue}": {"queue": queue} for queue in QUEUES},
    # Celery Beat: retention jobs land here in later tickets.
    beat_schedule={},
)


@celery_app.task(name="demo.llm")
def demo_llm() -> str:
    return "llm"


@celery_app.task(name="demo.default")
def demo_default() -> str:
    return "default"


@celery_app.task(name="demo.agent")
def demo_agent() -> str:
    return "agent"


@celery_app.task(name="demo.email")
def demo_email() -> str:
    return "email"
