"""Score a Job's Applications in a Scoring Run and read its Fit-Gap Reports (FR-A1.3).

Object storage, the LLM and the broker are faked; the API, the scoring task and PostgreSQL
are real.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text

from app import events, scoring_runs, storage
from app.auth import _redis
from app.db import tenant_session
from app.main import app
from smart_ats_scoring import pricing
from tests.test_jobs import FakeLlm, UnusableLlm, User, make_user
from tests.test_uploads import PROFILE, docx

pytestmark = pytest.mark.usefixtures("database")

MODEL = "test-reasoning"


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!")


@pytest.fixture(autouse=True)
def reasoning_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_REASONING_MODEL", MODEL)
    monkeypatch.setitem(
        pricing.PRICES, MODEL, pricing.Price(Decimal("2"), Decimal("0.2"), Decimal("10"))
    )


@pytest.fixture(autouse=True)
def objects(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Object storage as a dict."""
    stored: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "put", lambda key, data: stored.__setitem__(key, data))
    monkeypatch.setattr(storage, "get", lambda key: stored[key])
    return stored


@pytest.fixture(autouse=True)
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Scoring tasks sent to the broker, as their arguments."""
    sent: list[tuple[str, ...]] = []
    monkeypatch.setattr(scoring_runs.score_application, "delay", lambda *args: sent.append(args))
    return sent


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def recruiter() -> User:
    return make_user()


JD = "Backend Developer. Bắt buộc: Python, PostgreSQL. Ưu tiên: Docker. 3 năm kinh nghiệm."
CRITERIA = {
    "skills": [
        {"name": "Python", "must_have": True},
        {"name": "PostgreSQL", "must_have": True},
        {"name": "Docker", "must_have": False},
    ],
    "min_years_experience": 3,
    "education": None,
    "responsibilities": [],
    "salary_range": None,
}
CV = docx("Backend Developer tại Acme. Xây dựng API bằng Python. Làm việc nhóm 5 người.")


def query(user: User, sql: str, **params: Any) -> list[dict[str, Any]]:
    with tenant_session(user.tenant_id) as session:
        return [dict(row._mapping) for row in session.execute(text(sql), params)]


def make_job(user: User, objects: dict[str, bytes], confirmed: bool = True) -> str:
    """A Job parsed from JD, its criteria confirmed unless told otherwise."""
    key = f"t/{user.tenant_id}/jd/{uuid.uuid4()}.txt"
    objects[key] = JD.encode()
    [job] = query(
        user,
        "INSERT INTO jobs (tenant_id, title, level, status, jd_document_key, parse_status,"
        "  criteria, criteria_confirmed_at, created_by,"
        "  weight_technical, weight_soft_skills, weight_experience)"
        " VALUES (:tenant_id, 'Backend Developer', 'MID', 'DRAFT', :key, 'SUCCEEDED',"
        "  CAST(:criteria AS jsonb), CASE WHEN :confirmed THEN now() END, :user_id,"
        "  0.55, 0.15, 0.30) RETURNING id",
        tenant_id=user.tenant_id,
        key=key,
        criteria=json.dumps(CRITERIA),
        confirmed=confirmed,
        user_id=user.id,
    )
    return str(job["id"])


def add_application(
    user: User, objects: dict[str, bytes], job_id: str, cv: bytes = CV
) -> dict[str, str]:
    """A Candidate with a parsed CV Document, applied to the Job; returns their ids."""
    key = f"t/{user.tenant_id}/cv/{uuid.uuid4()}.docx"
    objects[key] = cv
    [row] = query(
        user,
        "WITH c AS ("
        "  INSERT INTO candidates (tenant_id, full_name, consent_source, consent_at,"
        "    last_activity_at)"
        "  VALUES (:tenant_id, 'Nguyễn Văn An', 'RECRUITER_ATTESTED', now(), now())"
        "  RETURNING id),"
        " d AS ("
        "  INSERT INTO cv_documents (tenant_id, candidate_id, storage_key, file_name, mime_type,"
        "    sha256, parse_status, parsed_profile)"
        "  SELECT :tenant_id, c.id, :key, 'an.docx', 'docx', :sha, 'PARSED',"
        "    CAST(:profile AS jsonb) FROM c RETURNING id, candidate_id)"
        " INSERT INTO applications (tenant_id, job_id, candidate_id, cv_document_id, source,"
        "  stage)"
        " SELECT :tenant_id, :job_id, d.candidate_id, d.id, 'UPLOAD', 'APPLIED' FROM d"
        " RETURNING id, cv_document_id",
        tenant_id=user.tenant_id,
        key=key,
        sha=uuid.uuid4().hex,
        profile=json.dumps(PROFILE),
        job_id=job_id,
    )
    return {"id": str(row["id"]), "cv_document_id": str(row["cv_document_id"])}


@pytest.fixture
def job(recruiter: User, objects: dict[str, bytes]) -> str:
    return make_job(recruiter, objects)


@pytest.fixture
def application(recruiter: User, objects: dict[str, bytes], job: str) -> dict[str, str]:
    return add_application(recruiter, objects, job)


async def start(client: AsyncClient, user: User, job_id: str) -> Response:
    return await client.post(f"/api/jobs/{job_id}/scoring-runs", headers=user.headers)


async def latest(client: AsyncClient, user: User, job_id: str) -> Response:
    return await client.get(f"/api/jobs/{job_id}/scoring-runs/latest", headers=user.headers)


async def test_starting_a_run_freezes_the_job_and_enqueues_each_application(
    client: AsyncClient,
    recruiter: User,
    job: str,
    application: dict[str, str],
    enqueued: list[tuple[str, ...]],
) -> None:
    response = await start(client, recruiter, job)

    assert response.status_code == 202
    run_id = response.json()["run_id"]
    assert enqueued == [(str(recruiter.tenant_id), run_id, application["id"])]
    run = (await latest(client, recruiter, job)).json()
    assert run | {"created_at": None, "results": None} == {
        "id": run_id,
        "status": "RUNNING",
        "running": True,
        "weights": {"technical": 55, "soft_skills": 15, "experience": 30},
        "model": MODEL,
        "prompt_version": "v1",
        "rubric_version": "v0",
        "created_at": None,
        "completed_at": None,
        "results": None,
    }
    [result] = run["results"]
    assert {k: result[k] for k in ("application_id", "status", "total_score")} == {
        "application_id": application["id"],
        "status": "PENDING",
        "total_score": None,
    }
    # The CV scored is the Application's CV when the run started.
    assert result["cv_document_id"] == result["current_cv_document_id"]
    assert result["cv_document_id"] == application["cv_document_id"]


# The scoring task, run in-process as a worker would run what the API enqueued.

# Quotes the CV, except the Experience one; the Gap quotes the JD.
SCORED: dict[str, Any] = {
    "technical": {"evidence": ["Xây dựng API bằng Python"], "reason": "Có Python", "grade": 4},
    "soft_skills": {"evidence": ["Làm việc nhóm"], "reason": "Làm việc nhóm", "grade": 3},
    "experience": {"evidence": ["10 năm ở Google"], "reason": "Đủ năm", "grade": 3},
    "strengths": [{"text": "Python vững", "evidence": ["Xây dựng API bằng Python"]}],
    "gaps": [{"text": "Thiếu PostgreSQL", "evidence": ["Bắt buộc: Python, PostgreSQL"]}],
    "recommendations": [{"text": "Học PostgreSQL trong 1 tháng", "evidence": []}],
}


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> FakeLlm:
    fake = FakeLlm(SCORED, MODEL)
    # Only the run's own model: a task reading the environment again fails with KeyError.
    monkeypatch.setattr(scoring_runs, "llm_from_env", lambda model: {MODEL: fake}[model])
    return fake


def run_scoring(enqueued: list[tuple[str, ...]]) -> None:
    while enqueued:
        scoring_runs.score_application.apply(args=enqueued.pop(0)).get()


@pytest.mark.usefixtures("redis")
async def test_scoring_writes_the_axis_scores_coverage_and_fit_gap_report(
    client: AsyncClient,
    recruiter: User,
    job: str,
    application: dict[str, str],
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = (await start(client, recruiter, job)).json()["run_id"]
    # The task scores with the run's model, whatever the environment says by now.
    monkeypatch.setenv("LLM_REASONING_MODEL", "changed-model")

    run_scoring(enqueued)

    run = (await latest(client, recruiter, job)).json()
    assert (run["status"], run["running"]) == ("COMPLETED", False)
    assert run["completed_at"] is not None
    [result] = run["results"]
    # Must-have Coverage 1/2; Technical 0.6 x 50 + 0.4 x 75; grade 3 is 50.
    # Total 0.55 x 60 + 0.15 x 50 + 0.30 x 50.
    assert {
        k: result[k]
        for k in (
            "status",
            "technical_score",
            "soft_skills_score",
            "experience_score",
            "total_score",
            "must_have_coverage",
            "must_have_detail",
            "grounding_rate",
            "error_code",
        )
    } == {
        "status": "SCORED",
        "technical_score": 60,
        "soft_skills_score": 50,
        "experience_score": 50,
        "total_score": 55.5,
        "must_have_coverage": 0.5,
        "must_have_detail": {"matched": ["Python"], "missing": ["PostgreSQL"]},
        "grounding_rate": 0.8,
        "error_code": None,
    }
    report = result["fit_gap_report"]
    assert [
        c["grounded"] for part in ("strengths", "gaps", "recommendations") for c in report[part]
    ] == [
        True,
        True,
        False,
    ]
    assert result["rubric_grades"]["experience"] | {"reason": None} == {
        "evidence": [],
        "dropped": ["10 năm ở Google"],
        "grounded": False,
        "grade": 3,
        "reason": None,
    }
    [entry] = query(recruiter, "SELECT user_id, feature, model, ref_type FROM ai_usage_entries")
    assert entry == {
        "user_id": recruiter.id,
        "feature": "SCORING",
        "model": MODEL,
        "ref_type": "score_result",
    }
    assert run["id"] == run_id


async def test_job_without_confirmed_criteria_cannot_be_scored(
    client: AsyncClient, recruiter: User, objects: dict[str, bytes]
) -> None:
    job_id = make_job(recruiter, objects, confirmed=False)
    add_application(recruiter, objects, job_id)

    assert (await start(client, recruiter, job_id)).status_code == 409
    assert (await latest(client, recruiter, job_id)).status_code == 404


async def test_job_without_applications_cannot_be_scored(
    client: AsyncClient, recruiter: User, job: str
) -> None:
    assert (await start(client, recruiter, job)).status_code == 409
    assert (await latest(client, recruiter, job)).status_code == 404


@pytest.mark.usefixtures("application")
async def test_job_being_scored_cannot_be_scored_again(
    client: AsyncClient, recruiter: User, job: str, enqueued: list[tuple[str, ...]]
) -> None:
    first = (await start(client, recruiter, job)).json()["run_id"]

    assert (await start(client, recruiter, job)).status_code == 409
    assert (await latest(client, recruiter, job)).json()["id"] == first
    assert len(enqueued) == 1


@pytest.mark.usefixtures("application")
async def test_long_run_still_scoring_keeps_blocking_a_new_one(
    client: AsyncClient, recruiter: User, job: str
) -> None:
    long = (await start(client, recruiter, job)).json()["run_id"]
    query(
        recruiter,
        "UPDATE scoring_runs SET created_at = now() - interval '2 hours' WHERE id = :id"
        " RETURNING id",
        id=long,
    )

    assert (await start(client, recruiter, job)).status_code == 409
    run = (await latest(client, recruiter, job)).json()
    assert (run["id"], run["status"], run["running"]) == (long, "RUNNING", True)


@pytest.mark.usefixtures("application")
async def test_concurrent_starts_create_one_run(
    client: AsyncClient, recruiter: User, job: str, enqueued: list[tuple[str, ...]]
) -> None:
    responses = await asyncio.gather(*(start(client, recruiter, job) for _ in range(2)))

    assert sorted(r.status_code for r in responses) == [202, 409]
    assert len(query(recruiter, "SELECT id FROM scoring_runs")) == 1
    assert len(enqueued) == 1


@pytest.mark.usefixtures("application")
async def test_model_without_a_price_is_refused_before_any_run_is_created(
    client: AsyncClient,
    recruiter: User,
    job: str,
    enqueued: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_REASONING_MODEL", "unpriced-model")

    assert (await start(client, recruiter, job)).status_code == 503
    assert query(recruiter, "SELECT id FROM scoring_runs") == []
    assert enqueued == []


@pytest.mark.cross_tenant
@pytest.mark.usefixtures("application")
async def test_other_tenants_job_is_not_found_on_both_endpoints(
    client: AsyncClient, recruiter: User, job: str, enqueued: list[tuple[str, ...]]
) -> None:
    await start(client, recruiter, job)
    other = make_user()

    assert (await start(client, other, job)).status_code == 404
    assert (await latest(client, other, job)).status_code == 404
    assert len(query(recruiter, "SELECT id FROM scoring_runs")) == 1
    assert len(enqueued) == 1


@pytest.mark.cross_tenant
@pytest.mark.usefixtures("application")
async def test_scoring_cannot_reach_another_tenants_result(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    await start(client, recruiter, job)
    [(_, run_id, application_id)] = enqueued

    scoring_runs.score_application.apply(
        args=(str(make_user().tenant_id), run_id, application_id)
    ).get()

    assert llm.calls == 0
    [result] = (await latest(client, recruiter, job)).json()["results"]
    assert result["status"] == "PENDING"


@pytest.mark.usefixtures("redis")
async def test_run_with_a_failed_result_ends_partial_once_no_result_is_pending(
    client: AsyncClient,
    recruiter: User,
    job: str,
    objects: dict[str, bytes],
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    readable = add_application(recruiter, objects, job)
    damaged = add_application(recruiter, objects, job, b"%PDF-1.7\n damaged")
    await start(client, recruiter, job)
    tasks = {args[2]: args for args in enqueued}

    scoring_runs.score_application.apply(args=tasks[damaged["id"]]).get()

    run = (await latest(client, recruiter, job)).json()
    assert (run["status"], run["completed_at"]) == ("RUNNING", None)

    scoring_runs.score_application.apply(args=tasks[readable["id"]]).get()

    run = (await latest(client, recruiter, job)).json()
    assert run["status"] == "PARTIAL" and run["completed_at"] is not None
    assert {r["application_id"]: (r["status"], r["error_code"]) for r in run["results"]} == {
        readable["id"]: ("SCORED", None),
        damaged["id"]: ("FAILED", "UNREADABLE"),
    }
    assert llm.calls == 1


class FailingLlm(FakeLlm):
    def structured(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise RuntimeError("provider down")


@pytest.mark.usefixtures("redis", "application")
async def test_run_whose_every_result_failed_is_still_partial(
    client: AsyncClient,
    recruiter: User,
    job: str,
    enqueued: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FailingLlm(SCORED, MODEL)
    monkeypatch.setattr(scoring_runs, "llm_from_env", lambda model: llm)
    await start(client, recruiter, job)

    run_scoring(enqueued)

    run = (await latest(client, recruiter, job)).json()
    assert run["status"] == "PARTIAL"
    assert [(r["status"], r["error_code"]) for r in run["results"]] == [
        ("FAILED", "SCORING_FAILED")
    ]
    # Nothing came back to bill.
    assert query(recruiter, "SELECT id FROM ai_usage_entries") == []


@pytest.mark.usefixtures("redis")
async def test_billed_response_it_cannot_use_fails_the_result_and_is_recorded_once(
    client: AsyncClient,
    recruiter: User,
    job: str,
    application: dict[str, str],
    enqueued: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scoring_runs, "llm_from_env", lambda model: UnusableLlm({}, MODEL))
    await start(client, recruiter, job)
    [args] = enqueued
    run_scoring(enqueued)

    scoring_runs.score_application.apply(args=args).get()  # redelivered

    run = (await latest(client, recruiter, job)).json()
    assert [(r["status"], r["error_code"]) for r in run["results"]] == [
        ("FAILED", "SCORING_FAILED")
    ]
    [result] = query(recruiter, "SELECT id FROM score_results")
    assert query(
        recruiter, "SELECT feature, input_tokens, ref_type, ref_id FROM ai_usage_entries"
    ) == [
        {
            "feature": "SCORING",
            "input_tokens": 1000,
            "ref_type": "score_result",
            "ref_id": result["id"],
        }
    ]


@pytest.mark.usefixtures("redis", "application")
async def test_redelivered_task_scores_nothing_twice(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    await start(client, recruiter, job)
    [args] = enqueued
    run_scoring(enqueued)

    scoring_runs.score_application.apply(args=args).get()

    assert llm.calls == 1
    assert len(query(recruiter, "SELECT id FROM ai_usage_entries")) == 1
    assert len(query(recruiter, "SELECT id FROM score_results")) == 1
    assert (await latest(client, recruiter, job)).json()["status"] == "COMPLETED"


@pytest.mark.usefixtures("redis")
async def test_scoring_announces_each_result_to_the_recruiter(
    client: AsyncClient,
    recruiter: User,
    job: str,
    application: dict[str, str],
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    run_id = (await start(client, recruiter, job)).json()["run_id"]
    async with _redis().pubsub() as sub:
        await sub.subscribe(events.channel(recruiter.tenant_id, recruiter.id))
        assert (await sub.get_message(timeout=5) or {})["type"] == "subscribe"

        run_scoring(enqueued)

        message = await sub.get_message(timeout=5)
    assert message is not None
    assert json.loads(message["data"]) == {
        "event": "scoring.result",
        "data": {
            "job_id": job,
            "run_id": run_id,
            "application_id": application["id"],
            "status": "SCORED",
        },
    }


@pytest.mark.usefixtures("redis", "application")
async def test_scoring_uses_the_job_as_frozen_when_the_run_started(
    client: AsyncClient,
    recruiter: User,
    job: str,
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    await start(client, recruiter, job)
    # The Recruiter drops the PostgreSQL must-have and reweighs before the task runs.
    query(
        recruiter,
        "UPDATE jobs SET criteria = jsonb_set(criteria, '{skills,1,must_have}', 'false'),"
        "  weight_technical = 1, weight_soft_skills = 0, weight_experience = 0 RETURNING id",
    )

    run_scoring(enqueued)

    run = (await latest(client, recruiter, job)).json()
    assert run["weights"] == {"technical": 55, "soft_skills": 15, "experience": 30}
    [result] = run["results"]
    assert (result["must_have_coverage"], result["total_score"]) == (0.5, 55.5)


@pytest.mark.usefixtures("redis")
async def test_latest_shows_the_newest_run_and_whether_the_cv_changed_since(
    client: AsyncClient,
    recruiter: User,
    job: str,
    objects: dict[str, bytes],
    application: dict[str, str],
    llm: FakeLlm,
    enqueued: list[tuple[str, ...]],
) -> None:
    await start(client, recruiter, job)
    run_scoring(enqueued)
    second = (await start(client, recruiter, job)).json()["run_id"]
    run_scoring(enqueued)
    # A new CV of the same Candidate replaces the Application's (FR-A1.2).
    other = add_application(recruiter, objects, make_job(recruiter, objects))
    query(
        recruiter,
        "UPDATE applications SET cv_document_id = :cv WHERE id = :id RETURNING id",
        cv=other["cv_document_id"],
        id=application["id"],
    )

    run = (await latest(client, recruiter, job)).json()

    assert run["id"] == second
    [result] = run["results"]
    assert result["cv_document_id"] == application["cv_document_id"]
    assert result["current_cv_document_id"] == other["cv_document_id"]


@pytest.mark.usefixtures("redis", "application")
@pytest.mark.parametrize("part", ["strengths", "gaps", "recommendations"])
async def test_report_missing_a_fit_gap_part_fails_the_result_and_is_billed(
    client: AsyncClient,
    recruiter: User,
    job: str,
    enqueued: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
    part: str,
) -> None:
    # FR-A1.3: every Score Result has all three parts of the Fit-Gap Report.
    fake = FakeLlm(SCORED | {part: []}, MODEL)
    monkeypatch.setattr(scoring_runs, "llm_from_env", lambda model: fake)
    await start(client, recruiter, job)

    run_scoring(enqueued)

    [result] = (await latest(client, recruiter, job)).json()["results"]
    assert (result["status"], result["error_code"], result["fit_gap_report"]) == (
        "FAILED",
        "SCORING_FAILED",
        None,
    )
    assert len(query(recruiter, "SELECT id FROM ai_usage_entries")) == 1
