"""Phase3 M5/M6: coding tools and multi-step tasks."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from personal_assistant.core import code_tools
from personal_assistant.core.code_tools import (
    is_whitelisted_command,
    parse_command,
    propose_patch,
)
from personal_assistant.core.tools import default_registry


def test_m5_tools_registered():
    preview = default_registry.get("propose_patch")
    assert preview.risk_level == "safe"
    assert preview.input_schema["properties"]["new_content"]["maxLength"] == 500000
    assert preview.output_schema["properties"]["diff"]["maxLength"] == 200020
    assert "truncated" in preview.output_schema["required"]
    assert default_registry.get("apply_patch_to_workspace").risk_level == "confirm"
    assert default_registry.get("run_whitelisted_command").risk_level == "confirm"


def test_command_whitelist_rejects_shell_control():
    with pytest.raises(ValueError):
        parse_command("pytest -q && echo bad")
    assert is_whitelisted_command(["pytest", "-q"])
    assert is_whitelisted_command(["npm", "run", "build"])
    assert is_whitelisted_command(["cargo", "check"])
    assert not is_whitelisted_command(["git", "status"])


@pytest.mark.asyncio
async def test_patch_preview_is_bounded_without_writing(tmp_path, monkeypatch):
    source = tmp_path / "bounded.py"
    source.write_text("old content\n", encoding="utf-8")

    class FakeProjectService:
        def __init__(self, db):
            del db

        async def get(self, project_id):
            assert project_id == 1
            return SimpleNamespace(root_path=str(tmp_path))

    monkeypatch.setattr(code_tools, "ProjectService", FakeProjectService)
    monkeypatch.setattr(code_tools, "PATCH_DIFF_MAX_CHARS", 10)

    preview = await propose_patch(None, 1, "bounded.py", "new content\n")

    assert preview["truncated"] is True
    assert len(preview["diff"]) < 40
    assert source.read_text(encoding="utf-8") == "old content\n"


async def _project(client, tmp_path) -> tuple[int, object]:
    root = tmp_path / "m5proj"
    root.mkdir()
    (root / "a.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    res = await client.post("/projects", json={"name": "m5", "root_path": str(root)})
    assert res.status_code == 201, res.text
    return res.json()["id"], root


@pytest.mark.asyncio
async def test_patch_preview_and_approved_apply(client, db, tmp_path):
    pid, root = await _project(client, tmp_path)
    preview = await propose_patch(
        db, pid, "a.py", "def value():\n    return 2\n"
    )
    assert "return 2" in preview["diff"]
    assert preview["truncated"] is False
    assert (root / "a.py").read_text(encoding="utf-8").endswith("return 1\n")

    req = await client.post(
        "/coding/patch/apply",
        json={
            "project_id": pid,
            "rel_path": "a.py",
            "new_content": "def value():\n    return 2\n",
            "expected_old_sha256": preview["old_sha256"],
        },
    )
    assert req.status_code == 200, req.text
    tc = req.json()["tool_call"]
    assert tc["status"] == "pending_approval"
    assert (root / "a.py").read_text(encoding="utf-8").endswith("return 1\n")

    approved = await client.post(f"/tool-calls/{tc['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "succeeded"
    assert (root / "a.py").read_text(encoding="utf-8").endswith("return 2\n")


@pytest.mark.asyncio
async def test_command_request_rejects_non_whitelisted_after_approval(client, tmp_path):
    pid, _ = await _project(client, tmp_path)
    req = await client.post(
        "/coding/commands/run",
        json={"project_id": pid, "command": "git status"},
    )
    assert req.status_code == 200
    tc = req.json()
    approved = await client.post(f"/tool-calls/{tc['id']}/approve")
    assert approved.status_code == 400
    got = await client.get(f"/tool-calls/{tc['id']}")
    assert got.json()["status"] == "failed"
    assert "白名单" in got.json()["error_message"]


@pytest.mark.asyncio
async def test_agent_task_waits_for_confirm_step_and_completes(client, tmp_path):
    pid, _ = await _project(client, tmp_path)
    create = await client.post(
        "/agent-tasks",
        json={
            "title": "run checks",
            "goal": "verify project",
            "steps": [
                {
                    "title": "preview patch",
                    "tool_name": "propose_patch",
                    "input_json": {
                        "project_id": pid,
                        "rel_path": "a.py",
                        "new_content": "def value():\n    return 1\n",
                    },
                },
                {
                    "title": "run pytest",
                    "tool_name": "run_whitelisted_command",
                    "input_json": {
                        "project_id": pid,
                        "command": "python -m pytest --version",
                    },
                },
            ],
        },
    )
    assert create.status_code == 201, create.text
    task = create.json()

    run = await client.post(f"/agent-tasks/{task['id']}/run")
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "waiting_approval"
    assert body["steps"][0]["status"] in {"succeeded", "failed"}
    step2 = body["steps"][1]
    assert step2["status"] == "waiting_approval"
    assert step2["tool_call_id"]

    approved = await client.post(f"/agent-task-steps/{step2['id']}/approve")
    assert approved.status_code == 200, approved.text
    done = approved.json()
    assert done["status"] == "succeeded"
    assert done["final_report_md"]
    assert any(ev["kind"] == "report" for ev in done["evidence"])
