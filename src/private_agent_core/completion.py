"""完成要求与命令语义的纯函数；不依赖旧业务配置、数据库或模型断言。"""
from __future__ import annotations

import shlex

from .coding_contracts import (
    ExecutionResult,
    Requirement,
    RunOutcome,
    VerificationResult,
)


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
    """兼容已有调用方；任务解释只由统一解析器生成，不代表操作授权。"""
    from .task_intent import interpret_task

    interpretation = interpret_task(message, explicit)
    return interpretation.requirements, interpretation.policy.model_dump()


def evaluate_requirements(run_id: str, requirements: list[Requirement], results: list[VerificationResult],
                          *, answered: bool = False, evidence_refs=(), unperformed=(), conflicts=()) -> RunOutcome:
    evidence = list(dict.fromkeys(key for result in results for key in result.evidence_ids))
    needed = {item.requirement_id for item in requirements if item.required}
    unresolved = [result for result in results if result.requirement_id in needed and result.status != "passed"]
    if conflicts or any(result.status == "blocked" for result in unresolved):
        goal = "blocked"
    elif any(result.status == "failed" for result in results):
        goal = "unmet"
    elif unresolved or unperformed and not (answered and all(item.kind == "preview" for item in requirements)):
        goal = "unknown"
    elif answered and (not requirements or all(item.kind == "preview" for item in requirements)):
        goal = "answered"
    elif requirements and needed:
        goal = "verified"
    else:
        goal = "unknown"
    return RunOutcome(run_id=run_id, goal_outcome=goal, requirements=requirements, verification_results=results,
                      evidence_ids=evidence, evidence_refs=list(evidence_refs),
                      unverified_items=list(dict.fromkeys([result.message for result in results if result in unresolved or result.status == "failed"]
                                                          + list(conflicts) + list(unperformed))))
