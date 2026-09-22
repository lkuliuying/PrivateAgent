"""Windows AppContainer 的独立身份、目录授权及可恢复清理。"""
from __future__ import annotations

import asyncio
import ctypes as c
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from ctypes import wintypes as w
from pathlib import Path

from .workspaces import FileLock

CONTROL_NAMES = frozenset({".git", ".codex", ".agents"})
SECRET_NAMES = frozenset({".ssh", ".aws", ".gnupg", ".npmrc", ".pypirc", ".netrc", "id_rsa", "id_ed25519", ".privateagent"})
SECRET_SUFFIXES = frozenset({".pem", ".key", ".pfx", ".p12"})
# 这些掩码描述限制目标；AppContainer 使用允许项收敛，不依赖包 SID 的拒绝项。
DENY_WRITE = 0xD0156
DENY_ALL = 0x1F01FF
DENY_PARENT = 0xD0040
MAX_PROTECTIONS = 16384
MAX_JOURNAL_BYTES = 8 * 1024 * 1024


class FileId(c.Structure):
    _fields_ = [("volume", c.c_ulonglong), ("identifier", c.c_ubyte * 16)]


class FileAttributes(c.Structure):
    _fields_ = [("attributes", w.DWORD), ("reparse_tag", w.DWORD)]


def _path_identity(path):
    value = Path(path).lstat()
    if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
        raise ValueError("沙箱授权对象不能是链接或重解析点")
    return {"device": value.st_dev, "inode": value.st_ino}


