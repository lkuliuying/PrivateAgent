"""完成要求与命令语义的纯函数；不依赖旧业务配置、数据库或模型断言。"""
from __future__ import annotations

import re
import shlex

from .coding_contracts import (
    ExecutionResult,
    Requirement,
    RunOutcome,
    VerificationResult,
)

_PREVIEW = re.compile(r"只(?:给|要|做|生成)?(?:方案|预览|补丁)|仅(?:生成)?预览|不要写入|不写入|preview only|only (?:a )?(?:plan|patch|preview)", re.I)
_WRITE = re.compile(r"创建|新建|写入|生成|修改|修复|更新|编辑|替换|删除|重命名|\b(?:create|write|modify|fix|update|edit|delete|rename)\b", re.I)
_TEST = re.compile(r"(?:运行|执行|跑|并|和|后|及)\s*(?:一下)?测试|测试(?:并|和)?(?:通过|验证)|\b(?:run|execute) (?:the )?tests?\b|\bpytest\b", re.I)
_NO_COMMAND = re.compile(r"(?:不|禁止|暂不|暂时不)(?:允许)?(?:运行|执行)(?:命令|测试)|do not (?:run|execute)|no commands", re.I)
_FILE = re.compile(r"(?<![A-Za-z0-9_./-])(?:[A-Za-z0-9_@.-]+/)*[A-Za-z0-9_@.-]+\.(?:py|txt|md|js|jsx|ts|tsx|vue|json|ya?ml|toml|rs|go|java|css|html|sql|sh|ps1)\b", re.I)
_COMMAND = re.compile(r"(?<![\w.-])(?:python(?:3)? -m pytest|pytest|npm (?:run (?:test|build)|test)|cargo (?:test|check|build)|go test|dotnet test)(?:[ A-Za-z0-9_./:=@-]*[A-Za-z0-9_/-])?", re.I)


def canonical_command(command: str) -> str:
    return shlex.join(shlex.split(command))


def command_kind(argv: list[str]) -> str:
    """类别由已登记工具的参数确定，模型不能配置成功退出码。"""
    if not argv:
        return "unclassified"
    if argv[0] in {"pytest"} or argv[:3] in (["python", "-m", "pytest"], ["python3", "-m", "pytest"]):
        diagnostic = {"--version", "-V", "--help", "-h", "--collect-only", "--co", "--fixtures", "--fixtures-per-test", "--markers", "--setup-plan"}
        return "unclassified" if any(arg.split("=", 1)[0] in diagnostic for arg in argv[1:]) else "test"
    if (argv[0] in {"npm", "pnpm", "yarn", "bun"} and argv[1:2] == ["test"]
            or argv[0] in {"cargo", "go", "dotnet"} and argv[1:2] == ["test"]
            or argv[0] in {"npm", "pnpm", "yarn", "bun"} and argv[1:3] == ["run", "test"]):
        return "test"
    if argv[0] in {"rg", "grep"}:
        return "search"
    if argv[0] in {"python", "python3", "node", "bun"} or argv[0].lower().startswith("powershell"):
        return "unclassified"
    if argv[0] in {"git", "ruff", "mypy", "npm", "pnpm", "yarn", "cargo", "go", "dotnet"}:
        return "development"
    return "unclassified"


def interpret_execution(*, execution_id: str, operation_id: str, argv: list[str], outcome: str,
                        exit_code: int | None = None, output_ref=None) -> ExecutionResult:
    category = command_kind(argv)
    verdict = "unknown"
    if outcome == "exited" and category != "unclassified":
        verdict = "succeeded" if exit_code in ({0, 1} if category == "search" else {0}) else "failed"
    elif outcome == "exited" and exit_code != 0 or outcome in {"failed", "timed_out", "cancelled"}:
        verdict = "failed"
    return ExecutionResult(execution_id=execution_id, operation_id=operation_id, outcome=outcome,
                           exit_code=exit_code, output_ref=output_ref, command_kind=category, validation_outcome=verdict)


def task_requirements(message: str, explicit: list[Requirement] = ()) -> tuple[list[Requirement], dict]:
    """仅提取可见的最低验收，不把启发式结果作为操作授权。"""
    preview = bool(_PREVIEW.search(message))
    answer = bool(re.match(r"\s*(?:请|帮我)?\s*(?:解释|说明|怎么|如何|为什么|是什么|explain|how|what|why)", message, re.I)) and not preview
    requirements: list[Requirement] = []

    def add(kind, scope, description, evidence_policy, origin="intent_rule", required=True):
        if not any(item.kind == kind and item.scope == scope for item in requirements):
            requirements.append(Requirement(requirement_id=f"requirement-{len(requirements) + 1}", kind=kind,
                                scope=scope, description=description, origin=origin, evidence_policy=evidence_policy, required=required))

    if preview:
        add("preview", "", "仅提供方案或补丁预览，不执行修改或命令", "response")
    elif not answer:
        if _WRITE.search(message):
            targets = list(dict.fromkeys(_FILE.findall(message)))
            for target in targets or [""]:
                add("file_changed", target, f"实际修改文件：{target or '所选项目'}", "disk")
        commands = list(dict.fromkeys(canonical_command(re.split(r"\s+(?:and|then|but|please)\b", m.group(0), maxsplit=1, flags=re.I)[0].strip())
                                      for m in _COMMAND.finditer(message)))
        for command in commands:
            category = command_kind(shlex.split(command))
            kind = "test" if category == "test" else "command"
            add(kind, command, f"{'测试通过' if kind == 'test' else '执行命令'}：{command}", "test_exit" if kind == "test" else "exit")
        if _TEST.search(message) and not any(item.kind == "test" for item in requirements):
            add("test", "", "在最后一次修改后运行测试并通过", "test_exit")
    for item in explicit:
        if preview and item.kind != "preview":
            raise ValueError("仅预览约束与执行验收要求冲突，请明确本次任务范围")
        add(item.kind, item.scope, item.description, item.evidence_policy, "user", item.required)
    if len(requirements) > 32:
        raise ValueError("验收要求超过 32 项，请缩小任务范围")
    return requirements, {"preview_only": preview, "answer_only": answer,
                          "commands_forbidden": preview or bool(_NO_COMMAND.search(message))}


def evaluate_requirements(run_id: str, requirements: list[Requirement], results: list[VerificationResult],
                          *, answered: bool = False, evidence_refs=()) -> RunOutcome:
    evidence = list(dict.fromkeys(key for result in results for key in result.evidence_ids))
    needed = {item.requirement_id for item in requirements if item.required}
    unresolved = [result for result in results if result.requirement_id in needed and result.status != "passed"]
    if any(result.status == "blocked" for result in unresolved):
        goal = "blocked"
    elif any(result.status == "failed" for result in results):
        goal = "unmet"
    elif unresolved:
        goal = "unknown"
    elif answered and (not requirements or all(item.kind == "preview" for item in requirements)):
        goal = "answered"
    elif requirements and needed:
        goal = "verified"
    else:
        goal = "unknown"
    return RunOutcome(run_id=run_id, goal_outcome=goal, requirements=requirements, verification_results=results,
                      evidence_ids=evidence, evidence_refs=list(evidence_refs),
                      unverified_items=[result.message for result in results if result in unresolved or result.status == "failed"])
