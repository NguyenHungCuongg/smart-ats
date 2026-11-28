"""Workspace Dashboard summary endpoint tests under ats_app RLS (SRS §2.1, ADR-0001)."""

import json
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app import audit, jobs, scoring_runs, storage, uploads
from app.db import tenant_session
from app.main import app
from smart_ats_scoring import pricing
from tests.test_jobs import JD, PARSED, FakeLlm, make_user
from tests.test_scoring_runs import (
    MODEL,
    SCORED,
    FakeEmbedder,
    add_application,
    calibrate_embedding,
    make_job,
)

pytestmark = pytest.mark.usefixtures("database")


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!")


@pytest.fixture(autouse=True)
def objects(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    stored: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "put", lambda key, data: stored.__setitem__(key, data))
    monkeypatch.setattr(storage, "get", lambda key: stored[key])
    for task in (jobs.parse, uploads.parse_cv, scoring_runs.score_application):
        monkeypatch.setattr(task, "delay", lambda *args: None)
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "test-model")
    monkeypatch.setitem(
        pricing.PRICES,
        "test-model",
        pricing.Price(Decimal(1), Decimal(1), Decimal(1)),
    )
    monkeypatch.setenv("LLM_REASONING_MODEL", MODEL)
    monkeypatch.setitem(pricing.PRICES, MODEL, pricing.Price(Decimal(1), Decimal(1), Decimal(1)))
    calibrate_embedding(monkeypatch)
    return stored


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_dashboard_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/dashboard")).status_code == 401
    assert (
        await client.get("/api/dashboard", headers={"Authorization": "Bearer invalid"})
    ).status_code == 401


async def test_dashboard_empty_workspace_returns_zeroed_summary(client: AsyncClient) -> None:
    admin = make_user("COMPANY_ADMIN")
    res = await client.get("/api/dashboard", headers=admin.headers)
    assert res.status_code == 200
    assert res.json() == {
        "total_jobs": 0,
        "jobs_by_status": {
            "DRAFT": 0,
            "PUBLISHED": 0,
            "PAUSED": 0,
            "CLOSED": 0,
            "ARCHIVED": 0,
        },
        "total_applications": 0,
        "pipeline_by_stage": {
            "APPLIED": 0,
            "SCREENING": 0,
            "SHORTLISTED": 0,
            "INTERVIEW": 0,
            "OFFER": 0,
            "HIRED": 0,
            "REJECTED": 0,
        },
        "action_items": {
            "pending_criteria_jobs": {"count": 0, "items": []},
            "failed_parse_jobs": {"count": 0, "items": []},
            "unscored_jobs": {"count": 0, "items": []},
            "new_applications_count": 0,
        },
        "recent_jobs": [],
        "recent_activity": [],
    }


