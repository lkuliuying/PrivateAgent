"""v0.5.0 B2：命令可信执行适配模块。

把 legacy ``run_whitelisted_command`` 包装为 versioned ``ToolSpec``
（契约见 ``agents/workflow_contracts.py``，B0 冻结）。安全边界
（威胁清单 docs/releases/v0.5.0/v0.5.0-b0-contracts-20260809.md §4.2）：

- 只接受参数数组，不经 shell；拒绝 shell 控制符与非白名单命令（全局默认
  前缀 + 项目 command profile 前缀合并）；
- 环境变量固定 allowlist，清除代理/凭据/无关继承变量；
- Windows 使用 Job Object（KILL_ON_JOB_CLOSE）清理整个进程树；取消/超时/
  退出后查询 job 内活跃进程数作为清理证据（``processes_remaining``）；
- stdout/stderr 流式读取（防管道阻塞）但有界持久化（行数/单行/总字节上限），
  写入前脱敏；最终输出截断并带标记；
- 崩溃后的 unknown execution 由 executions 管道拒绝自动重试
  （``non_idempotent``）。

POSIX 分支使用进程组（``start_new_session`` + ``os.killpg``），
v0.5.0 正式支持面为 Windows。
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.runtime import CancellationToken
from ..agents.tools import (
    ToolDispatchCancelled,
    ToolRiskLevel,
    ToolSpec,
    VersionedToolRegistry,
    current_execution_id,
)
from ..agents.workflow_contracts import WORKFLOW_CONTRACT_BY_NAME
from .code_tools import (
    COMMAND_TIMEOUT,
    is_whitelisted_command,
    parse_command,
    whitelisted_prefix_length,
)
from .patch_sets import _profile_to_args
from .permissions import PermissionError_
from .projects import ProjectService, resolve_within
from .result_parsers import parse_command_result

_COMMAND_CONTRACT = WORKFLOW_CONTRACT_BY_NAME["run_whitelisted_command"]

# === 输出边界 ===
MAX_STREAM_LINES = 5_000  # 每执行持久化行数上限
MAX_LINE_CHARS = 8_000  # 单行截断上限
MAX_OUTPUT_CHARS = 30_000  # 最终 output 汇总上限（与 legacy 一致）
_STREAM_TRUNCATED_MARKER = "[output truncated]"
_LINE_TRUNCATED_MARKER = "…（行已截断）"

# === 环境变量 allowlist：清除代理/凭据/无关继承变量 ===
_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SystemRoot",
        "WINDIR",
        "SystemDrive",
        "COMSPEC",
        "OS",
        "PROCESSOR_ARCHITECTURE",
        "PROCESSOR_ARCHITEW6432",
        "NUMBER_OF_PROCESSORS",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "APPDATA",
        "ProgramData",
        "ProgramFiles",
        "ProgramFiles(x86)",
        "PSModulePath",
        "PROMPT",
        "HOME",
        "LANG",
        "LC_ALL",
    }
)
_ENV_REJECT_PATTERN = re.compile(
    r"(PROXY|API[_-]?KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE
)


def build_safe_environment() -> dict[str, str]:
    """构造命令环境：allowlist 拷贝 + 拒绝代理/凭据类变量。

    Windows 进程环境变量名大小写不敏感但保留原始大小写（某些环境为全大写，
    如 SYSTEMROOT），按 casefold 匹配 allowlist。
    """
    allowed = {name.casefold() for name in _ENV_ALLOWLIST}
    env: dict[str, str] = {}
    for name, value in os.environ.items():
        if name.casefold() in allowed and not _ENV_REJECT_PATTERN.search(name):
            env[name] = value
    return env


# === 输出脱敏（持久化与模型可见前统一处理） ===
_SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_-]?key|password|secret|token)\s*[:=]\s*)[^\s,;]+"),
)


def _redact_line(text: str) -> str:
    redacted = text
    for pattern in _SECRET_TEXT_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


# === Windows Job Object：进程树级清理 ===
if sys.platform == "win32":  # pragma: win32
    import ctypes
    from ctypes import wintypes

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_TERMINATE = 0x0001

    class _LARGE_INTEGER(ctypes.Structure):
        _fields_ = [("QuadPart", ctypes.c_longlong)]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", _LARGE_INTEGER),
            ("PerJobUserTimeLimit", _LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", _LARGE_INTEGER),
            ("TotalKernelTime", _LARGE_INTEGER),
            ("ThisPeriodTotalUserTime", _LARGE_INTEGER),
            ("ThisPeriodTotalKernelTime", _LARGE_INTEGER),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]


class _JobObject:
    """Windows Job Object 封装（KILL_ON_JOB_CLOSE：句柄关闭即清理整棵树）。"""

    def __init__(self) -> None:
        self._handle: Any = None
        self._kernel32: Any = None
        if sys.platform != "win32":  # pragma: no cover - POSIX 分支
            return
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise RuntimeError("CreateJobObject failed，无法启用进程树清理")
        info = _EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        result = kernel32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not result:
            kernel32.CloseHandle(handle)
            raise RuntimeError("SetInformationJobObject failed，无法启用进程树清理")
        self._handle = handle
        self._kernel32 = kernel32

    def assign(self, pid: int) -> bool:
        if self._handle is None:
            return False
        process = self._kernel32.OpenProcess(
            _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, int(pid)
        )
        if not process:
            return False
        try:
            return bool(self._kernel32.AssignProcessToJobObject(self._handle, process))
        finally:
            self._kernel32.CloseHandle(process)

    def terminate(self, exit_code: int = 1) -> None:
        if self._handle is not None:
            self._kernel32.TerminateJobObject(self._handle, exit_code)

    def active_processes(self) -> int:
        """终止后查询 job 内仍活跃的进程数（0 表示整棵树已清理）。"""
        if self._handle is None:
            return 0
        accounting = _BASIC_ACCOUNTING_INFORMATION()
        returned = wintypes.DWORD()
        ok = self._kernel32.QueryInformationJobObject(
            self._handle,
            _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            ctypes.byref(returned),
        )
        if not ok:
            return 1
        return int(accounting.ActiveProcesses)

    def close(self) -> None:
        if self._handle is not None:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


@dataclass
class _BoundedOutputSink:
    """有界输出收集器：行数/单行/总字节三重上限，超限后只 drain 不记录。

    ``max_chars`` 为 profile 级 max_output_bytes 折算（None = MAX_OUTPUT_CHARS），
    summary() 截断超限部分并置 truncated。
    """

    lines: list[dict[str, Any]] = field(default_factory=list)
    line_count: int = 0
    char_count: int = 0
    truncated: bool = False
    max_chars: int | None = None

    def feed(self, kind: str, line: str) -> None:
        self.line_count += 1
        if len(self.lines) >= MAX_STREAM_LINES:
            self.truncated = True
            return
        bounded = line[:MAX_LINE_CHARS]
        if len(line) > MAX_LINE_CHARS:
            bounded += _LINE_TRUNCATED_MARKER
        self.lines.append({"kind": kind, "text": bounded})
        self.char_count += len(bounded)

    def summary(self, kind: str) -> str:
        # 保留换行分隔：避免行首尾粘连被脱敏正则吞并后续内容
        joined = "\n".join(
            item["text"] for item in self.lines if item["kind"] == kind
        )
        limit = min(MAX_OUTPUT_CHARS, self.max_chars or MAX_OUTPUT_CHARS)
        if len(joined) > limit:
            self.truncated = True
            return joined[:limit]
        return joined


@dataclass(frozen=True, slots=True)
class _ResolvedCommand:
    args: list[str]
    cwd: str
    timeout: float
    env: dict[str, str]
    matched_profile_name: str | None = None
    profile_version: int | None = None
    result_parser: str | None = None
    max_output_bytes: int | None = None


# P0-2 验收修复：命令参数路径特征（盘符/绝对路径/上级引用/子路径分隔符）
# 第二轮（P0-1）：盘符不要求斜杠——`C:outside` 等 drive-relative 同样拒绝。
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_PATH_SEPARATOR_RE = re.compile(r"[\\/]")
_DOTDOT_RE = re.compile(r"(^|[\\/])\.\.([\\/]|$)")

# 第二轮（P0-1）：命令感知 argv schema——按命令工具关键字拒绝工作区外
# 加载能力（模块/插件/临时目录/收集根）与路径类 flag 的越界值。
# reject：该 flag 无论值为何一律拒绝（MVP 内无合法使用场景）；
# path：flag 的值必须解析在 workspace 内（等号形式或下一 token）。
_COMMAND_ARG_POLICY: dict[str, dict[str, frozenset[str]]] = {
    "pytest": {
        "reject": frozenset(
            {"-p", "--pyargs", "--basetemp", "--rootdir", "--confcutdir"}
        ),
        "path": frozenset(),
    },
    "cargo": {"reject": frozenset(), "path": frozenset({"--manifest-path"})},
    "npm": {"reject": frozenset(), "path": frozenset({"--prefix"})},
}


# 工具关键字识别：argv 前缀 → 命令工具（python -m pytest / uv run pytest
# 与 pytest 本身都归 pytest；cargo/npm 按可执行名，忽略 Windows 后缀）。
def _command_key(args: Sequence[str]) -> str | None:
    if not args:
        return None
    exe_name = Path(args[0]).name.lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if exe_name.endswith(suffix):
            exe_name = exe_name[: -len(suffix)]
            break
    exe = exe_name
    rest = [a.lower() for a in args[1:]]
    if exe == "pytest":
        return "pytest"
    if exe in {"python", "py"} and rest[:2] == ["-m", "pytest"]:
        return "pytest"
    if exe == "uv" and rest[:2] == ["run", "pytest"]:
        return "pytest"
    if exe == "cargo":
        return "cargo"
    if exe == "npm":
        return "npm"
    return None


def _reject_command_args(root: str, remaining: Sequence[str], key: str | None) -> None:
    """命令剩余参数校验（第二轮 P0-1）：通用路径检查 + 命令感知 schema。

    - 通用：盘符/绝对路径/UNC 拒绝；``..`` 与相对子路径 resolve_within
      校验（工作区内允许）；``--flag=path`` 等号形式取 value 检查。
    - schema：reject flag 一律拒绝（pytest -p/--pyargs/--basetemp/
      --rootdir/--confcutdir 等工作区外加载能力）；path flag 的值必须
      解析在 workspace 内（等号形式或下一 token）。
    """
    policy = _COMMAND_ARG_POLICY.get(key or "") if key else None
    reject_flags = policy["reject"] if policy else frozenset()
    path_flags = policy["path"] if policy else frozenset()
    index = 0
    while index < len(remaining):
        token = remaining[index]
        index += 1
        if not token:
            continue
        name, sep, val = token.partition("=")
        has_inline_value = bool(sep and val)
        flag_name = name if name.startswith("-") else None
        if flag_name in reject_flags:
            raise PermissionError_(
                f"命令参数 {flag_name} 可加载 workspace 外模块/路径，已拒绝"
            )
        if flag_name in path_flags:
            if has_inline_value:
                value = val
            else:
                if index >= len(remaining):
                    raise PermissionError_(f"命令参数 {flag_name} 缺少值")
                value = remaining[index]
                index += 1
            _check_path_value(root, value, token=f"{flag_name} {value}")
            continue
        value = val if has_inline_value else token
        _check_path_value(root, value, token=token)


def _check_path_value(root: str, value: str, *, token: str) -> None:
    """单个参数值的 workspace 边界检查（盘符/绝对拒绝，相对 resolve 校验）。"""
    if not value:
        return
    if _WINDOWS_DRIVE_RE.match(value) or value.startswith(("/", "\\")):
        raise PermissionError_(f"命令参数不得使用绝对路径: {token}")
    if _DOTDOT_RE.search(value):
        resolve_within(root, value)
        return
    if _PATH_SEPARATOR_RE.search(value):
        resolve_within(root, value)


async def _resolve_command(
    db: AsyncSession,
    project_id: int,
    args: list[str],
    timeout: float | None,
) -> _ResolvedCommand:
    """白名单合并：全局默认前缀 + 项目 command profile（预授权）。

    E2：匹配 profile 后落地其 cwd_rel（resolve 校验仍在 root 内，否则拒绝）、
    env_allowlist（白名单注入，仍拒绝代理/凭据类）、max_output_bytes 与
    result_parser；非白名单 argv/cwd 全部拒绝。
    """
    project = await ProjectService(db).get(project_id)
    from .repo_patch_sets import ProjectCommandProfileRepository

    matched_profile = None
    matched_prefix_len = 0
    for profile in await ProjectCommandProfileRepository(db).list_by_project(
        project_id, enabled=True
    ):
        try:
            profile_args = _profile_to_args(profile.command_json)
        except ValueError:
            continue
        lowered = [a.lower() for a in profile_args]
        if lowered and [a.lower() for a in args[: len(lowered)]] == lowered:
            matched_profile = profile
            matched_prefix_len = len(profile_args)
            break
    if matched_profile is None and not is_whitelisted_command(args):
        raise PermissionError_("非白名单命令，已拒绝执行")
    if matched_profile is not None and (
        matched_profile.risk_level or "confirm"
    ) == "restricted":
        # E4（E0 §4.1）：restricted profile 永不自动获批——无论权限模式
        # 如何切换，匹配即拒绝；MVP 无任何自动放行渠道（仅人工处置）。
        raise PermissionError_(
            f"命令 profile「{matched_profile.name}」为 restricted，禁止自动执行"
        )
    effective_timeout = max(1.0, min(float(timeout or COMMAND_TIMEOUT), COMMAND_TIMEOUT))
    root = project.root_path
    # P0-2 验收修复：前缀之后剩余参数中的路径必须解析在 workspace 内
    # （cargo --manifest-path / npm --prefix / pytest 路径参数等越界注入拒绝）。
    # 第二轮（P0-1）：命令感知 schema——pytest -p/--pyargs/--basetemp 等工作区外
    # 加载能力直接拒绝；path flag 值必须 workspace 内。
    if matched_profile is not None:
        remaining = args[matched_prefix_len:]
    else:
        remaining = args[whitelisted_prefix_length(args):]
    _reject_command_args(root, remaining, _command_key(args))
    env = build_safe_environment()
    max_output_bytes: int | None = None
    result_parser: str | None = None
    profile_version: int | None = None
    if matched_profile is not None:
        # cwd_rel 非空时解析到 root 内；越界/非法即拒绝（执行时防御旧数据）
        if matched_profile.cwd_rel:
            cwd = str(resolve_within(root, matched_profile.cwd_rel))
        else:
            cwd = root
        if matched_profile.env_allowlist:
            for name in matched_profile.env_allowlist:
                if name and name in os.environ and not _ENV_REJECT_PATTERN.search(name):
                    env[name] = os.environ[name]
        max_output_bytes = matched_profile.max_output_bytes
        result_parser = matched_profile.result_parser
        profile_version = matched_profile.profile_version or 1
    else:
        cwd = root
    return _ResolvedCommand(
        args=args,
        cwd=cwd,
        timeout=effective_timeout,
        env=env,
        matched_profile_name=matched_profile.name if matched_profile else None,
        profile_version=profile_version,
        result_parser=result_parser,
        max_output_bytes=max_output_bytes,
    )


async def _read_stream(
    stream,
    kind: str,
    sink: _BoundedOutputSink,
    on_line: Callable[[str, str], Awaitable[None]] | None,
) -> None:
    while True:
        raw = await stream.readline()
        if not raw:
            break
        text = _redact_line(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        sink.feed(kind, text)
        if on_line is not None:
            await on_line(kind, text)


class _OutputPersister:
    """把流式行持久化到 tool_execution_output（有界、脱敏、尽力而为）。

    两个 reader task 可能并发调用 write，用锁串行化 flush；失败即关闭
    （不阻断命令执行，最终结果仍由 execution 记录承载）。
    """

    def __init__(self, db: AsyncSession, execution_id: str) -> None:
        self._db = db
        self._execution_id = execution_id
        self._run_id: str | None = None
        self._seq = 0
        self._buffer: list[dict[str, Any]] = []
        self._written = 0
        self._closed = False
        self._lock = asyncio.Lock()

    async def _resolve_run_id(self) -> str | None:
        if self._run_id is not None:
            return self._run_id
        try:
            row = (
                await self._db.execute(
                    sql_text(
                        "SELECT run_id FROM agent_tool_executions WHERE id = :id"
                    ),
                    {"id": self._execution_id},
                )
            ).scalar_one_or_none()
            self._run_id = str(row) if row else None
        except Exception:  # noqa: BLE001
            self._run_id = None
        return self._run_id

    async def write(self, kind: str, text: str) -> None:
        if self._closed or self._written >= MAX_STREAM_LINES:
            return
        async with self._lock:
            if self._written >= MAX_STREAM_LINES:
                return
            self._written += 1
            self._buffer.append({"kind": kind, "text": text})
            if len(self._buffer) >= 50:
                await self._flush_locked()

    async def _flush_locked(self) -> None:
        if not self._buffer:
            return
        rows = [
            {
                "seq": self._seq + index,
                "kind": item["kind"],
                "text": item["text"],
            }
            for index, item in enumerate(self._buffer)
        ]
        self._seq += len(rows)
        self._buffer.clear()
        run_id = await self._resolve_run_id()
        if run_id is None:
            self._closed = True
            return
        try:
            await self._db.execute(
                sql_text(
                    "INSERT INTO tool_execution_output "
                    "(run_id, execution_id, seq, kind, text) VALUES "
                    "(:run_id, :execution_id, :seq, :kind, :text)"
                ),
                [
                    {
                        "run_id": run_id,
                        "execution_id": self._execution_id,
                        **row,
                    }
                    for row in rows
                ],
            )
            await self._db.commit()
        except Exception:  # noqa: BLE001 - 流式持久化失败不阻断命令执行
            self._closed = True

    async def flush(self) -> None:
        async with self._lock:
            await self._flush_locked()

    async def close(self) -> None:
        self._closed = True
        await self.flush()


async def run_command(
    args: list[str],
    *,
    cwd: str,
    timeout: float,
    env: dict[str, str],
    cancellation: CancellationToken,
    output_sink: _BoundedOutputSink,
    on_line: Callable[[str, str], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """有界执行命令：Job Object 进程树清理 + 超时/取消 + 流式输出。"""
    job = _JobObject()
    proc: Any = None
    readers: list[asyncio.Task] = []
    cancelled = False
    timed_out = False
    processes_remaining = 0
    returncode = 1
    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            if not job.assign(proc.pid):
                raise RuntimeError("无法把命令进程挂入 Job Object，已拒绝执行")
            readers = [
                asyncio.create_task(
                    _read_stream(proc.stdout, "stdout", output_sink, on_line)
                ),
                asyncio.create_task(
                    _read_stream(proc.stderr, "stderr", output_sink, on_line)
                ),
            ]
            wait_task = asyncio.create_task(proc.wait())
            cancel_task = asyncio.create_task(cancellation.wait())
            try:
                done, _ = await asyncio.wait(
                    {wait_task, cancel_task},
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancellation.is_cancelled:
                    cancelled = True
                elif wait_task not in done:
                    timed_out = True
            finally:
                for task in (wait_task, cancel_task):
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
            if not cancelled and not timed_out:
                returncode = proc.returncode if proc.returncode is not None else 1
        except asyncio.CancelledError:
            # 运行级取消（CancellationToken）转为带证据的 ToolDispatchCancelled；
            # 任务级取消（外部 task.cancel）原样传播。
            if not cancellation.is_cancelled:
                raise
            cancelled = True
    finally:
        if timed_out or cancelled:
            job.terminate()
            if sys.platform == "win32":
                await asyncio.sleep(0.05)
            processes_remaining = job.active_processes()
        # 排空管道剩余输出（进程已退出或被终止 → EOF）；防止极端情况卡死。
        if readers:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.gather(*readers, return_exceptions=True), timeout=10
                )
            for task in readers:
                task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.shield(
                    asyncio.gather(*readers, return_exceptions=True)
                )
        job.close()
        if proc is not None and proc.returncode is None:
            with suppress(Exception):
                proc.kill()

    if timed_out:
        raise TimeoutError(
            f"命令超时（{timeout}s）"
            + (
                f"，进程树清理后残留 {processes_remaining} 个进程"
                if processes_remaining
                else ""
            )
        )
    if cancelled:
        raise ToolDispatchCancelled(
            "命令执行已取消"
            + (
                f"，进程树清理后残留 {processes_remaining} 个进程"
                if processes_remaining
                else ""
            )
        )

    stdout = output_sink.summary("stdout")
    stderr = output_sink.summary("stderr")
    combined = (stdout + ("\n" if stdout and stderr else "") + stderr).strip()
    output_limit = min(MAX_OUTPUT_CHARS, output_sink.max_chars or MAX_OUTPUT_CHARS)
    truncated = output_sink.truncated or len(combined) > output_limit
    if truncated and len(combined) > output_limit:
        combined = combined[:output_limit] + "\n" + _STREAM_TRUNCATED_MARKER
    return {
        "args": args,
        "cwd": cwd,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "output": combined,
        "truncated": truncated,
        "succeeded": returncode == 0,
        "cancelled": False,
        "processes_remaining": processes_remaining,
    }


async def run_whitelisted_command_trusted(
    db: AsyncSession,
    project_id: int,
    command: list[str],
    *,
    timeout: float | None = None,
    cancellation: CancellationToken,
    on_line: Callable[[str, str], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """审批后在授权项目根目录运行白名单命令（参数数组，不经 shell）。

    ``on_line`` 为可选行回调（测试钩子/未来 UI 复用），默认持久化流式行。
    """
    args = parse_command(command)
    resolved = await _resolve_command(db, project_id, args, timeout)
    execution_id = current_execution_id()
    persister = (
        _OutputPersister(db, execution_id) if execution_id is not None else None
    )
    sink = _BoundedOutputSink(max_chars=resolved.max_output_bytes)

    async def _default_on_line(kind: str, text: str) -> None:
        if persister is not None:
            await persister.write(kind, text)

    try:
        result = await run_command(
            args,
            cwd=resolved.cwd,
            timeout=resolved.timeout,
            env=resolved.env,
            cancellation=cancellation,
            output_sink=sink,
            on_line=on_line or _default_on_line,
        )
    finally:
        if persister is not None:
            await persister.close()
    result["project_id"] = project_id
    if resolved.matched_profile_name is not None:
        result["profile"] = resolved.matched_profile_name
        result["profile_version"] = resolved.profile_version or 1
        if resolved.result_parser:
            # E2：结构化解析结果（有界、脱敏；不信任模型文本声明）
            result["parsed"] = parse_command_result(
                resolved.result_parser, result.get("output") or ""
            )
    return result


def build_command_tool_registry(
    db: AsyncSession,
    *,
    legacy_registry=None,
    on_line: Callable[[str, str], Awaitable[None]] | None = None,
    command_risk: ToolRiskLevel | None = None,
) -> VersionedToolRegistry:
    """Build the versioned registry containing the audited command tool.

    ``command_risk``：E4 workspace 模式动态化——项目 enabled profile 全部
    safe 时传 SAFE（自动允许）；否则为 None（契约默认 confirm，审批把关）。
    """
    from .tools import default_registry

    source = legacy_registry or default_registry
    legacy = source.get(_COMMAND_CONTRACT.name)
    if legacy is None:
        raise RuntimeError(f"缺少内建工具：{_COMMAND_CONTRACT.name}")
    if legacy.risk_level != _COMMAND_CONTRACT.risk_level.value:
        raise RuntimeError(
            "工具风险等级与审核后的 Agent 契约不一致，拒绝迁移："
            f"{_COMMAND_CONTRACT.name}"
        )
    registry = VersionedToolRegistry()
    registry.register(
        _build_command_tool_spec(db, on_line=on_line, command_risk=command_risk)
    )
    return registry


def _build_command_tool_spec(
    db: AsyncSession,
    *,
    on_line: Callable[[str, str], Awaitable[None]] | None = None,
    command_risk: ToolRiskLevel | None = None,
) -> ToolSpec:
    async def execute(arguments: dict[str, Any], cancellation: CancellationToken) -> Any:
        if cancellation.is_cancelled:
            raise ToolDispatchCancelled("工具执行已取消")
        return await run_whitelisted_command_trusted(
            db,
            arguments["project_id"],
            arguments["command"],
            timeout=arguments.get("timeout"),
            cancellation=cancellation,
            on_line=on_line,
        )

    return ToolSpec(
        name=_COMMAND_CONTRACT.name,
        version=_COMMAND_CONTRACT.version,
        description=_COMMAND_CONTRACT.description,
        input_schema=_COMMAND_CONTRACT.input_schema,
        output_schema=_COMMAND_CONTRACT.output_schema,
        risk_level=command_risk or _COMMAND_CONTRACT.risk_level,
        required_capabilities=_COMMAND_CONTRACT.required_capabilities,
        timeout_ms=_COMMAND_CONTRACT.timeout_ms,
        max_input_bytes=_COMMAND_CONTRACT.max_input_bytes,
        max_output_bytes=_COMMAND_CONTRACT.max_output_bytes,
        idempotency=_COMMAND_CONTRACT.idempotency,
        supports_cancellation=_COMMAND_CONTRACT.supports_cancellation,
        redaction_policy=_COMMAND_CONTRACT.redaction_policy,
        executor=execute,
    )
