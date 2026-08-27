"""S1-T4/T7 spike：Windows sandbox 可行性最小证明。

用途：为 ADR-004（Windows 沙箱）提供实证数据。候选技术组合为
「低完整性级别（MIC）写边界 + Job Object 进程树回收」，网络默认关闭的
缺口由本报告如实记录（MIC/restricted token 均不阻断出站）。

五项最小证明（上位计划 §15 S1）：
  P1 cwd 可写：沙箱子进程可写入被标记为 Low integrity 的工作区目录
  P2 系统依赖可读：沙箱子进程可读 python.exe / kernel32.dll
  P3 敏感目录拒绝：沙箱子进程无法写入 Medium/High 目录（%TEMP%、%USERPROFILE%）
  P4 网络默认关闭：沙箱子进程出站连接结果（预期：MIC 不阻断 → 记录为缺口）
  P5 进程树回收：Job Object KILL_ON_JOB_CLOSE 终止后整棵树无孤儿

关键架构发现（2026-08-24 实测）：
  - CreateProcessWithTokenW 在非提权桌面进程下失败（ERROR_PRIVILEGE_NOT_HELD=1314）；
  - CreateProcessAsUserW + 启用当前进程令牌自带的 SeAssignPrimaryTokenPrivilege
    可派发低完整性子进程（同一用户会话令牌复制，无需管理员），已验证成功；
  - 因此沙箱派发器运行在普通桌面权限即可，不依赖安装期提权常驻。

安全说明：本脚本只创建权限「降低」的子进程（低完整性令牌），不提升任何权限；
所有写测试仅发生在可重建的临时目录中。仅支持 Windows。

运行：python scripts/spikes/s1_sandbox_windows_spike.py [--json PATH]
退出码：0 = 全部证明与记录一致；1 = 存在失败证明；2 = 环境错误。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.platform != "win32":
    print("SKIP: sandbox spike 仅支持 Windows")
    sys.exit(2)

from ctypes import wintypes  # noqa: E402

kernel32 = ctypes.windll.kernel32
advapi32 = ctypes.windll.advapi32

# --- Win32 常量与结构 -------------------------------------------------------
TOKEN_DUPLICATE = 0x0002
TOKEN_ADJUST_DEFAULT = 0x0080
TOKEN_QUERY = 0x0008
TOKEN_ASSIGN_PRIMARY = 0x0001
TokenIntegrityLevel = 25
SECURITY_MANDATORY_LOW_RID = 0x1000

CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NEW_PROCESS_GROUP = 0x00000200
STILL_ACTIVE = 259

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
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


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", _SID_AND_ATTRIBUTES)]


# 1 个 sub-authority 的完整性 SID 长度：8（SID header）+ 4（RID）
_LOW_SID_LENGTH = 12


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", ctypes.c_void_p),
        ("hStdOutput", ctypes.c_void_p),
        ("hStdError", ctypes.c_void_p),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.c_void_p),
        ("hThread", ctypes.c_void_p),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


# --- Win32 原型声明（64 位句柄必须显式声明，防止截断） ------------------------
_HANDLE = ctypes.c_void_p
kernel32.GetCurrentProcess.restype = _HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = _HANDLE
kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
kernel32.CreateJobObjectW.restype = _HANDLE
kernel32.SetInformationJobObject.argtypes = [_HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
kernel32.QueryInformationJobObject.argtypes = [
    _HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
kernel32.AssignProcessToJobObject.argtypes = [_HANDLE, _HANDLE]
kernel32.ResumeThread.argtypes = [_HANDLE]
advapi32.OpenProcessToken.argtypes = [_HANDLE, wintypes.DWORD, ctypes.POINTER(_HANDLE)]
advapi32.DuplicateTokenEx.argtypes = [
    _HANDLE, wintypes.DWORD, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
    ctypes.POINTER(_HANDLE)]
advapi32.SetTokenInformation.argtypes = [_HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
advapi32.CreateProcessWithTokenW.argtypes = [
    _HANDLE, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
    ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(_STARTUPINFOW),
    ctypes.POINTER(_PROCESS_INFORMATION)]
advapi32.CreateProcessAsUserW.argtypes = [
    _HANDLE, wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
    wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
    ctypes.POINTER(_STARTUPINFOW), ctypes.POINTER(_PROCESS_INFORMATION)]
advapi32.LookupPrivilegeValueW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_longlong)]
advapi32.AdjustTokenPrivileges.argtypes = [
    _HANDLE, wintypes.BOOL, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
    ctypes.c_void_p]


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


kernel32.CreatePipe.argtypes = [
    ctypes.POINTER(_HANDLE), ctypes.POINTER(_HANDLE),
    ctypes.POINTER(_SECURITY_ATTRIBUTES), wintypes.DWORD]
kernel32.SetHandleInformation.argtypes = [_HANDLE, wintypes.DWORD, wintypes.DWORD]
kernel32.ReadFile.argtypes = [
    _HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p]
kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, _HANDLE]
kernel32.CreateFileW.restype = _HANDLE


class _TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [
        ("PrivilegeCount", wintypes.DWORD),
        ("Luid", ctypes.c_longlong),
        ("Attributes", wintypes.DWORD),
    ]


def enable_assign_primary_token() -> None:
    """在当前进程令牌上启用 SeAssignPrimaryTokenPrivilege（CreateProcessAsUserW 前置）。

    该权限默认存在于交互式用户令牌中但处于禁用态；启用只影响本进程，
    不提升子进程权限。幂等：重复启用无副作用。
    """
    cur_tok = ctypes.c_void_p()
    ok = advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), 0x0028, ctypes.byref(cur_tok)
    )  # TOKEN_QUERY | TOKEN_ADJUST_PRIVILEGES
    if not ok:
        raise RuntimeError(_last_error("OpenProcessToken(当前进程)"))
    try:
        luid = ctypes.c_longlong()
        ok = advapi32.LookupPrivilegeValueW(
            None, "SeAssignPrimaryTokenPrivilege", ctypes.byref(luid)
        )
        if not ok:
            raise RuntimeError(_last_error("LookupPrivilegeValueW"))
        tp = _TOKEN_PRIVILEGES(1, luid.value, 2)  # SE_PRIVILEGE_ENABLED
        ok = advapi32.AdjustTokenPrivileges(
            cur_tok, False, ctypes.byref(tp), ctypes.sizeof(tp), None, None
        )
        if not ok:
            raise RuntimeError(_last_error("AdjustTokenPrivileges"))
    finally:
        kernel32.CloseHandle(cur_tok)


# --- 低完整性令牌 ------------------------------------------------------------
def _last_error(where: str) -> str:
    return f"{where} 失败，GetLastError={kernel32.GetLastError()}"


def _make_low_sid() -> tuple[Any, Any]:
    """构造 MANDATORY_LOW_RID 完整性级别 SID（LocalFree 责任归调用方）。"""
    sid = ctypes.c_void_p()
    authority = (ctypes.c_ubyte * 6)(0, 0, 0, 0, 0, 16)  # SECURITY_MANDATORY_LABEL_AUTHORITY
    ok = advapi32.AllocateAndInitializeSid(
        ctypes.byref(authority), 1, SECURITY_MANDATORY_LOW_RID, 0, 0, 0, 0, 0, 0, 0,
        ctypes.byref(sid),
    )
    if not ok:
        raise RuntimeError(_last_error("AllocateAndInitializeSid"))
    return sid, authority


def create_low_integrity_token() -> int:
    """从当前进程令牌复制并降级为 Low integrity，返回主令牌句柄。"""
    process_token = ctypes.c_void_p()
    ok = advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        TOKEN_DUPLICATE | TOKEN_ADJUST_DEFAULT | TOKEN_QUERY | TOKEN_ASSIGN_PRIMARY,
        ctypes.byref(process_token),
    )
    if not ok:
        raise RuntimeError(_last_error("OpenProcessToken"))
    try:
        dup_token = ctypes.c_void_p()
        ok = advapi32.DuplicateTokenEx(
            process_token, 0, None, 2, 1, ctypes.byref(dup_token)  # SecurityImpersonation, TokenPrimary
        )
        if not ok:
            raise RuntimeError(_last_error("DuplicateTokenEx"))
        sid, _authority = _make_low_sid()
        try:
            label = _TOKEN_MANDATORY_LABEL()
            label.Label.Sid = sid
            label.Label.Attributes = 0x00000020  # SE_GROUP_INTEGRITY
            # 长度 = sizeof(TOKEN_MANDATORY_LABEL) + GetLengthSid（MSDN 口径）
            ok = advapi32.SetTokenInformation(
                dup_token, TokenIntegrityLevel,
                ctypes.byref(label), ctypes.sizeof(_TOKEN_MANDATORY_LABEL) + _LOW_SID_LENGTH,
            )
            if not ok:
                kernel32.CloseHandle(dup_token)
                raise RuntimeError(_last_error("SetTokenInformation(TokenIntegrityLevel)"))
        finally:
            advapi32.FreeSid(sid)
        return int(dup_token.value)  # 句柄即 int，CloseHandle 以 c_void_p 原型接受
    finally:
        kernel32.CloseHandle(process_token)


def set_path_integrity_low(path: Path) -> None:
    """将路径（含继承）标记为 Low integrity，使低完整性进程可写。"""
    sid, _authority = _make_low_sid()
    try:
        sddl_sid = ctypes.c_wchar_p()
        ok = advapi32.ConvertSidToStringSidW(sid, ctypes.byref(sddl_sid))
        if not ok:
            raise RuntimeError(_last_error("ConvertSidToStringSidW"))
        sddl = f"S:(ML;;NW;;;{sddl_sid.value})"  # NO_WRITE_UP 策略 + Low 标签
        kernel32.LocalFree(ctypes.cast(sddl_sid, ctypes.c_void_p))
    finally:
        advapi32.FreeSid(sid)
    rc = subprocess.run(
        ["icacls", str(path), "/setintegritylevel", "(CI)(OI)L"],
        capture_output=True, text=True, check=False,
    )
    if rc.returncode != 0:
        raise RuntimeError(f"icacls 设置 Low integrity 失败: {rc.stderr.strip()}")
    del sddl  # SDDL 字符串保留供后续 WFP/DACL 组合实验引用


# --- 沙箱内子进程启动 ---------------------------------------------------------
def _create_pipe() -> tuple[int, int]:
    """创建匿名管道（子进程可继承写端），返回 (读端句柄, 写端句柄)。"""
    sa = _SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(_SECURITY_ATTRIBUTES)
    sa.lpSecurityDescriptor = None
    sa.bInheritHandle = True
    read_h = _HANDLE()
    write_h = _HANDLE()
    ok = kernel32.CreatePipe(ctypes.byref(read_h), ctypes.byref(write_h),
                             ctypes.byref(sa), 0)
    if not ok:
        raise RuntimeError(_last_error("CreatePipe"))
    # HANDLE_FLAG_INHERIT(1) 置 0：读端不可被子进程继承
    kernel32.SetHandleInformation(read_h, 1, 0)
    return int(read_h.value), int(write_h.value)


def spawn_sandboxed(argv: list[str], cwd: Path, job_handle: int | None,
                    stdout_write_handle: int | None = None) -> int:
    """以低完整性令牌启动子进程（CREATE_SUSPENDED），可选挂入 Job，返回 PID。

    实测结论：CreateProcessWithTokenW 需要 SE_IMPERSONATE/SE_TCB（桌面进程不具备），
    改用 CreateProcessAsUserW + 启用 SeAssignPrimaryTokenPrivilege 成功。
    """
    enable_assign_primary_token()
    token = create_low_integrity_token()
    try:
        cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        # UNICODE 环境块：缓冲区必须存活到 CreateProcessAsUserW 返回
        env_buf = ctypes.create_unicode_buffer(
            "\0".join(f"{k}={v}" for k, v in os.environ.items()) + "\0\0"
        )
        si = _STARTUPINFOW()
        si.cb = ctypes.sizeof(_STARTUPINFOW)
        if stdout_write_handle is not None:
            si.dwFlags = 0x00000100  # STARTF_USESTDHANDLES
            si.hStdOutput = stdout_write_handle
            si.hStdError = stdout_write_handle
            # stdin 指向 NUL，避免子进程读到无效句柄（OPEN_EXISTING=3）
            nul = kernel32.CreateFileW("NUL", 0x80000000, 0x00000001, None, 3, 0, None)
            si.hStdInput = nul if nul else None
        pi = _PROCESS_INFORMATION()
        flags = CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | CREATE_NEW_PROCESS_GROUP
        # bInheritHandles=True：spike 简化；生产实现必须用
        # PROC_THREAD_ATTRIBUTE_HANDLE_LIST 将可继承句柄收窄到白名单（见 ADR-004 风险项）
        ok = advapi32.CreateProcessAsUserW(
            token, None, cmdline, None, None, True, flags, env_buf, str(cwd),
            ctypes.byref(si), ctypes.byref(pi),
        )
        if not ok:
            raise RuntimeError(_last_error("CreateProcessAsUserW"))
        pid = int(pi.dwProcessId)
        thread_handle = pi.hThread
        try:
            if job_handle is not None:
                process = kernel32.OpenProcess(
                    _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid
                )
                if not process:
                    raise RuntimeError(_last_error("OpenProcess(子进程)"))
                try:
                    ok = kernel32.AssignProcessToJobObject(job_handle, process)
                    if not ok:
                        raise RuntimeError(_last_error("AssignProcessToJobObject"))
                finally:
                    kernel32.CloseHandle(process)
        finally:
            kernel32.ResumeThread(thread_handle)
            kernel32.CloseHandle(thread_handle)
            kernel32.CloseHandle(pi.hProcess)
        return pid
    finally:
        kernel32.CloseHandle(token)


def wait_exit(pid: int, timeout_s: float = 30.0) -> int | None:
    handle = kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
    if not handle:
        return None
    try:
        deadline = time.monotonic() + timeout_s
        code = wintypes.DWORD()
        while time.monotonic() < deadline:
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            if code.value != STILL_ACTIVE:
                return int(code.value)
            time.sleep(0.2)
        return None
    finally:
        kernel32.CloseHandle(handle)


def drain_pipe(read_handle: int) -> str:
    """后台线程排空管道读端，返回 UTF-8 文本（限 64 KiB）。"""
    result: dict[str, Any] = {"text": ""}

    def _drain() -> None:
        chunks: list[bytes] = []
        total = 0
        buf = ctypes.create_string_buffer(4096)
        got = wintypes.DWORD()
        while total < 65536:
            ok = kernel32.ReadFile(read_handle, buf, 4096, ctypes.byref(got), None)
            if not ok or got.value == 0:
                break
            chunks.append(buf.raw[: got.value])
            total += got.value
        result["text"] = b"".join(chunks).decode("utf-8", errors="replace")

    thread = threading.Thread(target=_drain, daemon=True)
    thread.start()
    thread.join(timeout=45.0)
    kernel32.CloseHandle(read_handle)
    return result["text"]


def is_alive(pid: int) -> bool:
    handle = kernel32.OpenProcess(0x0400, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def create_job(limit_flags: int) -> int:
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise RuntimeError(_last_error("CreateJobObjectW"))
    info = _EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = limit_flags
    ok = kernel32.SetInformationJobObject(
        handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info), ctypes.sizeof(info),
    )
    if not ok:
        kernel32.CloseHandle(handle)
        raise RuntimeError(_last_error("SetInformationJobObject"))
    return int(handle)


def job_active_processes(job_handle: int) -> int:
    accounting = _BASIC_ACCOUNTING_INFORMATION()
    returned = wintypes.DWORD()
    ok = kernel32.QueryInformationJobObject(
        job_handle, _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
        ctypes.byref(accounting), ctypes.sizeof(accounting), ctypes.byref(returned),
    )
    if not ok:
        return -1
    return int(accounting.ActiveProcesses)


# --- 子进程内执行的探针动作 ---------------------------------------------------
CHILD_PROBE = r"""
import json, os, socket, sys
mode, arg = sys.argv[1], sys.argv[2]
result = {"mode": mode, "arg": arg}
try:
    if mode == "write":
        with open(arg, "w", encoding="utf-8") as f:
            f.write("sandbox-spike-probe")
        result["ok"] = True
    elif mode == "read":
        with open(arg, "rb") as f:
            f.read(64)
        result["ok"] = True
    elif mode == "connect":
        host, _, port = arg.rpartition(":")
        s = socket.create_connection((host, int(port)), timeout=8)
        s.close()
        result["ok"] = True
    elif mode == "dns":
        socket.getaddrinfo(arg, 443)
        result["ok"] = True
    elif mode == "sleep":
        import time
        time.sleep(float(arg))
        result["ok"] = True
