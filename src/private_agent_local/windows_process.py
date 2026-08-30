"""Windows process-tree ownership and frozen-app DLL search isolation."""
from __future__ import annotations

import ctypes
from contextlib import contextmanager
from ctypes import wintypes


class BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", BasicLimits), ("io", ctypes.c_ulonglong * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]


class ProcessJob:
    """Closing the job kills descendants even after the original parent exits."""
    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        self.kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.handle = self.kernel.CreateJobObjectW(None, None)
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ValueError("无法建立本机命令进程保护，已拒绝执行")

    def assign(self, pid: int):
        process = self.kernel.OpenProcess(0x0100 | 0x0001, False, pid)  # SET_QUOTA | TERMINATE
        try:
            if not process or not self.kernel.AssignProcessToJobObject(self.handle, process):
                raise ValueError("无法关联命令进程保护，已停止执行")
        finally:
            if process:
                self.kernel.CloseHandle(process)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


@contextmanager
def system_dll_search():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetDllDirectoryW.argtypes = (wintypes.DWORD, wintypes.LPWSTR)
    kernel.SetDllDirectoryW.argtypes = (wintypes.LPCWSTR,)
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetDllDirectoryW(len(buffer), buffer)
    if length >= len(buffer) or not kernel.SetDllDirectoryW(None):
        raise ValueError("无法恢复系统 DLL 搜索路径，已拒绝启动外部工具")
    try:
        yield
    finally:
        kernel.SetDllDirectoryW(buffer.value if length else None)