def _protection_mode(relative):
    names = [part.casefold() for part in relative.parts]
    if (any(name == ".env" or name.startswith(".env.") or name in SECRET_NAMES for name in names)
            or relative.suffix.casefold() in SECRET_SUFFIXES):
        return DENY_ALL
    if any(name in CONTROL_NAMES for name in names):
        return DENY_WRITE
    return 0


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
        self.kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
        self.kernel.CreateFileW.restype = w.HANDLE
        self.kernel.GetFileInformationByHandleEx.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
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
        self.security.GetSecurityInfo.argtypes = [w.HANDLE, c.c_int, w.DWORD, c.c_void_p, c.c_void_p,
                                                 c.POINTER(c.c_void_p), c.c_void_p, c.POINTER(c.c_void_p)]
        self.security.SetSecurityInfo.argtypes = [w.HANDLE, c.c_int, w.DWORD, c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p]
        self.security.SetEntriesInAclW.argtypes = [w.ULONG, c.POINTER(Access), c.c_void_p, c.POINTER(c.c_void_p)]
        self.security.GetAce.argtypes = [c.c_void_p, w.DWORD, c.POINTER(c.c_void_p)]
        self.security.EqualSid.argtypes = [c.c_void_p, c.c_void_p]
        self.security.GetSecurityDescriptorControl.argtypes = [c.c_void_p, c.POINTER(w.WORD), c.POINTER(w.DWORD)]
        self.security.InitializeAcl.argtypes = [c.c_void_p, w.DWORD, w.DWORD]
        self.security.AddAce.argtypes = [c.c_void_p, w.DWORD, w.DWORD, c.c_void_p, w.DWORD]
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

    def acl(self, path, sid, *, write=False, revoke=False, deny=0, inherit=True, identity=None,
            restore_protected=None, restore_inherited=()):
        # 不同账号的数据目录仍可能共享工具目录，读改写 ACL 必须跨进程串行。
        with self.acl_writer():
            self._acl(path, sid, write=write, revoke=revoke, deny=deny, inherit=inherit, identity=identity,
                      restore_protected=restore_protected, restore_inherited=restore_inherited)

    @contextmanager
    def acl_target(self, path, identity=None):
        path = _directory(path)
        expected = identity or _path_identity(path)
        # 使用对象句柄改 ACL；不共享删除，阻止检查后被换成其他对象。
        handle = self.kernel.CreateFileW(str(path), 0x60000, 3, None, 3, 0x02200000, None)
        if handle == w.HANDLE(-1).value:
            raise c.WinError(c.get_last_error())
        try:
            identifier, attributes = FileId(), FileAttributes()
            if (not self.kernel.GetFileInformationByHandleEx(handle, 18, c.byref(identifier), c.sizeof(identifier))
                    or not self.kernel.GetFileInformationByHandleEx(handle, 9, c.byref(attributes), c.sizeof(attributes))):
                raise c.WinError(c.get_last_error())
            actual = {"device": identifier.volume, "inode": int.from_bytes(identifier.identifier, "little")}
            if attributes.attributes & 0x400 or actual != expected or _path_identity(path) != expected:
                raise ValueError("沙箱授权对象身份发生变化，未修改权限")
            yield handle
        finally:
            self.kernel.CloseHandle(handle)

    def _acl(self, path, sid, *, write=False, revoke=False, deny=0, inherit=True, identity=None,
             restore_protected=None, restore_inherited=()):
        with self.acl_target(path, identity) as handle:
            self._handle_acl(handle, sid, write=write, revoke=revoke, deny=deny, inherit=inherit,
                             restore_protected=restore_protected, restore_inherited=restore_inherited)

    @contextmanager
    def descriptor(self, handle):
        previous, descriptor = c.c_void_p(), c.c_void_p()
        error = self.security.GetSecurityInfo(handle, 1, 4, None, None, c.byref(previous), None, c.byref(descriptor))
        if error:
            raise c.WinError(error)
        try:
            if not previous:
                raise ValueError("目录没有显式 DACL，不能安全授予沙箱访问")
            yield previous, descriptor
        finally:
            self.kernel.LocalFree(descriptor)

    def entries(self, acl):
        result = []
        for index in range(int.from_bytes(c.string_at(acl, 8)[4:6], "little")):
            ace = c.c_void_p()
            if not self.security.GetAce(acl, index, c.byref(ace)):
                raise c.WinError(c.get_last_error())
            result.append(c.string_at(ace, int.from_bytes(c.string_at(ace, 4)[2:4], "little")))
        return result

    def protection_state(self, entry):
        with self.acl_target(entry["path"], entry["identity"]) as handle, self.descriptor(handle) as (acl, descriptor):
            entries = self.entries(acl)
            inherited_subjects = set()
            explicit_subjects = set()
            for ace in entries:
                if ace[0] not in {0, 1}:
                    raise ValueError("敏感对象包含无法安全判定的 ACL 类型，未授权执行；请核对目录权限")
                subject = (ace[0], ace[1] & ~16, ace[8:])
                # 同主体、同传播标志的显式与继承项可被合并，无法可靠增量还原时拒绝。
                if subject in inherited_subjects or ace[1] & 16 and subject in explicit_subjects:
                    raise ValueError("敏感对象存在可能合并的显式或继承授权，不能安全恢复权限；请核对目录权限")
                (inherited_subjects if ace[1] & 16 else explicit_subjects).add(subject)
                if ace[0] != 0:
                    continue
                sid = ace[8:]
                if len(sid) >= 16 and int.from_bytes(sid[2:8], "big") == 15 and int.from_bytes(sid[8:12], "little") == 2:
                    universal = len(sid) == 16 and int.from_bytes(sid[12:16], "little") in {1, 2}
                    mask = int.from_bytes(ace[4:8], "little")
                    # 原始 ACL 可能带通用位，先按文件对象展开，避免漏掉宽泛授权。
                    for generic, rights in ((0x10000000, 0x1F01FF), (0x80000000, 0x120089),
                                            (0x40000000, 0x120116), (0x20000000, 0x1200A0)):
                        if mask & generic:
                            mask |= rights
                    if not universal or mask & entry["deny"]:
                        raise ValueError("敏感对象已有重叠沙箱或宽泛应用包授权，不能安全收敛权限；请结束其他执行或核对目录权限")
            return {"original_protected": self.inheritance_protected(descriptor),
                    "inherited_aces": [ace.hex() for ace in entries if ace[1] & 16]}

    def inheritance_protected(self, descriptor):
        control, revision = w.WORD(), w.DWORD()
        if not self.security.GetSecurityDescriptorControl(descriptor, c.byref(control), c.byref(revision)):
            raise c.WinError(c.get_last_error())
        return bool(control.value & 0x1000)

    def _handle_acl(self, handle, sid, *, write=False, revoke=False, deny=0, inherit=True,
                    restore_protected=None, restore_inherited=()):
        """deny 表示需排除的权限分类；实际只收敛允许项，并临时阻止父级授权进入。"""
        with self.descriptor(handle) as (previous, descriptor):
            sid_bytes = c.string_at(sid, 8 + 4 * c.string_at(sid, 2)[1])
            old = self.entries(previous)
            retained = [ace for ace in old if not (ace[0] in {0, 1} and ace[8:] == sid_bytes)]
            if revoke and len(retained) == len(old) and restore_protected is None:
                return
            if restore_protected is False and self.inheritance_protected(descriptor):
                # Windows 在阻继承时将继承项转成显式项，只撤去本轮转换的精确副本。
                for encoded in restore_inherited:
                    inherited = bytes.fromhex(encoded)
                    converted = inherited[:1] + bytes((inherited[1] & ~16,)) + inherited[2:]
                    if converted in retained:
                        retained.remove(converted)
            grants = [] if revoke or deny == DENY_ALL else (
                [(0x1200A9, 3 if inherit else 0)] if deny == DENY_WRITE else
                [(0x1201BF, 0), (0x1301BF, 11)] if deny else [(0x1301BF if write else 0x1200A9, 3 if inherit else 0)])
            additions = [bytes((0, flags)) + (8 + len(sid_bytes)).to_bytes(2, "little")
                         + mask.to_bytes(4, "little") + sid_bytes for mask, flags in grants]
            insertion = next((index for index, ace in enumerate(retained) if ace[0] == 0 or ace[1] & 16), len(retained))
            entries = retained[:insertion] + additions + retained[insertion:]
            size, revision = 8 + sum(map(len, entries)), c.string_at(previous, 1)[0]
            updated = c.create_string_buffer(size)
            if not self.security.InitializeAcl(updated, size, revision):
                raise c.WinError(c.get_last_error())
            for ace in entries:
                if not self.security.AddAce(updated, revision, 0xFFFFFFFF, ace, len(ace)):
                    raise c.WinError(c.get_last_error())
            # 只移除本 SID；恢复继承时使用当前父目录规则，保留其他主体并发增加的显式项。
            flags = 4 | (0x80000000 if deny or restore_protected is True else 0x20000000 if restore_protected is False else 0)
            error = self.security.SetSecurityInfo(handle, 1, flags, None, None, updated, None)
            if error:
                raise c.WinError(error)


