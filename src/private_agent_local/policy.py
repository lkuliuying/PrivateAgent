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
    ("git", "branch"),
    ("git", "branch", "--list"),
    ("git", "branch", "-a"),
    ("git", "branch", "--all"),
    ("git", "branch", "--show-current"),
}
RUNNERS = {"pytest", "ruff", "mypy", "python", "python3", "node", "npm", "pnpm", "yarn", "bun", "cargo", "go", "dotnet", "git"}


@dataclass(frozen=True)
class PowerShellRule:
    path_parameters: frozenset[str] = frozenset()
    value_parameters: frozenset[str] = frozenset()
    switches: frozenset[str] = frozenset()


POWERSHELL_RULES = {
    "get-location": PowerShellRule(),
    "get-childitem": PowerShellRule(
        frozenset({"-path", "-literalpath"}),
        frozenset({"-filter", "-include", "-exclude", "-depth"}),
        frozenset({"-force", "-recurse", "-file", "-directory", "-name", "-hidden", "-readonly", "-system"}),
    ),
    "get-item": PowerShellRule(frozenset({"-path", "-literalpath"}), switches=frozenset({"-force"})),
    "get-content": PowerShellRule(
        frozenset({"-path", "-literalpath"}),
        frozenset({"-encoding", "-totalcount", "-tail", "-readcount", "-delimiter"}),
        frozenset({"-raw", "-force"}),
    ),
    "test-path": PowerShellRule(
        frozenset({"-path", "-literalpath"}),
        frozenset({"-pathtype"}),
    ),
    "select-string": PowerShellRule(
        frozenset({"-path", "-literalpath"}),
        frozenset({"-pattern", "-encoding", "-context"}),
        frozenset({"-simplematch", "-casesensitive", "-quiet", "-allmatches", "-notmatch"}),
    ),
    "set-content": PowerShellRule(
        frozenset({"-path", "-literalpath"}),
        frozenset({"-value", "-encoding"}),
        frozenset({"-nonewline", "-force"}),
    ),
    "add-content": PowerShellRule(
        frozenset({"-path", "-literalpath"}),
        frozenset({"-value", "-encoding"}),
        frozenset({"-nonewline", "-force"}),
    ),
    "clear-content": PowerShellRule(
        frozenset({"-path", "-literalpath"}),
        switches=frozenset({"-force"}),
    ),
    "new-item": PowerShellRule(
        frozenset({"-path"}),
        frozenset({"-itemtype", "-value"}),
        frozenset({"-force"}),
    ),
    "remove-item": PowerShellRule(
        frozenset({"-path", "-literalpath"}),
        switches=frozenset({"-force", "-recurse"}),
    ),
    "copy-item": PowerShellRule(
        frozenset({"-path", "-literalpath", "-destination"}),
        switches=frozenset({"-force", "-recurse"}),
    ),
    "move-item": PowerShellRule(
        frozenset({"-path", "-literalpath", "-destination"}),
        switches=frozenset({"-force"}),
    ),
    "rename-item": PowerShellRule(
        frozenset({"-path", "-literalpath", "-newname"}),
        switches=frozenset({"-force"}),
    ),
}


@dataclass(frozen=True)
class CommandPlan:
    argv: tuple[str, ...]
    display_argv: tuple[str, ...]
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
        raise ValueError("所有权限模式都只允许所选项目内的相对路径")
    scope, relative = root, value
    candidate = files.within(scope, relative, allow_missing=True)
    if protected(candidate):
        raise ValueError("凭据、客户端内部数据和系统目录不允许通过文件工具访问")
    return scope, relative


def _automatic(mode: str, require_approval: bool) -> bool:
    return mode in {"workspace", "full_access"} and not require_approval


def _validate_project_arguments(arguments: tuple[str, ...]) -> None:
    for argument in arguments:
        value = argument.split("=", 1)[1] if "=" in argument else argument
        windows = PureWindowsPath(value)
        if (Path(value).is_absolute() or windows.drive or windows.root or ".." in Path(value).parts
                or "\\" in value or files.secret_path(Path(value))):
            raise ValueError("命令参数只能引用所选项目内的相对路径")


