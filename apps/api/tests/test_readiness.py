import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app import readiness
from app.main import app


async def ok() -> None:
    return None


async def refused() -> None:
    raise ConnectionRefusedError("secret-host:6379")


async def hangs() -> None:
    await asyncio.sleep(60)


async def get_ready() -> tuple[int, dict[str, object]]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/ready")
    return response.status_code, response.json()


@pytest.fixture
def checks(monkeypatch: pytest.MonkeyPatch) -> dict[str, readiness.Check]:
    """The registry with every dependency healthy; tests swap in a failing one."""
    healthy: dict[str, readiness.Check] = dict.fromkeys(readiness.CHECKS, ok)
    monkeypatch.setattr(readiness, "CHECKS", healthy)
    return healthy


async def test_ready_when_every_dependency_connects(checks: dict[str, readiness.Check]) -> None:
    assert await get_ready() == (200, {"status": "ok"})


async def test_unavailable_names_the_failed_dependency(checks: dict[str, readiness.Check]) -> None:
    checks["redis"] = refused

    status, body = await get_ready()

    # The error text (a host name here) stays in the log, not in the public response.
    assert (status, body) == (503, {"status": "unavailable", "failed": ["redis"]})


async def test_hung_dependency_counts_as_failed(
    checks: dict[str, readiness.Check], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(readiness, "TIMEOUT_SECONDS", 0.05)
    checks["object_storage"] = hangs

    assert await get_ready() == (503, {"status": "unavailable", "failed": ["object_storage"]})


def test_checks_cover_db_redis_and_object_storage() -> None:
    assert set(readiness.CHECKS) == {"database", "redis", "object_storage"}
