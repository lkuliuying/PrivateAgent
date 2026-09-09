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
    "history": ["tests/unit/test_local_history.py"],
    "sandbox": ["tests/unit/test_windows_sandbox.py", "tests/coding_acceptance/test_host_probes.py"],
    "recovery": ["tests/unit/test_local_recovery.py"],
    "execution": ["tests/unit/test_local_execution_sessions.py"],
    "streaming": ["tests/unit/test_local_streaming.py", "tests/unit/test_local_models.py"],
    "execution-duration": ["tests/coding_acceptance/test_s4_duration.py"],
    "repository": [f"tests/unit/test_local_{name}.py" for name in ("file_ranges", "search_pagination", "patchsets")],
    "context": [f"tests/unit/test_local_{name}.py" for name in ("instructions", "context_history", "compaction")],
    "completion": ["tests/unit/test_local_completion.py"],
    "local": [f"tests/unit/test_local_{name}.py" for name in (
        "executor", "permissions", "context", "model_contract", "store", "ipc", "git",
    )],
    "contracts": ["tests/coding_acceptance/test_contracts.py", "tests/test_agent_v2_skeleton.py"],
    "baseline": ["tests/coding_acceptance/test_baseline.py"],
    "host": ["tests/unit/test_local_exec_host.py", "tests/coding_acceptance/test_host_probes.py"],
    "tooling": ["tests/coding_acceptance/test_tooling.py"],
    "duration": ["tests/coding_acceptance/test_host_duration.py"],
}


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