def command_plan(command: str, mode: str, *, require_approval: bool = False) -> CommandPlan:
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
        return CommandPlan(safe, safe, _automatic(mode, require_approval), "diagnostic")
    if argv[0] not in RUNNERS:
        raise ValueError("只允许登记的项目开发程序；PowerShell 请使用受控 PowerShell 工具")
    _validate_project_arguments(argv[1:])
    if any(files.secret_path(Path(arg)) or (Path(arg).is_absolute() and protected(Path(arg))) for arg in argv[1:]):
        raise ValueError("命令参数涉及受保护文件")
    if argv[0] in {"python", "python3", "node", "bun"} and any(arg in {"-c", "-e", "--eval", "-p", "--print"} for arg in argv[1:]):
        raise ValueError("不允许通过内联解释器绕过工具策略，请使用可审查的项目脚本")
    allowed_subcommands = {
        "git": {"status", "diff", "log", "show", "rev-parse", "ls-files", "branch"},
        "npm": {"test", "run", "exec", "--version"}, "pnpm": {"test", "run", "exec", "--version"},
        "yarn": {"test", "run", "--version"}, "cargo": {"test", "check", "build", "fmt", "clippy", "--version"},
        "go": {"test", "build", "vet", "fmt", "version"}, "dotnet": {"test", "build", "format", "--version"},
    }
    if argv[0] in allowed_subcommands and (len(argv) < 2 or argv[1] not in allowed_subcommands[argv[0]]):
        raise ValueError("该命令动作不在当前项目的开发任务范围内")
    if argv[0] == "git" and argv[1] == "branch" and argv not in DIAGNOSTICS:
        raise ValueError("模型只能查询本地分支；分支切换请由用户在项目分支下拉框中执行")
    if argv[0] == "git":
        # 扩展 Git 参数仍不能重新打开外部执行器或覆盖安全配置。
        if any(arg.startswith(("--ext-diff", "--textconv", "--exec-path", "--config-env", "--output", "-c")) for arg in argv[2:]):
            raise ValueError("不允许覆盖 Git 诊断安全配置")
        argv = ("git", "-c", "core.fsmonitor=false", "-c", "core.pager=cat", *argv[1:])
        if "diff" in argv or "show" in argv:
            argv = (*argv, "--no-ext-diff", "--no-textconv")
    profile = "full-access-development" if mode == "full_access" else "workspace-development" if mode == "workspace" else "confirmed-development"
    return CommandPlan(argv, argv, _automatic(mode, require_approval), profile)


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def powershell_plan(
    root: Path,
    command: str,
    arguments: list[str],
    mode: str,
    *,
    require_approval: bool = False,
) -> CommandPlan:
    if mode == "readonly":
        raise ValueError("只读模式不允许运行 PowerShell 命令")
    if os.name != "nt":
        raise ValueError("受控 PowerShell 工具只在 Windows 客户端可用")
    normalized = command.casefold()
    rule = POWERSHELL_RULES.get(normalized)
    if rule is None:
        raise ValueError("该 PowerShell 命令未登记；请使用项目文件工具或已登记的开发命令")
    if len(arguments) > 30 or any(not argument or len(argument) > 4000 or "\x00" in argument for argument in arguments):
        raise ValueError("PowerShell 参数超出限制")
    index = 0
    script_arguments: list[str] = []
    while index < len(arguments):
        parameter = arguments[index].casefold()
        if parameter in rule.switches:
            script_arguments.append(parameter)
            index += 1
            continue
        if parameter not in rule.path_parameters and parameter not in rule.value_parameters:
            raise ValueError("PowerShell 只接受登记的具名参数，不接受脚本、管道或位置参数")
        if index + 1 >= len(arguments):
            raise ValueError("PowerShell 参数缺少对应值")
        value = arguments[index + 1]
        if parameter in rule.path_parameters:
            files.within(root, value, allow_missing=True)
        # 参数名必须保留为 PowerShell 语法标记；仅对经过边界检查的参数值进行引用。
        script_arguments.extend((parameter, _powershell_quote(value)))
        index += 2
    canonical = next(name for name in POWERSHELL_RULES if name == normalized)
    display = ("powershell", command, *arguments)
    script = "& " + " ".join((_powershell_quote(canonical), *script_arguments))
    argv = ("powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script)
    profile = "full-access-powershell" if mode == "full_access" else "workspace-powershell" if mode == "workspace" else "confirmed-powershell"
    return CommandPlan(argv, display, _automatic(mode, require_approval), profile)
