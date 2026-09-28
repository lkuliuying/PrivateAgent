"""跨工具入口验证审批与沙箱分离，以及公开结果的敏感内容边界。"""
import json
import os
from unittest.mock import AsyncMock

import pytest
from test_execution_autonomy import permission
from test_execution_autonomy import session as session
from test_local_executor import call

from private_agent_local import policy
from private_agent_local.completion import content_ref


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["confirm", "workspace", "full_access"])
@pytest.mark.parametrize("tool,args", [
    ("run_project_command", {"command": "python task.py"}),
    ("run_powershell_command", {"command": "Get-ChildItem", "arguments": ["-LiteralPath", "."]}),
])
async def test_all_ordinary_entries_keep_sandbox(session, monkeypatch, mode, tool, args):
    if tool == "run_powershell_command" and os.name != "nt":
        pytest.skip("受控 PowerShell 只属于 Windows")
    owner, run, root = session
    permission(session, mode)
    execute = AsyncMock(return_value={"returncode": 0, "stdout": "done", "stderr": "", "truncated": False})
    approve = AsyncMock(return_value=True)
    monkeypatch.setattr("private_agent_local.runtime.run_command", execute)
    monkeypatch.setattr(owner, "approve", approve)
    result = await owner.tool(run, root, call(tool, args))
    assert "error" not in result, result
    assert execute.await_count == 1
    assert execute.await_args.kwargs["trusted"] is False
    assert approve.await_count == (1 if mode == "confirm" else 0)
    if tool == "run_powershell_command":
        assert "New-PSDrive" in execute.await_args.args[1][-1]


@pytest.mark.parametrize("mode", ["confirm", "workspace", "full_access"])
def test_trusted_plan_always_requires_separate_approval(mode):
    assert not policy.execution_plan(["python", "task.py"], mode, execution_mode="trusted_project").automatic


@pytest.mark.parametrize("mode,network,tty", [
    ("restricted", "approved", False), ("restricted", "allowlist", False),
    ("restricted", "none", True), ("trusted_project", "none", False),
    ("unknown", "approved", False),
])
def test_unsupported_boundaries_fail_closed(mode, network, tty):
    with pytest.raises(ValueError):
        policy.execution_boundary(mode, network, tty=tty)


@pytest.mark.asyncio
@pytest.mark.parametrize("known", [True, False])
async def test_secret_file_read_does_not_create_a_redacted_edit_baseline(session, known):
    owner, run, root = session
    secret = "synthetic-secret-for-boundary-testing-012345"
    owner.cloud.secrets = {"test-provider": secret} if known else {}
    original = ('setting' if known else 'password') + ' = "' + secret + '"\n'
    (root / "config.py").write_text(original, encoding="utf-8")
    result = await owner.tool(run, root, call("read_code_file", {"rel_path": "config.py"}))
    assert result["error_code"] == "sensitive_content_blocked"
    assert secret not in json.dumps(result)
    assert secret not in json.dumps(run["executions"])
    assert (root / "config.py").read_text(encoding="utf-8") == original
    with pytest.raises(ValueError, match="必须先调用 read_code_file"):
        owner.repository.latest(run["id"], "config.py")


@pytest.mark.asyncio
async def test_legacy_command_output_is_redacted_before_recording(session, monkeypatch):
    owner, run, root = session
    secret = "synthetic-command-output-secret-0123456789"
    owner.cloud.secrets = {"test-provider": secret}
    monkeypatch.setattr("private_agent_local.runtime.run_command", AsyncMock(return_value={
        "returncode": 0, "stdout": "prefix " + secret + " suffix", "stderr": "", "truncated": False,
    }))
    result = await owner.tool(run, root, call("run_project_command", {"command": "python task.py"}))
    assert "error" not in result, result
    assert "[REDACTED]" in result["stdout"]
    assert secret not in json.dumps(result)
    assert secret not in json.dumps(owner.store.run(run["id"])["executions"])


@pytest.mark.asyncio
async def test_legacy_public_arguments_and_evidence_use_the_same_filtered_receipt(session, monkeypatch):
    owner, run, root = session
    execute = AsyncMock(return_value={"returncode": 0, "stdout": "done", "stderr": "", "truncated": False})
    monkeypatch.setattr("private_agent_local.runtime.run_command", execute)
    result = await owner.tool(run, root, call("run_project_command", {"command": "python task.py password=synthetic-value"}))
    assert "error" not in result, result
    assert execute.await_args.args[1][-1] == "password=synthetic-value"
    assert result["args"][-1] == "password=[REDACTED]"
    execution = run["executions"][-1]
    assert execution["execution_result"]["output_ref"] == content_ref(execution["output"]).model_dump(mode="json")


def test_capabilities_do_not_advertise_unimplemented_domain_isolation():
    capability = policy.execution_capabilities("full_access")["security_policy"]
    assert capability["mode_changes_sandbox"] is False
    assert capability["trusted_execution_approval"] == "always"
    assert capability["domain_network_supported"] is False


@pytest.mark.parametrize("mode", ["readonly", "confirm", "workspace", "full_access"])
@pytest.mark.parametrize("directory", [".git", ".codex", ".agents"])
def test_native_file_entries_cannot_modify_control_directories(tmp_path, mode, directory):
    with pytest.raises(ValueError):
        policy.file_scope(tmp_path, directory + "/config.txt", mode)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_fast_execution_preserves_session_receipt_and_failure(session, monkeypatch, failed):
    owner, run, root = session

    async def finish_before_return(current, execution, *args, **kwargs):
        # 真实监控器可在 start 返回前提交完成摘要；摘要不能替代工具会话回执。
        execution.update(status="failed" if failed else "completed", execution_result={"outcome": "exited"},
                         output={"stdout": "done", "stderr": "", "returncode": int(failed)})
        if failed:
            execution.update(error_code="command_failed", error_message="命令失败")
        return {"execution_id": execution["id"], "status": "exited", "chunks": [], "dropped_bytes": 0,
                "state_version": 2, "stopped": True}

    monkeypatch.setattr(owner.execution_sessions, "start", finish_before_return)
    result = await owner.tool(run, root, call("exec_command", {"argv": ["python", "task.py"]}))
    assert result["status"] == "exited" and result["chunks"] == []
    assert result["state_version"] == 2
    assert (result.get("error_code") == "command_failed") is failed
    assert run["executions"][-1]["output"]["returncode"] == int(failed)
