"""Phase 6 M4-M6 API tests: goals, briefings, privacy, maintenance."""
from __future__ import annotations

import pytest
from sqlalchemy import delete

from personal_assistant.core.models import (
    Activity,
    AgentTask,
    Briefing,
    GoalCheckin,
    GoalLink,
    MemoryItem,
    PersonalGoal,
    ProviderCallAudit,
)


@pytest.fixture
async def cleanup(db):
    to_delete: list[tuple[type, int]] = []
    task_ids: list[int] = []
    yield to_delete, task_ids
    for task_id in task_ids:
        try:
            await db.execute(
                delete(Activity)
                .where(Activity.ref_type == "agent_task")
                .where(Activity.ref_id == task_id)
            )
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
    for model, oid in reversed(to_delete):
        try:
            await db.execute(delete(model).where(model.id == oid))
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()


@pytest.mark.asyncio
async def test_goals_routes_detail_checkin_briefing_and_task(client, cleanup):
    to_delete, task_ids = cleanup

    res = await client.post(
        "/goals",
        json={
            "title": "Build a proactive assistant",
            "domain": "project",
            "priority": "high",
            "success_criteria_md": "- Daily review is useful",
        },
    )
    assert res.status_code == 201, res.text
    goal = res.json()
    gid = goal["id"]
    to_delete.append((PersonalGoal, gid))

    res = await client.post(
        f"/goals/{gid}/links",
        json={"target_type": "agent_task", "target_id": 123, "relation": "supports"},
    )
    assert res.status_code == 201, res.text
    to_delete.append((GoalLink, res.json()["id"]))

    res = await client.post(
        f"/goals/{gid}/checkins",
        json={
            "progress_note_md": "Today hub and reminders are stable.",
            "confidence": 0.8,
            "next_actions_json": ["ship briefing", "audit privacy"],
        },
    )
    assert res.status_code == 201, res.text
    to_delete.append((GoalCheckin, res.json()["id"]))

    detail = (await client.get(f"/goals/{gid}")).json()
    assert detail["goal"]["title"] == "Build a proactive assistant"
    assert len(detail["links"]) == 1
    assert len(detail["checkins"]) == 1

    res = await client.post(f"/goals/{gid}/briefing")
    assert res.status_code == 200, res.text
    briefing = res.json()
    assert briefing["kind"] == "goal"
    assert "Build a proactive assistant" in briefing["body_md"]
    to_delete.append((Briefing, briefing["id"]))

    res = await client.post(f"/goals/{gid}/task-draft")
    assert res.status_code == 200, res.text
    task_id = res.json()["task_id"]
    task_ids.append(task_id)
    to_delete.append((AgentTask, task_id))
    task = (await client.get(f"/agent-tasks/{task_id}")).json()
    assert task["status"] == "plan_draft"
    assert task["plan_json"]["source"] == {"type": "personal_goal", "id": gid}


@pytest.mark.asyncio
async def test_today_briefing_list_and_to_task(client, cleanup):
    to_delete, task_ids = cleanup
    res = await client.post("/today/briefing")
    assert res.status_code == 201, res.text
    briefing = res.json()
    assert briefing["kind"] == "today"
    assert "Attention" in briefing["body_md"]
    to_delete.append((Briefing, briefing["id"]))

    res = await client.get("/briefings", params={"kind": "today"})
    assert res.status_code == 200
    assert any(b["id"] == briefing["id"] for b in res.json())

    res = await client.post(f"/briefings/{briefing['id']}/to-task")
    assert res.status_code == 200, res.text
    task_id = res.json()["task_id"]
    task_ids.append(task_id)
    to_delete.append((AgentTask, task_id))
    task = (await client.get(f"/agent-tasks/{task_id}")).json()
    assert task["status"] == "plan_draft"
    assert task["plan_json"]["source"] == {"type": "briefing", "id": briefing["id"]}

    res = await client.post("/briefings/weekly")
    assert res.status_code == 201, res.text
    weekly = res.json()
    assert weekly["kind"] == "weekly"
    assert "Goal Check-ins" in weekly["body_md"]
    to_delete.append((Briefing, weekly["id"]))


@pytest.mark.asyncio
async def test_privacy_preview_audits_and_maintenance(client, db, cleanup):
    to_delete, _task_ids = cleanup
    sensitive = MemoryItem(
        kind="note",
        title="Sensitive token",
        content_md="secret",
        summary="secret",
        enabled=True,
        sensitive=True,
        status="confirmed",
    )
    safe = MemoryItem(
        kind="note",
        title="Safe preference",
        content_md="prefers concise summaries",
        summary="concise summaries",
        enabled=True,
        sensitive=False,
        status="confirmed",
    )
    db.add_all([sensitive, safe])
    await db.commit()
    await db.refresh(sensitive)
    await db.refresh(safe)
    to_delete.append((MemoryItem, sensitive.id))
    to_delete.append((MemoryItem, safe.id))

    res = await client.post(
        "/privacy/preview",
        json={
            "purpose": "chat",
            "provider_type": "openai",
            "include_kb": True,
            "include_memories": True,
            "estimated_message_chars": 500,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["audit_id"] is not None
    assert "kb_chunks" in body["context_types"]
    assert "memories" in body["context_types"]
    assert body["sensitive_memory_excluded"] >= 1
    assert body["will_send_raw_sensitive_memory"] is False
    to_delete.append((ProviderCallAudit, body["audit_id"]))

    audits = (await client.get("/privacy/audits")).json()
    assert any(a["id"] == body["audit_id"] for a in audits)

    report = (await client.get("/maintenance/health-report")).json()
    assert "summary" in report
    assert "recommendations" in report