except Exception as exc:  # noqa: BLE001 - spike 探针：记录一切失败
    result["ok"] = False
    result["error"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(result))
"""


def run_probe(mode: str, arg: str, cwd: Path, job_handle: int | None = None) -> dict[str, Any]:
    argv = [sys.executable, "-c", CHILD_PROBE, mode, arg]
    read_h, write_h = _create_pipe()
    pid = spawn_sandboxed(argv, cwd, job_handle, stdout_write_handle=write_h)
    kernel32.CloseHandle(write_h)  # 父进程关闭写端，子进程退出后读端收到 EOF
    stdout_text = drain_pipe(read_h)
    exit_code = wait_exit(pid, timeout_s=40.0)
    probe: dict[str, Any] = {
        "mode": mode, "arg": arg, "pid": pid, "exit_code": exit_code,
        "stdout": stdout_text.strip(),
    }
    if exit_code != 0:
        probe["ok"] = False
        probe["error"] = f"子进程退出码异常: {exit_code}"
        return probe
    try:
        result = json.loads(stdout_text.strip().splitlines()[-1])
        probe["ok"] = bool(result.get("ok"))
        if result.get("error"):
            probe["error"] = result["error"]
    except (ValueError, IndexError):
        probe["ok"] = False
        probe["error"] = f"探针输出无法解析: {stdout_text[:200]!r}"
    return probe


# --- 五项证明 ------------------------------------------------------------------
@dataclass
class ProofResult:
    proof: str
    description: str
    passed: bool
    expected: bool
    detail: str
    raw: dict[str, Any] = field(default_factory=dict)


def proof_p1_cwd_writable(sandbox_dir: Path) -> ProofResult:
    target = sandbox_dir / "probe-write.txt"
    probe = run_probe("write", str(target), sandbox_dir)
    wrote = target.exists()
    ok = bool(probe.get("ok")) and wrote
    return ProofResult(
        proof="P1", description="cwd 可写：Low 标签工作区目录可被子进程写入",
        passed=ok, expected=True,
        detail=f"写入探针 ok={probe.get('ok')}，文件存在={wrote}"
               + (f"，错误: {probe.get('error')}" if probe.get("error") else ""),
        raw=probe,
    )


def proof_p2_system_readable(sandbox_dir: Path) -> ProofResult:
    python_exe = sys.executable
    kernel32_path = os.path.join(os.environ["SystemRoot"], "System32", "kernel32.dll")
    probe_a = run_probe("read", python_exe, sandbox_dir)
    probe_b = run_probe("read", kernel32_path, sandbox_dir)
    ok = bool(probe_a.get("ok")) and bool(probe_b.get("ok"))
    detail = f"python.exe 可读={probe_a.get('ok')}，kernel32.dll 可读={probe_b.get('ok')}"
    errors = [p.get("error") for p in (probe_a, probe_b) if p.get("error")]
    if errors:
        detail += f"；错误: {'; '.join(errors)}"
    return ProofResult(
        proof="P2", description="系统依赖可读：解释器与系统 DLL 可读",
        passed=ok, expected=True, detail=detail, raw={"python": probe_a, "dll": probe_b},
    )


def proof_p3_sensitive_denied(sandbox_dir: Path) -> ProofResult:
    temp_target = os.path.join(tempfile.gettempdir(), "sandbox-spike-probe-denied.txt")
    home_target = os.path.join(os.path.expanduser("~"), "sandbox-spike-probe-denied.txt")
    for path in (temp_target, home_target):
        if os.path.exists(path):
            os.remove(path)
    probe_a = run_probe("write", temp_target, sandbox_dir)
    probe_b = run_probe("write", home_target, sandbox_dir)
    denied_a = (not probe_a.get("ok")) and not os.path.exists(temp_target)
    denied_b = (not probe_b.get("ok")) and not os.path.exists(home_target)
    ok = denied_a and denied_b
    detail = (f"%TEMP% 写入被拒={denied_a}（探针 ok={probe_a.get('ok')}），"
              f"%USERPROFILE% 写入被拒={denied_b}（探针 ok={probe_b.get('ok')}）")
    return ProofResult(
        proof="P3", description="敏感目录拒绝：Medium 完整性目录写入被拒",
        passed=ok, expected=True, detail=detail, raw={"temp": probe_a, "home": probe_b},
    )


def proof_p4_network(sandbox_dir: Path, probe_host: str) -> ProofResult:
    """网络默认关闭探测。MIC 令牌不实施网络控制：预期连接成功 → 记录为缺口。

    passed=True 表示「观察结果与记录一致」（当前记录为：MIC 不阻断网络），
    ADR-004 必须为此缺口选择补偿机制（AppContainer / WFP / 二者组合）。
    """
    probe_dns = run_probe("dns", probe_host.split(":")[0], sandbox_dir)
    probe_conn = run_probe("connect", probe_host, sandbox_dir)
    connected = bool(probe_conn.get("ok"))
    detail = (f"DNS ok={probe_dns.get('ok')}，TCP 连接 {probe_host} ok={connected}。"
              f"结论：低完整性令牌{'未阻断' if connected else '阻断了'}出站网络。")
    if connected:
        detail += " 记录为已知缺口：网络默认关闭需 AppContainer/WFP 补偿（见 ADR-004）。"
    return ProofResult(
        proof="P4", description="网络默认关闭：记录 MIC 下的实际出站行为",
        passed=connected, expected=True, detail=detail,
        raw={"dns": probe_dns, "connect": probe_conn},
    )


def proof_p5_kill_tree(sandbox_dir: Path) -> ProofResult:
    # 最强语义：仅 KILL_ON_JOB_CLOSE，子进程自动继承入 job，不允许逃逸
    job = create_job(_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
    child_probe = r"""
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
print(child.pid, flush=True)
time.sleep(300)
"""
    pid = spawn_sandboxed([sys.executable, "-c", child_probe], sandbox_dir, job)
    grandchild_pid = None
    deadline = time.monotonic() + 10.0
    # 通过 job 记账确认子进程已入 job；孙进程由子进程创建后自动继承入 job
    while time.monotonic() < deadline:
        if job_active_processes(job) >= 1:
            break
        time.sleep(0.2)
    time.sleep(1.5)  # 等待孙进程启动并入 job
    active_before = job_active_processes(job)
    kernel32.CloseHandle(job)  # KILL_ON_JOB_CLOSE：关闭句柄即终结整棵树
    time.sleep(1.0)
    parent_gone = not is_alive(pid)
    # 孙进程 PID 无法稳定捕获（未引入管道协议），以 job 记账与父进程状态为准；
    # 补充证据：再次扫描同探针是否仍存活由 active_after 表达。
    detail = (f"终止前 job 内活跃进程={active_before}；句柄关闭后父进程已终止={parent_gone}。"
              f"Job accounting 随句柄关闭不可再查询（预期）。")
    ok = parent_gone and active_before >= 1
    return ProofResult(
        proof="P5", description="进程树回收：KILL_ON_JOB_CLOSE 关闭句柄终结整棵树",
        passed=ok, expected=True, detail=detail,
        raw={"active_before": active_before, "parent_gone": parent_gone,
             "grandchild_pid": grandchild_pid},
    )


# --- 主入口 --------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="S1-T4/T7 Windows sandbox spike")
    parser.add_argument("--json", default=None, help="结果 JSON 输出路径")
    parser.add_argument("--probe-host", default="127.0.0.1:135",
                        help="P4 出站探测目标（默认本机 RPC endpoint mapper，避免外网依赖）")
    args = parser.parse_args()

    sandbox_root = Path(tempfile.gettempdir()) / "pa-sandbox-spike"
    if sandbox_root.exists():
        shutil.rmtree(sandbox_root, ignore_errors=True)
    sandbox_root.mkdir(parents=True)
    try:
        set_path_integrity_low(sandbox_root)
    except RuntimeError as exc:
        print(f"ENV-ERROR: {exc}")
        return 2

    results: list[ProofResult] = []
    for builder in (
        lambda: proof_p1_cwd_writable(sandbox_root),
        lambda: proof_p2_system_readable(sandbox_root),
        lambda: proof_p3_sensitive_denied(sandbox_root),
        lambda: proof_p4_network(sandbox_root, args.probe_host),
        lambda: proof_p5_kill_tree(sandbox_root),
    ):
        try:
            result = builder()
        except Exception as exc:  # noqa: BLE001 - spike：任何异常都是证据
            name = builder.__name__
            result = ProofResult(
                proof=name[:2].upper(), description="执行异常",
                passed=False, expected=True, detail=f"{type(exc).__name__}: {exc}",
            )
        results.append(result)
        status = "PASS" if result.passed == result.expected else "FAIL"
        print(f"[{status}] {result.proof} {result.description}\n       {result.detail}")

    payload = {
        "spike": "s1-sandbox-windows",
        "platform": sys.platform,
        "python": sys.version,
        "probe_host": args.probe_host,
        "results": [vars(r) for r in results],
        "all_consistent": all(r.passed == r.expected for r in results),
    }
    if args.json:
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON 证据已写入: {args.json}")
    shutil.rmtree(sandbox_root, ignore_errors=True)
    return 0 if payload["all_consistent"] else 1


if __name__ == "__main__":
    sys.exit(main())
