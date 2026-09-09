"""以本机持久化事实和有界磁盘回读实现完成验证，不采信模型成功标记。"""
from __future__ import annotations

import asyncio
import json
import os
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
from private_agent_core.verification import OutputVerification

from . import files, policy

SCAN_IGNORED = files.IGNORED | {".pytest_cache", ".ruff_cache", ".mypy_cache", ".privateagent", ".codex"}
MAX_SCAN_FILES = 10_000
MAX_SCAN_BYTES = 64 * 1024 * 1024
BLOCKING_CODES = {"operation_denied", "approval_expired", "permission_blocked", "environment_unavailable", "local_tool_rejected", "patch_conflicted"}


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


class LocalCompletionVerifier:
    name = "local_completion"
    output_schema = None

    def __init__(self, owner, run: dict, root: Path):
        self.owner, self.run, self.root = owner, run, root
        self.last_outcome: RunOutcome | None = None
        self.failed_with_error = False
        self.last_candidate_nonempty = False

    async def verify(self, output: str, *, attempt: int) -> OutputVerification:
        if getattr(self.owner, "controls", None):
            await self.owner.controls.boundary(self.run)
        self.last_candidate_nonempty = bool(output.strip())
        if not self.last_candidate_nonempty:
            self.last_outcome = RunOutcome(run_id=self.run["id"], goal_outcome="unknown", unverified_items=["模型未提供任务结果说明"])
            self.run["verification_state"] = "failed"
            self.owner.store.save_run(self.run)
            return OutputVerification(passed=False, code="empty_output", message="尚未生成任务结果说明")
        try:
            outcome = await self.load_outcome(output)
        except asyncio.CancelledError:
            raise
        except Exception:
            # 验证器故障必须失败关闭，异常正文可能包含路径或敏感数据。
            outcome = RunOutcome(run_id=self.run["id"], goal_outcome="unknown",
                                 unverified_items=["完成验证器异常，结果未确认（verification_error）"])
            self.last_outcome = outcome
            self.failed_with_error = True
            self.run["verification_state"] = "failed"
            self.owner.store.save_run(self.run)
            return OutputVerification(passed=False, code="verification_error", message=outcome.unverified_items[0], retryable=False)
        if self.run.get("response_generation", 0) != self.run.get("generation", 0):
            return OutputVerification(passed=False, code="steering_superseded", message="用户约束已变化，请重新生成结果", retryable=True)
        self.last_outcome = outcome
        self.run["verification_state"] = "passed" if outcome.goal_outcome in {"answered", "verified"} else "failed"
        self.owner.store.save_run(self.run)
        if outcome.goal_outcome in {"verified", "answered"}:
            return OutputVerification(passed=True, code="completion_verified" if outcome.goal_outcome == "verified" else "answer_only",
                                      message="机器检查已通过" if outcome.goal_outcome == "verified" else "已回答，未声明执行修改")
        if outcome.goal_outcome == "unknown" and not outcome.requirements:
            return OutputVerification(passed=True, code="completion_unknown", message="没有明确的机器验收条件，结果未确认")
        message = "；".join(outcome.unverified_items)[:2000] or "任务要求尚未满足"
        return OutputVerification(passed=False, code="completion_" + outcome.goal_outcome, message=message,
                                  correction=("基于以下本机事实继续处理，不得把失败或预览声明为完成，也不得绕过拒绝：" + message)[:4000],
                                  retryable=outcome.goal_outcome == "unmet" and self.run.get("verification_retries", 0) < 2)

    async def load_outcome(self, output: str) -> RunOutcome:
        persisted = self.owner.store.run(self.run["id"])
        requirements = [Requirement.model_validate(item) for item in persisted["completion_requirements"]]
        history = [self.owner.store.run(identifier) for identifier in persisted.get("ancestor_run_ids", [])]
        if any(item.get("logical_task_id") != persisted.get("logical_task_id") or item["session_id"] != persisted["session_id"] for item in history):
            raise ValueError("恢复证据归属不一致")
        history.append(persisted)
        executions = [{**execution, "source_run_id": item["id"]} for item in history for execution in item["executions"]]
        started_ids = {event["payload"].get("execution_id") for item in history for event in item["events"] if event["type"] == "tool.started"}
        preview_only = persisted.get("completion_policy", {}).get("preview_only", False)
        refs: dict[str, EvidenceRef] = {}
        results = []

        def add_requirement(kind: str, scope: str, description: str, evidence_policy: str):
            if not any(item.kind == kind and item.scope == scope for item in requirements):
                requirements.append(Requirement(requirement_id=f"tool-requirement-{len(requirements) + 1}", kind=kind,
                                                scope=scope, description=description, origin="tool", evidence_policy=evidence_policy))

        # 已尝试的副作用也必须如实结算；不能靠模糊的初始请求洗掉失败命令。
        for execution in executions:
            # 预览策略已拦截的请求没有执行，不能反过来要求模型补做被禁止的修改。
            if preview_only and execution["id"] not in started_ids:
                continue
            if execution.get("scope", {}).get("kind") == "file":
                target = execution.get("target_path", "")
                add_requirement("file_changed", target, f"文件写入核对：{target}", "disk")
            elif execution.get("scope", {}).get("kind") == "files":
                for target in execution["scope"]["paths"]:
                    add_requirement("file_changed", target, f"补丁落盘核对：{target}", "disk")
            if execution.get("command"):
                kind = "test" if (execution.get("execution_result") or {}).get("command_kind") == "test" else "command"
                add_requirement(kind, execution["command"], f"{'测试结果' if kind == 'test' else '命令结果'}：{execution['command']}",
                                "test_exit" if kind == "test" else "exit")
        if len(requirements) > 128:
            raise ValueError("完成要求数量越界")
        current = await asyncio.to_thread(workspace_state, self.root) if any(item.kind in {"test", "command"} for item in requirements) else None
        terminal_sequences = {(item["id"], event["sequence"]): event for item in history for event in item["events"] if event["type"] in {"tool.completed", "tool.failed"}}

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
            status, message, ids = "unverified", "该条件仍需人工检查", []
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
                    elif result.get("validation_outcome") == "succeeded" and ids:
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
            results.append(VerificationResult(requirement_id=requirement.requirement_id, status=status,
                                              message=message[:2000], evidence_ids=ids))
        return evaluate_requirements(persisted["id"], requirements, results, evidence_refs=refs.values(),
                                     answered=not requirements or persisted.get("completion_policy", {}).get("preview_only", False))
