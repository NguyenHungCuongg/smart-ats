"""Reviewer Assignment and the RBAC matrix of SRS §2.2, enforced by FastAPI dependencies."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app import jobs, scoring_runs, storage, uploads
from app.main import app
from smart_ats_scoring import pricing
from tests.test_jobs import CONFIRMATION, User, make_user
from tests.test_scoring_runs import MODEL, add_application, make_job, query

pytestmark = pytest.mark.usefixtures("database")


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!")


@pytest.fixture(autouse=True)
def objects(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Object storage as a dict; the broker and the LLM are never reached."""
    stored: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "put", lambda key, data: stored.__setitem__(key, data))
    monkeypatch.setattr(storage, "get", lambda key: stored[key])
    for task in (jobs.parse, uploads.parse_cv, scoring_runs.score_application):
        monkeypatch.setattr(task, "delay", lambda *args: None)
    monkeypatch.setenv("LLM_REASONING_MODEL", MODEL)
    monkeypatch.setitem(pricing.PRICES, MODEL, pricing.Price(Decimal(1), Decimal(1), Decimal(1)))
    return stored


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def recruiter() -> User:
    return make_user()


@pytest.fixture
def reviewer(recruiter: User) -> User:
    return make_user("REVIEWER", recruiter.tenant_id)


@pytest.fixture
def job(recruiter: User, objects: dict[str, bytes]) -> str:
    return make_job(recruiter, objects)


async def assign(client: AsyncClient, by: User, job_id: str, *reviewers: Any) -> Response:
    ids = [str(r.id if isinstance(r, User) else r) for r in reviewers]
    return await client.put(
        f"/api/jobs/{job_id}/reviewers", headers=by.headers, json={"user_ids": ids}
    )


async def test_assigned_reviewer_reads_the_job_and_an_unassigned_one_finds_none(
    client: AsyncClient, recruiter: User, reviewer: User, job: str
) -> None:
    other = make_user("REVIEWER", recruiter.tenant_id)

    response = await assign(client, recruiter, job, reviewer)

    assert response.status_code == 200
    assert [r["id"] for r in response.json() if r["assigned"]] == [str(reviewer.id)]
    assert (await client.get(f"/api/jobs/{job}", headers=reviewer.headers)).status_code == 200
    # Unassigned, the Job is as unknown as another Tenant's (SAD §4.3).
    assert (await client.get(f"/api/jobs/{job}", headers=other.headers)).status_code == 404
    assert (await client.get(f"/api/jobs/{uuid.uuid4()}", headers=other.headers)).status_code == 404


async def test_assigning_replaces_the_whole_list_and_keeps_who_assigned_those_that_stay(
    client: AsyncClient, recruiter: User, reviewer: User, job: str
) -> None:
    second = make_user("REVIEWER", recruiter.tenant_id)
    admin = make_user("COMPANY_ADMIN", recruiter.tenant_id)
    await assign(client, recruiter, job, reviewer, second)

    response = await assign(client, admin, job, second)

    assert response.status_code == 200
    assert {r["id"]: r["assigned"] for r in response.json()} == {
        str(reviewer.id): False,
        str(second.id): True,
    }
    assert query(
        recruiter, "SELECT user_id, assigned_by FROM job_reviewers WHERE job_id = :id", id=job
    ) == [{"user_id": second.id, "assigned_by": recruiter.id}]
    assert (await client.get(f"/api/jobs/{job}", headers=reviewer.headers)).status_code == 404


def deactivated(user: User) -> User:
    query(user, "UPDATE users SET is_active = false WHERE id = :id RETURNING id", id=user.id)
    return user


