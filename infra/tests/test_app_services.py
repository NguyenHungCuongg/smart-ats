"""Smoke tests for the application services (Infra 05).

Run against the Compose stack from the host: see README "Infrastructure".
"""

import json
import os
import subprocess
import time
import urllib.request

from celery import Celery


def test_api_health() -> None:
    with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=10) as response:
        assert json.load(response) == {"status": "ok"}


def test_api_ready() -> None:
    """200 only if the api reaches PostgreSQL, Redis and SeaweedFS with its own credentials."""
    with urllib.request.urlopen("http://127.0.0.1:8000/api/ready", timeout=10) as response:
        assert json.load(response) == {"status": "ok"}


def test_web_serves_home_page() -> None:
    # The dev server compiles the page on the first request.
    with urllib.request.urlopen("http://127.0.0.1:3000/", timeout=60) as response:
        assert response.status == 200


def test_each_queue_has_its_own_worker() -> None:
    app = Celery(broker=f"redis://127.0.0.1:{os.environ.get('REDIS_HOST_PORT', '6379')}/0")
    expected = [["agent"], ["default"], ["email"], ["llm"]]
    # Workers have no healthcheck, so `up --wait` may return before they join the broker.
    deadline = time.monotonic() + 30
    while True:
        replies = app.control.inspect(timeout=2).active_queues() or {}
        queues = sorted(sorted(q["name"] for q in qs) for qs in replies.values())
        if queues == expected or time.monotonic() > deadline:
            break
    assert queues == expected


def test_beat_is_running() -> None:
    services = subprocess.run(
        ["docker", "compose", "ps", "--status", "running", "--services"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert "beat" in services
