"""Per-user progress events over SSE with one-time tickets (ADR-0003, SAD §4.3)."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from datetime import timedelta

import pytest
import uvicorn
from celery import Celery
from httpx import AsyncClient, Response
from sqlalchemy.orm import Session

from app import events
from app.auth import _access_token, _redis
from app.main import app

pytestmark = pytest.mark.usefixtures("database", "redis")


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """A client of the app served by a real uvicorn: httpx's ASGI transport waits for the whole
    body, which a stream never finishes. Same loop as the tests, like the cached clients."""
    server = uvicorn.Server(uvicorn.Config(app, port=0, log_level="warning", lifespan="off"))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
        yield client
    server.should_exit = True
    await serving


def bearer(tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {_access_token(user_id, tenant_id, 'RECRUITER')}"}


async def ticket_for(client: AsyncClient, tenant_id: uuid.UUID, user_id: uuid.UUID) -> str:
    response = await client.post("/api/events/ticket", headers=bearer(tenant_id, user_id))
    assert response.status_code == 200
    ticket: str = response.json()["ticket"]
    return ticket


async def subscribed(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Wait until a stream listens on the user's channel, so a publish cannot race it."""
    channel = events.channel(tenant_id, user_id)
    while (await _redis().pubsub_numsub(channel))[0][1] == 0:
        await asyncio.sleep(0.01)


async def next_event(response: Response) -> tuple[str, object]:
    fields: dict[str, str] = {}
    lines = response.aiter_lines()
    async with asyncio.timeout(5):
        async for line in lines:
            if line.startswith(":"):  # keep-alive comment
                continue
            if not line and fields:
                return fields["event"], json.loads(fields["data"])
            name, _, value = line.partition(": ")
            fields[name] = value
    raise AssertionError("stream ended")


async def get_stream(client: AsyncClient, ticket: str) -> Response:
    return await client.get("/api/events", params={"ticket": ticket})


async def test_ticket_requires_authentication(client: AsyncClient) -> None:
    assert (await client.post("/api/events/ticket")).status_code == 401


@pytest.mark.cross_tenant
async def test_stream_delivers_only_the_users_own_events(client: AsyncClient) -> None:
    tenant, other_tenant = uuid.uuid4(), uuid.uuid4()
    a, b = uuid.uuid4(), uuid.uuid4()
    ticket = await ticket_for(client, tenant, a)

    async with client.stream("GET", "/api/events", params={"ticket": ticket}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        await subscribed(tenant, a)
        redis = _redis()
        # Another user in the same Tenant, and the same user id in another Tenant.
        await redis.publish(events.channel(tenant, b), json.dumps({"event": "x", "data": "b"}))
        await redis.publish(
            events.channel(other_tenant, a), json.dumps({"event": "x", "data": "other"})
        )
        await redis.publish(events.channel(tenant, a), json.dumps({"event": "x", "data": "a"}))

        assert await next_event(response) == ("x", "a")


async def test_ticket_works_once(client: AsyncClient) -> None:
    tenant, user = uuid.uuid4(), uuid.uuid4()
    ticket = await ticket_for(client, tenant, user)
    async with client.stream("GET", "/api/events", params={"ticket": ticket}) as response:
        assert response.status_code == 200

    assert (await get_stream(client, ticket)).status_code == 401


async def test_expired_ticket_is_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(events, "TICKET_TTL", timedelta(milliseconds=50))
    ticket = await ticket_for(client, uuid.uuid4(), uuid.uuid4())
    await asyncio.sleep(0.2)

    assert (await get_stream(client, ticket)).status_code == 401


async def test_unknown_or_missing_ticket_is_rejected(client: AsyncClient) -> None:
    assert (await get_stream(client, "made-up")).status_code == 401
    assert (await client.get("/api/events")).status_code == 401


async def test_tenant_task_publishes_once_its_transaction_commits(
    client: AsyncClient, worker: Celery
) -> None:
    from app.worker import tenant_task

    @tenant_task(name="test.progress")
    def progress(tenant_id: uuid.UUID, session: Session, user_id: str, fail: bool) -> None:
        events.publish(session, uuid.UUID(user_id), "progress", {"fail": fail})
        if fail:
            raise RuntimeError("rolled back")

    tenant, user = uuid.uuid4(), uuid.uuid4()
    ticket = await ticket_for(client, tenant, user)
    async with client.stream("GET", "/api/events", params={"ticket": ticket}) as response:
        await subscribed(tenant, user)
        # A rolled-back task announces nothing; the committed one arrives.
        await asyncio.to_thread(progress.apply, args=[str(tenant), str(user), True])
        await asyncio.to_thread(progress.apply, args=[str(tenant), str(user), False])

        assert await next_event(response) == ("progress", {"fail": False})


async def test_stream_listens_before_the_client_hears_it_is_open(client: AsyncClient) -> None:
    # A client reloads its data on open (SAD §6): an event published right after must arrive.
    tenant, user = uuid.uuid4(), uuid.uuid4()
    ticket = await ticket_for(client, tenant, user)

    async with client.stream("GET", "/api/events", params={"ticket": ticket}) as response:
        await _redis().publish(
            events.channel(tenant, user), json.dumps({"event": "x", "data": "early"})
        )

        assert await next_event(response) == ("x", "early")


@pytest.fixture
def two_streams_per_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events, "MAX_STREAMS_PER_USER", 2)


async def open_streams(channel: str) -> int:
    count: int = (await _redis().pubsub_numsub(channel))[0][1]
    return count


@pytest.mark.usefixtures("two_streams_per_user")
async def test_ticket_is_refused_while_the_user_has_every_stream_open(client: AsyncClient) -> None:
    tenant, user = uuid.uuid4(), uuid.uuid4()
    async with AsyncExitStack() as streams:
        for _ in range(2):
            ticket = await ticket_for(client, tenant, user)
            response = await streams.enter_async_context(
                client.stream("GET", "/api/events", params={"ticket": ticket})
            )
            assert response.status_code == 200

        refused = await client.post("/api/events/ticket", headers=bearer(tenant, user))
        assert refused.status_code == 429
        # Another user of the same Tenant is not affected.
        await ticket_for(client, tenant, uuid.uuid4())

    # Closed streams no longer count.
    async with asyncio.timeout(5):
        while await open_streams(events.channel(tenant, user)):
            await asyncio.sleep(0.01)
    await ticket_for(client, tenant, user)


@pytest.mark.usefixtures("two_streams_per_user")
async def test_tickets_taken_ahead_cannot_open_more_streams_than_the_limit(
    client: AsyncClient,
) -> None:
    tenant, user = uuid.uuid4(), uuid.uuid4()
    tickets = [await ticket_for(client, tenant, user) for _ in range(3)]

    async with AsyncExitStack() as streams:
        statuses = [
            (
                await streams.enter_async_context(
                    client.stream("GET", "/api/events", params={"ticket": ticket})
                )
            ).status_code
            for ticket in tickets
        ]

        assert statuses == [200, 200, 429]
        assert await open_streams(events.channel(tenant, user)) == 2


async def test_streams_hold_redis_connections_from_a_bounded_pool(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(events, "MAX_STREAM_CONNECTIONS", 1)
    events._stream_redis.cache_clear()
    tenant = uuid.uuid4()
    first, second = [await ticket_for(client, tenant, uuid.uuid4()) for _ in range(2)]
    try:
        async with client.stream("GET", "/api/events", params={"ticket": first}) as response:
            assert response.status_code == 200

            assert (await get_stream(client, second)).status_code == 503
    finally:
        events._stream_redis.cache_clear()
