"""工具声明、只读 Git 和命令反馈的真实边界回归。"""
import json
import subprocess

import pytest
from test_local_executor import call, close, response, setup, until

from private_agent_core.tool_specs import (
    ToolFailure,
    ToolRegistry,
    ToolSpec,
    object_output,
)
from private_agent_local import git_tools, policy
from private_agent_local.execution_tools import BasicExecArgs, ExecArgs, Input
from private_agent_local.runtime import TERMINAL
from private_agent_local.tool_registry import REGISTRY, WRITE_TOOLS


def test_registry_rejects_duplicate_and_unsafe_parallel_contracts():
    spec = ToolSpec("read_example", Input, "read", parallel_safe=True)
    with pytest.raises(ValueError, match="重复"):
        ToolRegistry([spec, spec])
    with pytest.raises(ValueError, match="只读"):
        ToolSpec("write_example", Input, "write", effect="write", approval="policy", parallel_safe=True)
    with pytest.raises(ValueError, match="副作用"):
        ToolSpec("external_example", Input, "external", effect="external")
    assert WRITE_TOOLS == {item.name for item in REGISTRY if item.blocked_in_readonly}
    visible = {item.name for item in REGISTRY.visible("readonly", "1.0")}
    assert {"get_git_status", "get_git_diff", "get_execution_capabilities"} <= visible
    assert not {"exec_command", "request_execution", "apply_project_patch"} & visible


def test_output_contract_rejects_wrong_shape_non_json_and_oversize():
    spec = ToolSpec("read_example", Input, "read", output_schema=object_output(content="string"), max_output_bytes=64)
    assert spec.validate_output({"content": "正常", "source": "file"})["content"] == "正常"
    for value, expected in [
        ({"content": 123}, "invalid_tool_output"),
        ({"content": float("nan")}, "invalid_tool_output"),
        ({"content": "x" * 100}, "tool_output_too_large"),
    ]:
        with pytest.raises(ToolFailure) as result:
            spec.validate_output(value)
        assert result.value.code == expected


def test_ordinary_execution_defaults_and_advanced_contract_are_separate():
    fields = REGISTRY["exec_command"].definition().input_schema["properties"]
    assert set(fields) == set(BasicExecArgs.model_fields)
    assert not {"execution_mode", "network_policy", "tty", "stdin", "retention"} & set(fields)
    defaults = ExecArgs(argv=["python", "-m", "pytest"])
    assert (defaults.execution_mode, defaults.network_policy, defaults.tty, defaults.stdin, defaults.retention) == (
        "restricted", "none", False, False, "run",
    )
    assert "execution_mode" in REGISTRY["request_execution"].definition().input_schema["properties"]
    assert policy.execution_capabilities()["defaults"]["network_policy"] == "none"
    with pytest.raises(ToolFailure) as rejected:
        policy.command_plan("git push", "workspace")
    assert rejected.value.code == "command_not_allowed"


@pytest.mark.asyncio
async def test_readonly_git_tools_cover_dirty_staged_pagination_and_protected_paths(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    def git(*args):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    git("init")
    git("config", "user.name", "测试")
    git("config", "user.email", "test@example.test")
    (root / "a.txt").write_text("before\n", encoding="utf-8")
    (root / "b.txt").write_text("before\n", encoding="utf-8")
    git("add", "a.txt", "b.txt")
    git("commit", "-m", "fixture")
    (root / "a.txt").write_text("after\n", encoding="utf-8")
    git("add", "a.txt")
    (root / "b.txt").write_text("changed\n", encoding="utf-8")
    (root / ".env").write_text("synthetic-private-marker", encoding="utf-8")
    try:
        server.responses = [
            response(call("get_git_status", {}), call("get_git_diff", {"rel_path": "a.txt", "staged": True})),
            response(text="已检查差异"),
        ]
        run_id = (await client.post("/agent-runs", json={**body, "permission_mode": "readonly"})).json()["id"]
        run = await until(client, run_id, TERMINAL)
        assert run["status"] == "completed"
        records = app.state.desktop.runtime.store.run(run_id)["executions"]
        assert all(item["status"] == "completed" for item in records)
        listing = records[0]["output"]
        assert {item["rel_path"] for item in listing["entries"]} == {"a.txt", "b.txt"}
        assert "+after" in records[1]["output"]["diff"]
        assert not app.state.desktop.runtime.store.run(run_id)["approvals"]
        saved = app.state.desktop.runtime.store.run(run_id)
        first = await git_tools.execute(saved, root, "get_git_status", {"limit": 1})
        second = await git_tools.execute(saved, root, "get_git_status", {"limit": 1, "cursor": first["next_cursor"]})
        assert first["entries"][0] != second["entries"][0]
        with pytest.raises(ValueError):
            await git_tools.execute(saved, root, "get_git_diff", {"rel_path": ".env"})
        with pytest.raises(ValueError):
            await git_tools.execute(saved, root, "get_git_diff", {"rel_path": "../outside"})
        page = await git_tools.execute(saved, root, "get_git_diff", {"rel_path": "b.txt", "limit": 10})
        (root / "b.txt").write_text("newer\n", encoding="utf-8")
        with pytest.raises(ToolFailure) as stale:
            await git_tools.execute(saved, root, "get_git_diff", {"rel_path": "b.txt", "expected_version": page["version"]})
        assert stale.value.code == "stale_tool_input"
        assert "synthetic-private-marker" not in json.dumps(records)
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_non_repository_and_scoped_git_requests(tmp_path):
    run = {"permission_mode": "readonly", "completion_policy": {}}
    status = await git_tools.execute(run, tmp_path, "get_git_status", {})
    assert status["is_git"] is False
    with pytest.raises(ToolFailure) as error:
        await git_tools.execute(run, tmp_path, "get_git_diff", {"rel_path": "file.txt"})
    assert error.value.code == "not_git_repository"
