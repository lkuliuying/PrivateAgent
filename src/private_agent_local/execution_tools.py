"""持续执行工具边界：验证结构化参数、明确授权和真实结果转换。"""
from __future__ import annotations

import asyncio
import hashlib
import shlex
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import files, policy
from .completion import (
    canonical_command,
    content_ref,
    denied_operation,
    workspace_state,
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ExecArgs(Input):
    argv: list[str] = Field(min_length=1, max_length=40)
    cwd: str = Field(default=".", min_length=1, max_length=1024)
    yield_time_ms: int = Field(default=1000, ge=0, le=30_000)
    timeout_ms: int = Field(default=600_000, ge=1, le=86_400_000)
    output_budget: int = Field(default=32_000, ge=1024, le=64_000)
    tty: bool = False
    stdin: bool = False
    retention: Literal["run", "session"] = "run"
    execution_mode: Literal["restricted", "trusted_project"] = "restricted"
    network_policy: Literal["none", "approved"] = "none"


class ReadArgs(Input):
    execution_id: str = Field(min_length=8, max_length=64)
    cursor: int = Field(default=0, ge=0)
    wait_ms: int = Field(default=1000, ge=0, le=30_000)
    output_budget: int = Field(default=32_000, ge=1024, le=64_000)


class StdinArgs(Input):
    execution_id: str = Field(min_length=8, max_length=64)
    data: str = Field(default="", max_length=8192)
    eof: bool = False
    expected_state_version: int = Field(ge=1)


class CancelArgs(Input):
    execution_id: str = Field(min_length=8, max_length=64)
    request_id: str = Field(min_length=8, max_length=128)


TOOLS = {
    "exec_command": (ExecArgs, "Start a registered argv development command with project-relative cwd. yield_time_ms never kills it; continue with execution_id. Restricted execution currently unavailable. trusted_project + approved network ALWAYS requires explicit user approval of current-user file/network access. Default lifetime is run; session retention is visible and separately approved. No shell/eval."),
    "read_execution": (ReadArgs, "Read an execution owned by this session using next_cursor. Observe status, gaps and dropped_bytes; running is not success. Wait <=30s, no side effects."),
    "write_stdin": (StdinArgs, "Write bounded input or EOF to an approved execution with its current state version; user approval required for each input. Never supply credentials."),
    "cancel_execution": (CancelArgs, "Idempotently stop this session's execution tree. Only stopped=true confirms cleanup; request acceptance is not proof."),
    "list_executions": (Input, "List managed commands in this session, including visible retained services and their actual states."),
}


def program_versions(command):
    versions = {}
    for value in command:
        path = Path(value)
        if path.is_absolute() and path.is_file():
            with path.open("rb") as stream:
                versions[str(path)] = hashlib.file_digest(stream, "sha256").hexdigest()
    return versions


async def execute(owner, run, root, call, execution):
    name, arguments = call["name"], call["arguments"]
    args = TOOLS[name][0].model_validate(arguments)
    owner.execution_sessions._check(run, root)
    await owner.cloud.identity(owner.token)
    manager = owner.execution_sessions
    if name == "list_executions":
        return {"items": manager.list(run["session_id"]), "programs": [
            {"name": name, "available": shutil.which(name) is not None, "version": None, "version_source": "not_probed"}
            for name in sorted(policy.RUNNERS)]}
    if name == "read_execution":
        return await manager.read(args.execution_id, run["session_id"], after=args.cursor, wait_ms=args.wait_ms, limit=args.output_budget)
    if name == "cancel_execution":
        return await manager.cancel(args.execution_id, run["session_id"])
    if run["permission_mode"] == "readonly" or run.get("completion_policy", {}).get("commands_forbidden") or run.get("completion_policy", {}).get("preview_only"):
        raise ValueError("当前任务权限不允许运行命令或写入 stdin")
    execution["scope"] = {"kind": "command"}
    if denied_operation(run, execution["scope"]) or denied_operation(run, execution["scope"], collection="uncertain_operations"):
        raise ValueError("当前任务存在已拒绝或结果未知的命令，不允许换入口重试")
    if name == "write_stdin":
        record = manager.store.get(args.execution_id, run["session_id"])
        preview = {"tool_name": name, "previewable": False, "execution_id": args.execution_id,
                   "reason": "向当前进程输入以下文本（可能触发新的操作）：" + args.data + ("；随后关闭 stdin" if args.eof else ""),
                   "state_version": args.expected_state_version, "argv": record["argv"], "cwd": record["cwd"]}
        if not await owner.approve(run, call, preview):
            raise ValueError("stdin 输入已拒绝或审批过期")
        await owner.cloud.identity(owner.token)
        return await manager.write(args.execution_id, run["session_id"], args.data, args.eof, args.expected_state_version)
    if args.execution_mode != "trusted_project" or args.network_policy != "approved":
        raise ValueError("当前未验证文件/网络隔离；受限请求未执行。可请求用户明确批准可信项目及当前用户网络范围")
    if args.retention == "run" and args.timeout_ms > 3_600_000:
        raise ValueError("普通命令硬上限为 1 小时；持续服务必须声明 session 生命周期")
    plan = policy.command_plan(shlex.join(args.argv), run["permission_mode"], require_approval=True)
    _, relative = policy.file_scope(root, args.cwd, run["permission_mode"])
    cwd = files.within(root, relative)
    if not cwd.is_dir():
        raise ValueError("命令 cwd 必须是已授权项目内的目录")
    context = owner.contexts.get(run["id"])
    if context:
        rules, unseen = context.instructions(relative, before_write=True)
        if unseen and any(rule.trusted and rule.scope != "." for rule in rules):
            raise ValueError("请先读取命令工作目录的项目规则，再申请执行")
    prepared = files.prepare_process(list(plan.argv))
    baseline = await asyncio.to_thread(workspace_state, root)
    if baseline["digest"] is None:
        raise ValueError("无法生成有界项目版本，命令授权不能绑定当前脚本；请缩小项目范围")
    versions = await asyncio.to_thread(program_versions, prepared[0])
    binding = {"argv": prepared[0], "cwd": str(cwd), "environment": prepared[1], "program_versions": versions, "workspace": baseline["digest"],
               "retention": args.retention, "timeout_ms": args.timeout_ms, "network": args.network_policy}
    binding_sha = content_ref(binding).sha256
    preview = {"tool_name": name, "previewable": False, "argv": list(plan.display_argv), "cwd": relative,
               "authorization_sha256": binding_sha, "execution_mode": args.execution_mode, "network_policy": args.network_policy,
               "retention": args.retention, "timeout_ms": args.timeout_ms,
               "reason": "可信项目执行：以当前系统用户运行，可访问该用户可读写的项目外文件并联网，没有文件或网络沙箱。"
                         + ("此进程保留到会话关闭或授权到期，可在执行面板停止。" if args.retention == "session" else "任务结束时回收进程。")
                         + " 命令：" + shlex.join(args.argv) + "；cwd：" + relative}
    if not await owner.approve(run, call, preview):
        raise ValueError("命令执行已拒绝或审批过期")
    owner.execution_sessions._check(run, root)
    await owner.cloud.identity(owner.token)
    current = await asyncio.to_thread(workspace_state, root)
    if current["digest"] != baseline["digest"] or files.prepare_process(list(plan.argv)) != prepared or await asyncio.to_thread(program_versions, prepared[0]) != versions:
        raise ValueError("项目脚本、环境或程序位置在审批后变化，请重新审查")
    if context:
        context.instructions(relative, before_write=True)
    grant = owner.require_grant(run)
    remaining = args.timeout_ms
    if grant:
        remaining = min(remaining, int((datetime.fromisoformat(grant["expires_at"]) - datetime.now(timezone.utc)).total_seconds() * 1000))
    if context and args.retention == "run":
        remaining = min(remaining, int(context.remaining_seconds() * 1000))
    if remaining <= 0:
        raise ValueError("执行预算或授权已经到期")
    execution.update(command=canonical_command(shlex.join(args.argv)), workspace_version=run.get("workspace_version", 0), workspace_digest=baseline["digest"],
                     authorization_sha256=binding_sha)
    owner.event(run, "tool.started", name=name, tool_call_id=call["id"], execution_id=execution["id"])
    result = await manager.start(run, execution, root, cwd, list(plan.argv), args.model_copy(update={"timeout_ms": remaining}), prepared=prepared)
    return {**result, "args": args.argv, "profile": "trusted-project", "truncated": result["dropped_bytes"] > 0}
