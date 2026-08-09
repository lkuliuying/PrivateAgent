"""v0.5.0 B2：命令可信执行闭环测试。

覆盖主计划 B2 退出条件：
- shell 控制符和非白名单命令 100% 拒绝；
- 取消/超时后子进程残留为 0（Windows Job Object + POSIX 进程组）；
- stdout/stderr 不阻塞、不无限增长、不泄露 secret（有界 + 脱敏 + 截断）；
- 重试不重复运行未知状态命令（non_idempotent + unknown 人工处置）；
- 环境变量 allowlist（清除代理/凭据）；
- 项目 command profile 前缀合并；流式输出持久化与轮询 API。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete

from personal_assistant.agents import (
    AgentEvent,
    AgentEventType,
    AgentRunLimits,
    AgentRunRepository,
    ApprovedToolCall,
    CancellationToken,
    SqlToolApprovalConsumer,
    SqlToolApprovalRequester,
    ToolApprovalRepository,
    ToolCall,
    ToolCapability,
    ToolCapabilityPolicy,
    ToolExecutionRepository,
    ValidatedToolDispatcher,
)
from personal_assistant.agents.result_verification import CompositeToolResultVerifier
from personal_assistant.api import routes_agent_runs
from personal_assistant.core.command_workflow import (
    build_command_tool_registry,
    build_safe_environment,
)
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import Project
from personal_assistant.core.repo_patch_sets import ProjectCommandProfileRepository

PROJECT_PATH: str | None = None


def _venv_scripts_dir() -> str:
    """当前测试解释器所在目录（venv Scripts），保证白名单 python 可解析。"""
    return str(Path(sys.executable).parent)


@pytest.fixture(autouse=True)
def _venv_on_path(monkeypatch):
    """模拟安装版环境：venv Scripts 位于 PATH 首位，白名单 python 命令可解析。"""
    monkeypatch.setenv("PATH", _venv_scripts_dir() + os.pathsep + os.environ.get("PATH", ""))


def _process_alive(pid: int) -> bool:
    """跨平台进程存活检查（Windows 用 OpenProcess + GetExitCodeProcess）。"""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


async def _make_project(db, tmp_path: Path) -> int:
    project = Project(name=f"b2-proj-{uuid4().hex[:8]}", root_path=str(tmp_path))
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project.id


async def _create_run(db, *, tool_call_id: str = "call-cmd-1") -> str:
    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    await repository.create_run(run_id=run_id, limits=AgentRunLimits())
    await repository.record_event(
        AgentEvent(run_id=run_id, sequence=1, type=AgentEventType.RUN_STARTED)
    )
    await repository.record_event(
        AgentEvent(
            run_id=run_id,
            sequence=2,
            type=AgentEventType.TOOL_REQUESTED,
            step_id=str(uuid4()),
            payload={
                "ordinal": 1,
                "kind": "tool",
                "tool_call_id": tool_call_id,
                "name": "run_whitelisted_command",
            },
        )
    )
    return run_id


async def _cleanup(db, run_id: str, project_id: int | None = None) -> None:
    if run_id:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    if project_id:
        await db.execute(delete(Project).where(Project.id == project_id))
    await db.commit()


def _command_arguments(project_id: int, command: list[str], **extra) -> dict:
    arguments = {"project_id": project_id, "command": command}
    arguments.update(extra)
    return arguments


def _dispatcher(
    db,
    run_id: str,
    *,
    approval_id: str | None = None,
    approval_token: str | None = None,
    on_line=None,
    with_verifier: bool = False,
) -> ValidatedToolDispatcher:
    registry = build_command_tool_registry(db, on_line=on_line)
    from personal_assistant.agents.result_verification import (
        CodeCommandResultVerifier,
        ShellResultVerifier,
    )

    result_verifier = (
        CompositeToolResultVerifier(
            [
                ShellResultVerifier(
                    expected_returncode=0,
                    reject_timeout=True,
                    reject_cancelled=True,
                ),
                CodeCommandResultVerifier(),
            ]
        )
        if with_verifier
        else None
    )
    return ValidatedToolDispatcher(
        registry,
        policy=ToolCapabilityPolicy(
            granted_capabilities=frozenset(
                {
                    ToolCapability.PROCESS_EXECUTE,
                    ToolCapability.FILESYSTEM_READ,
                }
            )
        ),
        approval_requester=SqlToolApprovalRequester(db, run_id=run_id),
        approval_consumer=(
            SqlToolApprovalConsumer(
                db,
                approval_id=approval_id,
                token=approval_token,
            )
            if approval_id is not None
            else None
        ),
        execution_store=ToolExecutionRepository(db, run_id=run_id),
        result_verifier=result_verifier,
    )


async def _request_approval_and_approve(
    db, run_id: str, call: ToolCall
) -> ApprovedToolCall:
    pending = await _dispatcher(db, run_id).execute(
        call, cancellation=CancellationToken()
    )
    assert pending.success is False
    assert pending.error_code == "approval_required"
    approvals = await ToolApprovalRepository(db).list_for_run(run_id)
    assert len(approvals) == 1
    return await ToolApprovalRepository(db).approve(approvals[0].id)


async def _execute_approved(db, run_id: str, call: ToolCall, token: CancellationToken):
    approved = await _request_approval_and_approve(db, run_id, call)
    dispatcher = _dispatcher(
        db, run_id, approval_id=approved.approval_id, approval_token=approved.token
    )
    return await dispatcher.execute(call, cancellation=token)


@pytest.fixture(autouse=True)
def _patch_project_path(tmp_path, monkeypatch):
    global PROJECT_PATH
    PROJECT_PATH = str(tmp_path)
    yield
    PROJECT_PATH = None


# ---------------- 白名单与控制符 ----------------

async def _reject_via_approved_path(db, project_id: int, call: ToolCall):
    """独立 run 走完整审批路径后由执行器拒绝（证明审批不削弱白名单强制）。"""
    run_id = await _create_run(db, tool_call_id=call.id)
    try:
        approved = await _request_approval_and_approve(db, run_id, call)
        return await _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=approved.token
        ).execute(call, cancellation=CancellationToken())
    finally:
        await _cleanup(db, run_id)


async def _add_python_c_profile(db, project_id: int, name: str = "py-c") -> None:
    """预授权 python -c 前缀（项目 command profile 合并用例/自定义脚本测试用）。"""
    repo = ProjectCommandProfileRepository(db)
    await repo.create(
        project_id=project_id,
        name=name,
        command_json={"args": ["python", "-c"]},
        kind="custom",
    )


@pytest.mark.asyncio
async def test_shell_control_tokens_rejected(db, tmp_path):
    """shell 控制符（独立 token）与字符串命令 100% 拒绝。"""
    project_id = await _make_project(db, tmp_path)
    try:
        for index, bad in enumerate(
            (
                ["python", "-c", "print(1)", "&&", "echo", "2"],
                ["python", "-c", "print(1)", ";", "echo"],
                ["python", "-c", "print(1)", "|", "more"],
                ["python", "-c", "print(1)", ">", "out.txt"],
            )
        ):
            call = ToolCall(
                id=f"call-ctl-{index}",
                name="run_whitelisted_command",
                arguments=_command_arguments(project_id, bad),
            )
            result = await _reject_via_approved_path(db, project_id, call)
            assert result.success is False
            assert "控制符" in (result.error or ""), bad

        string_call = ToolCall(
            id="call-ctl-string",
            name="run_whitelisted_command",
            arguments={"project_id": project_id, "command": "pytest -q"},
        )
        run_id = await _create_run(db, tool_call_id="call-ctl-string")
        try:
            string_result = await _dispatcher(db, run_id).execute(
                string_call, cancellation=CancellationToken()
            )
            assert string_result.success is False
            assert string_result.error_code == "input_schema_invalid"
        finally:
            await _cleanup(db, run_id)
    finally:
        await _cleanup(db, None, project_id)


@pytest.mark.asyncio
async def test_non_whitelisted_command_rejected(db, tmp_path):
    """非白名单命令拒绝（审批通过后执行器仍拒绝）。"""
    project_id = await _make_project(db, tmp_path)
    try:
        for index, command in enumerate(
            (
                ["powershell", "-c", "Remove-Item *"],
                ["rm", "-rf", "."],
                ["curl", "http://example.test"],
                ["python", "-c", "print('hi')"],
            )
        ):
            call = ToolCall(
                id=f"call-nwl-{index}",
                name="run_whitelisted_command",
                arguments=_command_arguments(project_id, command),
            )
            result = await _reject_via_approved_path(db, project_id, call)
            assert result.success is False, command
            assert "非白名单命令" in (result.error or ""), command
    finally:
        await _cleanup(db, None, project_id)


# ---------------- 成功执行与验证器 ----------------

@pytest.mark.asyncio
async def test_approved_command_runs_successfully(db, tmp_path):
    """审批通过 → 白名单 pytest 命令执行成功，输出含成功标记且 result 字段完整。"""
    (tmp_path / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-cmd-1",
            name="run_whitelisted_command",
            arguments=_command_arguments(
                project_id, ["python", "-m", "pytest", "-q"]
            ),
        )
        result = await _execute_approved(db, run_id, call, CancellationToken())
        assert result.success is True, result.error
        output = result.output
        assert output["args"] == ["python", "-m", "pytest", "-q"]
        assert output["cwd"] == str(tmp_path)
        assert output["returncode"] == 0
        assert output["succeeded"] is True
        assert output["cancelled"] is False
        assert output["processes_remaining"] == 0
        assert "passed" in output["output"]
    finally:
        await _cleanup(db, run_id, project_id)


@pytest.mark.asyncio
async def test_command_verifier_rejects_failing_command(db, tmp_path):
    """退出码非 0 → 验证器失败关闭（Shell+CodeCommand 组合验证器注入）。"""
    project_id = await _make_project(db, tmp_path)
    await _add_python_c_profile(db, project_id)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-cmd-1",
            name="run_whitelisted_command",
            arguments=_command_arguments(
                project_id, ["python", "-c", "import sys; sys.exit(1)"]
            ),
        )
        approved = await _request_approval_and_approve(db, run_id, call)
        dispatcher = _dispatcher(
            db,
            run_id,
            approval_id=approved.approval_id,
            approval_token=approved.token,
            with_verifier=True,
        )
        result = await dispatcher.execute(call, cancellation=CancellationToken())
        assert result.success is False
        assert result.error_code == "shell_exit_code_unexpected"
    finally:
        await _cleanup(db, run_id, project_id)


# ---------------- 流式输出、截断与脱敏 ----------------

@pytest.mark.asyncio
async def test_streaming_output_persisted_and_pollable(db, tmp_path, client, monkeypatch):
    """流式行持久化到 tool_execution_output，轮询 API 按 seq 续读。"""
    from sqlalchemy import text as sql_text

    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    project_id = await _make_project(db, tmp_path)
    await _add_python_c_profile(db, project_id)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-cmd-1",
            name="run_whitelisted_command",
            arguments=_command_arguments(
                project_id,
                ["python", "-c", "import sys; print('line1'); print('line2'); print('passed')"],
            ),
        )
        result = await _execute_approved(db, run_id, call, CancellationToken())
        assert result.success is True

        records = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
        assert len(records) == 1
        execution_id = records[0].id

        rows = (
            await db.execute(
                sql_text(
                    "SELECT seq, kind, text FROM tool_execution_output "
                    "WHERE execution_id = :id ORDER BY seq"
                ),
                {"id": execution_id},
            )
        ).all()
        assert len(rows) >= 3
        assert any("line1" in row[2] for row in rows)
        assert any("passed" in row[2] for row in rows)

        page = await client.get(
            f"/agent-runs/{run_id}/executions/{execution_id}/output"
        )
        assert page.status_code == 200
        body = page.json()
        assert len(body["lines"]) >= 3
        assert body["last_seq"] >= 2
        assert body["finished"] is True

        # after_seq 续读：从 last_seq 之后无新行
        resumed = await client.get(
            f"/agent-runs/{run_id}/executions/{execution_id}/output"
            f"?after_seq={body['last_seq']}"
        )
        assert resumed.json()["lines"] == []
    finally:
        await _cleanup(db, run_id, project_id)


@pytest.mark.asyncio
async def test_output_is_redacted_and_encoding_safe(db, tmp_path):
    """secret 不进输出（脱敏）；非法 UTF-8 不崩溃。"""
    project_id = await _make_project(db, tmp_path)
    await _add_python_c_profile(db, project_id)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-cmd-1",
            name="run_whitelisted_command",
            arguments=_command_arguments(
                project_id,
                [
                    "python", "-c",
                    "import sys; print('api_key=super-secret-42'); "
                    "sys.stdout.buffer.write(b'\\xff\\xfe\\n'); print('passed')",
                ],
            ),
        )
        result = await _execute_approved(db, run_id, call, CancellationToken())
        assert result.success is True
        output = result.output
        assert "super-secret-42" not in output["output"]
        assert "api_key=[REDACTED]" in output["output"]
        assert "passed" in output["output"]
    finally:
        await _cleanup(db, run_id, project_id)


@pytest.mark.asyncio
async def test_output_flood_is_bounded_and_non_blocking(db, tmp_path):
    """输出洪泛：不阻塞（子进程不因管道满卡死），持久化行数有界。"""
    from sqlalchemy import text as sql_text

    project_id = await _make_project(db, tmp_path)
    await _add_python_c_profile(db, project_id)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-cmd-1",
            name="run_whitelisted_command",
            arguments=_command_arguments(
                project_id,
                [
                    "python", "-c",
                    "import sys\n"
                    "for i in range(20000):\n"
                    "    print(f'flood-{i}')\n"
                    "print('passed')",
                ],
            ),
        )
        result = await _execute_approved(db, run_id, call, CancellationToken())
        assert result.success is True
        assert result.output["truncated"] is True

        records = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
        execution_id = records[0].id
        count = (
            await db.execute(
                sql_text(
                    "SELECT COUNT(*) FROM tool_execution_output "
                    "WHERE execution_id = :id"
                ),
                {"id": execution_id},
            )
        ).scalar_one()
        assert count <= 5_000
    finally:
        await _cleanup(db, run_id, project_id)


# ---------------- 超时 / 取消 / 进程树清理 ----------------

@pytest.mark.asyncio
async def test_timeout_kills_process_tree(db, tmp_path):
    """超时：整棵进程树被清理（子进程残留为 0）。"""
    project_id = await _make_project(db, tmp_path)
    await _add_python_c_profile(db, project_id)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-cmd-1",
            name="run_whitelisted_command",
            arguments=_command_arguments(
                project_id,
                [
                    "python", "-c",
                    "import subprocess, time, sys\n"
                    "child = subprocess.Popen([sys.executable, '-c', "
                    "'import time; time.sleep(120)'])\n"
                    "print('child-pid', child.pid, flush=True)\n"
                    "time.sleep(120)",
                ],
                timeout=4,
            ),
        )
        class _ChildPidSink:
            def __init__(self) -> None:
                self.child_pid: int | None = None

            async def on_line(self, kind: str, text: str) -> None:
                del kind
                if text.startswith("child-pid"):
                    self.child_pid = int(text.split()[-1])

        sink = _ChildPidSink()
        result = await _execute_approved_with_hook(
            db, run_id, call, CancellationToken(), sink.on_line
        )
        assert result.success is False
        assert result.error_code == "timeout"
        assert sink.child_pid is not None
        # 等待清理完成后子进程必须已终止（进程树残留为 0）
        await asyncio.sleep(0.5)
        assert not _process_alive(sink.child_pid)
    finally:
        await _cleanup(db, run_id, project_id)


async def _execute_approved_with_hook(db, run_id, call, token, on_line):
    approved = await _request_approval_and_approve(db, run_id, call)
    dispatcher = _dispatcher(
        db,
        run_id,
        approval_id=approved.approval_id,
        approval_token=approved.token,
        on_line=on_line,
    )
    return await dispatcher.execute(call, cancellation=token)


@pytest.mark.asyncio
async def test_cancel_cleans_process_tree(db, tmp_path):
    """用户取消：CancellationToken 触发进程树清理，子进程残留为 0。"""
    project_id = await _make_project(db, tmp_path)
    await _add_python_c_profile(db, project_id)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-cmd-1",
            name="run_whitelisted_command",
            arguments=_command_arguments(
                project_id,
                [
                    "python", "-c",
                    "import subprocess, time, sys\n"
                    "child = subprocess.Popen([sys.executable, '-c', "
                    "'import time; time.sleep(120)'])\n"
                    "print('child-pid', child.pid, flush=True)\n"
                    "time.sleep(120)",
                ],
            ),
        )
        token = CancellationToken()
        child_pid: list[int] = []

        async def watch_line(kind: str, text: str) -> None:
            del kind
            if text.startswith("child-pid"):
                child_pid.append(int(text.split()[-1]))
                token.cancel()

        from personal_assistant.agents import ToolDispatchCancelled

        with pytest.raises(ToolDispatchCancelled):
            await _execute_approved_with_hook(db, run_id, call, token, watch_line)
        # 取消状态已持久化到 execution 记录
        records = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
        assert records and records[0].status == "cancelled"
        assert "命令执行已取消" in (records[0].error_message or "")
        assert child_pid
        await asyncio.sleep(0.5)
        assert not _process_alive(child_pid[0])
    finally:
        await _cleanup(db, run_id, project_id)


# ---------------- 环境变量 allowlist ----------------

@pytest.mark.asyncio
async def test_environment_is_sanitized(db, tmp_path, monkeypatch):
    """环境变量 allowlist：代理/凭据类变量不传给子进程。"""
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.test:8080")
    monkeypatch.setenv("MY_API_KEY", "super-secret-env")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    project_id = await _make_project(db, tmp_path)
    await _add_python_c_profile(db, project_id)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-cmd-1",
            name="run_whitelisted_command",
            arguments=_command_arguments(
                project_id,
                [
                    "python", "-c",
                    "import os\n"
                    "print('proxy', os.environ.get('HTTP_PROXY', 'none'))\n"
                    "print('key', os.environ.get('MY_API_KEY', 'none'))\n"
                    "print('has-path', bool(os.environ.get('PATH')))\n"
                    "print('passed')",
                ],
            ),
        )
        result = await _execute_approved(db, run_id, call, CancellationToken())
        assert result.success is True
        assert "proxy none" in result.output["output"]
        assert "key none" in result.output["output"]
        assert "has-path True" in result.output["output"]
    finally:
        await _cleanup(db, run_id, project_id)


def test_safe_environment_never_contains_secret_variables(monkeypatch):
    """build_safe_environment 输出不含代理/凭据类变量。"""
    monkeypatch.setenv("HTTP_PROXY", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("DB_PASSWORD", "x")
    env = build_safe_environment()
    for name in ("HTTP_PROXY", "AWS_SECRET_ACCESS_KEY", "DB_PASSWORD"):
        assert name not in env


# ---------------- 项目 command profile 合并 ----------------

@pytest.mark.asyncio
async def test_project_profile_allows_custom_command_prefix(db, tmp_path):
    """项目 profile 前缀：预授权自定义命令可执行，未配置命令仍拒绝。"""
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db)
    try:
        repo = ProjectCommandProfileRepository(db)
        await repo.create(
            project_id=project_id,
            name="typecheck",
            command_json={"args": ["node", "run", "check"]},
            kind="typecheck",
        )
        allowed = ToolCall(
            id="call-cmd-1",
            name="run_whitelisted_command",
            arguments=_command_arguments(
                project_id, ["node", "run", "check", "--strict"]
            ),
        )
        result = await _execute_approved(db, run_id, allowed, CancellationToken())
        # node 可能不存在 → 允许失败（executor_error），但绝不能被白名单拒绝
        assert result.error_code != "permission_denied"
        assert "非白名单命令" not in (result.error or "")

        blocked = ToolCall(
            id="call-blocked",
            name="run_whitelisted_command",
            arguments=_command_arguments(project_id, ["node", "run", "deploy"]),
        )
        denied = await _reject_via_approved_path(db, project_id, blocked)
        assert denied.success is False
        assert "非白名单命令" in (denied.error or "")
    finally:
        await _cleanup(db, run_id, project_id)


# ---------------- 崩溃不重放 / flag 组合 ----------------

@pytest.mark.asyncio
async def test_unknown_execution_is_not_replayed(db, tmp_path):
    """崩溃后的未知状态命令不自动重跑。"""
    project_id = await _make_project(db, tmp_path)
    await _add_python_c_profile(db, project_id)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-cmd-1",
            name="run_whitelisted_command",
            arguments=_command_arguments(
                project_id, ["python", "-c", "print('passed')"]
            ),
        )
        approved = await _request_approval_and_approve(db, run_id, call)
        first = await _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=approved.token
        ).execute(call, cancellation=CancellationToken())
        assert first.success is True

        records = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
        assert len(records) == 1 and records[0].status == "succeeded"
        records[0].status = "unknown"
        records[0].error_code = "state_unknown"
        await db.commit()

        second = await _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=None
        ).execute(call, cancellation=CancellationToken())
        assert second.success is False
        assert second.error_code == "execution_state_unknown"
    finally:
        await _cleanup(db, run_id, project_id)


@pytest.mark.asyncio
async def test_command_flag_off_not_registered(db, monkeypatch):
    """关闭 Command flag：工具不可见；开启后注册且 PROCESS_EXECUTE 已授予。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_command_workflow_enabled", False)
    monkeypatch.setattr(
        routes_agent_runs.cfg, "agent_run_read_only_tools_enabled", False
    )
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", False)
    bundle = await routes_agent_runs.get_agent_tool_bundle(db)
    assert bundle is None

    monkeypatch.setattr(routes_agent_runs.cfg, "agent_command_workflow_enabled", True)
    bundle = await routes_agent_runs.get_agent_tool_bundle(db)
    assert bundle is not None
    names = {definition.name for definition in bundle.definitions}
    assert "run_whitelisted_command" in names

    spec = build_command_tool_registry(db).get("run_whitelisted_command")
    from personal_assistant.agents.tools import ToolPolicyDecision

    policy = ToolCapabilityPolicy(
        granted_capabilities=frozenset(
            {ToolCapability.PROCESS_EXECUTE, ToolCapability.FILESYSTEM_READ}
        )
    )
    assert policy.evaluate(spec) == ToolPolicyDecision.REQUIRE_APPROVAL
    denied = ToolCapabilityPolicy(granted_capabilities=frozenset())
    assert denied.evaluate(spec) == ToolPolicyDecision.DENY


@pytest.mark.asyncio
async def test_command_spec_matches_frozen_contract():
    """registry 产出的 ToolSpec 与 B0 冻结契约一致（验证器清单含 shell+code_command）。"""
    from personal_assistant.agents.workflow_contracts import WORKFLOW_CONTRACT_BY_NAME

    contract = WORKFLOW_CONTRACT_BY_NAME["run_whitelisted_command"]
    from personal_assistant.core.command_workflow import _build_command_tool_spec

    spec = _build_command_tool_spec(None)
    assert spec.name == contract.name
    assert spec.version == contract.version
    assert spec.risk_level == contract.risk_level
    assert spec.required_capabilities == contract.required_capabilities
    assert spec.idempotency == contract.idempotency
    assert spec.timeout_ms == contract.timeout_ms
    assert spec.supports_cancellation is True
    assert dict(spec.input_schema) == dict(contract.input_schema)
    assert contract.required_result_verifiers == ("shell", "code_command")
