"""使用合成文件验证 AppContainer 敏感对象拒绝、控制目录只读和授权回收。"""
import asyncio
import ctypes as c
import hashlib
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from ctypes import wintypes as w
from pathlib import Path

import pytest

from private_agent_local import files, windows_sandbox
from private_agent_local.executor import run_command
from private_agent_local.windows_sandbox import (
    DENY_ALL,
    DENY_PARENT,
    DENY_WRITE,
    SandboxLease,
    WindowsSecurity,
    _check_tree,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.name != "nt", reason="仅验证 Windows AppContainer 原生边界")]


def make_project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return root


def write_fixture(root, relative, value="synthetic-value"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


async def run_probe(root, state, source):
    write_fixture(root, "sandbox_probe.py", source)
    result = await run_command(root, [sys._base_executable, "sandbox_probe.py"], sandbox_directory=state)
    assert result["returncode"] == 0, result["stderr"]
    assert not list(state.glob("*.json"))
    return json.loads(result["stdout"])


def acl_entries(path, *, ordered=False):
    api = WindowsSecurity()
    acl, descriptor = c.c_void_p(), c.c_void_p()
    with api.acl_target(path) as handle:
        error = api.security.GetSecurityInfo(handle, 1, 4, None, None, c.byref(acl), None, c.byref(descriptor))
        assert error == 0
        try:
            entries = []
            for index in range(int.from_bytes(c.string_at(acl, 8)[4:6], "little")):
                ace = c.c_void_p()
                assert api.security.GetAce(acl, index, c.byref(ace))
                size = int.from_bytes(c.string_at(ace, 4)[2:4], "little")
                entries.append(c.string_at(ace, size))
            return entries if ordered else sorted(entries)
        finally:
            api.kernel.LocalFree(descriptor)


def assert_acl_unchanged(before):
    def describe(ace):
        return (ace[0], ace[1], hex(int.from_bytes(ace[4:8], "little")), hashlib.sha256(ace[8:]).hexdigest()[:8])
    differences = {}
    for path, expected in before.items():
        actual = acl_entries(path)
        if actual != expected:
            differences[str(path)] = {"added": [describe(ace) for ace in actual if ace not in expected],
                                      "removed": [describe(ace) for ace in expected if ace not in actual],
                                      "counts": [len(expected), len(actual)]}
    assert not differences, differences


@contextmanager
def fixture_sid(value="S-1-5-21-123456-654321-999999-31337"):
    api, sid = WindowsSecurity(), c.c_void_p()
    api.security.ConvertStringSidToSidW.argtypes = [w.LPCWSTR, c.POINTER(c.c_void_p)]
    assert api.security.ConvertStringSidToSidW(value, c.byref(sid))
    try:
        yield api, sid
    finally:
        api.kernel.LocalFree(sid)


def inheritance_state(path):
    api = WindowsSecurity()
    with api.acl_target(path) as handle, api.descriptor(handle) as (_, descriptor):
        return api.inheritance_protected(descriptor)


def add_fixture_ace(path, sid, *, mask=0x1301BF, flags=0):
    api = WindowsSecurity()
    sid_bytes = c.string_at(sid, 8 + 4 * c.string_at(sid, 2)[1])
    addition = bytes((0, flags)) + (8 + len(sid_bytes)).to_bytes(2, "little") + mask.to_bytes(4, "little") + sid_bytes
    with api.acl_target(path) as handle, api.descriptor(handle) as (previous, _):
        entries = [addition, *api.entries(previous)]
        size, revision = 8 + sum(map(len, entries)), c.string_at(previous, 1)[0]
        updated = c.create_string_buffer(size)
        assert api.security.InitializeAcl(updated, size, revision)
        for ace in entries:
            assert api.security.AddAce(updated, revision, 0xFFFFFFFF, ace, len(ace))
        assert api.security.SetSecurityInfo(handle, 1, 4, None, None, updated, None) == 0


async def test_scan_classifies_existing_objects_and_ancestors_without_reading_contents(tmp_path, monkeypatch):
    root = make_project(tmp_path)
    secret = write_fixture(root, "nested/.env.local")
    control = write_fixture(root, ".git/objects/example")
    write_fixture(root, "ordinary.txt")
    monkeypatch.setattr(Path, "read_bytes", lambda *args: pytest.fail("安全扫描不能读取文件正文"))
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: pytest.fail("安全扫描不能读取文件正文"))
    policies = {item["path"]: item for item in _check_tree(root, write=True)}
    assert policies[str(secret)]["deny"] == DENY_ALL
    assert policies[str(control)]["deny"] == DENY_WRITE
    assert policies[str(root)]["deny"] == DENY_PARENT
    assert not policies[str(root)]["inherit"]
    assert str(root / "ordinary.txt") not in policies
    assert str(root / ".env.future") not in policies


