"""本机权限策略；策略检查不等于操作系统沙箱或管理员授权。"""
from __future__ import annotations

import os
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from private_agent_core.tool_specs import ToolFailure

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
ALLOWED_SUBCOMMANDS = {
    "git": {"status", "diff", "log", "show", "rev-parse", "ls-files", "branch"},
    "npm": {"test", "run", "exec", "--version"}, "pnpm": {"test", "run", "exec", "--version"},
    "yarn": {"test", "run", "--version"}, "cargo": {"test", "check", "build", "fmt", "clippy", "--version"},
    "go": {"test", "build", "vet", "fmt", "version"}, "dotnet": {"test", "build", "format", "--version"},
}


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

# 文件副作用统一经过读取版本、补丁预览和日志；项目脚本的间接写入仍由执行策略约束。
POWERSHELL_FILE_WRITES = frozenset({"set-content", "add-content", "clear-content", "new-item", "remove-item", "copy-item", "move-item", "rename-item"})


@dataclass(frozen=True)
class CommandPlan:
    argv: tuple[str, ...]
    display_argv: tuple[str, ...]
    automatic: bool
    profile: str
    inline_code: bool = False


def protected(path: Path) -> bool:
    if files.secret_path(path) or any(part.casefold() in {".codex", ".agents", ".privateagent", "privateagent", "privateagentremote", "com.personal-assistant.desktop", "com.personal-assistant.desktop.remote"} for part in path.parts):
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
    for directory in [candidate, *candidate.parents]:
        if directory == root:
            break
        if directory.is_dir() and (directory / ".git").exists():
            raise ValueError("项目工具不进入子模块或嵌套 Git 仓库，请单独授权该项目")
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


def _inline_argument(argv: tuple[str, ...]) -> int | None:
    """识别解释器的代码参数；代码之后的参数不再作为解释器选项解析。"""
    if not argv or argv[0] not in {"python", "python3", "node", "bun"}:
        return None
    python = argv[0] in {"python", "python3"}
    index, safe_prefix = 1, True
    while index < len(argv):
        argument = argv[index]
        if not python:
            option, separator, value = argument.partition("=")
            if option in {"-r", "--require", "--import", "--loader", "--experimental-loader"}:
                preload = value if separator else argv[index + 1] if index + 1 < len(argv) else ""
                if preload.casefold().startswith("data:"):
                    raise ValueError("内联代码请使用已声明的受限 eval 入口，不允许 data URL 预加载")
        if argument in {"--", "-"}:
            return None
        if not argument.startswith("-"):
            if not safe_prefix and any(
                    value.startswith(("-c", "-e", "-p")) and not value.startswith("--")
                    or value in {"--eval", "--print"} or value.startswith(("--eval=", "--print="))
                    or not python and value.split("=", 1)[0] in {"-r", "--require", "--import", "--loader", "--experimental-loader"}
                    or python and value.startswith("-") and not value.startswith("--") and "c" in value[1:]
                    for value in argv[index + 1:]):
                raise ValueError("内联命令使用了未支持的解释器前置选项")
            return None
        offset = None
        if python:
            short_option = next((flag for flag in argument[1:] if flag in "cmWX"), None) if not argument.startswith("--") else None
            if short_option == "m":
                return None
            if argument == "--check-hash-based-pycs":
                index += 2
                continue
            if short_option in {"W", "X"}:
                index += 2 if argument.index(short_option, 1) == len(argument) - 1 else 1
                continue
            if not argument.startswith("--") and "c" in argument[1:]:
                offset = argument.index("c", 1) + 1
                safe_prefix &= all(flag in "BEIOsSubqvx" for flag in argument[1:offset - 1])
            else:
                safe_prefix &= not argument.startswith("--") and all(flag in "BEIOsSubqvx" for flag in argument[1:])
        else:
            if argument in {"-e", "-p", "-pe", "--eval", "--print"}:
                offset = len(argument)
            elif argument.startswith("--eval="):
                offset = argument.index("=") + 1
                if offset == len(argument):
                    raise ValueError("内联命令缺少代码")
            elif argument.startswith("--print="):
                raise ValueError("Node --print 的代码必须使用独立参数")
            elif argument.startswith(("-e", "-p")) and not argument.startswith("--"):
                raise ValueError("Node 内联短选项的代码必须使用独立参数")
            elif argument in {"-r", "--require", "--import", "--input-type"}:
                # 未支持的前置选项仍要扫描其后的 eval，避免旧入口漏过紧贴式代码。
                safe_prefix = False
                index += 2
                continue
            else:
                safe_prefix &= argument in {"--input-type=module", "--input-type=commonjs", "--no-warnings", "--no-deprecation"}
        if offset is not None:
            payload_index = index if len(argument) > offset else index + 1
            payload = argument[offset:] if payload_index == index else argv[payload_index] if payload_index < len(argv) else ""
            if not safe_prefix or not payload.strip():
                raise ValueError("内联命令缺少代码或使用了未支持的解释器前置选项")
            return payload_index
        index += 1
    return None


