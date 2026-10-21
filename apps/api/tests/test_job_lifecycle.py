"""The Job lifecycle of FR-A3.1: transitions, metadata, and ARCHIVED as read-only."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any, get_args

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient, Response

from app import jobs, pipeline, scoring_runs, uploads
from app.main import app
from tests.test_jobs import CONFIRMATION, User, make_user
from tests.test_scoring_runs import make_job, query

pytestmark = pytest.mark.usefixtures("database")

STATUSES = ["DRAFT", "PUBLISHED", "PAUSED", "CLOSED", "ARCHIVED"]
ACTIONS = ["publish", "pause", "resume", "close", "archive", "reopen"]
# The diagram of FR-A3.1, edge by edge.
EDGES = {
    ("DRAFT", "publish"): "PUBLISHED",
    ("PUBLISHED", "pause"): "PAUSED",
    ("PAUSED", "resume"): "PUBLISHED",
    ("PUBLISHED", "close"): "CLOSED",
    ("PAUSED", "close"): "CLOSED",
    ("CLOSED", "archive"): "ARCHIVED",
    ("CLOSED", "reopen"): "PUBLISHED",
}


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def recruiter() -> User:
    return make_user()


def job_in(user: User, status: str) -> str:
    job_id = make_job(user, {})
    query(user, "UPDATE jobs SET status = :s WHERE id = :id RETURNING id", s=status, id=job_id)
    return job_id


def stored(user: User, job_id: str) -> dict[str, Any]:
    [job] = query(user, "SELECT status, updated_at FROM jobs WHERE id = :id", id=job_id)
    return job


async def transition(client: AsyncClient, user: User, job_id: str, action: str) -> Response:
    return await client.post(
        f"/api/jobs/{job_id}/transitions", headers=user.headers, json={"action": action}
    )


@pytest.mark.parametrize(("status", "action"), [(s, a) for s in STATUSES for a in ACTIONS])
async def test_each_edge_moves_the_job_and_every_other_pair_is_refused(
    client: AsyncClient, recruiter: User, status: str, action: str
) -> None:
    job_id = job_in(recruiter, status)
    before = stored(recruiter, job_id)

    response = await transition(client, recruiter, job_id, action)

    after = stored(recruiter, job_id)
    if (status, action) in EDGES:
        assert response.status_code == 200
        assert response.json()["status"] == after["status"] == EDGES[status, action]
        assert after["updated_at"] > before["updated_at"]
    else:
        assert response.status_code == 409
        assert after == before


async def test_concurrent_transitions_lose_no_edge(client: AsyncClient, recruiter: User) -> None:
    job_id = job_in(recruiter, "PUBLISHED")

    pause, close = await asyncio.gather(
        transition(client, recruiter, job_id, "pause"),
        transition(client, recruiter, job_id, "close"),
    )

    # Paused then closed, or closed first so that pausing no longer applies: never a close
    # that a pause overwrote.
    assert close.status_code == 200
    assert pause.status_code in (200, 409)
    assert stored(recruiter, job_id)["status"] == "CLOSED"


async def test_unknown_action_is_rejected(client: AsyncClient, recruiter: User) -> None:
    job_id = job_in(recruiter, "DRAFT")

    assert (await transition(client, recruiter, job_id, "delete")).status_code == 422


@pytest.mark.cross_tenant
async def test_other_tenants_job_cannot_be_moved(client: AsyncClient, recruiter: User) -> None:
    job_id = job_in(recruiter, "DRAFT")

    assert (await transition(client, make_user(), job_id, "publish")).status_code == 404
    assert stored(recruiter, job_id)["status"] == "DRAFT"


# Metadata.


async def patch(client: AsyncClient, user: User, job_id: str, body: dict[str, Any]) -> Response:
    return await client.patch(f"/api/jobs/{job_id}", headers=user.headers, json=body)


async def test_metadata_changes_only_the_fields_sent(client: AsyncClient, recruiter: User) -> None:
    job_id = job_in(recruiter, "PUBLISHED")
    before = stored(recruiter, job_id)
    body = {"department": "Engineering", "location": "Hà Nội", "apply_deadline": "2026-12-31"}

    response = await patch(client, recruiter, job_id, body)

    assert response.status_code == 200
    job = response.json()
    assert {k: job[k] for k in body} == body
    # Not sent, so unchanged.
    assert (job["title"], job["level"], job["work_mode"]) == ("Backend Developer", "MID", None)
    assert stored(recruiter, job_id)["updated_at"] > before["updated_at"]

    response = await patch(
        client, recruiter, job_id, {"title": "Senior Dev", "level": "SENIOR", "location": None}
    )

    assert response.status_code == 200
    job = response.json()
    assert (job["title"], job["level"], job["department"], job["location"]) == (
        "Senior Dev",
        "SENIOR",
        "Engineering",
        None,
    )


@pytest.mark.parametrize(
    "body", [{"title": None}, {"level": None}, {"title": ""}, {"level": "CEO"}]
)
async def test_metadata_refuses_a_missing_title_or_level(
    client: AsyncClient, recruiter: User, body: dict[str, Any]
) -> None:
    job_id = job_in(recruiter, "DRAFT")

    assert (await patch(client, recruiter, job_id, body)).status_code == 422


async def test_metadata_waits_for_the_parse_that_would_overwrite_it(
    client: AsyncClient, recruiter: User
) -> None:
    job_id = job_in(recruiter, "DRAFT")
    query(recruiter, "UPDATE jobs SET parse_status = 'PENDING' RETURNING id")

    assert (await patch(client, recruiter, job_id, {"location": "HCM"})).status_code == 409


@pytest.mark.cross_tenant
async def test_other_tenants_job_metadata_cannot_change(
    client: AsyncClient, recruiter: User
) -> None:
    job_id = job_in(recruiter, "DRAFT")

    assert (await patch(client, make_user(), job_id, {"location": "HCM"})).status_code == 404


async def test_job_list_filters_by_status(client: AsyncClient, recruiter: User) -> None:
    draft, published = job_in(recruiter, "DRAFT"), job_in(recruiter, "PUBLISHED")

    async def ids(**params: str) -> list[str]:
        response = await client.get("/api/jobs", headers=recruiter.headers, params=params)
        return [job["id"] for job in response.json()]

    assert await ids(status="PUBLISHED") == [published]
    assert await ids(status="DRAFT") == [draft]
    assert await ids() == [published, draft]
    response = await client.get("/api/jobs", headers=recruiter.headers, params={"status": "X"})
    assert response.status_code == 422


# ARCHIVED is read-only: every write endpoint refuses, every read still answers.

# Each with a body it would accept on a Job not archived.
WRITES: dict[str, tuple[str, str, dict[str, Any]]] = {
    "confirm criteria": ("PUT", "/criteria", {"json": CONFIRMATION}),
    "upload": (
        "POST",
        "/uploads",
        {"files": {"files": ("cv.pdf", b"%PDF")}, "data": {"consent_confirmed": "true"}},
    ),
    "score": ("POST", "/scoring-runs", {}),
    "assign reviewers": ("PUT", "/reviewers", {"json": {"user_ids": []}}),
    "edit metadata": ("PATCH", "", {"json": {"location": "HCM"}}),
    "transition": ("POST", "/transitions", {"json": {"action": "reopen"}}),
    # The Job has no Application: refused for it, it would be a 404.
    "move stages": (
        "POST",
        "/applications/stage",
        {"json": {"applications": [{"id": str(uuid.uuid4()), "version": 0}], "to_stage": "OFFER"}},
    ),
}


@pytest.mark.parametrize("name", WRITES)
async def test_every_write_to_an_archived_job_is_refused(
    client: AsyncClient, recruiter: User, name: str
) -> None:
    job_id = job_in(recruiter, "ARCHIVED")
    before = stored(recruiter, job_id)

    method, path, body = WRITES[name]
    response = await client.request(
        method, f"/api/jobs/{job_id}{path}", headers=recruiter.headers, **body
    )

    assert response.status_code == 409
    assert stored(recruiter, job_id) == before


async def test_an_archived_job_still_reads(client: AsyncClient, recruiter: User) -> None:
    job_id = job_in(recruiter, "ARCHIVED")

    for path in ("", "/applications", "/uploads", "/reviewers"):
        response = await client.get(f"/api/jobs/{job_id}{path}", headers=recruiter.headers)
        assert response.status_code == 200, path
    [job] = (await client.get("/api/jobs", headers=recruiter.headers)).json()
    assert job["status"] == "ARCHIVED"


def test_every_write_under_a_job_takes_a_writer_dependency() -> None:
    """So a write endpoint added later cannot forget ARCHIVED (FR-A3.1)."""
    writers = {get_args(alias)[1].dependency for alias in (jobs.JobWriter, jobs.LockedJob)}

    def calls(dependant: Dependant) -> set[Any]:
        return {d.call for d in dependant.dependencies}.union(
            *(calls(d) for d in dependant.dependencies)
        )

    # The OpenAPI schema lists every route the app serves, from whichever router.
    served = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/jobs/{job_id}")
        for method in operations
        if method != "get"
    }
    routes = {
        (method, route.path): route
        for module in (jobs, uploads, scoring_runs, pipeline)
        for route in module.router.routes
        if isinstance(route, APIRoute)
        for method in route.methods or ()
    }
    assert served <= routes.keys()
    assert sorted(key for key in served if not writers & calls(routes[key].dependant)) == []
    # And each is in WRITES, so the test above proves its 409.
    assert len(served) == len(WRITES)