@pytest.mark.parametrize(
    "who",
    [
        pytest.param(lambda r: make_user("RECRUITER", r.tenant_id), id="a recruiter"),
        pytest.param(lambda r: deactivated(make_user("REVIEWER", r.tenant_id)), id="revoked"),
        pytest.param(lambda r: uuid.uuid4(), id="no such user"),
        pytest.param(
            lambda r: make_user("REVIEWER"), id="another tenant's", marks=pytest.mark.cross_tenant
        ),
    ],
)
async def test_only_active_reviewers_of_the_tenant_can_be_assigned(
    client: AsyncClient,
    recruiter: User,
    reviewer: User,
    job: str,
    who: Callable[[User], User | uuid.UUID],
) -> None:
    await assign(client, recruiter, job, reviewer)

    response = await assign(client, recruiter, job, who(recruiter))

    assert response.status_code == 422
    # Nothing changed.
    assert query(recruiter, "SELECT user_id FROM job_reviewers") == [{"user_id": reviewer.id}]


async def test_reviewer_reads_applications_without_contact_fields_and_the_latest_run(
    client: AsyncClient, recruiter: User, reviewer: User, objects: dict[str, bytes]
) -> None:
    job = make_job(recruiter, objects)
    add_application(recruiter, objects, job)
    query(
        recruiter,
        "UPDATE candidates SET email = 'an@example.com', phone = '0901234567' RETURNING id",
    )
    await client.post(f"/api/jobs/{job}/scoring-runs", headers=recruiter.headers)
    await assign(client, recruiter, job, reviewer)

    response = await client.get(f"/api/jobs/{job}/applications", headers=reviewer.headers)

    assert response.status_code == 200
    [application] = response.json()
    assert application["full_name"] == "Nguyễn Văn An"
    # Not even empty: the fields are not there (SRS §2.1).
    assert {"email", "phone"}.isdisjoint(application)
    [seen_by_recruiter] = (
        await client.get(f"/api/jobs/{job}/applications", headers=recruiter.headers)
    ).json()
    assert seen_by_recruiter["email"] == "an@example.com"
    run = await client.get(f"/api/jobs/{job}/scoring-runs/latest", headers=reviewer.headers)
    assert run.status_code == 200
    assert {"email", "phone"}.isdisjoint(run.json()["results"][0])


async def list_jobs(client: AsyncClient, user: User, **params: str) -> list[dict[str, Any]]:
    response = await client.get("/api/jobs", headers=user.headers, params=params)
    assert response.status_code == 200
    result: list[dict[str, Any]] = response.json()
    return result


async def test_job_list_shows_managers_every_job_and_a_reviewer_only_assigned_ones(
    client: AsyncClient, recruiter: User, reviewer: User, objects: dict[str, bytes]
) -> None:
    admin = make_user("COMPANY_ADMIN", recruiter.tenant_id)
    first, second = make_job(recruiter, objects), make_job(recruiter, objects)
    add_application(recruiter, objects, first)
    add_application(recruiter, objects, first)
    await assign(client, recruiter, first, reviewer)

    # Newest first.
    assert [
        (j["id"], j["status"], j["application_count"]) for j in await list_jobs(client, admin)
    ] == [(second, "DRAFT", 0), (first, "DRAFT", 2)]
    assert [j["id"] for j in await list_jobs(client, recruiter)] == [second, first]
    assert [j["id"] for j in await list_jobs(client, reviewer)] == [first]


@pytest.mark.cross_tenant
async def test_job_list_never_shows_another_tenants_jobs(
    client: AsyncClient, job: str, objects: dict[str, bytes]
) -> None:
    other = make_user()
    make_job(other, objects)

    assert job not in [j["id"] for j in await list_jobs(client, other)]
    assert len(await list_jobs(client, other)) == 1


# The matrix of SRS §2.2, row by row in its order. Each row lists its tenant-role cells that
# restrict access and how its feature is reached; a feature not built yet is skipped with its
# FR, and the ticket that builds it lifts the skip. The ✅ cells are the features' own tests.
# System Admin's column waits for its login (FR-C1.1 has none yet).

