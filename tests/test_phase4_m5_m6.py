"""第四阶段 M5/M6：任务计划 2.0、Provider 路由和备份治理。"""
from __future__ import annotations

from pathlib import Path
import subprocess

import pytest


async def _project(client, tmp_path, name: str = "m5proj") -> tuple[int, Path]:
    root = tmp_path / name
    root.mkdir()
    (root / "a.py").write_text("def v():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    res = await client.post("/projects", json={"name": name, "root_path": str(root)})
    assert res.status_code == 201, res.text
    return res.json()["id"], root


@pytest.mark.asyncio
async def test_task_plan_draft_edit_approve_and_run_boundary(client, tmp_path):
    pid, _ = await _project(client, tmp_path)
    res = await client.post(
        "/agent-tasks/plan",
        json={"title": "分析测试失败", "goal": "帮我分析这个项目为什么测试失败", "project_id": pid},
    )
    assert res.status_code == 201, res.text
    task = res.json()
    assert task["status"] == "plan_draft"
    assert len(task["steps"]) >= 2

    res = await client.post(f"/agent-tasks/{task['id']}/run")
    assert res.status_code == 400
    assert "批准" in res.json()["detail"]

    edited_steps = [
        {"title": "先看状态", "tool_name": "get_git_status", "input_json": {"project_id": pid}},
        {
            "title": "运行测试",
            "tool_name": "run_whitelisted_command",
            "input_json": {"project_id": pid, "command": "pytest -q"},
        },
    ]
    res = await client.patch(
        f"/agent-tasks/{task['id']}/plan",
        json={"steps": edited_steps},
    )
    assert res.status_code == 200, res.text
    assert res.json()["steps"][0]["title"] == "先看状态"

    res = await client.post(f"/agent-tasks/{task['id']}/approve-plan")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "plan_approved"

    res = await client.post(f"/agent-tasks/{task['id']}/run")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "waiting_approval"
    assert any(s["status"] == "waiting_approval" for s in body["steps"])


@pytest.mark.asyncio
async def test_task_pause_cancel_resume_from(client, tmp_path):
    pid, _ = await _project(client, tmp_path)
    task = (
        await client.post(
            "/agent-tasks/plan",
            json={"title": "暂停测试", "goal": "验证暂停继续", "project_id": pid},
        )
    ).json()
    await client.patch(
        f"/agent-tasks/{task['id']}/plan",
        json={
            "steps": [
                {"title": "先看状态", "tool_name": "get_git_status", "input_json": {"project_id": pid}},
                {
                    "title": "运行测试",
                    "tool_name": "run_whitelisted_command",
                    "input_json": {"project_id": pid, "command": "pytest -q"},
                },
            ]
        },
    )
    assert (await client.post(f"/agent-tasks/{task['id']}/approve-plan")).status_code == 200

    res = await client.post(f"/agent-tasks/{task['id']}/pause")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "paused"

    res = await client.post(f"/agent-tasks/{task['id']}/resume")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] in {"waiting_approval", "succeeded"}

    first_step = body["steps"][0]["id"]
    res = await client.post(f"/agent-tasks/{task['id']}/resume-from/{first_step}")
    assert res.status_code == 200, res.text

    res = await client.post(f"/agent-tasks/{task['id']}/cancel")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_providers_config_privacy_and_remote_guard(client):
    res = await client.get("/providers")
    assert res.status_code == 200, res.text
    assert res.json()["config"]["provider_type"] in {"ollama", "openai", "claude"}

    res = await client.patch(
        "/providers",
        json={
            "provider_type": "openai",
            "remote_provider_enabled": False,
            "openai_base_url": "https://example.invalid/v1",
            "openai_model": "test-model",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["privacy"]["remote_provider_enabled"] is False
    assert body["privacy"]["sends"] == []

    res = await client.post("/providers/test")
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_backup_export_and_restore_preview(client):
    res = await client.post("/backup/export")
    assert res.status_code == 200, res.text
    body = res.json()
    path = Path(body["path"])
    assert path.exists()
    assert body["tables"]["settings"] >= 0

    res = await client.post("/backup/restore/preview", json={"path": str(path)})
    assert res.status_code == 200, res.text
    preview = res.json()
    assert "settings" in preview["will_restore"]
    assert "tables" in preview

    path.unlink(missing_ok=True)
