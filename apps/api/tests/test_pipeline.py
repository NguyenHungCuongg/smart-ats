"""The Application pipeline and its Kanban Board: Stage changes, their history and optimistic
locking (FR-A3.2).

Object storage and the broker are faked; the API and PostgreSQL are real.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app import storage
from app.db import tenant_session
from app.main import app
from tests.test_jobs import User, make_user
from tests.test_scoring_runs import add_application, make_job, query

pytestmark = pytest.mark.usefixtures("database")

ALEMBIC = Config(Path(__file__).parents[1] / "alembic.ini")


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!")


@pytest.fixture(autouse=True)
def objects(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Object storage as a dict."""
    stored: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "put", lambda key, data: stored.__setitem__(key, data))
    monkeypatch.setattr(storage, "get", lambda key: stored[key])
    return stored


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def recruiter() -> User:
    return make_user()


@pytest.fixture
def job(recruiter: User, objects: dict[str, bytes]) -> str:
    return make_job(recruiter, objects)


def test_backfill_gives_each_application_its_creation(
    recruiter: User, objects: dict[str, bytes], job: str
) -> None:
    other = make_user()
    command.downgrade(ALEMBIC, "0009")
    application = add_application(recruiter, objects, job)
    query(recruiter, "UPDATE applications SET stage = 'INTERVIEW' RETURNING id")
    other_application = add_application(other, objects, make_job(other, objects))

    command.upgrade(ALEMBIC, "head")

    # Each Tenant's Applications, though forced RLS binds the migration's owner too.
    for user, row, stage in (
        (recruiter, application, "INTERVIEW"),
        (other, other_application, "APPLIED"),
    ):
        [created_at] = query(user, "SELECT created_at FROM applications")
        assert query(
            user,
            "SELECT from_stage, to_stage, changed_by, changed_at, note"
            " FROM application_stage_history WHERE application_id = :id",
            id=row["id"],
        ) == [
            {
                "from_stage": None,
                "to_stage": stage,
                "changed_by": user.id,
                "changed_at": created_at["created_at"],
                "note": "backfill",
            }
        ]


@pytest.mark.parametrize(
    "statement",
    ["UPDATE application_stage_history SET note = 'x'", "DELETE FROM application_stage_history"],
)
def test_history_is_append_only(
    recruiter: User, objects: dict[str, bytes], job: str, statement: str
) -> None:
    with pytest.raises(ProgrammingError) as exc, tenant_session(recruiter.tenant_id) as session:
        session.execute(text(statement))
    assert isinstance(exc.value.orig, psycopg.errors.InsufficientPrivilege)


STAGES = ["APPLIED", "SCREENING", "SHORTLISTED", "INTERVIEW", "OFFER", "HIRED", "REJECTED"]


async def move(
    client: AsyncClient, user: User, application_id: str, to_stage: str, version: int, **body: Any
) -> Response:
    return await client.patch(
        f"/api/applications/{application_id}/stage",
        headers=user.headers,
        json={"to_stage": to_stage, "version": version, **body},
    )


async def move_many(
    client: AsyncClient, user: User, job_id: str, to_stage: str, *seen: tuple[str, int]
) -> Response:
    return await client.post(
        f"/api/jobs/{job_id}/applications/stage",
        headers=user.headers,
        json={"applications": [{"id": i, "version": v} for i, v in seen], "to_stage": to_stage},
    )


async def cards(client: AsyncClient, user: User, job_id: str) -> dict[str, dict[str, Any]]:
    response = await client.get(f"/api/jobs/{job_id}/applications", headers=user.headers)
    assert response.status_code == 200
    return {a["id"]: a for a in response.json()}


async def history(client: AsyncClient, user: User, application_id: str) -> list[dict[str, Any]]:
    response = await client.get(
        f"/api/applications/{application_id}/stage-history", headers=user.headers
    )
    assert response.status_code == 200
    changes: list[dict[str, Any]] = response.json()
    return [{k: c[k] for k in ("from_stage", "to_stage", "changed_by", "note")} for c in changes]


@pytest.fixture
def application(recruiter: User, objects: dict[str, bytes], job: str) -> str:
    return add_application(recruiter, objects, job)["id"]


async def in_stage(client: AsyncClient, user: User, application_id: str, stage: str) -> int:
    """Move the APPLIED Application to stage; returns its version then."""
    if stage == "APPLIED":
        return 0
    response = await move(client, user, application_id, stage, 0)
    assert response.status_code == 200
    version: int = response.json()["version"]
    return version


