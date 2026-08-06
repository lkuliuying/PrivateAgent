#!/usr/bin/env python3
"""只读读取 Windows 进程环境变量（0.2.1 QA 辅助）。

安装版 sidecar 的 ``PA_API_TOKEN`` 由 Tauri 运行时注入（不落盘），QA 需要该
token 做真实 Agent API smoke。本工具通过 PEB 只读读取目标进程环境块，
不做任何修改；仅用于本机发布 QA，不做通用渗透用途。

用法：uv run python scripts/read_process_env.py <pid> [VAR_NAME...]
      不指定 VAR_NAME 时列出全部键名。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import sys

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", w.WORD),
        ("MaximumLength", w.WORD),
        ("Buffer", ctypes.c_void_p),
    ]


class RTL_USER_PROCESS_PARAMETERS(ctypes.Structure):
    _fields_ = [
        ("Reserved1", ctypes.c_ubyte * 16),
        ("Reserved2", ctypes.c_ubyte * 10),
        ("ImagePathName", UNICODE_STRING),
        ("CommandLine", UNICODE_STRING),
        ("Environment", UNICODE_STRING),
    ]


class PEB(ctypes.Structure):
    _fields_ = [
        ("Reserved1", ctypes.c_ubyte * 2),
        ("BeingDebugged", ctypes.c_ubyte),
        ("Reserved2", ctypes.c_ubyte),
        ("Reserved3", ctypes.c_ubyte * 4),
        ("Ldr", ctypes.c_void_p),
        ("ProcessParameters", ctypes.c_void_p),
    ]


class PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Reserved1", ctypes.c_void_p),
        ("PebBaseAddress", ctypes.c_void_p),
        ("Reserved2", ctypes.c_void_p * 2),
        ("UniqueProcessId", ctypes.c_void_p),
        ("Reserved3", ctypes.c_void_p),
    ]


def read_process_env(pid: int) -> dict[str, str]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise OSError(f"OpenProcess failed: {ctypes.get_last_error()}")
    try:
        pbi = PROCESS_BASIC_INFORMATION()
        status = ntdll.NtQueryInformationProcess(
            handle, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None
        )
        if status != 0:
            raise OSError(f"NtQueryInformationProcess failed: {status}")
        if not pbi.PebBaseAddress:
            raise OSError("process has no PEB")

        def read_mem(addr: int, size: int) -> bytes:
            buf = ctypes.create_string_buffer(size)
            read = ctypes.c_size_t()
            if not kernel32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(read)):
                raise OSError(f"ReadProcessMemory failed: {ctypes.get_last_error()}")
            return buf.raw[: read.value]

        peb = PEB()
        peb_bytes = read_mem(pbi.PebBaseAddress, ctypes.sizeof(PEB))
        ctypes.memmove(ctypes.byref(peb), peb_bytes, ctypes.sizeof(PEB))
        if not peb.ProcessParameters:
            raise OSError("no process parameters")
        params = RTL_USER_PROCESS_PARAMETERS()
        params_bytes = read_mem(peb.ProcessParameters, ctypes.sizeof(RTL_USER_PROCESS_PARAMETERS))
        ctypes.memmove(ctypes.byref(params), params_bytes, ctypes.sizeof(RTL_USER_PROCESS_PARAMETERS))
        env_addr = params.Environment.Buffer
        env_len = params.Environment.Length or params.Environment.MaximumLength
        if env_len <= 0:
            env_len = 32 * 1024
        raw = read_mem(env_addr, env_len)
        text = raw.decode("utf-16-le", errors="replace")
        env: dict[str, str] = {}
        for entry in text.split("\x00"):
            if "=" in entry:
                key, _, value = entry.partition("=")
                env[key] = value
        return env
    finally:
        kernel32.CloseHandle(handle)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    pid = int(sys.argv[1])
    wanted = sys.argv[2:]
    env = read_process_env(pid)
    if wanted:
        for name in wanted:
            print(f"{name}={env.get(name, '<missing>')}")
    else:
        for key in sorted(env):
            value = env[key]
            redacted = value if len(value) < 64 else value[:32] + "…(len=%d)" % len(value)
            print(f"{key}={redacted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
