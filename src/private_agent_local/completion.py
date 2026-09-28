"""以本机持久化事实和有界磁盘回读实现完成验证，不采信模型成功标记。"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
from datetime import datetime, timezone
from pathlib import Path

from private_agent_core.coding_contracts import (
    ContentRef,
    EvidenceRef,
    Requirement,
    RunOutcome,
    VerificationResult,
)
from private_agent_core.completion import canonical_command, evaluate_requirements
from private_agent_core.task_intent import TaskPolicy
from private_agent_core.verification import OutputVerification

from . import files, policy, reflection, reflection_review, task_constraints
from .observer import record_checks, selected_checks
from .output import validate_output_schema, verify_structured_output
from .planning import completion_blockers, proposal_blockers

SCAN_IGNORED = files.IGNORED | {".pytest_cache", ".ruff_cache", ".mypy_cache", ".privateagent", ".codex"}
MAX_SCAN_FILES = 10_000
MAX_SCAN_BYTES = 64 * 1024 * 1024
BLOCKING_CODES = {"operation_denied", "approval_expired", "permission_blocked", "environment_unavailable", "local_tool_rejected", "patch_conflicted", "user_constraint"}


def content_ref(value: dict | str) -> ContentRef:
    data = (value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)).encode("utf-8")
    return ContentRef(sha256=files.digest(data), bytes=len(data))


def workspace_state(root: Path) -> dict:
    """不读取凭据、链接及构建目录；扫描不完整时不产生可用的代码版本。"""
    manifest, total = {}, 0
    try:
        for current, directories, names in os.walk(root, followlinks=False, onerror=_scan_error):
            directories[:] = sorted(name for name in directories if name not in SCAN_IGNORED
                                    and not policy.protected(Path(current) / name))
            if any((Path(current) / name).is_symlink() or getattr(Path(current) / name, "is_junction", lambda: False)()
                   for name in directories):
                return {"digest": None, "files": {}}
            for name in sorted(names):
                candidate = Path(current) / name
                if policy.protected(candidate):
                    continue
                if candidate.is_symlink():
                    return {"digest": None, "files": {}}
                relative = candidate.relative_to(root).as_posix()
                path = files.within(root, relative)
                stat = path.stat()
                total += stat.st_size
                if stat.st_nlink > 1 or total > MAX_SCAN_BYTES or len(manifest) >= MAX_SCAN_FILES:
                    return {"digest": None, "files": {}}
                with path.open("rb") as stream:
                    data = stream.read(MAX_SCAN_BYTES - (total - stat.st_size) + 1)
                if len(data) != stat.st_size or path.stat().st_mtime_ns != stat.st_mtime_ns:
                    return {"digest": None, "files": {}}
                manifest[relative] = files.digest(data)
    except (OSError, ValueError):
        return {"digest": None, "files": {}}
    return {"digest": content_ref(manifest).sha256, "files": manifest}


def _scan_error(error):
    raise error


def file_digest(root: Path, relative: str) -> str | None:
    try:
        path = files.within(root, relative)
        if policy.protected(path) or not path.is_file() or path.stat().st_nlink > 1 or path.stat().st_size > files.MAX_FILE_BYTES:
            return None
        with path.open("rb") as stream:
            data = stream.read(files.MAX_FILE_BYTES + 1)
        return files.digest(data) if len(data) <= files.MAX_FILE_BYTES else None
    except (OSError, ValueError):
        return None


def operation_scope(name: str, arguments: dict) -> dict:
    """脚本的文件范围无法静态证明；命令拒绝保守绑定整个项目副作用范围。"""
    if name == "write_project_file":
        return {"kind": "file", "path": os.path.normcase(str(Path(arguments["rel_path"]))).replace("\\", "/")}
    if name == "run_powershell_command":
        arguments_list = arguments.get("arguments", [])
        paths = [arguments_list[index + 1] for index, item in enumerate(arguments_list[:-1])
                 if item.lower() in {"-path", "-literalpath", "-destination", "-newname"}]
        return {"kind": "command", "paths": [os.path.normcase(str(Path(value))).replace("\\", "/") for value in paths]}
    return {"kind": "command"}


def denied_operation(run: dict, scope: dict, *, collection: str = "denied_operations") -> bool:
    for denial in run.get(collection, []):
        old = denial["scope"]
        if old["kind"] == "external" or scope["kind"] == "external":
            if old["kind"] == scope["kind"] and old.get("source_id") == scope.get("source_id") and old.get("tool") == scope.get("tool"):
                return True
            continue
        if old["kind"] == "command" or scope["kind"] == "command":
            return True
        for first in old.get("paths", [old.get("path", "")]):
            for second in scope.get("paths", [scope.get("path", "")]):
                first, second = first.casefold(), second.casefold()
                if first == second or first.startswith(second + "/") or second.startswith(first + "/"):
                    return True
    return False


def unknown_outcome(run_id: str, message: str = "此记录没有可用的完成验证证据") -> dict:
    return RunOutcome(run_id=run_id, goal_outcome="unknown", unverified_items=[message]).model_dump(mode="json")


def command_matches(requirement: Requirement, execution: dict) -> bool:
    if not execution.get("command"):
        return False
    if requirement.scope:
        return canonical_command(execution["command"]) == canonical_command(requirement.scope)
    return requirement.kind == "command" or (execution.get("execution_result") or {}).get("command_kind") == "test"


def script_exit_check(command: str) -> bool:
    """脚本及受限内联命令可核验退出码；测试帮助和版本查询不替代测试。"""
    try:
        argv = shlex.split(command)
        if (len(argv) >= 2 and argv[0] in {"python", "python3", "node", "bun"} and not argv[1].startswith("-")
                and Path(argv[1]).suffix.lower() in {".py", ".js", ".mjs", ".cjs"}):
            return True
        return policy.execution_plan(argv, "workspace").inline_code
    except ValueError:
        return False


def command_is_observation(execution: dict, terminal: dict | None) -> bool:
    """成功且未改变工作区的辅助命令只留审计；明确要求和测试仍单独验收。"""
    result = execution.get("execution_result") or {}
    return bool(terminal and terminal["type"] == "tool.completed"
                and terminal["payload"].get("execution_id") == execution["id"]
                and result.get("outcome") == "exited"
                and result.get("command_kind") in {"search", "development", "unclassified"}
                and result.get("validation_outcome") in {"succeeded", "unknown"}
                and (result.get("validation_outcome") == "succeeded" or result.get("exit_code") == 0)
                and execution.get("workspace_digest")
                and execution.get("workspace_changed") is False)


class LocalCompletionVerifier:
    name = "local_completion"
    output_schema = None

    def __init__(self, owner, run: dict, root: Path):
        self.owner, self.run, self.root = owner, run, root
        self.output_schema = validate_output_schema(run.get("output_schema"))
        self.last_outcome: RunOutcome | None = None
        self.failed_with_error = False
        self.last_candidate_nonempty = False
        self.constraint_message: str | None = None

    async def verify(self, output: str, *, attempt: int) -> OutputVerification:
        self.constraint_message = None
        review = None
        if getattr(self.owner, "controls", None):
            await self.owner.controls.boundary(self.run)
        if self.output_schema is not None:
            if self.run.get("response_generation", 0) != self.run.get("generation", 0):
                return OutputVerification(passed=False, code="steering_superseded",
                    message="用户约束已变化，请重新生成结构化结果", retryable=True)
            invalid = verify_structured_output(output, self.output_schema)
            if invalid is not None:
                self.last_candidate_nonempty = bool(output.strip())
                self.last_outcome = None
                self.run["verification_state"] = "failed"
                self.owner.store.save_run(self.run)
                return invalid
        self.last_candidate_nonempty = bool(output.strip())
        if not self.last_candidate_nonempty:
            self.last_outcome = RunOutcome(run_id=self.run["id"], goal_outcome="unknown", unverified_items=["模型未提供任务结果说明"])
            self.run["verification_state"] = "failed"
            self.owner.store.save_run(self.run)
            return OutputVerification(passed=False, code="empty_output", message="尚未生成任务结果说明")
        try:
            task_constraints.refresh_interpretation(self.run)
            self.owner.store.save_run(self.run)
            if self.run.get("collaboration_mode") == "plan":
                _, checks = selected_checks(self.run, self.root)
                record_checks(self.owner, self.run, checks, [])
                return self.verify_proposal()
            outcome = await self.load_outcome(output)
            if self.run.get("response_generation", 0) != self.run.get("generation", 0):
                return OutputVerification(passed=False, code="steering_superseded",
                    message="用户约束已变化，旧完成证据不计入新目标纠错", retryable=True)
            plan_status, plan_messages = completion_blockers(self.run)
            if plan_status:
                outcome = outcome.model_copy(update={
                    "goal_outcome": "blocked" if "blocked" in {plan_status, outcome.goal_outcome} else "unmet",
                    "unverified_items": [*outcome.unverified_items, *plan_messages],
                })
            changed = {item.requirement_id for item in outcome.requirements if item.kind == "file_changed"}
            if (outcome.goal_outcome == "verified" and reflection.requires_review(self.run)
                    and any(item.requirement_id in changed and item.status == "passed" for item in outcome.verification_results)):
                review = await reflection_review.review_completion(self.owner, self.run, self.root, output, outcome)
                if review.code == "steering_superseded":
                    return review
                if review.passed:
                    # 复核初次扫描前也可能有外部写入；交付前重新核验原操作证据。
                    outcome = await self.load_outcome(output)
                else:
                    # 复核只能阻止交付；不能把模型意见转换为文件、测试或人工验收证据。
                    outcome = outcome.model_copy(update={
                        "goal_outcome": "unmet" if review.retryable else "unknown",
                        "unverified_items": [*outcome.unverified_items, review.message],
                    })
            if self.run.get("response_generation", 0) != self.run.get("generation", 0):
                return OutputVerification(passed=False, code="steering_superseded",
                    message="用户约束已变化，旧完成证据不计入新目标纠错", retryable=True)
            correction = reflection.record_verification(self.run, outcome)
            if correction is not None:
                with self.owner.store.transaction(run=self.run):
                    self.run["reflection_state"] = correction
                    self.owner.event(self.run, "reflection.verification_observed", goal_outcome=outcome.goal_outcome)
        except asyncio.CancelledError:
            raise
        except Exception:
            # 验证器故障必须失败关闭，异常正文可能包含路径或敏感数据。
            outcome = RunOutcome(run_id=self.run["id"], goal_outcome="unknown",
                                 unverified_items=["完成验证器异常，结果未确认（verification_error）"])
            self.last_outcome = outcome
            self.failed_with_error = True
            if self.run.get("observer_config", {}).get("checks"):
                self.run.pop("observer_checks", None)
                self.owner.event(self.run, "observer.checks_failed", error_code="verification_error")
            self.run["verification_state"] = "failed"
            self.owner.store.save_run(self.run)
            return OutputVerification(passed=False, code="verification_error", message=outcome.unverified_items[0], retryable=False)
        if self.run.get("response_generation", 0) != self.run.get("generation", 0):
            return OutputVerification(passed=False, code="steering_superseded", message="用户约束已变化，请重新生成结果", retryable=True)
        self.last_outcome = outcome
        if review is not None and not review.passed:
            self.run["verification_state"] = "failed"
            self.owner.store.save_run(self.run)
            return review
        limits = TaskPolicy.model_validate(self.run.get("completion_policy", {}))
        required = [item for item in outcome.requirements if item.required]
        checked = {item.requirement_id for item in outcome.verification_results
                   if item.status == "passed" and item.evidence_ids}
        # 仅对已核实的文件修改正常收尾；缺失证据、其他要求或先前命令不能借禁止测试放行。
        if (outcome.goal_outcome == "unknown" and required
                and (limits.tests_forbidden or limits.commands_forbidden) and not limits.conflicts
                and all(item.kind == "file_changed" and item.requirement_id in checked for item in outcome.requirements)
                and all(item.status == "passed" for item in outcome.verification_results)
                and outcome.unverified_items and set(outcome.unverified_items) == set(limits.unperformed)):
            skipped = "测试" if limits.tests_forbidden else "命令"
            self.constraint_message = f"修改已完成；按用户要求未运行{skipped}，功能正确性尚未验证"
            self.run["verification_state"] = "passed"
            self.owner.store.save_run(self.run)
            return OutputVerification(passed=True, code="completion_limited", message=self.constraint_message, retryable=False)
        self.run["verification_state"] = "passed" if outcome.goal_outcome in {"answered", "verified"} else "failed"
        self.owner.store.save_run(self.run)
        if outcome.goal_outcome in {"verified", "answered"}:
            return OutputVerification(passed=True, code="completion_verified" if outcome.goal_outcome == "verified" else "answer_only",
                                      message="机器检查已通过" if outcome.goal_outcome == "verified" else "已回答，未声明执行修改")
        if outcome.goal_outcome == "unknown" and not outcome.requirements:
            return OutputVerification(passed=True, code="completion_unknown", message="没有明确的机器验收条件，结果未确认")
        message = "；".join(outcome.unverified_items)[:2000] or "任务要求尚未满足"
        missing = [{"requirement_id": item.requirement_id, "status": item.status, "evidence_ids": item.evidence_ids}
                   for item in outcome.verification_results if item.status != "passed"][:8]
        correction = "基于本机事实继续处理，不得把失败或预览声明为完成，也不得绕过拒绝。缺失检查：" + json.dumps(missing, ensure_ascii=False)
        correction += "。先说明要修正的问题、与前次尝试的区别及预期验证，再通过已有工具取得证据。" + message
        return OutputVerification(passed=False, code="completion_" + outcome.goal_outcome, message=message,
                                  correction=correction[:4000],
                                  retryable=outcome.goal_outcome == "unmet" and self.run.get("verification_retries", 0) < 2)

    def verify_proposal(self) -> OutputVerification:
        messages = proposal_blockers(self.run)
        if self.run.get("pending_input"):
            messages.append("请等待用户回答当前问题")
        if self.run.get("response_generation", 0) != self.run.get("generation", 0):
            messages.append("用户约束已变化，请重新核对计划")
        self.last_outcome = RunOutcome(run_id=self.run["id"], goal_outcome="unmet" if messages else "answered",
            requirements=[Requirement.model_validate(item) for item in self.run.get("completion_requirements", [])],
            unverified_items=messages or ["仅完成计划制定，尚未实施或验证项目修改"])
        self.run["verification_state"] = "failed" if messages else "passed"
        self.owner.store.save_run(self.run)
        return OutputVerification(passed=not messages, code="plan_incomplete" if messages else "plan_ready",
            message="；".join(messages) if messages else "实施计划已就绪，等待用户选择执行",
            correction="；".join(messages) if messages else None,
            retryable=bool(messages) and self.run.get("verification_retries", 0) < 2)

    async def load_outcome(self, output: str) -> RunOutcome:
        persisted = self.owner.store.run(self.run["id"])
        requirements = [Requirement.model_validate(item) for item in persisted["completion_requirements"]]
        observer_requirements, observer_checks = selected_checks(persisted, self.root)
        observer_ids = {item.requirement_id for item in observer_requirements}
        # 检查快照不混入用户来源；同名用户要求仍保留各自结果，不能相互撤销。
        requirements.extend(observer_requirements)
        if observer_checks:
            self.owner.event(self.run, "observer.checks_started", config_version=persisted["observer_config"]["version"],
                             check_count=len(observer_checks))
        history = [self.owner.store.run(identifier) for identifier in persisted.get("ancestor_run_ids", [])]
        if any(item.get("logical_task_id") != persisted.get("logical_task_id") or item["session_id"] != persisted["session_id"] for item in history):
            raise ValueError("恢复证据归属不一致")
        history.append(persisted)
        executions = [{**execution, "source_run_id": item["id"]} for item in history for execution in item["executions"]]
        started_ids = {event["payload"].get("execution_id") for item in history for event in item["events"] if event["type"] == "tool.started"}
        preview_only = persisted.get("completion_policy", {}).get("preview_only", False)
        limits = TaskPolicy.model_validate(persisted.get("completion_policy", {}))
        refs: dict[str, EvidenceRef] = {}
        results = []
        terminal_sequences = {(item["id"], event["sequence"]): event for item in history for event in item["events"]
                              if event["type"] in {"tool.completed", "tool.failed"}}
        commands: dict[str, dict] = {}
        commands_with_effects: set[str] = set()

        def add_requirement(kind: str, scope: str, description: str, evidence_policy: str):
            if not any(item.kind == kind and item.scope == scope for item in requirements):
                requirements.append(Requirement(requirement_id=f"tool-requirement-{len(requirements) + 1}", kind=kind,
                                                scope=scope, description=description, origin="tool", evidence_policy=evidence_policy))

        # 实际副作用、失败及未知结果仍需结算；工具尝试本身不新增用户目标。
        for execution in executions:
            # 预览策略已拦截的请求没有执行，不能反过来要求模型补做被禁止的修改。
            if (preview_only or execution.get("error_code") == "user_constraint") and execution["id"] not in started_ids:
                continue
            if (execution.get("error_code") == "local_tool_rejected" and execution["id"] not in started_ids
                    and not any(execution.get(key) for key in ("execution_result", "file_evidence", "patch_evidence"))):
                # 参数或工具不适用且尚未启动，仅保留失败审计；用户明确指定的要求仍在下方核验。
                continue
            if execution.get("scope", {}).get("kind") == "file":
                target = execution.get("target_path", "")
                add_requirement("file_changed", target, f"文件写入核对：{target}", "disk")
            elif execution.get("scope", {}).get("kind") == "files":
                for target in execution["scope"]["paths"]:
                    add_requirement("file_changed", target, f"补丁落盘核对：{target}", "disk")
            if execution.get("command"):
                command = canonical_command(execution["command"])
                commands[command] = execution
                if execution["id"] in started_ids and (execution.get("workspace_changed") is not False
                                                       or not execution.get("workspace_digest")):
                    commands_with_effects.add(command)
        for command, execution in commands.items():
            terminal = terminal_sequences.get((execution["source_run_id"], execution.get("source_sequence")))
            # 后一次只读成功不能抹掉同一命令先前已产生或无法核对的副作用。
            if command not in commands_with_effects and execution["id"] in started_ids and command_is_observation(execution, terminal):
                continue
            if any(item.kind in {"test", "command"} and item.scope and canonical_command(item.scope) == command
                   for item in requirements):
                continue
            kind = "test" if (execution.get("execution_result") or {}).get("command_kind") == "test" else "command"
            add_requirement(kind, execution["command"], f"{'测试结果' if kind == 'test' else '命令结果'}：{execution['command']}",
                            "test_exit" if kind == "test" else "exit")
        if len(requirements) > 128:
            raise ValueError("完成要求数量越界")
        current = await asyncio.to_thread(workspace_state, self.root) if any(item.kind in {"test", "command"} for item in requirements) else None

        def evidence(execution, facts) -> list[str]:
            sequence = execution.get("source_sequence")
            event = terminal_sequences.get((execution["source_run_id"], sequence))
            if not event or event["payload"].get("execution_id") != execution["id"]:
                return []
            key = "evidence-" + execution["id"]
            if execution["source_run_id"] != persisted["id"]:
                # 新运行重新核对磁盘或代码版本后登记新证据，保留原操作与事件的来源。
                revalidated = self.owner.event(self.run, "evidence.revalidated", source_run_id=execution["source_run_id"],
                    source_sequence=sequence, operation_id=execution["operation_id"], execution_id=execution["id"], content_ref=content_ref(facts).model_dump(mode="json"))
                sequence = revalidated["sequence"]
            refs[key] = EvidenceRef(evidence_id=key, run_id=persisted["id"], operation_id=execution["operation_id"],
                                    execution_id=execution["id"], tool_call_id=execution["tool_call_id"],
                                    source_sequence=sequence, content_ref=content_ref(facts), verified_at=datetime.now(timezone.utc),
                                    workspace_version=execution.get("workspace_version", 0))
            return [key]

        for requirement in requirements:
            status, message, ids = "unverified", requirement.description + "；缺少适用证据，仍需人工检查", []
            matching = []
            if requirement.kind == "preview":
                effect_ids = {item["id"] for item in executions if item.get("scope")}
                if effect_ids & started_ids:
                    status, message = "failed", "预览任务出现执行请求，不能宣称仅预览完成"
                elif output.strip():
                    status, message = "passed", "已生成文字方案或预览，未执行修改"
                    event = next(event for event in reversed(persisted["events"]) if event["type"] == "model.completed")
                    key = f"response-{event['sequence']}"
                    refs[key] = EvidenceRef(evidence_id=key, run_id=persisted["id"], operation_id=key,
                                            source_sequence=event["sequence"], content_ref=content_ref(output),
                                            verified_at=datetime.now(timezone.utc), workspace_version=persisted.get("workspace_version", 0))
                    ids = [key]
            elif requirement.kind == "artifact":
                if requirement.requirement_id in observer_ids:
                    task_constraints.guard_paths(self.run, self.root, [requirement.scope])
                actual = await asyncio.to_thread(file_digest, self.root, requirement.scope)
                if actual is not None:
                    sequence = persisted["last_event_sequence"]
                    key = f"artifact-{requirement.requirement_id}-{sequence}"
                    refs[key] = EvidenceRef(evidence_id=key, run_id=persisted["id"], operation_id=f"verification-{sequence}",
                                            source_sequence=sequence, content_ref=content_ref({"path": requirement.scope, "sha256": actual}),
                                            verified_at=datetime.now(timezone.utc), workspace_version=persisted.get("workspace_version", 0))
                    status, message, ids = "passed", f"已核对产物存在及内容摘要：{requirement.scope}（不代表功能正确）", [key]
                else:
                    status, message = "failed", f"产物不存在或不能安全回读：{requirement.scope}"
            elif requirement.kind == "file_changed":
                matching = [item for item in executions if
                            (item.get("scope", {}).get("kind") == "file" and (not requirement.scope or item.get("target_path") == requirement.scope))
                            or (item.get("scope", {}).get("kind") == "files" and (not requirement.scope or requirement.scope in item["scope"]["paths"]))]
                candidates = matching[-1:] if requirement.scope else list(reversed(matching))
                status, message = "failed", f"缺少实际文件变化证据：{requirement.scope or '所选项目'}"
                for item in candidates:
                    if item.get("patch_set_id"):
                        patch_facts = self.owner.patches.facts(item["source_run_id"], item["patch_set_id"], self.root)
                        selected = [fact for fact in patch_facts if not requirement.scope or fact["rel_path"] == requirement.scope]
                        if selected and all(fact["verified"] and fact["changed"] for fact in selected):
                            ids = evidence(item, {"patch_set_id": item["patch_set_id"], "files": patch_facts})
                            if ids:
                                status, message = "passed", f"补丁日志与当前磁盘状态一致：{requirement.scope or '所选项目'}（不代表功能正确）"
                                break
                        message = "补丁记录缺失、文件被后续修改或操作尚未全部验证"
                        continue
                    facts = item.get("file_evidence") or {}
                    actual = await asyncio.to_thread(file_digest, self.root, item["target_path"])
                    if (facts.get("verified") and actual is not None and actual == facts.get("sha256")
                            and facts.get("changed")):
                        ids = evidence(item, {**facts, "current_sha256": actual})
                        if ids:
                            status, message = "passed", f"文件存在且写后摘要一致：{item['target_path']}（不代表功能正确）"
                            break
                    message = f"文件回读与写入事实不一致或没有实际变化：{item['target_path']}"
            elif requirement.kind in {"command", "test"}:
                matching = [item for item in executions if command_matches(requirement, item)]
                if requirement.requirement_id in observer_ids:
                    matching = [item for item in matching if item.get("cwd") == "."
                                or item.get("tool_name") == "run_project_command"]
                status, message = "failed", f"尚未执行要求的{'测试' if requirement.kind == 'test' else '命令'}：{requirement.scope}"
                if matching:
                    item = matching[-1]
                    result = item.get("execution_result") or {}
                    ids = evidence(item, result)
                    outcome = result.get("outcome", "unknown")
                    if outcome in {"timed_out", "cancelled", "failed"}:
                        status, message = "blocked", {"timed_out": "命令超时", "cancelled": "命令已取消", "failed": "命令未能启动或执行"}[outcome]
                    elif outcome == "unknown":
                        status, message = "unverified", "执行宿主结果未知，禁止自动重放"
                    elif result.get("validation_outcome") == "failed":
                        status, message = "failed", f"{'测试失败' if requirement.kind == 'test' else '命令失败'}：{item['command']}（退出码 {result.get('exit_code')}）"
                    elif current is None or current["digest"] is None or item.get("workspace_digest") is None:
                        status, message = "unverified", "工作区超出有界扫描范围或无法安全读取，命令结果尚未验证"
                    elif (current["digest"] != item.get("workspace_digest") or item.get("workspace_changed")
                          or item.get("workspace_version") != persisted.get("workspace_version", 0)):
                        status, message = "failed", "执行后工作区发生变化或无法完整核对，旧验证证据已过期"
                    elif (result.get("validation_outcome") == "succeeded" or (
                            requirement.kind == "command" and requirement.evidence_policy == "exit"
                            and script_exit_check(item["command"])
                            and result.get("outcome") == "exited" and result.get("exit_code") == 0)) and ids:
                        status, message = "passed", f"{item['command']} 按登记的退出码规则通过（不代表任意需求成立）"
                    else:
                        status, message = "unverified", "命令已退出，但其业务含义无法自动判定"
            if status != "passed":
                blocking = next((item for item in reversed(matching) if item.get("error_code") in BLOCKING_CODES), None)
                if blocking:
                    status, message = "blocked", blocking["error_message"]
                elif requirement.kind in {"command", "test"} and persisted.get("completion_policy", {}).get("commands_forbidden"):
                    status, message = "blocked", "用户要求暂不运行命令，验证受阻"
                elif requirement.kind in {"file_changed", "command", "test"} and persisted.get("permission_mode") == "readonly":
                    status, message = "blocked", "当前只读模式不允许执行写入或命令"
                if requirement.kind in {"command", "test"} and requirement.scope and requirement.scope not in message:
                    message = f"{requirement.scope}：{message}"
            results.append(VerificationResult(requirement_id=requirement.requirement_id, status=status,
                                              message=message[:2000], evidence_ids=ids))
        unperformed = list(limits.unperformed)
        scope_issue = persisted.get("command_scope_issue")
        if scope_issue:
            unperformed.append(scope_issue["message"])
        # 追加限制不能抹去已执行事实；是否通过仍由上面的版本和证据检查决定。
        prior_commands = [item for item in executions if item["id"] in started_ids and item.get("command")]
        if any((item.get("execution_result") or {}).get("command_kind") == "test" for item in prior_commands):
            unperformed = ["用户禁止继续运行测试；先前测试记录保留，未据此推定当前目标全部通过"
                           if item.startswith("用户禁止运行测试") else item for item in unperformed]
        if prior_commands:
            unperformed = ["用户禁止继续运行命令；先前执行记录保留，未据此推定当前目标全部通过"
                           if item.startswith("用户要求不运行命令") else item for item in unperformed]
        if self.run.get("generation", 0) == persisted.get("generation", 0):
            record_checks(self.owner, self.run, observer_checks, results)
        return evaluate_requirements(persisted["id"], requirements, results, evidence_refs=refs.values(),
                                     answered=not requirements or preview_only,
                                     unperformed=unperformed, conflicts=[*limits.conflicts,
                                         *([scope_issue["message"]] if scope_issue and scope_issue["status"] == "violated" else [])])