def _directory(path):
    path = Path(path).absolute()
    if any(p.is_symlink() or p.is_junction() for p in [path, *path.parents]):
        raise ValueError("沙箱授权路径不能包含链接或目录联接")
    return path.resolve(strict=True)


SCAN_TIMEOUT_SECONDS = 30


def _check_tree(root, *, write=False, deadline=None):
    deadline = deadline if deadline is not None else time.monotonic() + SCAN_TIMEOUT_SECONDS
    protections = {}

    def protect(path, mask, inherit):
        key = str(path)
        if key not in protections:
            if len(protections) >= MAX_PROTECTIONS:
                raise ValueError("沙箱敏感对象超过安全检查上限，未授权执行；请缩小工作区")
            protections[key] = {"path": key, "deny": mask, "inherit": inherit, "identity": _path_identity(path)}
        else:
            protections[key]["deny"] |= mask
            protections[key]["inherit"] |= inherit

    def check_deadline():
        if time.monotonic() >= deadline:
            scope = "工作区" if write else "工具目录"
            raise ValueError(f"沙箱安全检查超过 {SCAN_TIMEOUT_SECONDS} 秒（{scope}：{root}），未授权执行；请使用较小的工作区或独立工具环境")

    check_deadline()
    for current, directories, names in os.walk(root, followlinks=False, onerror=lambda error: (_ for _ in ()).throw(error)):
        check_deadline()
        for name in [*directories, *names]:
            check_deadline()
            path = Path(current) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError("沙箱目录包含链接或目录联接，未授权执行")
            # 硬链接共享文件 ACL，递归授予写权限会同时影响工作区外的同一文件。
            if write and path.is_file() and path.stat().st_nlink != 1:
                raise ValueError("可写沙箱工作区包含硬链接文件，未授权执行")
            if write and (mask := _protection_mode(path.relative_to(root))):
                protect(path, mask, path.is_dir())
                # 目标不授予 DELETE 仍不够，父目录也不能向沙箱授予 DELETE_CHILD。
                for ancestor in path.parents:
                    protect(ancestor, DENY_PARENT, False)
                    if ancestor == root:
                        break
    check_deadline()
    return sorted(protections.values(), key=lambda item: (len(Path(item["path"]).parts), item["path"]))


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
    # 批处理同名入口不能证明依赖当前解释器，避免额外授权无关的开发运行时。
    if (not getattr(sys, "frozen", False) and executable.suffix.lower() == ".exe"
            and executable.stem.lower() in {"python", "python3", "pytest"}):
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
        entries = [{"path": str(p), "write": p == root, "identity": _path_identity(p)}
                   for p in [root, *roots] if p == root or not p.is_relative_to(root)]
        # 所有授权目录共享检查时限，完整检查后才能授予 ACL；正常的大型运行库不按文件数拒绝。
        deadline = time.monotonic() + SCAN_TIMEOUT_SECONDS
        protections = []
        for entry in entries:
            protections.extend(_check_tree(Path(entry["path"]), write=entry["write"], deadline=deadline))
        self.name = "pa.execution." + uuid.uuid4().hex
        self.lock = FileLock(self.base / (self.name + ".lock"))
        self.path = self.base / (self.name + ".json")
        self.record = {"version": 2, "profile": self.name, "owner": self.api.identity(os.getpid()), "host": None,
                       "paths": entries, "protections": protections}
        self.sid = None
        self.closed = False
        try:
            self._save()
        except BaseException:
            self.lock.close()
            raise
        try:
            self.sid = self.api.sid(self.name, create=True)
            # 完整预检与设置不可被另一租约交错；同一敏感对象不允许重叠授权。
            with self.api.acl_writer():
                for entry in protections:
                    entry.update(self.api.protection_state(entry))
                self._save()
                for entry in entries:
                    self.api.acl(entry["path"], self.sid, write=entry["write"], identity=entry["identity"])
                for entry in protections:
                    self.api.acl(entry["path"], self.sid, deny=entry["deny"], inherit=entry["inherit"], identity=entry["identity"])
            self.environment = dict(environment)
            temporary = self.api.folder(self.sid) / "Temp"
            temporary.mkdir(exist_ok=True)
            self.environment.update(TEMP=str(temporary), TMP=str(temporary), PYTHONDONTWRITEBYTECODE="1")
        except BaseException:
            self.close()
            raise

    def _save(self):
        payload = json.dumps(self.record).encode("utf-8")
        if len(payload) > MAX_JOURNAL_BYTES:
            raise ValueError("沙箱恢复日志超过大小限制，未授权执行")
        temporary = self.path.with_suffix(".pending")
        with temporary.open("wb") as stream:
            stream.write(payload)
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
            with api.acl_writer():
                # 先撤去父级授权，再恢复原继承标志；始终保留其他主体的当前 ACL。
                for entry in [*record["paths"], *record.get("protections", [])]:
                    path = Path(entry["path"])
                    if path.exists():
                        api.acl(_directory(path), sid, revoke=True, identity=entry.get("identity"),
                                restore_protected=entry.get("original_protected"), restore_inherited=entry.get("inherited_aces", ()))
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
            if path.is_symlink() or path.stat().st_size > MAX_JOURNAL_BYTES:
                raise ValueError("沙箱清理记录无效，已停止执行")
            try:
                lock = FileLock(path.with_suffix(".lock"))
            except ValueError:
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if (record.get("version") not in {1, 2} or record.get("profile") != path.stem
                        or len(record.get("paths", [])) > 128 or len(record.get("protections", [])) > MAX_PROTECTIONS):
                    raise ValueError("沙箱清理记录版本或归属无效")
                if any(identity and api.identity(identity["pid"]) == identity for identity in [record.get("owner"), record.get("host")]):
                    raise ValueError("旧沙箱进程仍然存活，不能清理或重新授权")
                cls._cleanup(api, record)
                path.unlink()
            finally:
                lock.close()