async def test_sensitive_objects_cannot_be_read_written_deleted_or_renamed(tmp_path):
    root = make_project(tmp_path)
    names = [".env", "nested/.env.local", "keys/client.pem", "keys/client.key", ".ssh/id_ed25519", ".npmrc"]
    for name in names:
        write_fixture(root, name)
    results = await run_probe(root, tmp_path / "leases", f"""
import json
from pathlib import Path
results = {{}}
for name in {names!r}:
    path = Path(name)
    for action, operation in [('read', path.read_bytes), ('write', lambda: path.write_text('changed')), ('delete', path.unlink), ('rename', lambda: path.rename(str(path) + '.moved'))]:
        try:
            operation()
            results[name + ':' + action] = 'allowed'
        except PermissionError:
            results[name + ':' + action] = 'denied'
Path('ordinary.txt').write_text('allowed')
print(json.dumps(results))
""")
    assert len(results) == len(names) * 4 and set(results.values()) == {"denied"}
    assert (root / "ordinary.txt").read_text() == "allowed"
    for name in names:
        assert (root / name).read_text() == "synthetic-value"
        (root / name).write_text("owner-can-write")


async def test_control_directories_are_readable_but_immutable_including_new_children(tmp_path):
    root = make_project(tmp_path)
    names = [".git", ".codex", ".agents"]
    for name in names:
        write_fixture(root, name + "/nested/config.txt")
    results = await run_probe(root, tmp_path / "leases", f"""
import json
from pathlib import Path
results = {{}}
for name in {names!r}:
    directory = Path(name)
    path = directory / 'nested/config.txt'
    results[name + ':read'] = path.read_text()
    operations = [('write', lambda: path.write_text('changed')), ('delete', path.unlink), ('new', lambda: (directory / 'new.txt').write_text('changed')), ('mkdir', lambda: (directory / 'new').mkdir()), ('rename', lambda: directory.rename(name + '.moved'))]
    for action, operation in operations:
        try:
            operation()
            results[name + ':' + action] = 'allowed'
        except PermissionError:
            results[name + ':' + action] = 'denied'
Path('ordinary').mkdir()
Path('ordinary/file.txt').write_text('allowed')
Path('ordinary/file.txt').unlink()
Path('ordinary').rmdir()
print(json.dumps(results))
""")
    for name in names:
        assert results.pop(name + ":read") == "synthetic-value"
    assert set(results.values()) == {"denied"}


async def test_protected_ancestor_cannot_be_deleted_or_moved(tmp_path):
    root = make_project(tmp_path)
    write_fixture(root, "nested/deeper/.env")
    results = await run_probe(root, tmp_path / "leases", """
import json, shutil
from pathlib import Path
results = {}
for name, operation in [('rename', lambda: Path('nested').rename('moved')), ('delete', lambda: shutil.rmtree('nested'))]:
    try:
        operation()
        results[name] = 'allowed'
    except PermissionError:
        results[name] = 'denied'
print(json.dumps(results))
""")
    assert results == {"rename": "denied", "delete": "denied"}
    assert (root / "nested/deeper/.env").read_text() == "synthetic-value"


async def test_conflicting_application_package_allow_rejects_before_execution(tmp_path):
    root = make_project(tmp_path)
    control = write_fixture(root, ".git/nested/config.txt")
    api, sid = WindowsSecurity(), c.c_void_p()
    api.security.ConvertStringSidToSidW.argtypes = [w.LPCWSTR, c.POINTER(c.c_void_p)]
    assert api.security.ConvertStringSidToSidW("S-1-15-2-1", c.byref(sid))
    try:
        api.acl(control, sid, write=True, inherit=False)
        before = acl_entries(control)
        _, env = files.prepare_process([os.environ["COMSPEC"]])
        state = tmp_path / "leases"
        with pytest.raises(ValueError, match="宽泛应用包授权"):
            await SandboxLease.prepare(root, [os.environ["COMSPEC"]], env, directory=state)
        assert not list(state.glob("*.json"))
        assert control.read_text() == "synthetic-value"
        assert acl_entries(control) == before
    finally:
        api.acl(control, sid, revoke=True)
        api.kernel.LocalFree(sid)