def _command_plan(argv: tuple[str, ...], mode: str, *, require_approval: bool, allow_inline: bool) -> CommandPlan:
    if mode not in MODES:
        raise ValueError("未知的命令权限模式")
    if mode == "readonly":
        raise ValueError("只读模式不允许运行命令")
    if (not argv or len(argv) > 40 or any(not isinstance(arg, str) or not arg or len(arg) > 2000 or "\x00" in arg for arg in argv)):
        raise ValueError("命令参数为空或超出限制")
    inline = _inline_argument(argv)
    if inline is not None and (not allow_inline or argv[0] == "bun"):
        raise ValueError("内联解释器只允许通过现代受限执行入口运行")
    ordinary = tuple(arg for index, arg in enumerate(argv) if index != inline)
    if any(any(c in arg for c in "&|;<>`$\r\n") for arg in ordinary):
        raise ValueError("命令必须为单个程序及参数，不允许 shell 拼接或替换")
    if argv in DIAGNOSTICS:
        # 禁止 Git 外部 diff/textconv/fsmonitor，避免诊断命令触发项目配置中的程序。
        safe = ("git", "-c", "core.fsmonitor=false", "-c", "core.pager=cat", *argv[1:])
        if argv[1] == "diff":
            safe = (*safe, "--no-ext-diff", "--no-textconv")
        return CommandPlan(safe, safe, _automatic(mode, require_approval), "diagnostic")
    if argv[0] not in RUNNERS:
        raise ToolFailure("command_not_allowed", "只允许登记的项目开发程序；先查询 get_execution_capabilities。文件与 Git 查询优先使用专用工具")
    _validate_project_arguments(ordinary[1:])
    if any(files.secret_path(Path(arg)) or (Path(arg).is_absolute() and protected(Path(arg))) for arg in ordinary[1:]):
        raise ValueError("命令参数涉及受保护文件")
    if inline is None and argv[0] in {"python", "python3", "node", "bun"} and any(arg in {"-c", "-e", "--eval", "-p", "--print"} for arg in argv[1:]):
        raise ValueError("不允许通过内联解释器绕过工具策略，请使用可审查的项目脚本")
    if argv[0] in ALLOWED_SUBCOMMANDS and (len(argv) < 2 or argv[1] not in ALLOWED_SUBCOMMANDS[argv[0]]):
        raise ToolFailure("command_not_allowed", "该命令动作不在当前项目的开发任务范围内；先查询 get_execution_capabilities")
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
    return CommandPlan(argv, argv, _automatic(mode, require_approval), profile, inline_code=inline is not None)


def command_plan(command: str, mode: str, *, require_approval: bool = False) -> CommandPlan:
    return _command_plan(tuple(shlex.split(command, posix=True)), mode, require_approval=require_approval, allow_inline=False)


def execution_plan(argv: list[str], mode: str, *, execution_mode: str = "restricted", require_approval: bool = False) -> CommandPlan:
    """现代入口保留 argv 原值；内联代码与项目脚本共享同一系统沙箱边界。"""
    if execution_mode not in {"restricted", "trusted_project"}:
        raise ValueError("未知的命令执行模式")
    return _command_plan(tuple(argv), mode, require_approval=require_approval or execution_mode == "trusted_project",
                         allow_inline=execution_mode == "restricted")


