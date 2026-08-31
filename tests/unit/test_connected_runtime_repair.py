"""在临时安装目录验证补丁、停机门禁及回滚，不接触真实服务与凭据。"""

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("runtime_repair", ROOT / "scripts/repair-connected-runtime.py")
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)


@pytest.fixture
def original_server_proxy():
    result = subprocess.run(
        ["git", "-C", str(ROOT), "show", "599f97f:src/personal_assistant/api/routes_desktop_model.py"],
        capture_output=True, check=True,
    )
    assert repair.digest(result.stdout) == "6cc944005325654c85a5c0c3ded180bcd1ea37f88b9ac1db3c674f17d47383b5"
    return result.stdout


@pytest.fixture
def layout(tmp_path, monkeypatch):
    source, package, backup = tmp_path / "source", tmp_path / "installed", tmp_path / "backup"
    for relative in repair.FILES:
        src, dest = source / relative, package / relative
        src.parent.mkdir(parents=True, exist_ok=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes((ROOT / "src/personal_assistant" / relative).read_bytes())
        if relative in {"config.py", "main_api.py"}:
            result = subprocess.run(
                ["git", "-C", str(ROOT), "show", f"debcd81:src/personal_assistant/{relative}"],
                capture_output=True, check=True,
            )
            dest.write_bytes(result.stdout)
    unrelated = package / "server_entry.py"
    unrelated.write_bytes("# 服务器既有部署修复\n".encode())
    monkeypatch.setattr(repair, "require_stopped", lambda: None)
    return source, package, backup, unrelated


def test_round_trip_preserves_unrelated_files_and_is_idempotent(layout):
    source, package, backup, unrelated = layout
    original = {name: repair.read_regular(package / name) for name in repair.FILES}
    assert repair.apply(source, package, backup) == "APPLIED_AND_VERIFIED"
    for record in repair.check(source, package):
        assert repair.digest(record["before"]) == repair.digest(record["after"])
    assert unrelated.read_bytes() == "# 服务器既有部署修复\n".encode()
    assert repair.apply(source, package, backup) == "ALREADY_APPLIED"
    assert repair.rollback(package, backup) == "ROLLED_BACK_AND_VERIFIED"
    assert {name: repair.read_regular(package / name) for name in repair.FILES} == original
    assert unrelated.read_bytes() == "# 服务器既有部署修复\n".encode()


@pytest.mark.parametrize("location,relative", [("source", "config.py"), ("package", "main_api.py"), ("package", "api/routes_admin_logs.py")])
def test_unknown_changes_are_rejected_before_backup_or_write(layout, location, relative):
    source, package, backup, _ = layout
    root = source if location == "source" else package
    (root / relative).write_bytes("# 尚未核对的改动\n".encode())
    original = {name: repair.read_regular(package / name) for name in repair.FILES}
    with pytest.raises(ValueError):
        repair.apply(source, package, backup)
    assert not backup.exists()
    assert {name: repair.read_regular(package / name) for name in repair.FILES} == original


def test_original_server_proxy_is_corrected_only_in_installed_copy(layout, original_server_proxy):
    source, package, backup, _ = layout
    path = source / "api/routes_desktop_model.py"
    old = original_server_proxy
    path.write_bytes(old)
    assert repair.digest(old) == "6cc944005325654c85a5c0c3ded180bcd1ea37f88b9ac1db3c674f17d47383b5"
    repair.apply(source, package, backup)
    assert path.read_bytes() == old
    assert repair.digest((package / "api/routes_desktop_model.py").read_bytes()) == "e978968f313921c32de9c2a15b29505a222e4985830dd29866848f60109aaf55"


@pytest.mark.parametrize("field_fixed", [False, True])
def test_known_installed_proxy_upgrades_to_current_source_and_rolls_back(layout, original_server_proxy, field_fixed):
    source, package, backup, _ = layout
    for relative in repair.FILES:
        (package / relative).write_bytes((source / relative).read_bytes())
    old = original_server_proxy
    if field_fixed:
        old = old.replace(b"profile.reasoning_efforts or []", b"profile.reasoning_efforts_json or []")
        assert repair.digest(old) == "e978968f313921c32de9c2a15b29505a222e4985830dd29866848f60109aaf55"
    target = package / "api/routes_desktop_model.py"
    target.write_bytes(old)
    original = {name: repair.read_regular(package / name) for name in repair.FILES}
    current_source = (source / "api/routes_desktop_model.py").read_bytes()

    assert repair.apply(source, package, backup) == "APPLIED_AND_VERIFIED"
    assert target.read_bytes() == current_source
    assert repair.digest(current_source) != repair.digest(old)
    assert repair.apply(source, package, backup) == "ALREADY_APPLIED"
    assert repair.rollback(package, backup) == "ROLLED_BACK_AND_VERIFIED"
    assert {name: repair.read_regular(package / name) for name in repair.FILES} == original


@pytest.mark.parametrize("location", ["source", "package"])
def test_unknown_proxy_changes_are_rejected_before_backup_or_write(layout, location):
    source, package, backup, _ = layout
    root = source if location == "source" else package
    relative = "api/routes_desktop_model.py"
    changed = (source / relative).read_bytes() + "\n# 尚未核对的代理修改\n".encode()
    (root / relative).write_bytes(changed)
    original = {name: repair.read_regular(package / name) for name in repair.FILES}

    with pytest.raises(ValueError, match="api/routes_desktop_model.py"):
        repair.apply(source, package, backup)
    assert not backup.exists()
    assert {name: repair.read_regular(package / name) for name in repair.FILES} == original


def test_proxy_upgrade_does_not_overwrite_previous_backup(layout, original_server_proxy):
    source, package, backup, _ = layout
    path = source / "api/routes_desktop_model.py"
    current_source = path.read_bytes()
    path.write_bytes(original_server_proxy)
    repair.apply(source, package, backup)
    previous_backup = {entry.name: entry.read_bytes() for entry in backup.iterdir()}
    original = {name: repair.read_regular(package / name) for name in repair.FILES}
    path.write_bytes(current_source)

    with pytest.raises(FileExistsError):
        repair.apply(source, package, backup)
    assert {name: repair.read_regular(package / name) for name in repair.FILES} == original
    assert {entry.name: entry.read_bytes() for entry in backup.iterdir()} == previous_backup


def test_partial_write_failure_can_be_rolled_back(layout, monkeypatch):
    source, package, backup, _ = layout
    original = {name: repair.read_regular(package / name) for name in repair.FILES}
    actual = repair.write_atomic
    calls = 0

    def fail_second(path, data, metadata):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated disk failure")
        actual(path, data, metadata)

    monkeypatch.setattr(repair, "write_atomic", fail_second)
    with pytest.raises(OSError):
        repair.apply(source, package, backup)
    assert (backup / "manifest.json").is_file()
    monkeypatch.setattr(repair, "write_atomic", actual)
    repair.rollback(package, backup)
    assert {name: repair.read_regular(package / name) for name in repair.FILES} == original


def test_rollback_refuses_later_changes(layout):
    source, package, backup, _ = layout
    repair.apply(source, package, backup)
    changed = package / "core/admin_logs.py"
    changed.write_bytes("# 必须保留的后续修复\n".encode())
    with pytest.raises(ValueError, match="新改动"):
        repair.rollback(package, backup)
    assert changed.read_bytes() == "# 必须保留的后续修复\n".encode()


def test_existing_backup_and_tampered_manifest_are_rejected(layout):
    source, package, backup, _ = layout
    repair.apply(source, package, backup)
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "../outside.py"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="固定文件"):
        repair.rollback(package, backup)
    (package / "config.py").write_bytes((backup / "0.before").read_bytes())
    with pytest.raises(FileExistsError):
        repair.apply(source, package, backup)


