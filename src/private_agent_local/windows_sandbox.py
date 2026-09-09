"""Windows AppContainer 的独立身份、目录授权及可恢复清理。"""
from __future__ import annotations

import asyncio
import ctypes as c
import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from contextlib import contextmanager
from ctypes import wintypes as w
from pathlib import Path

from .workspaces import FileLock


class Trustee(c.Structure):
    _fields_ = [("multiple", c.c_void_p), ("operation", c.c_int), ("form", c.c_int),
                ("kind", c.c_int), ("name", c.c_void_p)]


class Access(c.Structure):
    _fields_ = [("permissions", w.DWORD), ("mode", c.c_int), ("inheritance", w.DWORD), ("trustee", Trustee)]


class WindowsSecurity:
    def __init__(self):
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.security = c.WinDLL("advapi32", use_last_error=True)
        self.userenv = c.WinDLL("userenv", use_last_error=True)
        self.ole = c.WinDLL("ole32", use_last_error=True)
        self.kernel.LocalFree.argtypes = [c.c_void_p]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.kernel.OpenProcess.restype = w.HANDLE
        self.kernel.GetCurrentProcess.restype = w.HANDLE
        self.kernel.CreateMutexW.argtypes = [c.c_void_p, w.BOOL, w.LPCWSTR]
        self.kernel.CreateMutexW.restype = w.HANDLE
        self.kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        self.kernel.ReleaseMutex.argtypes = [w.HANDLE]
        self.security.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
        self.userenv.GetUserProfileDirectoryW.argtypes = [w.HANDLE, w.LPWSTR, c.POINTER(w.DWORD)]
        self.kernel.GetProcessTimes.argtypes = [w.HANDLE, *([c.POINTER(w.FILETIME)] * 4)]
        self.kernel.GetExitCodeProcess.argtypes = [w.HANDLE, c.POINTER(w.DWORD)]
        self.security.FreeSid.argtypes = [c.c_void_p]
        self.security.ConvertSidToStringSidW.argtypes = [c.c_void_p, c.POINTER(w.LPWSTR)]
        self.security.GetNamedSecurityInfoW.argtypes = [w.LPCWSTR, c.c_int, w.DWORD, c.c_void_p, c.c_void_p,
                                                       c.POINTER(c.c_void_p), c.c_void_p, c.POINTER(c.c_void_p)]
        self.security.SetNamedSecurityInfoW.argtypes = [w.LPWSTR, c.c_int, w.DWORD, c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p]
        self.security.SetEntriesInAclW.argtypes = [w.ULONG, c.POINTER(Access), c.c_void_p, c.POINTER(c.c_void_p)]
        self.security.GetAce.argtypes = [c.c_void_p, w.DWORD, c.POINTER(c.c_void_p)]
        self.security.EqualSid.argtypes = [c.c_void_p, c.c_void_p]
        self.userenv.CreateAppContainerProfile.argtypes = [w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, c.c_void_p, w.DWORD, c.POINTER(c.c_void_p)]
        self.userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [w.LPCWSTR, c.POINTER(c.c_void_p)]
        self.userenv.DeleteAppContainerProfile.argtypes = [w.LPCWSTR]
        self.userenv.GetAppContainerFolderPath.argtypes = [w.LPCWSTR, c.POINTER(w.LPWSTR)]
        self.ole.CoTaskMemFree.argtypes = [c.c_void_p]

    def home(self):
        token = w.HANDLE()
        if not self.security.OpenProcessToken(self.kernel.GetCurrentProcess(), 8, c.byref(token)):
            raise c.WinError(c.get_last_error())
        try:
            size = w.DWORD(32768)
            buffer = c.create_unicode_buffer(size.value)
            if not self.userenv.GetUserProfileDirectoryW(token, buffer, c.byref(size)):
                raise c.WinError(c.get_last_error())
            return Path(buffer.value).resolve()
        finally:
            self.kernel.CloseHandle(token)

    def identity(self, pid):
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            if c.get_last_error() == 87:
                return None
            raise c.WinError(c.get_last_error())
        try:
            times = [w.FILETIME() for _ in range(4)]
            code = w.DWORD()
            if not self.kernel.GetProcessTimes(handle, *(c.byref(t) for t in times)) or not self.kernel.GetExitCodeProcess(handle, c.byref(code)):
                raise c.WinError(c.get_last_error())
            return {"pid": pid, "created": (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime} if code.value == 259 else None
        finally:
            self.kernel.CloseHandle(handle)

    def sid(self, name, *, create=False):
        sid = c.c_void_p()
        hr = self.userenv.CreateAppContainerProfile(name, name, "PrivateAgent isolated execution", None, 0, c.byref(sid)) if create else self.userenv.DeriveAppContainerSidFromAppContainerName(name, c.byref(sid))
        if hr < 0:
            raise OSError(f"AppContainer identity failed: {hr:#x}")
        return sid

    def folder(self, sid):
        text, folder = w.LPWSTR(), w.LPWSTR()
        if not self.security.ConvertSidToStringSidW(sid, c.byref(text)):
            raise c.WinError(c.get_last_error())
        try:
            hr = self.userenv.GetAppContainerFolderPath(text, c.byref(folder))
            if hr < 0:
                raise OSError(f"AppContainer folder failed: {hr:#x}")
            return Path(folder.value)
        finally:
            self.kernel.LocalFree(c.cast(text, c.c_void_p))
            if folder:
                self.ole.CoTaskMemFree(c.cast(folder, c.c_void_p))

    @contextmanager
    def acl_writer(self):
        name = "Global\\PrivateAgent.SandboxACL." + hashlib.sha256(str(self.home()).casefold().encode()).hexdigest()
        handle = self.kernel.CreateMutexW(None, False, name)
        if not handle:
            raise c.WinError(c.get_last_error())
        acquired = False
        try:
            acquired = self.kernel.WaitForSingleObject(handle, 30000) in {0, 0x80}
            if not acquired:
                raise ValueError("另一执行器正在调整沙箱权限，等待超时，命令未执行")
            yield
        finally:
            if acquired:
                self.kernel.ReleaseMutex(handle)
            self.kernel.CloseHandle(handle)

    def acl(self, path, sid, *, write=False, revoke=False):
        # 不同账号的数据目录仍可能共享工具目录，读改写 ACL 必须跨进程串行。
        with self.acl_writer():
            self._acl(path, sid, write=write, revoke=revoke)

    def _acl(self, path, sid, *, write=False, revoke=False):
        previous, descriptor, updated = c.c_void_p(), c.c_void_p(), c.c_void_p()
        error = self.security.GetNamedSecurityInfoW(str(path), 1, 4, None, None, c.byref(previous), None, c.byref(descriptor))
        if error:
            raise c.WinError(error)
        try:
            if not previous:
                raise ValueError("目录没有显式 DACL，不能安全授予沙箱访问")
            if revoke:
                present = False
                for index in range(int.from_bytes(c.string_at(previous, 8)[4:6], "little")):
                    ace = c.c_void_p()
                    if not self.security.GetAce(previous, index, c.byref(ace)):
                        raise c.WinError(c.get_last_error())
                    if c.string_at(ace, 1) == b"\x00" and self.security.EqualSid(c.c_void_p(ace.value + 8), sid):
                        present = True
                        break
                # 意图先写日志；失败的授权可能从未添加 ACE，此时不触碰该目录 DACL。
                if not present:
                    return
            access = Access(0x1301BF if write else 0x1200A9, 4 if revoke else 1, 3, Trustee(None, 0, 0, 0, sid.value))
            error = self.security.SetEntriesInAclW(1, c.byref(access), previous, c.byref(updated))
            if error:
                raise c.WinError(error)
            # 只删除本次独立 SID 的 ACE，不恢复旧快照覆盖其他主体的新权限。
            error = self.security.SetNamedSecurityInfoW(str(path), 1, 4, None, None, updated, None)
            if error:
                raise c.WinError(error)
        finally:
            self.kernel.LocalFree(updated)
            self.kernel.LocalFree(descriptor)


def _directory(path):
    path = Path(path).absolute()
    if any(p.is_symlink() or p.is_junction() for p in [path, *path.parents]):
        raise ValueError("沙箱授权路径不能包含链接或目录联接")
    return path.resolve(strict=True)


def _check_tree(root, *, write=False):
    count = 0
    for current, directories, names in os.walk(root, followlinks=False, onerror=lambda error: (_ for _ in ()).throw(error)):
        for name in [*directories, *names]:
            count += 1
            path = Path(current) / name
            if count > 50000:
                raise ValueError("沙箱授权扫描超过 50000 项，请缩小工作区或工具目录")
            if path.is_symlink() or path.is_junction():
                raise ValueError("沙箱目录包含链接或目录联接，未授权执行")
            # 硬链接共享文件 ACL，递归授予写权限会同时影响工作区外的同一文件。
            if write and path.is_file() and path.stat().st_nlink != 1:
                raise ValueError("可写沙箱工作区包含硬链接文件，未授权执行")


def runtime_roots(argv, environment):
    executable = shutil.which(argv[0], path=environment.get("PATH", ""))
    if not executable:
        raise ValueError("找不到命令运行时，不能准备沙箱")
    executable = Path(executable).resolve(strict=True)
    candidates = {executable.parent}
    for directory in list(candidates):
        config = directory.parent / "pyvenv.cfg"
        if directory.name.lower() == "scripts" and config.is_file():
            candidates.add(directory.parent)
            if config.stat().st_size > 8192:
                raise ValueError("Python 虚拟环境配置超过大小限制")
            for line in config.read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition("=")
                if separator and key.strip() == "home":
                    candidates.add(Path(value.strip()))
    if not getattr(sys, "frozen", False) and executable.stem.lower() in {"python", "python3", "pytest"}:
        candidates.add(Path(sys.base_prefix))
    system = Path(environment.get("SYSTEMROOT", environment.get("SystemRoot", r"C:\Windows"))).resolve()
    roots = sorted({_directory(p.resolve()) for p in candidates if p.is_dir()}, key=lambda p: len(str(p)))
    result = []
    home = WindowsSecurity().home()
    for path in roots:
        # Windows 自带系统文件已有包访问权限，绝不修改系统目录 ACL。
        if path.is_relative_to(system) or any(path.is_relative_to(p) for p in result):
            continue
        if path == Path(path.anchor) or path == home:
            raise ValueError("运行时目录范围过宽，不能授权沙箱")
        result.append(path)
    if len(result) > 16:
        raise ValueError("运行时授权目录超过 16 个")
    return result


class SandboxLease:
    @classmethod
    async def prepare(cls, root, argv, environment, *, directory=None):
        task = asyncio.create_task(asyncio.to_thread(cls, root, argv, environment, directory=directory))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            lease = await task
            await asyncio.to_thread(lease.close)
            raise

    def __init__(self, root, argv, environment, *, directory=None):
        if os.name != "nt":
            raise ValueError("当前平台没有已验证的原生沙箱")
        self.api = WindowsSecurity()
        self.base = Path(directory) if directory else Path(tempfile.gettempdir()) / "privateagent-sandbox-leases"
        self.base.mkdir(parents=True, exist_ok=True)
        self.base = _directory(self.base)
        self.recover(self.base)
        root = _directory(root)
        if self.base.is_relative_to(root) or root == Path(root.anchor) or root == self.api.home():
            raise ValueError("工作区覆盖沙箱控制目录或用户根目录，不能执行")
        roots = runtime_roots(argv, environment)
        entries = [{"path": str(p), "write": p == root} for p in [root, *roots] if p == root or not p.is_relative_to(root)]
        for entry in entries:
            _check_tree(Path(entry["path"]), write=entry["write"])
        self.name = "pa.execution." + uuid.uuid4().hex
        self.lock = FileLock(self.base / (self.name + ".lock"))
        self.path = self.base / (self.name + ".json")
        self.record = {"version": 1, "profile": self.name, "owner": self.api.identity(os.getpid()), "host": None, "paths": entries}
        self.sid = None
        self.closed = False
        try:
            self._save()
        except BaseException:
            self.lock.close()
            raise
        try:
            self.sid = self.api.sid(self.name, create=True)
            for entry in entries:
                self.api.acl(entry["path"], self.sid, write=entry["write"])
            self.environment = dict(environment)
            temporary = self.api.folder(self.sid) / "Temp"
            temporary.mkdir(exist_ok=True)
            self.environment.update(TEMP=str(temporary), TMP=str(temporary), PYTHONDONTWRITEBYTECODE="1")
        except BaseException:
            self.close()
            raise

    def _save(self):
        temporary = self.path.with_suffix(".pending")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(self.record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def bind(self, pid):
        self.record["host"] = self.api.identity(pid)
        if self.record["host"] is None:
            raise ValueError("执行宿主已退出，不能绑定沙箱")
        self._save()

    @staticmethod
    def _cleanup(api, record):
        sid = api.sid(record["profile"])
        try:
            for entry in record["paths"]:
                path = Path(entry["path"])
                if path.exists():
                    api.acl(_directory(path), sid, revoke=True)
            hr = api.userenv.DeleteAppContainerProfile(record["profile"])
            if hr < 0 and hr & 0xFFFF not in {2, 3}:
                raise OSError(f"AppContainer cleanup failed: {hr:#x}")
        finally:
            api.security.FreeSid(sid)

    def close(self):
        if self.closed:
            return
        try:
            host = self.record["host"]
            if host and self.api.identity(host["pid"]) == host:
                raise ValueError("宿主尚未退出，沙箱授权保留待核对")
            self._cleanup(self.api, self.record)
            self.path.unlink(missing_ok=True)
        finally:
            self.closed = True
            if self.sid:
                self.api.security.FreeSid(self.sid)
            self.lock.close()

    @classmethod
    def recover(cls, directory):
        api = WindowsSecurity()
        for path in Path(directory).glob("pa.execution.*.json"):
            if path.is_symlink() or path.stat().st_size > 32768:
                raise ValueError("沙箱清理记录无效，已停止执行")
            try:
                lock = FileLock(path.with_suffix(".lock"))
            except ValueError:
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("version") != 1 or record.get("profile") != path.stem or len(record.get("paths", [])) > 128:
                    raise ValueError("沙箱清理记录版本或归属无效")
                if any(identity and api.identity(identity["pid"]) == identity for identity in [record.get("owner"), record.get("host")]):
                    raise ValueError("旧沙箱进程仍然存活，不能清理或重新授权")
                cls._cleanup(api, record)
                path.unlink()
            finally:
                lock.close()