@pytest.mark.parametrize("principal", ["S-1-15-2-1", "S-1-15-2-2"])
async def test_inherit_only_application_package_allow_rejects_before_execution(tmp_path, principal):
    root = make_project(tmp_path)
    write_fixture(root, ".env")
    with fixture_sid(principal) as (api, sid):
        try:
            add_fixture_ace(root, sid, mask=0x10000000, flags=11)
            before = {path: acl_entries(path) for path in (root, root / ".env")}
            _, env = files.prepare_process([os.environ["COMSPEC"]])
            state = tmp_path / "leases"
            with pytest.raises(ValueError, match="宽泛应用包授权"):
                await SandboxLease.prepare(root, [os.environ["COMSPEC"]], env, directory=state)
            assert not list(state.glob("*.json"))
            assert_acl_unchanged(before)
        finally:
            api.acl(root, sid, revoke=True)


@pytest.mark.parametrize("kind", [5, 9, 11])
async def test_unknown_allow_ace_type_rejects_before_any_grant(tmp_path, monkeypatch, kind):
    root = make_project(tmp_path)
    write_fixture(root, ".env")
    original = WindowsSecurity.entries
    calls = []

    def unknown_entry(self, acl):
        entries = original(self, acl)
        return [bytes((kind, 0, 4, 0)), *entries]

    monkeypatch.setattr(WindowsSecurity, "entries", unknown_entry)
    monkeypatch.setattr(WindowsSecurity, "acl", lambda *args, **kwargs: calls.append(kwargs))
    _, env = files.prepare_process([os.environ["COMSPEC"]])
    with pytest.raises(ValueError, match="无法安全判定的 ACL 类型"):
        await SandboxLease.prepare(root, [os.environ["COMSPEC"]], env, directory=tmp_path / "leases")
    assert all(call.get("revoke") for call in calls)


async def test_cleanup_restores_inheritance_and_preserves_new_unrelated_explicit_ace(tmp_path):
    root = make_project(tmp_path)
    secret = write_fixture(root, ".env")
    control = write_fixture(root, ".git/config")
    with fixture_sid() as (api, initial_sid), fixture_sid("S-1-5-21-123456-654321-999999-31338") as (_, later_sid):
        api.acl(control, initial_sid, inherit=False, restore_protected=True)
        targets = [root, secret, control, control.parent]
        before = {path: acl_entries(path) for path in targets}
        flags_before = {path: inheritance_state(path) for path in targets}
        assert flags_before[control] and not flags_before[secret]
        _, env = files.prepare_process([os.environ["COMSPEC"]])
        lease = await SandboxLease.prepare(root, [os.environ["COMSPEC"]], env, directory=tmp_path / "leases")
        try:
            assert all(inheritance_state(path) for path in targets)
            api.acl(secret, later_sid, write=True, inherit=False)
        finally:
            lease.close()
        later_bytes = c.string_at(later_sid, 8 + 4 * c.string_at(later_sid, 2)[1])
        later_entries = [ace for ace in acl_entries(secret) if ace[8:] == later_bytes]
        assert len(later_entries) == 1 and not later_entries[0][1] & 16
        before[secret] = sorted([*before[secret], *later_entries])
        assert_acl_unchanged(before)
        assert {path: inheritance_state(path) for path in targets} == flags_before
        api.acl(secret, later_sid, revoke=True)
        api.acl(control, initial_sid, revoke=True, restore_protected=False)


async def test_overlapping_sensitive_lease_rejects_and_first_boundary_remains_enforced(tmp_path, monkeypatch):
    root = make_project(tmp_path)
    write_fixture(root, ".env")
    _, env = files.prepare_process([sys._base_executable])
    first_state, second_state = tmp_path / "first-leases", tmp_path / "second-leases"
    first = await SandboxLease.prepare(root, [sys._base_executable], env, directory=first_state)
    try:
        with pytest.raises(ValueError, match="重叠沙箱"):
            await SandboxLease.prepare(root, [sys._base_executable], env, directory=second_state)
        assert not list(second_state.glob("*.json"))

        async def existing_lease(*args, **kwargs):
            return first

        monkeypatch.setattr(SandboxLease, "prepare", existing_lease)
        result = await run_probe(root, first_state, """
import json
from pathlib import Path
try:
    Path('.env').read_text()
    result = 'allowed'
except PermissionError:
    result = 'denied'
Path('ordinary.txt').write_text('allowed')
print(json.dumps({'secret': result}))
""")
        assert result == {"secret": "denied"}
        assert (root / "ordinary.txt").read_text() == "allowed"
    finally:
        first.close()