async def test_active_stages_move_forward_and_back_and_each_move_is_recorded(
    client: AsyncClient, recruiter: User, job: str, application: str
) -> None:
    admin = make_user("COMPANY_ADMIN", recruiter.tenant_id)

    forward = await move(client, recruiter, application, "INTERVIEW", 0)
    back = await move(client, admin, application, "SCREENING", 1, note="Cần phỏng vấn lại")

    assert forward.json() == {"id": application, "stage": "INTERVIEW", "version": 1}
    assert back.json() == {"id": application, "stage": "SCREENING", "version": 2}
    card = (await cards(client, recruiter, job))[application]
    assert (card["stage"], card["version"]) == ("SCREENING", 2)
    assert await history(client, recruiter, application) == [
        {
            "from_stage": "APPLIED",
            "to_stage": "INTERVIEW",
            "changed_by": str(recruiter.id),
            "note": None,
        },
        {
            "from_stage": "INTERVIEW",
            "to_stage": "SCREENING",
            "changed_by": str(admin.id),
            "note": "Cần phỏng vấn lại",
        },
    ]


async def test_rejecting_keeps_the_reason_and_reopening_drops_it(
    client: AsyncClient, recruiter: User, job: str, application: str
) -> None:
    await move(client, recruiter, application, "REJECTED", 0, rejected_reason="Thiếu Python")
    assert (await cards(client, recruiter, job))[application]["rejected_reason"] == "Thiếu Python"

    response = await move(client, recruiter, application, "OFFER", 1, note="Ứng viên bổ sung CV")

    assert response.status_code == 200
    card = (await cards(client, recruiter, job))[application]
    assert (card["stage"], card["rejected_reason"]) == ("OFFER", None)
    # The history keeps the reason the Application no longer has.
    assert [c["note"] for c in await history(client, recruiter, application)] == [
        "Thiếu Python",
        "Ứng viên bổ sung CV",
    ]


@pytest.mark.parametrize("note", [None, "   "], ids=["none", "blank"])
async def test_reopening_without_a_reason_is_refused(
    client: AsyncClient, recruiter: User, job: str, application: str, note: str | None
) -> None:
    await move(client, recruiter, application, "REJECTED", 0)

    response = await move(client, recruiter, application, "SCREENING", 1, note=note)

    assert response.status_code == 422
    assert (await cards(client, recruiter, job))[application]["stage"] == "REJECTED"


@pytest.mark.parametrize("to_stage", ["HIRED", "REJECTED"])
async def test_a_rejected_application_reopens_only_to_an_active_stage(
    client: AsyncClient, recruiter: User, application: str, to_stage: str
) -> None:
    await move(client, recruiter, application, "REJECTED", 0)

    response = await move(client, recruiter, application, to_stage, 1, note="Lý do")

    assert response.status_code == 409


@pytest.mark.parametrize("to_stage", STAGES)
async def test_hired_is_final(
    client: AsyncClient, recruiter: User, job: str, application: str, to_stage: str
) -> None:
    await move(client, recruiter, application, "HIRED", 0)

    response = await move(client, recruiter, application, to_stage, 1, note="Lý do")

    assert response.status_code == 409
    assert (await cards(client, recruiter, job))[application]["stage"] == "HIRED"


@pytest.mark.parametrize("stage", [s for s in STAGES if s != "HIRED"])
async def test_a_move_to_the_stage_it_is_in_is_refused(
    client: AsyncClient, recruiter: User, application: str, stage: str
) -> None:
    version = await in_stage(client, recruiter, application, stage)

    response = await move(client, recruiter, application, stage, version, note="Lý do")

    assert response.status_code == 409


async def test_the_later_of_two_moves_from_the_same_version_is_refused(
    client: AsyncClient, recruiter: User, job: str, application: str
) -> None:
    other = make_user("RECRUITER", recruiter.tenant_id)

    first, second = await asyncio.gather(
        move(client, recruiter, application, "SCREENING", 0),
        move(client, other, application, "INTERVIEW", 0),
    )

    assert sorted([first.status_code, second.status_code]) == [200, 409]
    winner = "SCREENING" if first.status_code == 200 else "INTERVIEW"
    card = (await cards(client, recruiter, job))[application]
    assert (card["stage"], card["version"]) == (winner, 1)
    assert len(await history(client, recruiter, application)) == 1


async def test_bulk_move_changes_every_application_and_records_each(
    client: AsyncClient, recruiter: User, objects: dict[str, bytes], job: str, application: str
) -> None:
    second = add_application(recruiter, objects, job)["id"]
    await move(client, recruiter, second, "SCREENING", 0)

    response = await move_many(client, recruiter, job, "SHORTLISTED", (application, 0), (second, 1))

    assert response.status_code == 200
    assert sorted((m["id"], m["stage"], m["version"]) for m in response.json()) == sorted(
        [(application, "SHORTLISTED", 1), (second, "SHORTLISTED", 2)]
    )
    assert (await history(client, recruiter, second))[-1] == {
        "from_stage": "SCREENING",
        "to_stage": "SHORTLISTED",
        "changed_by": str(recruiter.id),
        "note": None,
    }