@pytest.fixture
def cli_layout(layout, monkeypatch):
    source, package, backup, _ = layout
    monkeypatch.setattr(repair, "SOURCE", source)
    monkeypatch.setattr(repair, "PACKAGE", package)
    monkeypatch.setattr(repair, "BACKUP", backup)
    monkeypatch.setattr(repair.sys, "platform", "linux")
    monkeypatch.setattr(repair.os, "geteuid", lambda: 0, raising=False)
    return layout


def test_cli_default_backup_remains_compatible(cli_layout, monkeypatch, capsys):
    _, package, backup, _ = cli_layout
    original = {name: repair.read_regular(package / name) for name in repair.FILES}
    for action, expected in (("apply", "APPLIED_AND_VERIFIED"), ("rollback", "ROLLED_BACK_AND_VERIFIED")):
        monkeypatch.setattr(repair.sys, "argv", ["repair-connected-runtime.py", action])
        repair.main()
        assert json.loads(capsys.readouterr().out) == {"status": expected, "backup": str(backup)}
    assert {name: repair.read_regular(package / name) for name in repair.FILES} == original


def test_cli_new_backup_preserves_previous_patch_and_rolls_back(cli_layout, original_server_proxy, monkeypatch, capsys):
    source, package, backup, _ = cli_layout
    source_proxy = source / "api/routes_desktop_model.py"
    current_source = source_proxy.read_bytes()
    source_proxy.write_bytes(original_server_proxy)
    repair.apply(source, package, backup)
    previous_backup = {entry.name: entry.read_bytes() for entry in backup.iterdir()}
    previous_package = {name: repair.read_regular(package / name) for name in repair.FILES}
    source_proxy.write_bytes(current_source)
    new_backup = backup.with_name("rollback-connected-runtime-1.0.4")

    for action, expected in (("check", "CHECK_PASSED"), ("apply", "APPLIED_AND_VERIFIED"),
                             ("apply", "ALREADY_APPLIED"), ("rollback", "ROLLED_BACK_AND_VERIFIED")):
        monkeypatch.setattr(repair.sys, "argv", ["repair-connected-runtime.py", action, "--backup-dir", str(new_backup)])
        repair.main()
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == expected
        if action == "check":
            assert not new_backup.exists()
        else:
            assert result["backup"] == str(new_backup)
        if action == "apply":
            assert (package / "api/routes_desktop_model.py").read_bytes() == current_source
        assert {entry.name: entry.read_bytes() for entry in backup.iterdir()} == previous_backup
    assert {name: repair.read_regular(package / name) for name in repair.FILES} == previous_package


