"""本机权限策略；策略检查不等于操作系统沙箱或管理员授权。"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from . import files

MODES = frozenset({"readonly", "confirm", "workspace", "full_access"})
DIAGNOSTICS = {
    ("git", "status", "--short"),
    ("git", "diff", "--stat"),
    ("git", "diff", "--no-ext-diff", "--no-textconv"),
    ("git", "log", "-5", "--oneline"),
    ("git", "rev-parse", "--show-toplevel"),
}
RUNNERS = {"pytest", "ruff", "mypy", "python", "python3", "node", "npm", "pnpm", "yarn", "bun", "cargo", "go", "dotnet", "git"}


@dataclass(frozen=True)
class CommandPlan:
    argv: tuple[str, ...]
    automatic: bool
    profile: str


def protected(path: Path) -> bool:
    if files.secret_path(path) or any(part.casefold() in {".codex", ".privateagent", "privateagent", "privateagentremote", "com.personal-assistant.desktop", "com.personal-assistant.desktop.remote"} for part in path.parts):
        return True
    if os.name == "nt":
        system_roots = [Path(os.environ.get("WINDIR", "C:/Windows")), Path("C:/ProgramData/Microsoft")]
    else:
        system_roots = [Path(p) for p in ("/etc", "/usr", "/bin", "/sbin", "/proc", "/sys", "/dev", "/boot")]
    return any(path == root or path.is_relative_to(root) for root in system_roots)


def file_scope(root: Path, value: str, mode: str) -> tuple[Path, str]:
    path = Path(value)
    if path.is_absolute():
        if mode != "full_access":
            raise ValueError("当前权限仅允许项目内相对路径")
        windows = PureWindowsPath(value)
        if windows.drive.startswith("\\\\") or ".." in path.parts:
            raise ValueError("完全访问不允许网络共享路径或路径回退")
        scope = Path(path.anchor)
        relative = path.relative_to(scope).as_posix()
    else:
        scope, relative = root, value
    candidate = files.within(scope, relative, allow_missing=True)
    if protected(candidate):
        raise ValueError("凭据、客户端内部数据和系统目录不允许通过文件工具访问")
    return scope, relative


def command_plan(command: str, mode: str) -> CommandPlan:
    if mode == "readonly":
        raise ValueError("只读模式不允许运行命令")
    argv = tuple(shlex.split(command, posix=True))
    if not argv or len(argv) > 40 or any(any(c in arg for c in "&|;<>`$\r\n\x00") for arg in argv):
        raise ValueError("命令必须为单个程序及参数，不允许 shell 拼接或替换")
    if argv in DIAGNOSTICS:
        # 禁止 Git 外部 diff/textconv/fsmonitor，避免诊断命令触发项目配置中的程序。
        safe = ("git", "-c", "core.fsmonitor=false", "-c", "core.pager=cat", *argv[1:])
        if argv[1] == "diff":
            safe = (*safe, "--no-ext-diff", "--no-textconv")
        return CommandPlan(safe, mode in {"workspace", "full_access"}, "diagnostic")
    if mode != "full_access":
        return CommandPlan(tuple(files.parse_command(command)), False, "project-script")
    if argv[0] not in RUNNERS:
        raise ValueError("完全访问不允许 shell、提权、网络传输或未登记的执行程序")
    if any(files.secret_path(Path(arg)) or (Path(arg).is_absolute() and protected(Path(arg))) for arg in argv[1:]):
        raise ValueError("命令参数涉及受保护文件")
    if argv[0] in {"python", "python3", "node", "bun"} and any(arg in {"-c", "-e", "--eval", "-p", "--print"} for arg in argv[1:]):
        raise ValueError("不允许通过内联解释器绕过工具策略，请使用可审查的项目脚本")
    allowed_subcommands = {
        "git": {"status", "diff", "log", "show", "rev-parse", "ls-files"},
        "npm": {"test", "run", "exec", "--version"}, "pnpm": {"test", "run", "exec", "--version"},
        "yarn": {"test", "run", "--version"}, "cargo": {"test", "check", "build", "fmt", "clippy", "--version"},
        "go": {"test", "build", "vet", "fmt", "version"}, "dotnet": {"test", "build", "format", "--version"},
    }
    if argv[0] in allowed_subcommands and (len(argv) < 2 or argv[1] not in allowed_subcommands[argv[0]]):
        raise ValueError("该命令动作不在完全访问的开发任务范围内")
    if argv[0] == "git":
        # 扩展 Git 参数仍不能重新打开外部执行器或覆盖安全配置。
        if any(arg.startswith(("--ext-diff", "--textconv", "--exec-path", "--config-env", "--output", "-c")) for arg in argv[2:]):
            raise ValueError("不允许覆盖 Git 诊断安全配置")
        argv = ("git", "-c", "core.fsmonitor=false", "-c", "core.pager=cat", *argv[1:])
        if "diff" in argv or "show" in argv:
            argv = (*argv, "--no-ext-diff", "--no-textconv")
    return CommandPlan(argv, True, "full-access-development")