@pytest.mark.parametrize(
    ("spoiler", "code"),
    [
        pytest.param(lambda first, second: ((first, 0), (second, 0)), 409, id="a stale version"),
        pytest.param(lambda first, second: ((first, 0), (str(uuid.uuid4()), 0)), 404, id="none"),
    ],
)
async def test_bulk_move_with_one_bad_application_changes_none(
    client: AsyncClient,
    recruiter: User,
    objects: dict[str, bytes],
    job: str,
    application: str,
    spoiler: Callable[[str, str], tuple[tuple[str, int], ...]],
    code: int,
) -> None:
    second = add_application(recruiter, objects, job)["id"]
    await move(client, recruiter, second, "SCREENING", 0)

    response = await move_many(client, recruiter, job, "OFFER", *spoiler(application, second))

    assert response.status_code == code
    board = await cards(client, recruiter, job)
    assert (board[application]["stage"], board[application]["version"]) == ("APPLIED", 0)
    assert await history(client, recruiter, application) == []


async def test_bulk_move_takes_only_the_jobs_own_applications(
    client: AsyncClient, recruiter: User, objects: dict[str, bytes], application: str
) -> None:
    other_job = make_job(recruiter, objects)

    response = await move_many(client, recruiter, other_job, "SCREENING", (application, 0))

    assert response.status_code == 404


async def test_an_archived_jobs_applications_cannot_move(
    client: AsyncClient, recruiter: User, job: str, application: str
) -> None:
    query(recruiter, "UPDATE jobs SET status = 'ARCHIVED' RETURNING id")

    response = await move(client, recruiter, application, "SCREENING", 0)

    assert response.status_code == 409
    assert (await cards(client, recruiter, job))[application]["version"] == 0


async def test_reviewer_cannot_move_but_reads_the_history_of_an_assigned_job(
    client: AsyncClient, recruiter: User, job: str, application: str
) -> None:
    assigned = make_user("REVIEWER", recruiter.tenant_id)
    unassigned = make_user("REVIEWER", recruiter.tenant_id)
    await client.put(
        f"/api/jobs/{job}/reviewers",
        headers=recruiter.headers,
        json={"user_ids": [str(assigned.id)]},
    )
    await move(client, recruiter, application, "SCREENING", 0)

    assert (await move(client, assigned, application, "INTERVIEW", 1)).status_code == 403
    response = await move_many(client, assigned, job, "INTERVIEW", (application, 1))
    assert response.status_code == 403
    assert len(await history(client, assigned, application)) == 1
    response = await client.get(
        f"/api/applications/{application}/stage-history", headers=unassigned.headers
    )
    assert response.status_code == 404


@pytest.mark.cross_tenant
async def test_other_tenants_application_is_not_found(
    client: AsyncClient, recruiter: User, job: str, application: str
) -> None:
    other = make_user()

    assert (await move(client, other, application, "SCREENING", 0)).status_code == 404
    assert (await move_many(client, other, job, "SCREENING", (application, 0))).status_code == 404
    response = await client.get(
        f"/api/applications/{application}/stage-history", headers=other.headers
    )
    assert response.status_code == 404
    assert (await cards(client, recruiter, job))[application]["version"] == 0


def scored(user: User, application: dict[str, str], job_id: str, total: str | None) -> None:
    """A Scoring Run of the Job, newer than any before, that scored application at total, or
    is still scoring it."""
    query(
        user,
        "WITH r AS ("
        "  INSERT INTO scoring_runs (tenant_id, job_id, trigger_mode, weights,"
        "    criteria_snapshot, model, prompt_version, rubric_version, status, created_at)"
        "  VALUES (:t, :job_id, 'MANUAL', '{}', '{}', 'm', 'p', 'r', 'RUNNING',"
        "    clock_timestamp()) RETURNING id)"
        " INSERT INTO score_results (tenant_id, scoring_run_id, application_id, cv_document_id,"
        "  status, total_score)"
        " SELECT :t, r.id, :id, :cv,"
        "  CASE WHEN CAST(:total AS numeric) IS NULL THEN 'PENDING' ELSE 'SCORED' END,"
        "  CAST(:total AS numeric) FROM r RETURNING id",
        t=user.tenant_id,
        job_id=job_id,
        id=application["id"],
        cv=application["cv_document_id"],
        total=total,
    )


async def test_board_cards_carry_source_version_and_the_latest_total(
    client: AsyncClient, recruiter: User, objects: dict[str, bytes], job: str
) -> None:
    application = add_application(recruiter, objects, job)
    never_scored = add_application(recruiter, objects, job)["id"]
    scored(recruiter, application, job, "61.5")
    scored(recruiter, application, job, "82.25")
    # A run still scoring it leaves the last Total on the card.
    scored(recruiter, application, job, None)

    board = await cards(client, recruiter, job)

    card = board[application["id"]]
    assert (card["source"], card["version"], card["total_score"]) == ("UPLOAD", 0, 82.25)
    assert board[never_scored]["total_score"] is None