@pytest.mark.parametrize("inherited_write,explicit_mask", [(False, 0x1200A9), (True, 0x1200A9), (False, 0x1301BF)])
async def test_mergeable_explicit_and_inherited_aces_reject_without_changing_permissions(tmp_path, inherited_write, explicit_mask):
    root = make_project(tmp_path)
    secret = write_fixture(root, ".env")
    with fixture_sid() as (api, sid):
        sid_bytes = c.string_at(sid, 8 + 4 * c.string_at(sid, 2)[1])
        try:
            api.acl(root, sid, write=inherited_write)
            add_fixture_ace(secret, sid, mask=explicit_mask)
            original = [ace for ace in acl_entries(secret) if ace[8:] == sid_bytes]
            assert sorted(ace[1] for ace in original) == [0, 16]
            before = {path: acl_entries(path) for path in (root, secret)}
            _, env = files.prepare_process([os.environ["COMSPEC"]])
            state = tmp_path / "leases"
            with pytest.raises(ValueError, match="可能合并"):
                await SandboxLease.prepare(root, [os.environ["COMSPEC"]], env, directory=state)
            assert not list(state.glob("*.json"))
            assert_acl_unchanged(before)
        finally:
            api.acl(root, sid, revoke=True)
            api.acl(secret, sid, revoke=True)


async def test_cleanup_reinherits_current_parent_rules_without_old_explicit_copy(tmp_path):
    root = make_project(tmp_path)
    secret = write_fixture(root, ".env")
    with fixture_sid() as (api, sid):
        sid_bytes = c.string_at(sid, 8 + 4 * c.string_at(sid, 2)[1])
        try:
            api.acl(root, sid)
            _, env = files.prepare_process([os.environ["COMSPEC"]])
            lease = await SandboxLease.prepare(root, [os.environ["COMSPEC"]], env, directory=tmp_path / "leases")
            try:
                api.acl(root, sid, write=True)
            finally:
                lease.close()
            restored = [ace for ace in acl_entries(secret) if ace[8:] == sid_bytes]
            assert [(ace[1], int.from_bytes(ace[4:8], "little")) for ace in restored] == [(16, 0x1301BF)]
        finally:
            api.acl(root, sid, revoke=True)


async def test_acl_control_changes_are_denied_to_sandbox_owner(tmp_path):
    root = make_project(tmp_path)
    write_fixture(root, ".agents/config.txt")
    results = await run_probe(root, tmp_path / "leases", """
import ctypes as c, json
from ctypes import wintypes as w
api = c.WinDLL('advapi32', use_last_error=True)
api.GetNamedSecurityInfoW.argtypes = [w.LPCWSTR,c.c_int,w.DWORD,c.c_void_p,c.c_void_p,c.POINTER(c.c_void_p),c.c_void_p,c.POINTER(c.c_void_p)]
api.SetNamedSecurityInfoW.argtypes = [w.LPCWSTR,c.c_int,w.DWORD,c.c_void_p,c.c_void_p,c.c_void_p,c.c_void_p]
acl, descriptor = c.c_void_p(), c.c_void_p()
assert api.GetNamedSecurityInfoW('.agents/config.txt',1,4,None,None,c.byref(acl),None,c.byref(descriptor)) == 0
try:
    error = api.SetNamedSecurityInfoW('.agents/config.txt',1,4,None,None,acl,None)
finally:
    c.windll.kernel32.LocalFree.argtypes = [c.c_void_p]
    c.windll.kernel32.LocalFree(descriptor)
print(json.dumps({'set_dacl_error': error}))
""")
    assert results["set_dacl_error"] == 5


async def test_partial_protection_failure_rolls_back_only_lease_sid(tmp_path, monkeypatch):
    root = make_project(tmp_path)
    secret = write_fixture(root, ".env")
    control = write_fixture(root, ".agents/config.txt")
    targets = [root, secret, control, control.parent]
    before = {path: acl_entries(path) for path in targets}
    original = WindowsSecurity.acl
    failed = False

    def fail_once(self, path, sid, **options):
        nonlocal failed
        if not failed and options.get("deny") and Path(path) == secret:
            failed = True
            raise OSError("fixture deny failure")
        return original(self, path, sid, **options)

    monkeypatch.setattr(WindowsSecurity, "acl", fail_once)
    _, env = files.prepare_process([os.environ["COMSPEC"]])
    state = tmp_path / "leases"
    with pytest.raises(OSError, match="fixture deny failure"):
        await SandboxLease.prepare(root, [os.environ["COMSPEC"]], env, directory=state)
    assert failed and not list(state.glob("*.json"))
    assert_acl_unchanged(before)


