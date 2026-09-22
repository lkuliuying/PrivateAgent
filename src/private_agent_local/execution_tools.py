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

from private_agent_core.tool_specs import ToolSpec, object_output

from . import files, policy, task_constraints
from .completion import (
    canonical_command,
    content_ref,
    denied_operation,
    workspace_state,
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BasicExecArgs(Input):
    argv: list[str] = Field(min_length=1, max_length=40)
    cwd: str = Field(default=".", min_length=1, max_length=1024)
    yield_time_ms: int = Field(default=1000, ge=0, le=30_000)
    timeout_ms: int = Field(default=600_000, ge=1, le=86_400_000)
    output_budget: int = Field(default=32_000, ge=1024, le=64_000)


class ExecArgs(BasicExecArgs):
    tty: bool = False
    stdin: bool = False
    retention: Literal["run", "session"] = "run"
    execution_mode: Literal["restricted", "trusted_project"] = Field(default="restricted", description='Local tests: restricted + network_policy="none" + tty=false. Never escalate to fix invalid arguments.')
    network_policy: Literal["none", "approved"] = "none"


class ReadArgs(Input):
    execution_id: str = Field(min_length=8, max_length=64)
    cursor: int = Field(default=0, ge=0, description="首次为整数 0，后续用此执行的 next_cursor。")
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


SPECS = (
    ToolSpec("exec_command", ExecArgs,
             "Run development argv in the project. Restricted, offline, no tty/stdin and run lifetime use workspace/full_access permission; confirm requires approval. Restricted Python -c and Node -e/--eval/-p/--print support short inline code as one argv item, with the same project access as scripts. No shell chaining. Inspect get_execution_capabilities if unsure. yield_time_ms never kills the process; continue with read_execution. Prefer patch tools for file edits. Advanced access uses request_execution.",
             effect="process", approval="policy", capabilities=("command.execute",), idempotent=False,
             supports_cancellation=True, execution_protocol=True, display_model=BasicExecArgs,
             output_schema=object_output(execution_id="string", status="string")),
    ToolSpec("request_execution", ExecArgs,
             "Explicit advanced command request for stdin, tty, session retention or approved network. All fields describe a request, never a grant. trusted_project with approved network requires user approval of current-user file/network access. Never use it to bypass a rejected ordinary command.",
             effect="process", approval="always", capabilities=("command.execute",), idempotent=False,
             supports_cancellation=True, execution_protocol=True,
             output_schema=object_output(execution_id="string", status="string")),
    ToolSpec("read_execution", ReadArgs,
             "Read this session's execution using next_cursor. Observe status, gaps and dropped_bytes; running is not success. Wait <=30s.",
             capabilities=("execution.read",), supports_cancellation=True, execution_protocol=True),
    ToolSpec("write_stdin", StdinArgs,
             "Write bounded input or EOF with the current state version. Same-run approved restricted stdin can reuse workspace/full_access authorization; other input requires approval. Read current execution state before retrying. Never supply credentials.",
             effect="process", approval="policy", capabilities=("command.execute",), idempotent=False,
             supports_cancellation=True, execution_protocol=True),
    ToolSpec("cancel_execution", CancelArgs,
             "Idempotently stop this session's execution tree. Only stopped=true confirms cleanup; request acceptance is not proof.",
             effect="control", capabilities=("execution.cancel",), supports_cancellation=True, execution_protocol=True),
    ToolSpec("list_executions", Input,
             "List managed commands in this session and their actual states. For allowed programs and actions use get_execution_capabilities.",
             capabilities=("execution.read",), execution_protocol=True, output_schema=object_output(items="array")),
    ToolSpec("get_execution_capabilities", Input,
             "Inspect available registered programs, allowed actions, PowerShell parameters and execution modes without running a project command. Availability is not permission; user restrictions still apply.",
             capabilities=("execution.read",), execution_protocol=True, output_schema=object_output(programs="array")),
)
TOOLS = {spec.name: (spec.input_model, spec.description) for spec in SPECS}


def program_versions(command):
    versions = {}
    for value in command:
        path = Path(value)
        if path.is_absolute() and path.is_file():
            with path.open("rb") as stream:
                versions[str(path)] = hashlib.file_digest(stream, "sha256").hexdigest()
    return versions


async def execute(owner, run, root, call, execution):
    generation = run.get("generation", 0)
    name, arguments = call["name"], call["arguments"]
    args = TOOLS[name][0].model_validate(arguments)
    owner.execution_sessions._check(run, root)
    await owner.cloud.identity(owner.token)
    manager = owner.execution_sessions
    if name == "get_execution_capabilities":
        return {**policy.execution_capabilities(run["permission_mode"]), "permission_mode": run["permission_mode"],
                "task_restrictions": task_constraints.restrictions(run).model_dump(),
                "runtime": await manager.capabilities()}
    if name == "list_executions":
        return {"items": manager.list(run["session_id"]), "programs": [
            {"name": name, "available": shutil.which(name) is not None, "version": None, "version_source": "not_probed"}
            for name in sorted(policy.RUNNERS)]}
    if name == "read_execution":
        return await manager.read(args.execution_id, run["session_id"], after=args.cursor, wait_ms=args.wait_ms, limit=args.output_budget)
    if name == "cancel_execution":
        return await manager.cancel(args.execution_id, run["session_id"])
    if run["permission_mode"] == "readonly":
        raise ValueError("当前任务权限不允许运行命令或写入 stdin")
    execution["scope"] = {"kind": "command"}
    if denied_operation(run, execution["scope"]) or denied_operation(run, execution["scope"], collection="uncertain_operations"):
        raise ValueError("当前任务存在已拒绝或结果未知的命令，不允许换入口重试")
    if name == "write_stdin":
        def guard_input():
            manager._check(run, root)
            owner.controls.guard(run, generation)
            if run["permission_mode"] == "readonly":
                raise ValueError("当前任务权限不允许写入 stdin")
            task_constraints.guard_command(run, root, [], stdin=True)
            if denied_operation(run, execution["scope"]) or denied_operation(run, execution["scope"], collection="uncertain_operations"):
                raise ValueError("当前任务存在已拒绝或结果未知的命令，不允许继续输入")

        def input_binding(record):
            # 输出游标可以正常推进；输入授权只绑定进程归属、权限边界和输入版本。
            return {key: record.get(key) for key in (
                "execution_id", "operation_id", "host_instance_id", "run_id", "session_id", "project_id", "workspace_id",
                "tool_call_id", "argv", "cwd", "status", "state_version", "stdin_open", "tty", "execution_mode",
                "network_policy", "authorization_sha256", "stopped")}

        def reusable_input(record):
            authorization = record.get("authorization_sha256")
            if (run["permission_mode"] not in {"workspace", "full_access"}
                    or record.get("execution_id") != args.execution_id or record.get("run_id") != run["id"]
                    or any(record.get(key) != run[key] for key in ("session_id", "project_id", "workspace_id"))
                    or record.get("stdin_open") is not True or record.get("tty") is not False
                    or record.get("execution_mode") != "restricted" or record.get("network_policy") != "none"
                    or record.get("status") != "running" or record.get("stopped") is not False
                    or record.get("state_version") != args.expected_state_version
                    or any(not isinstance(record.get(key), str) or not record[key] for key in ("tool_call_id", "operation_id"))
                    or not isinstance(authorization, str) or len(authorization) != 64
                    or any(character not in "0123456789abcdef" for character in authorization)):
                return False
            return any(approval.get("status") == "consumed" and not approval.get("invalidated_by_control")
                       and approval.get("run_id") == run["id"]
                       and approval.get("tool_name") in {"exec_command", "request_execution"}
                       and approval.get("tool_call_id") == record.get("tool_call_id")
                       and approval.get("operation_id") == record.get("operation_id")
                       and approval.get("preview", {}).get("authorization_sha256") == authorization
                       for approval in run.get("approvals", []))

        guard_input()
        record = manager.store.get(args.execution_id, run["session_id"])
        if ("state_version" in record and record["state_version"] != args.expected_state_version
                or record.get("stdin_open") is False or "status" in record and record["status"] != "running"):
            raise ValueError("执行状态已变化或 stdin 已关闭，请重新读取状态")
        binding = input_binding(record)
        automatic = reusable_input(record)
        preview = {"tool_name": name, "previewable": False, "execution_id": args.execution_id,
                   "reason": "向当前进程输入以下文本（可能触发新的操作）：" + args.data + ("；随后关闭 stdin" if args.eof else ""),
                   "state_version": args.expected_state_version, "argv": record["argv"], "cwd": record["cwd"]}
        if not automatic and not await owner.approve(run, call, preview):
            raise ValueError("stdin 输入已拒绝或审批过期")

        def verify_input(active_record=None):
            guard_input()
            records = [manager.store.get(args.execution_id, run["session_id"])]
            if active_record is not None:
                records.append(active_record)
            if any(input_binding(item) != binding or automatic and not reusable_input(item) for item in records):
                raise ValueError("执行归属、授权或输入状态在核对期间变化，本次输入未发送")

        def before_send(active_record):
            # 等待输入锁期间仍可能撤销授权，发送前同时核对持久记录和实际宿主槽位。
            verify_input(active_record)
            if automatic:
                owner.event(run, "tool.auto_approved", name=name, tool_call_id=call["id"], policy_profile="restricted-stdin",
                            execution_id=args.execution_id, grant_id=run.get("full_access_grant_id"),
                            arguments_sha256=execution["arguments_sha256"], authorization_sha256=active_record["authorization_sha256"],
                            preview={**preview, "reason": "复用本任务已批准的受限进程 stdin 授权；输入仍绑定当前状态版本。"})

        await owner.cloud.identity(owner.token)
        verify_input()
        return await manager.write(args.execution_id, run["session_id"], args.data, args.eof, args.expected_state_version,
                                   before_send=before_send)
    restricted = policy.execution_boundary(args.execution_mode, args.network_policy, tty=args.tty)
    if not restricted:
        task_constraints.guard_network(run)
    if args.retention == "run" and args.timeout_ms > 3_600_000:
        raise ValueError("普通命令硬上限为 1 小时；持续服务必须声明 session 生命周期")
    ordinary = (name == "exec_command" and restricted and args.network_policy == "none"
                and not args.tty and not args.stdin and args.retention == "run")
    plan = policy.execution_plan(args.argv, run["permission_mode"], execution_mode=args.execution_mode, require_approval=not ordinary)
    task_constraints.guard_command(run, root, args.argv, cwd=args.cwd, diagnostic=plan.profile == "diagnostic")
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
    # 内联正文是代码数据，不能把其中的绝对路径形式当成本机文件读取；正文已由参数摘要绑定。
    versioned_programs = prepared[0][:1] if plan.inline_code else prepared[0]
    versions = await asyncio.to_thread(program_versions, versioned_programs)
    binding = {"argv": prepared[0], "cwd": str(cwd), "environment": prepared[1], "program_versions": versions, "workspace": baseline["digest"],
               "retention": args.retention, "timeout_ms": args.timeout_ms, "network": args.network_policy, "execution_mode": args.execution_mode}
    binding_sha = content_ref(binding).sha256
    preview = {"tool_name": name, "previewable": False, "argv": list(plan.display_argv), "cwd": relative,
               "authorization_sha256": binding_sha, "execution_mode": args.execution_mode, "network_policy": args.network_policy,
               "retention": args.retention, "timeout_ms": args.timeout_ms,
               "reason": ("受限项目执行：项目可读写，工具目录只读，网络被系统阻断；独立临时目录随执行回收。" if restricted else
                          "可信项目执行：以当前系统用户运行，可访问该用户可读写的项目外文件并联网，没有文件或网络沙箱。")
                         + ("此进程保留到会话关闭或授权到期，可在执行面板停止。" if args.retention == "session" else "任务结束时回收进程。")
                         + " 命令：" + shlex.join(args.argv) + "；cwd：" + relative}
    if not plan.automatic and not await owner.approve(run, call, preview):
        raise ValueError("命令执行已拒绝或审批过期")
    owner.execution_sessions._check(run, root)
    await owner.cloud.identity(owner.token)
    current = await asyncio.to_thread(workspace_state, root)
    if current["digest"] != baseline["digest"] or files.prepare_process(list(plan.argv)) != prepared or await asyncio.to_thread(program_versions, versioned_programs) != versions:
        phase = "自动授权核对期间" if plan.automatic else "审批后"
        raise ValueError("项目脚本、环境或程序位置在" + phase + "变化，请重新审查")
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
                     authorization_sha256=binding_sha, cwd=relative)
    execution["command_scope"] = task_constraints.capture_command_scope(run, root, args.argv, relative)
    if run.get("recovery_contract_version") or execution["command_scope"]:
        execution["before_manifest"] = baseline
    owner.controls.guard(run, generation)
    if not restricted:
        task_constraints.guard_network(run)
    task_constraints.guard_command(run, root, args.argv, cwd=relative, diagnostic=plan.profile == "diagnostic")
    if denied_operation(run, execution["scope"]) or denied_operation(run, execution["scope"], collection="uncertain_operations"):
        raise ValueError("当前任务存在已拒绝或结果未知的命令，不允许换入口重试")
    if plan.automatic:
        owner.event(run, "tool.auto_approved", name=name, tool_call_id=call["id"], policy_profile=plan.profile,
                    grant_id=run.get("full_access_grant_id"), arguments_sha256=execution["arguments_sha256"],
                    authorization_sha256=binding_sha, preview={**preview,
                        "reason": "依据当前项目权限自动授权；仅允许系统沙箱内、禁网且无交互的任务命令。" + preview["reason"]})
    owner.event(run, "tool.started", name=name, tool_call_id=call["id"], execution_id=execution["id"])
    result = await manager.start(run, execution, root, cwd, list(plan.argv), args.model_copy(update={"timeout_ms": remaining}), prepared=prepared)
    return {**result, "args": args.argv, "profile": "appcontainer" if restricted else "trusted-project", "truncated": result["dropped_bytes"] > 0}
