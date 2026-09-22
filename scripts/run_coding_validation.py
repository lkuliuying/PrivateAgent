"""在全新目录中运行明确列出的本机测试，不加载业务配置或数据库。"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from coding_validation_process import managed_process

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    "workbench": ["tests/unit/test_workspace_features.py", "tests/unit/test_workbench_integrations.py"],
    "security": ["tests/unit/test_security_permissions.py", "tests/unit/test_secret_filter.py",
                 "tests/unit/test_security_boundaries.py", "tests/unit/test_sandbox_sensitive_paths.py",
                 "tests/unit/test_security_streaming.py"],
    "output": ["tests/unit/test_local_output.py"],
    "reflection": ["tests/unit/test_local_reflection.py", "tests/unit/test_reflection_review.py",
                   "tests/unit/test_reflection_integration.py"],
    "observer": ["tests/unit/test_observer_checks.py", "tests/unit/test_observer_steps.py"],
    "reasoning": ["tests/unit/test_responses_adapter.py", "tests/unit/test_reasoning_decisions.py"],
    "context-alignment": ["tests/unit/test_context_alignment.py", "tests/unit/test_local_distribution.py"],
    "orchestration": ["tests/unit/test_local_planning.py", "tests/unit/test_local_progress.py", "tests/unit/test_local_plan_mode.py"],
    "memory": ["tests/unit/test_local_memories.py", "tests/unit/test_local_compaction.py", "tests/unit/test_local_context_history.py", "tests/unit/test_local_instructions.py"],
    "project-management": ["tests/unit/test_local_project_management.py", "tests/unit/test_local_store.py"],
    "shared-models": ["tests/unit/test_model_gateway.py", "tests/unit/test_model_metadata.py", "tests/unit/test_model_probe.py"],
    "desktop-packaging": ["tests/packaging/test_nsis_installer_template.py", "tests/packaging/test_release_manifest.py", "tests/packaging/test_sign_installer.py"],
    "documentation": ["tests/unit/test_documentation_mcp.py"],
    "tool-selection": ["tests/unit/test_tool_catalog.py", "tests/unit/test_tool_selection_runtime.py"],
    "execution-autonomy": ["tests/unit/test_execution_autonomy.py"],
    "execution-alignment": ["tests/unit/test_execution_inline.py", "tests/unit/test_execution_stdin_authorization.py", "tests/unit/test_execution_inline_completion.py"],
    "parallel": ["tests/unit/test_parallel_tools.py", "tests/unit/test_agent_runtime.py", "tests/unit/test_local_recovery.py"],
    "tools": ["tests/unit/test_local_tool_registry.py", "tests/unit/test_local_model_contract.py",
              "tests/unit/test_local_permissions.py", "tests/unit/test_local_executor.py"],
    "direct-models": ["tests/unit/test_direct_models.py", "tests/unit/test_local_access.py", "tests/unit/test_local_model_routing.py", "tests/unit/test_model_metadata.py", "tests/unit/test_model_probe.py"],
    "phase-d": ["tests/coding_acceptance/test_s6_phase_d.py"],
    "acceptance": ["tests/coding_acceptance/test_s6_acceptance.py", "tests/coding_acceptance/test_s6_delivery.py",
                   "tests/coding_acceptance/test_s6_external.py", "tests/coding_acceptance/test_s6_isolation.py",
                   "tests/coding_acceptance/test_s6_custody.py", "tests/coding_acceptance/test_s6_models.py", "tests/coding_acceptance/test_s6_direct_evaluation.py", "tests/unit/test_model_evaluation.py", "tests/coding_acceptance/test_s6_phase_d.py"],
    "model-evaluation": ["tests/coding_acceptance/test_s6_models.py", "tests/coding_acceptance/test_s6_direct_evaluation.py", "tests/unit/test_model_evaluation.py"],
    "local-probe": ["tests/coding_acceptance/test_s6_local_probe.py"],
    "external": ["tests/coding_acceptance/test_s6_external.py"],
    "isolation": ["tests/coding_acceptance/test_s6_isolation.py"],
    "custody": ["tests/coding_acceptance/test_s6_custody.py"],
    "history": ["tests/unit/test_local_history.py"],
    "sandbox": ["tests/unit/test_windows_sandbox.py", "tests/coding_acceptance/test_host_probes.py"],
    "recovery": ["tests/unit/test_local_recovery.py"],
    "execution": ["tests/unit/test_local_execution_sessions.py"],
    "streaming": ["tests/unit/test_local_streaming.py", "tests/unit/test_local_models.py"],
    "execution-duration": ["tests/coding_acceptance/test_s4_duration.py"],
    "repository": [f"tests/unit/test_local_{name}.py" for name in ("file_ranges", "search_pagination", "patchsets")],
    "context": [f"tests/unit/test_local_{name}.py" for name in ("instructions", "context_history", "compaction")],
    "completion": ["tests/unit/test_local_completion.py", "tests/unit/test_task_intent.py", "tests/unit/test_local_task_constraints.py"],
    "local": [f"tests/unit/test_local_{name}.py" for name in (
        "executor", "permissions", "context", "model_contract", "store", "ipc", "git",
    )],
    "contracts": ["tests/coding_acceptance/test_contracts.py"],
    "baseline": ["tests/coding_acceptance/test_baseline.py"],
    "host": ["tests/unit/test_local_exec_host.py", "tests/coding_acceptance/test_host_probes.py"],
    "tooling": ["tests/coding_acceptance/test_tooling.py"],
    "duration": ["tests/coding_acceptance/test_host_duration.py"],
}

SUITES["tool-evolution"] = list(dict.fromkeys(
    path for suite in ("tools", "tool-selection", "execution-autonomy", "execution-alignment", "parallel", "documentation", "execution", "repository", "context", "completion", "orchestration")
    for path in SUITES[suite]
))

SUITES["security-regression"] = list(dict.fromkeys(
    path for suite in ("security", "sandbox", "execution", "execution-autonomy", "execution-alignment",
                       "tools", "reasoning", "direct-models", "documentation", "repository", "streaming")
    for path in SUITES[suite]
))


def new_directory(parent: Path, prefix: str) -> Path:
    """继承父目录 ACL，避免 Windows 上私有 ACL 排除受限令牌。"""
    path = parent / f"{prefix}-{uuid.uuid4().hex}"
    path.mkdir(mode=0o777)
    if path.is_symlink() or not path.resolve().is_relative_to(parent.resolve()):
        raise ValueError("隔离目录越界")
    return path.resolve()


def isolated_environment(directory: Path) -> dict[str, str]:
    allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "SYSTEMDRIVE",
               "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment.update({
        "TEMP": str(directory / "tmp"), "TMP": str(directory / "tmp"),
        "PYTHONPATH": os.pathsep.join(str(ROOT / p) for p in ("src", "scripts", "tests/coding_acceptance", "tests/unit")),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "CODING_VALIDATION_DIR": str(directory),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
    })
    return environment


def run(suite: str) -> int:
    parent = ROOT / ".run" / "coding-agent-validation"
    if not parent.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("测试根目录不能链接到仓库以外")
    parent.mkdir(parents=True, exist_ok=True)
    directory = new_directory(parent, suite)
    (directory / "tmp").mkdir()
    tests = [item for name, items in SUITES.items() if name not in {"duration", "execution-duration"} for item in items] if suite == "all" else SUITES[suite]
    tests = list(dict.fromkeys(tests))
    paths = [(ROOT / item).resolve(strict=True) for item in tests]
    if any(not path.is_relative_to(ROOT / "tests") for path in paths):
        raise ValueError("测试文件越界")
    command = [str(Path(sys.executable).absolute()), "-B", "-m", "pytest",
               "-c", str(ROOT / "pyproject.toml"), "--noconftest", "-p", "no:cacheprovider",
               "-p", "coding_validation_plugin", "-p", "pytest_asyncio.plugin",
               "-o", "addopts=", "-o", "filterwarnings=", "-q", "-ra", *map(str, paths)]
    manifest = {"suite": suite, "command": command, "cwd": str(directory), "exit_code": None}
    print(f"隔离目录：{directory}", flush=True)
    try:
        with managed_process(command, cwd=directory, env=isolated_environment(directory),
                             stdin=subprocess.DEVNULL) as process:
            manifest["exit_code"] = process.wait(timeout=900)
    except subprocess.TimeoutExpired:
        manifest["exit_code"] = 124
        print("隔离测试超过 900 秒，已请求回收所属进程树", file=sys.stderr)
    finally:
        (directory / "invocation.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest["exit_code"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=[*SUITES, "all"], default="all")
    args = parser.parse_args()
    return run(args.suite)


if __name__ == "__main__":
    raise SystemExit(main())