DENIED = "❌"  # every probe answers 403
ASSIGNED = "✅ Assigned"  # 200 on an assigned Job, 404 on any other (SAD §4.3)
HIDDEN = "❌ (no contact fields)"  # the Applications come without email or phone

Probe = Callable[[AsyncClient, User, str], Awaitable[Response]]


def call(method: str, path: str, **kwargs: Any) -> Probe:
    """A request to path, whose {job} is the Job under test."""

    async def probe(client: AsyncClient, user: User, job_id: str) -> Response:
        return await client.request(method, path.format(job=job_id), headers=user.headers, **kwargs)

    return probe


async def move_first(client: AsyncClient, user: User, job_id: str) -> Response:
    """Move the first Application of the Job, as user finds it."""
    response = await client.get(f"/api/jobs/{job_id}/applications", headers=user.headers)
    application = response.json()[0]
    return await client.patch(
        f"/api/applications/{application['id']}/stage",
        headers=user.headers,
        json={"to_stage": "SCREENING", "version": application["version"]},
    )


EVERYONE = ("COMPANY_ADMIN", "RECRUITER", "REVIEWER")
MATRIX: list[tuple[str, dict[str, str], list[Probe] | str]] = [
    ("Quản lý Tenant, gói, AI Budget nền tảng", dict.fromkeys(EVERYONE, DENIED), "FR-C1.4"),
    ("Xem số liệu tổng hợp theo tenant", dict.fromkeys(EVERYONE, DENIED), "FR-C1.4"),
    (
        "Quản lý Workspace & Member",
        {"RECRUITER": DENIED, "REVIEWER": DENIED},
        [
            call("GET", "/api/members"),
            call("POST", "/api/invitations", json={"email": "a@example.com", "role": "REVIEWER"}),
        ],
    ),
    ("Xem AI Usage của tenant", {"REVIEWER": DENIED}, "FR-C1.4"),
    (
        "Xử lý yêu cầu xóa dữ liệu ứng viên, cấu hình Retention",
        {"RECRUITER": DENIED, "REVIEWER": DENIED},
        "FR-C1.2, FR-C1.5",
    ),
    (
        "Tạo & Parse Job (FR-A1.1), quản lý vòng đời Job (FR-A3.1)",
        {"REVIEWER": DENIED},
        [
            call("POST", "/api/jobs", data={"text": "Backend Developer"}),
            call("PUT", "/api/jobs/{job}/criteria", json=CONFIRMATION),
            call("POST", "/api/jobs/{job}/transitions", json={"action": "publish"}),
            call("PATCH", "/api/jobs/{job}", json={"location": "HCM"}),
        ],
    ),
    ("Bật/tắt Public Apply Link (FR-A3.4)", {"REVIEWER": DENIED}, "FR-A3.4"),
    (
        "Upload & Parse CV (FR-A1.2)",
        {"REVIEWER": DENIED},
        [
            call(
                "POST",
                "/api/jobs/{job}/uploads",
                files={"files": ("cv.pdf", b"%PDF")},
                data={"consent_confirmed": "true"},
            ),
            call("GET", "/api/jobs/{job}/uploads"),
        ],
    ),
    # Rediscovery (FR-A1.6) joins this row when it is built.
    (
        "Chạy Scoring (FR-A1.3), Rediscovery (FR-A1.6)",
        {"REVIEWER": DENIED},
        [call("POST", "/api/jobs/{job}/scoring-runs")],
    ),
    ("Kích hoạt Agent & Recruiter Decision (FR-A0)", {"REVIEWER": DENIED}, "FR-A0"),
    (
        "Xem Fit-Gap Report & điểm số",
        {"REVIEWER": ASSIGNED},
        [
            call("GET", "/api/jobs/{job}"),
            call("GET", "/api/jobs/{job}/applications"),
            call("GET", "/api/jobs/{job}/scoring-runs/latest"),
        ],
    ),
    (
        "Xem thông tin liên hệ ứng viên",
        {"REVIEWER": HIDDEN},
        [call("GET", "/api/jobs/{job}/applications")],
    ),
    ("Chốt Shortlist, sinh câu hỏi phỏng vấn (FR-A1.4)", {"REVIEWER": DENIED}, "FR-A1.4"),
    ("Xem câu hỏi phỏng vấn", {"REVIEWER": ASSIGNED}, "FR-A1.4"),
    ("Xuất PDF (FR-A1.5)", {"REVIEWER": DENIED}, "FR-A1.5"),
    ("Soạn & gửi Email (FR-A2.1)", {"REVIEWER": DENIED}, "FR-A2.1"),
    ("Comment & Interview Score (FR-A2.2)", {"REVIEWER": ASSIGNED}, "FR-A2.2"),
    (
        "Đổi Stage, Bulk Actions (FR-A3.2)",
        {"REVIEWER": DENIED},
        [
            move_first,
            call(
                "POST",
                "/api/jobs/{job}/applications/stage",
                json={"applications": [], "to_stage": "SCREENING"},
            ),
        ],
    ),
    (
        "Gán Reviewer",
        {"REVIEWER": DENIED},
        [
            call("PUT", "/api/jobs/{job}/reviewers", json={"user_ids": []}),
            call("GET", "/api/jobs/{job}/reviewers"),
        ],
    ),
    ("Xem Activity Timeline (FR-A3.3)", {"REVIEWER": ASSIGNED}, "FR-A3.3"),
]