def execution_boundary(execution_mode: str, network_policy: str, *, tty: bool = False) -> bool:
    """审批模式不能放宽沙箱；只有显式可信请求可以申请脱离隔离。"""
    if execution_mode == "restricted":
        if network_policy != "none" or tty:
            raise ToolFailure("invalid_execution_options", '受限模式要求 execution_mode="restricted"、network_policy="none"、tty=false。'
                              '当前不支持受限命令按域联网；不得自动改用 trusted_project 绕过拒绝。')
        return True
    if execution_mode != "trusted_project" or network_policy != "approved":
        raise ToolFailure("invalid_execution_options", '解除沙箱必须显式申请 execution_mode="trusted_project" 和 network_policy="approved"，'
                          '每次均须用户明确审批当前用户的文件及网络访问。')
    return False


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def execution_capabilities(permission_mode: str = "confirm") -> dict:
    """仅检查程序存在性，不执行版本探针或暴露环境变量。"""
    return {
        "programs": [{"name": name, "available": shutil.which(name) is not None,
                      "allowed_actions": sorted(ALLOWED_SUBCOMMANDS.get(name, ())) or None}
                     for name in sorted(RUNNERS)],
        "defaults": {"execution_mode": "restricted", "network_policy": "none", "tty": False,
                     "stdin": False, "retention": "run"},
        "path_policy": "project_relative", "shell": False, "inline_eval": True,
        "security_policy": {"version": "1.0", "mode_changes_sandbox": False,
                            "legacy_execution_mode": "restricted", "trusted_execution_approval": "always",
                            "restricted_network": "none", "domain_network_supported": False,
                            "protected_paths": "existing_sensitive_objects_and_control_directories",
                            "future_sensitive_filename_rules": False,
                            "overlapping_protected_workspaces": "reject", "conflicting_package_grants": "reject"},
        "inline_policy": {"execution_mode": "restricted", "network_policy": "none", "tty": False,
                          "interpreters": {"python": ["-c"], "python3": ["-c"], "node": ["-e", "--eval", "-p", "--print"]},
                          "max_argument_characters": 2000, "legacy_and_trusted": "denied",
                          "filesystem_scope": "project_with_existing_sensitive_objects_denied_and_control_directories_readonly"},
        "approval_required": not _automatic(permission_mode, False),
        "approval_policy": {
            "ordinary_restricted": "policy" if _automatic(permission_mode, False) else "required",
            "advanced_request": "required", "stdin_input": "policy" if _automatic(permission_mode, False) else "required",
            "stdin_automatic_conditions": {"same_run": True, "approved_start": True, "execution_mode": "restricted",
                                           "network_policy": "none", "tty": False, "state_version": "current"},
            "automatic_conditions": {"tool": "exec_command", "execution_mode": "restricted",
                                     "network_policy": "none", "tty": False, "stdin": False, "retention": "run"},
            "sandbox_unavailable": "reject_without_fallback",
        },
        "powershell": [{"command": name, "path_parameters": sorted(rule.path_parameters),
                        "value_parameters": sorted(rule.value_parameters), "switches": sorted(rule.switches)}
                       for name, rule in POWERSHELL_RULES.items() if name not in POWERSHELL_FILE_WRITES]
                      if os.name == "nt" else [],
    }


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
    if normalized in POWERSHELL_FILE_WRITES:
        raise ValueError("PowerShell 直接文件写入已收敛到统一补丁工具；请使用 read_code_file、propose_project_patch 和 apply_project_patch")
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
            allowed = sorted(rule.path_parameters | rule.value_parameters | rule.switches)
            raise ValueError("PowerShell 只接受登记的具名参数，不接受脚本、管道或位置参数。"
                             "参数名和值须为独立数组元素，路径使用 -LiteralPath；当前命令允许的参数：" + ", ".join(allowed))
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
    # 所有审批模式使用相同的受限命令边界；PSDrive 不需要磁盘根目录读取权限。
    script = ("New-PSDrive -Name PrivateAgentWorkspace -PSProvider FileSystem -Root "
              + _powershell_quote(str(root)) + " -ErrorAction Stop | Out-Null; "
              "Set-Location -LiteralPath 'PrivateAgentWorkspace:' -ErrorAction Stop; " + script)
    argv = ("powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script)
    profile = "full-access-powershell" if mode == "full_access" else "workspace-powershell" if mode == "workspace" else "confirmed-powershell"
    return CommandPlan(argv, display, _automatic(mode, require_approval), profile)
