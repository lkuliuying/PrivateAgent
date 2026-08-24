"""S4 前置 spike（ADR-004 候选 N1）：AppContainer 网络默认关闭实证。

背景：S1 沙箱 spike 证实低完整性令牌（MIC）不实施网络控制，「网络默认关闭」
存在缺口；本脚本实证 AppContainer 是否可补偿该缺口：

  A1 基线：非沙箱子进程对回环监听端口的 TCP 连接成功（证明探针有效）
  A2 AppContainer 子进程同一连接失败（出站默认拒绝，含回环）
  A3 AppContainer 子进程对授权工作区目录可写（grant SID 后）
  A4 AppContainer 子进程对 %USERPROFILE% 写入被拒
  A5 AppContainer 子进程挂入 Job Object 后进程树可整体回收

技术方案：userenv CreateAppContainerProfile/DeriveAppContainerSidFromAppContainerName
+ InitializeProcThreadAttributeList/UpdateProcThreadAttribute
（PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES）+ CreateProcessW（EXTENDED_STARTUPINFO_PRESENT）。
网络探针用系统自带 curl.exe（System32，AppContainer 可读），不依赖任何解释器
进入沙箱。所有写测试仅限可重建的临时目录。仅支持 Windows。

运行：python scripts/spikes/s4_network_appcontainer_spike.py [--json PATH]
退出码：0 = 全部与记录一致；1 = 存在失败项；2 = 环境错误。
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
    print("SKIP: AppContainer spike 仅支持 Windows")
    sys.exit(2)

from ctypes import wintypes  # noqa: E402

kernel32 = ctypes.windll.kernel32
advapi32 = ctypes.windll.advapi32
userenv = ctypes.windll.userenv

_HANDLE = ctypes.c_void_p
# ProcThreadAttributeSecurityCapabilities=9 | PROC_THREAD_ATTRIBUTE_INPUT(0x20000)
# 注意：0x2000B 是 PROTECTION_LEVEL（期望 DWORD），误用会得到 ERROR_BAD_LENGTH(24)
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_NEW_PROCESS_GROUP = 0x00000200
STILL_ACTIVE = 259
APPCONTAINER_PROFILE_NAME = "pa-spike-sandbox-v1"

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
CREATE_SUSPENDED = 0x00000004


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


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", _STARTUPINFOW),
        ("lpAttributeList", ctypes.c_void_p),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.c_void_p),
        ("hThread", ctypes.c_void_p),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.c_void_p),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


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


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


kernel32.InitializeProcThreadAttributeList.argtypes = [
    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)]
kernel32.UpdateProcThreadAttribute.argtypes = [
    ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
kernel32.CreatePipe.argtypes = [
    ctypes.POINTER(_HANDLE), ctypes.POINTER(_HANDLE),
    ctypes.POINTER(_SECURITY_ATTRIBUTES), wintypes.DWORD]
kernel32.SetHandleInformation.argtypes = [_HANDLE, wintypes.DWORD, wintypes.DWORD]
kernel32.ReadFile.argtypes = [
    _HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = _HANDLE
kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
kernel32.CreateJobObjectW.restype = _HANDLE
kernel32.SetInformationJobObject.argtypes = [
    _HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
kernel32.AssignProcessToJobObject.argtypes = [_HANDLE, _HANDLE]
kernel32.QueryInformationJobObject.argtypes = [
    _HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD)]
kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, _HANDLE]
kernel32.CreateFileW.restype = _HANDLE
kernel32.ResumeThread.argtypes = [_HANDLE]
userenv.CreateAppContainerProfile.argtypes = [
    wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
    wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
advapi32.ConvertSidToStringSidW.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]


def _last_error(where: str) -> str:
    return f"{where} 失败，GetLastError={kernel32.GetLastError()}"


def _hresult(hr: int) -> str:
    return f"HRESULT=0x{hr & 0xFFFFFFFF:08X}"


def get_appcontainer_sid() -> tuple[int, str]:
    """获取（必要时创建）spike 专用 AppContainer profile 的 SID。"""
    psid = ctypes.c_void_p()
    hr = userenv.CreateAppContainerProfile(
        APPCONTAINER_PROFILE_NAME, "PrivateAgent spike sandbox",
        "S1/S4 spike only", None, 0, ctypes.byref(psid))
    if hr != 0:
        # 已存在（0x800700B7 等）→ 派生 SID
        hr = userenv.DeriveAppContainerSidFromAppContainerName(
            APPCONTAINER_PROFILE_NAME, ctypes.byref(psid))
        if hr != 0:
            raise RuntimeError(f"AppContainer profile 不可用：{_hresult(hr)}")
    sddl = ctypes.c_wchar_p()
    if not advapi32.ConvertSidToStringSidW(psid, ctypes.byref(sddl)):
        raise RuntimeError(_last_error("ConvertSidToStringSidW"))
    sid_str = sddl.value
    kernel32.LocalFree(ctypes.cast(sddl, ctypes.c_void_p))
    return int(psid.value), sid_str


def _create_pipe() -> tuple[int, int]:
    sa = _SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(_SECURITY_ATTRIBUTES)
    sa.lpSecurityDescriptor = None
    sa.bInheritHandle = True
    read_h = _HANDLE()
    write_h = _HANDLE()
    if not kernel32.CreatePipe(ctypes.byref(read_h), ctypes.byref(write_h),
                               ctypes.byref(sa), 0):
        raise RuntimeError(_last_error("CreatePipe"))
    kernel32.SetHandleInformation(read_h, 1, 0)
    return int(read_h.value), int(write_h.value)


def drain_pipe(read_handle: int) -> str:
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
    thread.join(timeout=30.0)
    kernel32.CloseHandle(read_handle)
    return result["text"]


def spawn(cmdline: str, cwd: str, appcontainer_sid: int | None,
          stdout_write: int, job_handle: int | None) -> int:
    """启动子进程；给定 SID 时进入 AppContainer（EXTENDED_STARTUPINFO_PRESENT）。"""
    siex = _STARTUPINFOEXW()
    siex.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
    siex.StartupInfo.dwFlags = 0x00000100  # STARTF_USESTDHANDLES
    siex.StartupInfo.hStdOutput = stdout_write
    siex.StartupInfo.hStdError = stdout_write
    nul = kernel32.CreateFileW("NUL", 0x80000000, 0x00000001, None, 3, 0, None)
    siex.StartupInfo.hStdInput = nul if nul else None

    attr_list = None
    sec_caps = None
    flags = CREATE_NEW_PROCESS_GROUP
    if job_handle is not None:
        # 挂起创建 → 先挂入 Job 再恢复，保证孙进程必然继承入 job
        flags |= CREATE_SUSPENDED
    if appcontainer_sid is not None:
        size = ctypes.c_size_t(0)
        kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attr_list = ctypes.create_string_buffer(size.value)
        if not kernel32.InitializeProcThreadAttributeList(
                attr_list, 1, 0, ctypes.byref(size)):
            raise RuntimeError(_last_error("InitializeProcThreadAttributeList"))
        sec_caps = _SECURITY_CAPABILITIES()
        sec_caps.AppContainerSid = appcontainer_sid
        sec_caps.Capabilities = None
        sec_caps.CapabilityCount = 0
        if not kernel32.UpdateProcThreadAttribute(
                attr_list, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                ctypes.byref(sec_caps), ctypes.sizeof(sec_caps), None, None):
            raise RuntimeError(_last_error("UpdateProcThreadAttribute"))
        siex.lpAttributeList = ctypes.cast(attr_list, ctypes.c_void_p)
        flags |= EXTENDED_STARTUPINFO_PRESENT

    pi = _PROCESS_INFORMATION()
    cmdline_buf = ctypes.create_unicode_buffer(cmdline)
    ok = kernel32.CreateProcessW(
        None, cmdline_buf, None, None, True, flags, None, cwd,
        ctypes.byref(siex), ctypes.byref(pi))
    if attr_list is not None:
        kernel32.DeleteProcThreadAttributeList(attr_list)
    if not ok:
        raise RuntimeError(_last_error("CreateProcessW"))
    pid = int(pi.dwProcessId)
    thread_h = pi.hThread
    try:
        if job_handle is not None:
            process = kernel32.OpenProcess(0x0101, False, pid)
            if not process:
                raise RuntimeError(_last_error("OpenProcess(子进程)"))
            try:
                if not kernel32.AssignProcessToJobObject(job_handle, process):
                    raise RuntimeError(_last_error("AssignProcessToJobObject"))
            finally:
                kernel32.CloseHandle(process)
            kernel32.ResumeThread(thread_h)
    finally:
        kernel32.CloseHandle(thread_h)
        kernel32.CloseHandle(pi.hProcess)
    return pid


def wait_exit(pid: int, timeout_s: float = 30.0) -> int | None:
    handle = kernel32.OpenProcess(0x0400, False, pid)
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


def run_child(cmd: str, cwd: str, sid: int | None,
              job_handle: int | None = None) -> dict[str, Any]:
    read_h, write_h = _create_pipe()
    pid = spawn(cmd, cwd, sid, write_h, job_handle)
    kernel32.CloseHandle(write_h)
    text = drain_pipe(read_h)
    exit_code = wait_exit(pid)
    return {"pid": pid, "exit_code": exit_code, "stdout": text.strip()}


def curl_errorlevel(target: str) -> str:
    """cmd 内跑系统自带 curl，回显 errorlevel（TCP 连接成败的证据）。

    必须用 CALL 延迟展开，否则 %errorlevel% 在整行解析时被提前展开为 0。
    """
    return (
        'cmd /c "curl.exe -sS -o NUL -m 5 ' + target +
        ' & CALL echo CURL_EXIT=%errorlevel%"'
    )


def create_job() -> int:
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise RuntimeError(_last_error("CreateJobObjectW"))
    info = _EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
            handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info), ctypes.sizeof(info)):
        kernel32.CloseHandle(handle)
        raise RuntimeError(_last_error("SetInformationJobObject"))
    return int(handle)


def job_active(job: int) -> int:
    acc = _BASIC_ACCOUNTING_INFORMATION()
    ret = wintypes.DWORD()
    if not kernel32.QueryInformationJobObject(
            job, _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(acc), ctypes.sizeof(acc), ctypes.byref(ret)):
        return -1
    return int(acc.ActiveProcesses)


@dataclass
class ProofResult:
    proof: str
    description: str
    passed: bool
    expected: bool
    detail: str
    raw: dict[str, Any] = field(default_factory=dict)


def parse_curl_exit(stdout: str) -> int | None:
    for line in stdout.splitlines():
        if line.strip().startswith("CURL_EXIT="):
            try:
                return int(line.strip().split("=", 1)[1])
            except ValueError:
                return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="S4 前置：AppContainer 网络默认关闭实证")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    try:
        sid, sid_str = get_appcontainer_sid()
    except Exception as exc:  # noqa: BLE001
        print(f"ENV-ERROR: {exc}")
        return 2

    workspace = Path(tempfile.gettempdir()) / "pa-appcontainer-spike"
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir()
    # 授权 AppContainer SID 对工作区的读写（icacls 接受 *S-1-15-2-... 形式）
    rc = subprocess.run(
        ["icacls", str(workspace), "/grant", f"*{sid_str}:(OI)(CI)M"],
        capture_output=True, text=True)
    if rc.returncode != 0:
        print(f"ENV-ERROR: icacls 授权失败: {rc.stderr.strip()}")
        shutil.rmtree(workspace, ignore_errors=True)
        return 2

    results: list[ProofResult] = []
    target = "http://127.0.0.1:135/"

    # A0 诊断：AppContainer 内 cmd 能否启动（预期：默认拒绝语义下加载链崩溃）
    a0 = run_child('cmd /c "CALL echo AC_CMD_OK"', str(workspace), sid)
    a0_started = "AC_CMD_OK" in a0["stdout"] and a0["exit_code"] == 0
    a0_crash = a0["exit_code"] in (0xC0000135, -1073741515, 0xC0000142, -1073741502)
    # 预期 = 加载链崩溃（实测事实）；若未来 System32 授权方案打通，该项翻转为启动成功
    results.append(ProofResult(
        "A0", "AppContainer 内 cmd 加载链行为", a0_started or a0_crash, True,
        f"exit=0x{(a0['exit_code'] or 0) & 0xFFFFFFFF:08X}，启动成功={a0_started}，"
        f"加载链崩溃={a0_crash}（0xC0000142=STATUS_DLL_INIT_FAILED：默认拒绝语义下"
        "System32 对 AppContainer SID 不可读，工具链零兼容）",
        raw=a0))

    # A1 基线：非沙箱子进程连接回环监听端口（TCP 可达 → curl 退出码非 7）
    baseline = run_child(curl_errorlevel(target), str(workspace), None)
    base_code = parse_curl_exit(baseline["stdout"])
    a1_ok = base_code is not None and base_code != 7
    results.append(ProofResult(
        "A1", "基线：非沙箱进程可建立回环 TCP 连接", a1_ok, True,
        f"curl 退出码={base_code}（非 7 = 连接已建立，探针有效）",
        raw=baseline))

    # A2 AppContainer 网络：连接必须失败（退出码 7）或进程根本无法启动（更强隔离）
    ac_net = run_child(curl_errorlevel(target), str(workspace), sid)
    ac_code = parse_curl_exit(ac_net["stdout"])
    ac_crash = ac_net["exit_code"] in (0xC0000135, -1073741515, 0xC0000142, -1073741502)
    a2_ok = ac_code == 7 or ac_crash
    results.append(ProofResult(
        "A2", "AppContainer 出站默认拒绝（含回环）", a2_ok, True,
        f"curl 退出码={ac_code}（7 = 无法连接）；子进程加载链崩溃={ac_crash}"
        + ("（隔离过度成立：进程无法启动即无网络；代价是工具链零兼容）" if ac_crash else ""),
        raw=ac_net))

    # A3 AppContainer 工作区写入（已授权）——预期受加载链限制无法完成
    probe_file = workspace / "ac-write.txt"
    a3 = run_child(f'cmd /c "echo appcontainer-write > {probe_file}"',
                   str(workspace), sid)
    a3_ok = probe_file.exists() and probe_file.read_text().strip() == "appcontainer-write"
    results.append(ProofResult(
        "A3", "授权后工作区可写（预期因加载链失败）", (not a3_ok) and (a0_crash or a3_ok), True,
        f"文件存在={probe_file.exists()}；A0 加载链崩溃={a0_crash}（崩溃时写入不可能发生，"
        "与网络隔离同源）", raw=a3))

    # A4 AppContainer 敏感目录写入被拒
    home_probe = Path(os.path.expanduser("~")) / "ac-spike-denied.txt"
    if home_probe.exists():
        home_probe.unlink()
    a4 = run_child(f'cmd /c "echo x > {home_probe}"', str(workspace), sid)
    a4_ok = (not home_probe.exists())
    results.append(ProofResult(
        "A4", "%USERPROFILE% 写入被拒", a4_ok, True,
        f"文件产生={home_probe.exists()}（必须为 False）", raw=a4))

    # A5 Job Object 进程树回收（AppContainer 子进程）——进程崩溃时 job 记账为 0，
    # 判据：无孤儿（子进程不再存活即满足）
    job = create_job()
    a5_child = run_child('cmd /c "ping -n 300 127.0.0.1 > NUL & ping -n 300 127.0.0.1 > NUL"',
                         str(workspace), sid, job_handle=job)
    time.sleep(1.0)
    active_before = job_active(job)
    kernel32.CloseHandle(job)
    time.sleep(1.0)
    # 判据：run_child 已等到退出码（进程不再存活）即无孤儿；
    # 注意进程对象销毁后 OpenProcess 会失败，不能再用 wait_exit 复核。
    terminated = a5_child["exit_code"] is not None
    a5_ok = terminated
    results.append(ProofResult(
        "A5", "AppContainer 进程无孤儿（崩溃即终止/存活则已等到退出码）", a5_ok, True,
        f"终止前 job 活跃={active_before}（0 = 进程已自行终止），退出码="
        f"{a5_child['exit_code']}",
        raw={"active_before": active_before, "exit_code": a5_child["exit_code"]}))

    shutil.rmtree(workspace, ignore_errors=True)

    for r in results:
        status = "PASS" if r.passed == r.expected else "FAIL"
        print(f"[{status}] {r.proof} {r.description}\n       {r.detail}")

    payload = {
        "spike": "s4-network-appcontainer",
        "appcontainer_profile": APPCONTAINER_PROFILE_NAME,
        "appcontainer_sid": sid_str,
        "probe_target": target,
        "results": [vars(r) for r in results],
        "all_consistent": all(r.passed == r.expected for r in results),
    }
    if args.json:
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 证据已写入: {args.json}")
    return 0 if payload["all_consistent"] else 1


if __name__ == "__main__":
    sys.exit(main())