@pytest.mark.parametrize("location", ["relative", "root", "outside", "nested", "source", "installed", "file"])
def test_cli_rejects_unsafe_backup_before_writing(cli_layout, location, monkeypatch, capsys):
    source, package, backup, _ = cli_layout
    paths = {
        "relative": Path("backup-relative"), "root": backup.parent,
        "outside": backup.parent.parent / "outside-backup", "nested": backup / "nested",
        "source": source, "installed": package, "file": backup.with_name("backup-file"),
    }
    if location == "file":
        paths[location].write_text("必须保留的文件", encoding="utf-8")
    original = {name: repair.read_regular(package / name) for name in repair.FILES}
    monkeypatch.setattr(repair.sys, "argv", ["repair-connected-runtime.py", "apply", "--backup-dir", str(paths[location])])
    with pytest.raises(SystemExit) as error:
        repair.main()
    assert error.value.code == 1
    assert "STOP:" in capsys.readouterr().err
    assert not backup.exists()
    assert {name: repair.read_regular(package / name) for name in repair.FILES} == original
    if location == "file":
        assert paths[location].read_text(encoding="utf-8") == "必须保留的文件"


def test_cli_rejects_backup_ancestor_of_source(cli_layout, monkeypatch, capsys):
    source, _, _, _ = cli_layout
    monkeypatch.setattr(repair, "SOURCE", source / "src" / "personal_assistant")
    monkeypatch.setattr(repair.sys, "argv", ["repair-connected-runtime.py", "check", "--backup-dir", str(source)])
    with pytest.raises(SystemExit) as error:
        repair.main()
    assert error.value.code == 1
    assert "不能与源码或安装目录重叠" in capsys.readouterr().err


def test_cli_rejects_link_backup(cli_layout, monkeypatch, capsys):
    source, _, backup, _ = cli_layout
    alias = backup.with_name("backup-link")
    try:
        alias.symlink_to(source, target_is_directory=True)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows 当前用户无创建符号链接权限")
        raise
    monkeypatch.setattr(repair.sys, "argv", ["repair-connected-runtime.py", "check", "--backup-dir", str(alias)])
    with pytest.raises(SystemExit) as error:
        repair.main()
    assert error.value.code == 1
    assert "拒绝链接" in capsys.readouterr().err
    assert not backup.exists()


@pytest.mark.parametrize("status,allowed", [("STOPPED", True), ("RUNNING", False), ("FATAL", False), ("EXITED", False)])
def test_service_must_be_explicitly_stopped(monkeypatch, status, allowed):
    def query(*args, **kwargs):
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert "PYTHONINSPECT" not in kwargs["env"]
        return SimpleNamespace(stdout=f"private-agent {status} fixture\n".encode(), returncode=3)

    monkeypatch.setenv("PYTHONINSPECT", "0")
    monkeypatch.setattr(repair.subprocess, "run", query)
    if allowed:
        repair.require_stopped()
    else:
        with pytest.raises(ValueError, match="STOPPED"):
            repair.require_stopped()