async def test_changed_object_identity_refuses_acl_mutation(tmp_path):
    path = write_fixture(tmp_path, "file.txt")
    expected = windows_sandbox._path_identity(path)
    path.rename(tmp_path / "original.txt")
    write_fixture(tmp_path, "file.txt", "replacement")
    with pytest.raises(ValueError, match="身份发生变化"):
        with WindowsSecurity().acl_target(path, expected):
            pytest.fail("对象已更换，不能获得 ACL 修改句柄")


async def test_sensitive_allow_masks_stay_restricted_after_parent_write_grant(tmp_path):
    root = make_project(tmp_path)
    secret = write_fixture(root, ".env")
    control = write_fixture(root, ".git/config")
    _, env = files.prepare_process([os.environ["COMSPEC"]])
    lease = await SandboxLease.prepare(root, [os.environ["COMSPEC"]], env, directory=tmp_path / "leases")
    try:
        sid = c.string_at(lease.sid, 8 + 4 * c.string_at(lease.sid, 2)[1])
        for path, mask in [(secret, DENY_ALL), (control, DENY_WRITE)]:
            found = [(entry[0], entry[1], int.from_bytes(entry[4:8], "little"))
                     for entry in acl_entries(path) if entry[8:] == sid]
            assert all(kind != 0 or flags & 8 or rights & mask == 0 for kind, flags, rights in found), found
    finally:
        lease.close()


async def test_process_uses_the_exact_lease_appcontainer_identity(tmp_path, monkeypatch):
    root = make_project(tmp_path)
    write_fixture(root, ".env")
    expected = []
    original = SandboxLease.bind

    def bind(self, pid):
        expected.append(c.string_at(self.sid, 8 + 4 * c.string_at(self.sid, 2)[1]).hex())
        original(self, pid)

    monkeypatch.setattr(SandboxLease, "bind", bind)
    result = await run_probe(root, tmp_path / "leases", """
import ctypes as c, json
from ctypes import wintypes as w
k, a = c.WinDLL('kernel32'), c.WinDLL('advapi32')
k.GetCurrentProcess.restype = w.HANDLE
a.OpenProcessToken.argtypes = [w.HANDLE,w.DWORD,c.POINTER(w.HANDLE)]
a.GetTokenInformation.argtypes = [w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.POINTER(w.DWORD)]
t, needed = w.HANDLE(), w.DWORD()
buffer = c.create_string_buffer(1024)
assert a.OpenProcessToken(k.GetCurrentProcess(),8,c.byref(t))
assert a.GetTokenInformation(t,31,buffer,len(buffer),c.byref(needed))
sid = c.c_void_p.from_buffer(buffer)
from pathlib import Path
try:
    Path('.env').read_text()
    result = 'allowed'
except PermissionError:
    result = 'denied'
print(json.dumps({'sid': c.string_at(sid, 8 + 4 * c.string_at(sid, 2)[1]).hex(), 'read': result}))
k.CloseHandle.argtypes = [w.HANDLE]
k.CloseHandle(t)
""")
    assert result["sid"] == expected[0]
    assert result["read"] == 'denied'


async def test_crashed_sensitive_lease_recovers_acl_and_inheritance(tmp_path):
    root = make_project(tmp_path)
    secret = write_fixture(root, ".env")
    control = write_fixture(root, ".git/config")
    targets = [root, secret, control, control.parent]
    before = {path: acl_entries(path) for path in targets}
    state = tmp_path / "leases"
    source = Path(__file__).resolve().parents[2] / "src"
    code = (
        f"import sys,os; sys.path.insert(0,{str(source)!r}); from pathlib import Path; "
        "from private_agent_local import files; from private_agent_local.windows_sandbox import SandboxLease; "
        f"SandboxLease(Path({str(root)!r}), [os.environ['COMSPEC']], files.prepare_process([os.environ['COMSPEC']])[1], directory=Path({str(state)!r})); os._exit(23)"
    )
    _, env = files.prepare_process([sys.executable])
    child = await asyncio.create_subprocess_exec(sys.executable, "-B", "-c", code, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    output, error = await child.communicate()
    assert child.returncode == 23, (output, error)
    assert len(list(state.glob("*.json"))) == 1
    await asyncio.to_thread(SandboxLease.recover, state)
    assert not list(state.glob("*.json"))
    assert_acl_unchanged(before)