CELLS = [
    pytest.param(
        role,
        cell,
        [] if isinstance(probes, str) else probes,
        id=f"{row} | {role}",
        marks=[pytest.mark.skip(reason=f"{probes}: chưa làm")] if isinstance(probes, str) else [],
    )
    for row, cells, probes in MATRIX
    for role, cell in cells.items()
]


@pytest.fixture
async def jobs_of(
    client: AsyncClient, recruiter: User, reviewer: User, objects: dict[str, bytes]
) -> tuple[str, str]:
    """A Job assigned to reviewer and one that is not, each with an Application and a run."""
    assigned, unassigned = make_job(recruiter, objects), make_job(recruiter, objects)
    for job_id in (assigned, unassigned):
        add_application(recruiter, objects, job_id)
        await client.post(f"/api/jobs/{job_id}/scoring-runs", headers=recruiter.headers)
    query(recruiter, "UPDATE candidates SET email = id || '@example.com' RETURNING id")
    await assign(client, recruiter, assigned, reviewer)
    return assigned, unassigned


@pytest.mark.parametrize(("role", "cell", "probes"), CELLS)
async def test_rbac_matrix(
    client: AsyncClient,
    recruiter: User,
    reviewer: User,
    jobs_of: tuple[str, str],
    role: str,
    cell: str,
    probes: list[Probe],
) -> None:
    user = reviewer if role == "REVIEWER" else make_user(role, recruiter.tenant_id)
    assigned, unassigned = jobs_of
    for probe in probes:
        if cell == DENIED:
            assert (await probe(client, user, assigned)).status_code == 403
        elif cell == ASSIGNED:
            assert (await probe(client, user, assigned)).status_code == 200
            assert (await probe(client, user, unassigned)).status_code == 404
        else:
            response = await probe(client, user, assigned)
            assert response.status_code == 200
            assert all({"email", "phone"}.isdisjoint(a) for a in response.json())


@pytest.mark.cross_tenant
async def test_other_tenants_job_reviewers_are_not_found(
    client: AsyncClient, recruiter: User, reviewer: User, job: str
) -> None:
    other = make_user()

    assert (await assign(client, other, job)).status_code == 404
    response = await client.get(f"/api/jobs/{job}/reviewers", headers=other.headers)
    assert response.status_code == 404
    await assign(client, recruiter, job, reviewer)
    assert (await list_jobs(client, make_user("REVIEWER", other.tenant_id))) == []