@pytest.mark.usefixtures("redis")
async def test_dashboard_aggregates_statuses_stages_actions_recent_jobs_and_activity(
    client: AsyncClient,
    objects: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = make_user("COMPANY_ADMIN")
    recruiter = make_user("RECRUITER", admin.tenant_id)
    former_recruiter = make_user("RECRUITER", admin.tenant_id)
    reviewer_member = make_user("REVIEWER", admin.tenant_id)

    # 1. Six DRAFT jobs whose JD parse succeeded, criteria not yet confirmed -> count=6, items=5
    monkeypatch.setattr(jobs, "llm_from_env", lambda model, **_: FakeLlm(PARSED))
    pending_criteria_ids: list[str] = []
    for i in range(6):
        created = await client.post(
            "/api/jobs",
            headers=former_recruiter.headers,
            data={"text": f"Backend Engineer {i}\n{JD}"},
        )
        assert created.status_code == 202
        jid = created.json()["id"]
        jobs.parse.apply(args=(str(admin.tenant_id), jid, str(former_recruiter.id))).get()
        pending_criteria_ids.append(jid)

    # 2. Failed parse DRAFT job
    failed_created = await client.post(
        "/api/jobs", headers=recruiter.headers, data={"text": "Broken JD"}
    )
    failed_job_id = failed_created.json()["id"]
    with tenant_session(admin.tenant_id) as session:
        jobs.fail_parse(session, uuid.UUID(failed_job_id), recruiter.id, "LLM_UNAVAILABLE")

    # 3. Confirmed PUBLISHED job with 2 applications -> initially unscored, then scored, then +1 app
    scored_job_id = make_job(recruiter, objects)
    await client.post(
        f"/api/jobs/{scored_job_id}/transitions",
        headers=recruiter.headers,
        json={"action": "publish"},
    )
    app1 = add_application(recruiter, objects, scored_job_id)
    app2 = add_application(recruiter, objects, scored_job_id)

    # Move app2 -> INTERVIEW
    move_res = await client.patch(
        f"/api/applications/{app2['id']}/stage",
        headers=recruiter.headers,
        json={"to_stage": "INTERVIEW", "version": 0},
    )
    assert move_res.status_code == 200

    # Before scoring: scored_job_id is in unscored_jobs
    before_score = (await client.get("/api/dashboard", headers=recruiter.headers)).json()
    assert [j["id"] for j in before_score["action_items"]["unscored_jobs"]["items"]] == [
        scored_job_id
    ]

    # Score both applications on scored_job_id -> leaves unscored_jobs
    monkeypatch.setattr(scoring_runs, "llm_from_env", lambda model, **_: FakeLlm(SCORED))
    monkeypatch.setattr(scoring_runs, "embedder_from_env", lambda model, **_: FakeEmbedder())
    run_res = await client.post(
        f"/api/jobs/{scored_job_id}/scoring-runs", headers=recruiter.headers
    )
    assert run_res.status_code == 202
    run_id = run_res.json()["run_id"]
    for aid in (app1["id"], app2["id"]):
        scoring_runs.score_application.apply(args=(str(admin.tenant_id), run_id, aid)).get()

    after_score = (await client.get("/api/dashboard", headers=recruiter.headers)).json()
    assert after_score["action_items"]["unscored_jobs"] == {"count": 0, "items": []}

    # Add a 3rd application (OFFER) after latest run -> scored_job_id re-enters unscored_jobs
    app3 = add_application(recruiter, objects, scored_job_id)
    await client.patch(
        f"/api/applications/{app3['id']}/stage",
        headers=recruiter.headers,
        json={"to_stage": "OFFER", "version": 0},
    )

    # 4. Archived job with an unscored application (HIRED) -> excluded from unscored_jobs
    archived_job_id = make_job(recruiter, objects)
    arch_app = add_application(recruiter, objects, archived_job_id)
    await client.patch(
        f"/api/applications/{arch_app['id']}/stage",
        headers=recruiter.headers,
        json={"to_stage": "HIRED", "version": 0},
    )
    for action in ("publish", "close", "archive"):
        assert (
            await client.post(
                f"/api/jobs/{archived_job_id}/transitions",
                headers=recruiter.headers,
                json={"action": action},
            )
        ).status_code == 200

    # 5. Revoke former_recruiter and change reviewer_member role (creates member.* audit entries)
    assert (
        await client.patch(
            f"/api/members/{reviewer_member.id}",
            headers=admin.headers,
            json={"role": "RECRUITER"},
        )
    ).status_code == 200
    assert (
        await client.delete(f"/api/members/{former_recruiter.id}", headers=admin.headers)
    ).status_code == 204

    admin_res = await client.get("/api/dashboard", headers=admin.headers)
    assert admin_res.status_code == 200
    admin_data: dict[str, Any] = admin_res.json()

    assert admin_data["total_jobs"] == 9
    assert admin_data["jobs_by_status"] == {
        "DRAFT": 7,
        "PUBLISHED": 1,
        "PAUSED": 0,
        "CLOSED": 0,
        "ARCHIVED": 1,
    }
    assert admin_data["total_applications"] == 4
    assert admin_data["pipeline_by_stage"] == {
        "APPLIED": 1,
        "SCREENING": 0,
        "SHORTLISTED": 0,
        "INTERVIEW": 1,
        "OFFER": 1,
        "HIRED": 1,
        "REJECTED": 0,
    }
    assert admin_data["action_items"]["new_applications_count"] == 1
    assert admin_data["action_items"]["pending_criteria_jobs"]["count"] == 6
    assert len(admin_data["action_items"]["pending_criteria_jobs"]["items"]) == 5
    assert [j["id"] for j in admin_data["action_items"]["pending_criteria_jobs"]["items"]] == list(
        reversed(pending_criteria_ids[1:])
    )
    assert admin_data["action_items"]["failed_parse_jobs"]["count"] == 1
    assert [j["id"] for j in admin_data["action_items"]["failed_parse_jobs"]["items"]] == [
        failed_job_id
    ]
    assert admin_data["action_items"]["unscored_jobs"]["count"] == 1
    assert [j["id"] for j in admin_data["action_items"]["unscored_jobs"]["items"]] == [
        scored_job_id
    ]

    assert len(admin_data["recent_jobs"]) == 5
    assert admin_data["recent_jobs"][0]["id"] == archived_job_id
    assert admin_data["recent_jobs"][0]["criteria_confirmed"] is True
    assert admin_data["recent_jobs"][0]["application_count"] == 1

    # Recent activity: capped at 10, newest-first, never exposes ip or request_id.
    assert len(admin_data["recent_activity"]) == 10
    serialized_activity = json.dumps(admin_data["recent_activity"])
    assert '"ip"' not in serialized_activity
    assert '"request_id"' not in serialized_activity
    admin_actions = [e["action"] for e in admin_data["recent_activity"]]
    assert "member.revoked" in admin_actions
    assert "member.role_changed" in admin_actions

    # Recruiter sees full Workspace metrics, without Company-Admin-only member.* audit rows.
    recruiter_data: dict[str, Any] = (
        await client.get("/api/dashboard", headers=recruiter.headers)
    ).json()
    assert recruiter_data["total_jobs"] == 9
    assert recruiter_data["total_applications"] == 4
    recruiter_actions = [e["action"] for e in recruiter_data["recent_activity"]]
    assert "member.revoked" not in recruiter_actions
    assert "member.role_changed" not in recruiter_actions

    # Revoked member's full_name remains visible on audit entries they authored.
    with tenant_session(admin.tenant_id) as session:
        audit.record(
            session,
            actor_type="USER",
            actor_user_id=former_recruiter.id,
            action="job.metadata_changed",
            entity_id=uuid.UUID(scored_job_id),
            before={"location": None},
            after={"location": "HCM"},
        )
    refreshed = (await client.get("/api/dashboard", headers=recruiter.headers)).json()
    assert refreshed["recent_activity"][0]["actor"] == {
        "id": str(former_recruiter.id),
        "full_name": "Test User",
    }


async def test_dashboard_reviewer_sees_only_assigned_scope_and_no_management_actions(
    client: AsyncClient, objects: dict[str, bytes]
) -> None:
    admin = make_user("COMPANY_ADMIN")
    recruiter = make_user("RECRUITER", admin.tenant_id)
    reviewer = make_user("REVIEWER", admin.tenant_id)

    assigned_job = make_job(recruiter, objects)
    unassigned_job = make_job(recruiter, objects)

    # Fail another draft job to populate workspace management action_items
    extra_draft = (
        await client.post("/api/jobs", headers=recruiter.headers, data={"text": JD})
    ).json()["id"]
    with tenant_session(admin.tenant_id) as session:
        jobs.fail_parse(session, uuid.UUID(extra_draft), recruiter.id, "PARSE_FAILED")

    assigned_app = add_application(recruiter, objects, assigned_job)
    unassigned_app1 = add_application(recruiter, objects, unassigned_job)
    unassigned_app2 = add_application(recruiter, objects, unassigned_job)
    await client.patch(
        f"/api/applications/{unassigned_app2['id']}/stage",
        headers=recruiter.headers,
        json={"to_stage": "SCREENING", "version": 0},
    )

    await client.put(
        f"/api/jobs/{assigned_job}/reviewers",
        headers=recruiter.headers,
        json={"user_ids": [str(reviewer.id)]},
    )
    # Record an application stage change on assigned_job so Reviewer has both job & app activity
    await client.patch(
        f"/api/applications/{assigned_app['id']}/stage",
        headers=recruiter.headers,
        json={"to_stage": "SHORTLISTED", "version": 0},
    )
    # Also add asecond APPLIED application on assigned_job
    add_application(recruiter, objects, assigned_job)
    _ = unassigned_app1

    res = await client.get("/api/dashboard", headers=reviewer.headers)
    assert res.status_code == 200
    data = res.json()

    assert data["total_jobs"] == 1
    assert data["jobs_by_status"] == {
        "DRAFT": 1,
        "PUBLISHED": 0,
        "PAUSED": 0,
        "CLOSED": 0,
        "ARCHIVED": 0,
    }
    assert data["total_applications"] == 2
    assert data["pipeline_by_stage"] == {
        "APPLIED": 1,
        "SCREENING": 0,
        "SHORTLISTED": 1,
        "INTERVIEW": 0,
        "OFFER": 0,
        "HIRED": 0,
        "REJECTED": 0,
    }
    # Management action_items are empty for REVIEWER
    assert data["action_items"] == {
        "pending_criteria_jobs": {"count": 0, "items": []},
        "failed_parse_jobs": {"count": 0, "items": []},
        "unscored_jobs": {"count": 0, "items": []},
        "new_applications_count": 1,
    }
    assert [j["id"] for j in data["recent_jobs"]] == [assigned_job]
    # Reviewer never sees unassigned job/app or workspace member activity
    activity_actions = [e["action"] for e in data["recent_activity"]]
    assert "application.stage_changed" in activity_actions
    assert "job.reviewers_changed" in activity_actions
    assert all(e["after"] != {"stage": "SCREENING"} for e in data["recent_activity"])


@pytest.mark.cross_tenant
async def test_dashboard_isolates_tenants_under_rls(
    client: AsyncClient, objects: dict[str, bytes]
) -> None:
    tenant_a = make_user("COMPANY_ADMIN")
    tenant_b = make_user("COMPANY_ADMIN")

    job_a = make_job(tenant_a, objects)
    add_application(tenant_a, objects, job_a)
    with tenant_session(tenant_a.tenant_id) as session:
        audit.record(
            session,
            actor_type="USER",
            actor_user_id=tenant_a.id,
            action="job.created",
            entity_id=uuid.UUID(job_a),
            after={"status": "DRAFT"},
        )

    res_b = await client.get("/api/dashboard", headers=tenant_b.headers)
    assert res_b.status_code == 200
    data_b = res_b.json()
    assert data_b["total_jobs"] == 0
    assert data_b["total_applications"] == 0
    assert data_b["recent_jobs"] == []
    assert data_b["recent_activity"] == []
    assert job_a not in json.dumps(data_b)
