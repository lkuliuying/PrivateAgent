"""从用户来源重建任务策略；普通工具审批和模型输出不能解除限制。"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
from pathlib import Path

from private_agent_core.completion import canonical_command, command_kind
from private_agent_core.task_intent import (
    TaskInterpretation,
    TaskPolicy,
    interpret_task,
    merge_policy,
    merge_task,
    rebuild_task,
)

from . import files, policy


class TaskConstraintError(ValueError):
    """操作被任务限制拦截，未进入执行器，不产生补做义务。"""


def store_interpretation(run: dict, value: TaskInterpretation) -> None:
    run.update(task_interpretation=value.model_dump(mode="json"),
               completion_policy=value.policy.model_dump(),
               completion_requirements=[item.model_dump(mode="json") for item in value.requirements])


def refresh_interpretation(run: dict) -> TaskInterpretation | None:
    raw = run.get("task_interpretation")
    if raw is not None:
        value = rebuild_task(TaskInterpretation.model_validate(raw))
        if run.get("goal") is not None and value.sources[0].text != run["goal"]:
            raise ValueError("任务解释的原始来源与持久化目标不一致，不能继续执行")
    elif run.get("goal"):
        explicit = [item for item in run.get("completion_requirements", []) if item.get("origin") == "user"]
        value = interpret_task(run["goal"], explicit).model_copy(update={"schema_version": "1.0"})
    else:
        # 无原文的历史记录保留既有限制；恢复入口另行补齐原始目标及追加来源。
        return None
    if value.schema_version != "1.2":
        merged = merge_policy(value.policy, TaskPolicy.model_validate(run.get("completion_policy", {})))
        value = rebuild_task(value.model_copy(update={"policy": merged}))
    value = value.model_copy(update={"goal_version": run.get("goal_version", value.goal_version)})
    store_interpretation(run, value)
    return value


def apply_steer(run: dict, message: str, request_id: str, *, source_run_id: str | None = None) -> None:
    current = refresh_interpretation(run)
    if current is None:
        raise ValueError("缺少原始任务目标，不能安全合并追加限制")
    source_id = "steer-" + hashlib.sha256(((source_run_id or run["id"]) + ":" + request_id).encode()).hexdigest()[:24]
    value = merge_task(current, interpret_task(message, source_id=source_id, source_kind="steer"))
    run["goal_version"] = value.goal_version
    store_interpretation(run, value)


def restore_interpretation(owner, run: dict) -> None:
    version = run.get("goal_version", 1)
    raw = run.get("task_interpretation")
    if raw is None or raw.get("schema_version", "1.0") != "1.2":
        goal = run.get("goal")
        identifiers = [*run.get("ancestor_run_ids", []), run["id"]]
        items = owner.store.context.items(run["session_id"])
        initial = any(item["run_id"] == identifiers[0] and item["source"] == "user"
                      and item["message"]["role"] == "user" and item["message"]["content"] == goal for item in items)
        explicit = raw.get("explicit_requirements", []) if raw else [
            item for item in run.get("completion_requirements", []) if item.get("origin") == "user"]
        rebuilt = interpret_task(goal, explicit) if goal else None
        seen = set()
        for identifier in identifiers:
            for record in owner.recovery.controls(identifier):
                if record["kind"] not in {"steer", "answer"} or record["status"] != "applied":
                    continue
                source_id = "steer-" + hashlib.sha256(((record.get("source_run_id") or identifier) + ":" + record["request_id"]).encode()).hexdigest()[:24]
                if source_id in seen:
                    continue
                seen.add(source_id)
                if rebuilt is not None:
                    rebuilt = merge_task(rebuilt, interpret_task(record["message"], source_id=source_id, source_kind="steer"))
        expected = [source.model_dump() for source in rebuilt.sources] if rebuilt else []
        complete = initial and rebuilt is not None and len(expected) == version and (raw is None or raw.get("sources") == expected)
        if complete:
            store_interpretation(run, rebuilt.model_copy(update={"goal_version": version}))
            return
        # 没有独立原始证据时只保留旧限制；派生缓存不能充当迁移放行的依据。
        note = "旧任务原始来源不完整或不一致，保留既有限制；请新建任务使用新的解析规则"
        cached = TaskPolicy.model_validate(run.get("completion_policy", {}))
        run["completion_policy"] = merge_policy(cached, TaskPolicy(unperformed=[note])).model_dump()
    if run.get("task_interpretation") is None and run.get("goal"):
        refresh_interpretation(run)
        for identifier in [*run.get("ancestor_run_ids", []), run["id"]]:
            for record in owner.recovery.controls(identifier):
                if record["kind"] in {"steer", "answer"} and record["status"] == "applied":
                    apply_steer(run, record["message"], record["request_id"], source_run_id=record.get("source_run_id", identifier))
    run["goal_version"] = version
    refresh_interpretation(run)


def restrictions(run: dict) -> TaskPolicy:
    return TaskPolicy.model_validate(run.get("completion_policy", {}))


def _inside(root: Path, target: Path, allowed: str) -> bool:
    base = files.within(root, allowed.rstrip("/") or ".", allow_missing=True)
    return target == base or (allowed.endswith("/") or base.is_dir()) and target.is_relative_to(base)


def guard_paths(run: dict, root: Path, paths: list[str], *, write=False) -> None:
    if write and run.get("collaboration_mode") == "plan":
        raise TaskConstraintError("规划模式只允许调研和制定计划，不能修改项目")
    limits = restrictions(run)
    if write and run.get("command_scope_issue"):
        raise TaskConstraintError(run["command_scope_issue"]["message"])
    if write and (limits.writes_forbidden or limits.preview_only):
        raise TaskConstraintError("用户禁止修改文件；本次写入未执行")
    groups = [*limits.access_scopes, *(limits.write_scopes if write else [])]
    for relative in paths:
        # 白名单与最终目标使用同一个实际路径校验，防止别名、链接和目录穿越。
        policy.file_scope(root, relative, run["permission_mode"])
        target = files.within(root, relative, allow_missing=True)
        if any(not any(_inside(root, target, allowed) for allowed in group) for group in groups):
            raise TaskConstraintError("目标超出用户限定的路径范围：" + relative)
        if write and any(_inside(root, target, forbidden) for forbidden in limits.forbidden_write_paths):
            raise TaskConstraintError("用户禁止修改此路径：" + relative)


def _test_command(root: Path, argv: list[str], cwd: str) -> bool:
    """追踪实际调用的脚本及钩子；未知代码按既有权限执行，不推定为测试。"""
    def direct(args):
        if args:
            args = [Path(args[0]).name.removesuffix(".exe"), *args[1:]]
        return bool(args and (command_kind(args) == "test" or args[0] in {"pytest", "vitest", "jest", "mocha"}
                    or args[:3] in (["python", "-m", "pytest"], ["python3", "-m", "pytest"], ["python", "-m", "unittest"], ["python3", "-m", "unittest"])
                    or args[:2] == ["playwright", "test"]))

    if direct(argv):
        return True
    if argv[:1] and argv[0] in {"npm", "pnpm", "yarn", "bun"} and argv[1:2] in (["exec"], ["dlx"]):
        return direct([arg for arg in argv[2:] if arg != "--"])
    if argv[:1] and argv[0] in {"npm", "pnpm", "yarn", "bun"}:
        try:
            path = files.within(root, (Path(cwd) / "package.json").as_posix())
            if path.stat().st_size > 65536:
                return False
            document = json.loads(path.read_text(encoding="utf-8"))
            scripts = document.get("scripts", {}) if isinstance(document, dict) else {}
            if not isinstance(scripts, dict):
                return False
            visited = set()

            def inspect(args, depth=0):
                if direct(args):
                    return True
                if depth >= 16 or not args or args[0] not in {"npm", "pnpm", "yarn", "bun", "npx"}:
                    return False
                tail = [arg for arg in args[1:] if arg != "--"]
                if args[0] == "npx" or tail[:1] in (["exec"], ["dlx"]):
                    return direct(tail if args[0] == "npx" else tail[1:])
                name = tail[1] if len(tail) > 1 and tail[0] in {"run", "run-script"} else tail[0] if tail else ""
                if name in visited:
                    return False
                visited.add(name)
                for key in ("pre" + name, name, "post" + name):
                    body = scripts.get(key)
                    if not isinstance(body, str):
                        continue
                    for part in re.split(r"&&|\|\||[;\n|]", body):
                        if inspect(shlex.split(part), depth + 1):
                            return True
                return False

            return inspect(argv)
        except (ValueError, OSError):
            return False
    return False


def _requested_test(run: dict, root: Path, argv: list[str], cwd: str) -> bool:
    if not _test_command(root, argv, cwd):
        return False
    command = canonical_command(shlex.join(argv))
    return any(item["kind"] == "test" and not item.get("scope") or
               item["kind"] in {"test", "command"} and item.get("scope") == command
               for item in run.get("completion_requirements", []))


def capture_command_scope(run: dict, root: Path, argv: list[str], cwd=".") -> dict | None:
    limits = restrictions(run)
    if (limits.write_scopes or limits.forbidden_write_paths) and _requested_test(run, root, argv, cwd):
        return limits.model_dump()
    return None


def check_command_scope(run: dict, execution: dict, root: Path, before: dict, after: dict) -> None:
    """记录执行期间的越界变化，不覆盖文件，也不把不完整快照当作核验通过。"""
    limits = execution.get("command_scope")
    if not limits:
        return
    issue = None
    if before.get("digest") is None or after.get("digest") is None:
        issue = {"status": "unverified", "paths": [], "message": "执行前后文件快照不完整，修改范围尚未核实；停止后续修改"}
    else:
        changed = sorted(path for path in before["files"].keys() | after["files"].keys()
                         if before["files"].get(path) != after["files"].get(path))
        outside = []
        check = {"permission_mode": run["permission_mode"], "completion_policy": limits}
        for path in changed:
            try:
                guard_paths(check, root, [path], write=True)
            except ValueError:
                outside.append(path)
        if outside:
            issue = {"status": "violated", "paths": outside,
                     "message": "执行期间检测到范围外文件变化，停止后续修改：" + "、".join(outside)[:1500]}
    execution["scope_check"] = issue or {"status": "passed", "paths": []}
    if issue:
        run["command_scope_issue"] = issue
        execution.update(status="failed", error_code="user_constraint", error_message=issue["message"])


def guard_command(run: dict, root: Path, argv: list[str], *, cwd=".", diagnostic=False,
                  powershell_paths: list[str] | None = None, stdin=False) -> None:
    if run.get("collaboration_mode") == "plan":
        raise TaskConstraintError("规划模式不能运行命令或向进程发送输入")
    limits = restrictions(run)
    if limits.commands_forbidden or limits.preview_only:
        raise TaskConstraintError("用户要求不运行命令；本次命令或 stdin 未执行")
    constrained = (run.get("command_scope_issue") or limits.tests_forbidden or limits.writes_forbidden or limits.write_scopes
                   or limits.access_scopes or limits.forbidden_write_paths)
    if not constrained:
        return
    if stdin:
        raise TaskConstraintError("当前任务有限制，无法确定 stdin 是否触发被禁止的操作；输入未发送")
    if powershell_paths is not None:
        guard_paths(run, root, powershell_paths or ["."])
        return
    if limits.access_scopes:
        guard_paths(run, root, [cwd])
        raise TaskConstraintError("无法证明命令仅读取用户限定路径；请使用内置文件工具")
    if diagnostic or any(tuple(argv) == policy.command_plan(shlex.join(registered), run["permission_mode"]).argv
                         for registered in policy.DIAGNOSTICS):
        return
    if run.get("command_scope_issue"):
        raise TaskConstraintError(run["command_scope_issue"]["message"])
    if limits.tests_forbidden and _test_command(root, argv, cwd):
        raise TaskConstraintError("用户禁止运行测试；测试命令、别名或封装脚本未执行")
    if limits.writes_forbidden or (limits.write_scopes or limits.forbidden_write_paths) and not _requested_test(run, root, argv, cwd):
        raise TaskConstraintError("无法证明命令符合用户的文件修改范围；命令未执行")


def tool_allowed(name: str, run: dict) -> bool:
    if name == "request_user_input":
        return run.get("collaboration_mode") == "plan" and run.get("recovery_contract_version") == "1.0"
    if run.get("collaboration_mode") == "plan" and name not in {
        "update_run_plan", "read_code_file", "list_project_directory", "search_project_files",
        "read_context_content", "read_patch_preview", "get_git_status", "get_git_diff",
        "list_documentation_sources", "call_documentation_tool", "tool_search", "list_skills", "load_skill", "read_skill_reference", "list_mcp_tools", "call_mcp_tool", "run_readonly_agents", "read_web_page", "verify_local_preview",
    }:
        return False
    limits = restrictions(run)
    if name in {"call_documentation_tool", "call_mcp_tool", "read_web_page", "verify_local_preview"}:
        return not limits.network_forbidden
    if name in {"write_project_file", "apply_project_patch"}:
        return not (limits.writes_forbidden or limits.preview_only or run.get("command_scope_issue"))
    if name in {"exec_command", "request_execution", "run_project_command", "run_powershell_command", "write_stdin"}:
        if limits.commands_forbidden or limits.preview_only:
            return False
        if name == "write_stdin":
            return not (limits.tests_forbidden or limits.writes_forbidden or limits.write_scopes
                        or limits.access_scopes or limits.forbidden_write_paths)
    return True


def guard_network(run: dict) -> None:
    if restrictions(run).network_forbidden:
        raise TaskConstraintError("用户禁止联网，本次外部请求未执行；审批不能解除该限制")
