"""在临时仓库和伪服务中验证更新边界，不加载生产配置或连接数据库。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = load_script("start-connected-server")
updater = load_script("update-connected-server")


@pytest.fixture
def source_tree(tmp_path):
    root = tmp_path / "checkout"
    package = root / "src/personal_assistant"
    package.mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "alembic").mkdir()
    (root / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "server_entry.py").write_text("def main():\n    print('ORIGINAL_ENTRY_CALLED')\n", encoding="utf-8")
    script = root / "scripts/start-connected-server.py"
    shutil.copyfile(ROOT / "scripts/start-connected-server.py", script)
    return root, package, script


def run_launcher(script, cwd, *args):
    return subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(script), *args], cwd=cwd,
                          capture_output=True, encoding="utf-8", timeout=15)


def test_source_check_does_not_import_package_or_read_environment(source_tree, tmp_path):
    root, package, script = source_tree
    (package / "__init__.py").write_text("raise RuntimeError('must-not-import')\n", encoding="utf-8")
    (root / ".env").write_text("this is not a valid environment file", encoding="utf-8")
    result = run_launcher(script, tmp_path, "--check")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["package"] == str(package)
    assert not list(root.rglob("__pycache__"))


def test_launch_delegates_original_entry_and_requires_original_workdir(source_tree, tmp_path):
    root, _, script = source_tree
    result = run_launcher(script, root)
    assert result.returncode == 0, result.stderr
    assert "ORIGINAL_ENTRY_CALLED" in result.stdout
    result = run_launcher(script, tmp_path)
    assert result.returncode == 1
    assert "ORIGINAL_ENTRY_CALLED" not in result.stdout


@pytest.mark.parametrize("relative", ["src/personal_assistant/__init__.py", "src/personal_assistant/server_entry.py", "alembic.ini"])
def test_missing_source_refuses_fallback_to_installed_package(source_tree, relative):
    root, _, script = source_tree
    (root / relative).unlink()
    result = run_launcher(script, root, "--check")
    assert result.returncode == 1
    assert "SOURCE_ENTRY_REFUSED" in result.stderr


def test_existing_import_prevents_switching_half_of_application(source_tree, monkeypatch):
    _, package, _ = source_tree
    monkeypatch.setitem(sys.modules, "personal_assistant.old_module", object())
    with pytest.raises(ValueError, match="已加载"):
        launcher.select_source(package)


def test_source_precedes_an_old_installed_copy(source_tree, tmp_path):
    root, package, script = source_tree
    old = tmp_path / "site-packages/personal_assistant"
    old.mkdir(parents=True)
    (old / "__init__.py").write_text("raise RuntimeError('old-package-used')\n", encoding="utf-8")
    code = "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')"
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(old.parent), str(script), "--check"],
                            cwd=root, capture_output=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["package"] == str(package)


def test_audit_detects_installed_only_patches_and_normalizes_line_endings(source_tree, tmp_path):
    _, package, _ = source_tree
    installed = tmp_path / "installed"
    shutil.copytree(package, installed)
    (installed / "server_entry.py").write_bytes((package / "server_entry.py").read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert launcher.audit_installed(package, installed)["differences"] == []
    (installed / "hotfix.py").write_text("private_value = 'not-for-report'\n", encoding="utf-8")
    (package / "new.py").write_text("", encoding="utf-8")
    report = launcher.audit_installed(package, installed)
    assert [entry["path"] for entry in report["differences"]] == ["hotfix.py", "new.py"]
    assert "not-for-report" not in json.dumps(report)
    assert report["status"] == "REVIEW_REQUIRED"


def test_audit_refuses_unreadable_walk_instead_of_reporting_a_match(source_tree, monkeypatch):
    _, package, _ = source_tree

    def unreadable(*args, **kwargs):
        kwargs["onerror"](PermissionError("denied"))

    monkeypatch.setattr(launcher.os, "walk", unreadable)
    with pytest.raises(PermissionError):
        launcher.code_hashes(package)


def test_audit_refuses_symlinks(source_tree, tmp_path):
    _, package, _ = source_tree
    link = package / "outside.py"
    target = tmp_path / "outside.py"
    target.write_text("", encoding="utf-8")
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("当前 Windows 环境不允许创建真实符号链接")
    with pytest.raises(ValueError, match="类型"):
        launcher.code_hashes(package)


def raw_git(root, *args):
    env = os.environ.copy()
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            encoding="utf-8", env=env, timeout=15, check=True)
    return result.stdout if "-z" in args or args[:2] == ("cat-file", "blob") else result.stdout.strip()


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    remote, repo = tmp_path / "remote.git", tmp_path / "server"
    remote.mkdir()
    repo.mkdir()
    raw_git(remote, "init", "--bare")
    raw_git(repo, "init", "-b", updater.BRANCH)
    raw_git(repo, "config", "user.name", "isolated-test")
    raw_git(repo, "config", "user.email", "test@example.invalid")
    raw_git(repo, "config", "core.autocrlf", "false")
    raw_git(repo, "remote", "add", "origin", str(remote))
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    for name in ("src/personal_assistant/__init__.py", "src/personal_assistant/server_entry.py", "src/private_agent_core/__init__.py"):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
    raw_git(repo, "add", ".")
    raw_git(repo, "commit", "-m", "initial")
    raw_git(repo, "push", "origin", updater.BRANCH)
    before = raw_git(repo, "rev-parse", "HEAD")
    developer = tmp_path / "developer"
    raw_git(tmp_path, "clone", "-b", updater.BRANCH, str(remote), str(developer))
    raw_git(developer, "config", "user.name", "isolated-test")
    raw_git(developer, "config", "user.email", "test@example.invalid")
    raw_git(developer, "config", "core.autocrlf", "false")
    events = []
    monkeypatch.setattr(updater, "ROOT", repo)
    monkeypatch.setattr(updater, "BACKUPS", tmp_path / "backups")
    monkeypatch.setattr(updater, "git", lambda *args, **kwargs: raw_git(repo, *args))
    monkeypatch.setattr(updater, "source_check", lambda: events.append("source-check"))
    monkeypatch.setattr(updater, "require_running_source", lambda: events.append("running-check") or 123)
    monkeypatch.setattr(updater, "wait_running_source", lambda: events.append("stable-check"))

    def supervisor(args, **kwargs):
        if args[:4] == ["runuser", "-u", updater.ACCOUNT, "--"]:
            if "archive" in args:
                subprocess.run(args[4:], stdout=kwargs["stdout_file"], stderr=subprocess.PIPE, timeout=15, check=True)
                events.append("source-backup")
                return ""
            assert args[-3:] == ["-m", "pip", "check"]
            events.append("dependencies-check")
            return ""
        assert args[:3] == updater.SUPERVISOR
        assert args[-1] == "private-agent"
        events.append(args[-2])
        return "private-agent STOPPED\n" if args[-2] == "status" else ""

    monkeypatch.setattr(updater, "command", supervisor)
    return repo, developer, before, events


def publish(developer, relative="src/personal_assistant/feature.py", content="value = 1\n"):
    path = developer / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    raw_git(developer, "add", "--", relative)
    raw_git(developer, "commit", "-m", "tested update")
    raw_git(developer, "push", "origin", updater.BRANCH)
    return raw_git(developer, "rev-parse", "HEAD")


def test_fast_forward_stops_before_checkout_then_starts_only_one_service(deployment):
    repo, developer, before, events = deployment
    target = publish(developer)
    checked_before, checked_target, paths = updater.preflight()
    assert (checked_before, checked_target) == (before, target)
    assert paths == ["src/personal_assistant/feature.py"]
    assert raw_git(repo, "rev-parse", "HEAD") == before
    assert "stop" not in events
    assert not updater.BACKUPS.exists()
    events.clear()
    assert updater.apply_update(before, target) == "PROCESS_RUNNING_REQUIRES_ACCEPTANCE"
    assert events == ["running-check", "source-backup", "running-check", "stop", "status", "source-check", "start", "stable-check"]
    assert raw_git(repo, "rev-parse", "HEAD") == target


@pytest.mark.parametrize("reason", ["untracked", "staged", "merge", "rebase", "wrong-branch", "diverged", "ahead"])
def test_unsafe_git_states_never_stop_service_or_overwrite_files(deployment, reason):
    repo, developer, before, events = deployment
    if reason != "ahead":
        publish(developer)
    if reason in {"untracked", "staged"}:
        (repo / "local.py").write_text("preserve me", encoding="utf-8")
        if reason == "staged":
            raw_git(repo, "add", "local.py")
    elif reason == "merge":
        (repo / ".git/MERGE_HEAD").write_text(before + "\n", encoding="ascii")
    elif reason == "rebase":
        (repo / ".git/rebase-merge").mkdir()
    elif reason == "wrong-branch":
        raw_git(repo, "switch", "-c", "other")
    else:
        (repo / "local.py").write_text("preserve me", encoding="utf-8")
        raw_git(repo, "add", "local.py")
        raw_git(repo, "commit", "-m", "server-only")
    original = raw_git(repo, "rev-parse", "HEAD")
    with pytest.raises(updater.UpdateRefused):
        updater.preflight()
    assert "stop" not in events
    assert raw_git(repo, "rev-parse", "HEAD") == original
    if (repo / "local.py").exists():
        assert (repo / "local.py").read_text() == "preserve me"


@pytest.mark.parametrize("relative", ["pyproject.toml", "uv.lock", "requirements.txt", "alembic/versions/new.py", "scripts/update-connected-server.py", "src/personal_assistant/config.py", "src/personal_assistant/server_entry.py", "src/personal_assistant/core/models.py", "src/personal_assistant/core/settings.py", "src/personal_assistant/schema.json", "src/private_agent_core/schema.json"])
def test_dependency_migration_startup_and_unknown_changes_require_manual_update(deployment, relative):
    repo, developer, before, events = deployment
    publish(developer, relative)
    with pytest.raises(updater.UpdateRefused, match="MANUAL_UPDATE_REQUIRED"):
        updater.preflight()
    assert raw_git(repo, "rev-parse", "HEAD") == before
    assert "stop" not in events


def test_reviewed_target_change_is_rejected(deployment):
    _, developer, before, events = deployment
    publish(developer)
    with pytest.raises(updater.UpdateRefused, match="TARGET_CHANGED"):
        updater.preflight(before)
    assert "stop" not in events


def test_no_changes_does_not_restart_service(deployment):
    _, _, before, events = deployment
    assert updater.apply_update(before, before) == "ALREADY_CURRENT"
    assert "stop" not in events


def test_failure_after_stop_does_not_start_service_or_reset_history(deployment, monkeypatch):
    repo, developer, before, events = deployment
    target = publish(developer)
    updater.preflight()

    def fail_check():
        raise updater.UpdateRefused("SOURCE_CHECK_FAILED")

    monkeypatch.setattr(updater, "source_check", fail_check)
    with pytest.raises(updater.UpdateRefused, match="SOURCE_CHECK_FAILED"):
        updater.apply_update(before, target)
    assert "stop" in events and "start" not in events
    assert raw_git(repo, "rev-parse", "HEAD") == target


def test_stop_failure_never_updates_checkout(deployment, monkeypatch):
    repo, developer, before, _ = deployment
    target = publish(developer)
    updater.preflight()
    original = updater.command
    monkeypatch.setattr(updater, "command", lambda args, **kwargs: "private-agent RUNNING pid 123\n" if args[:3] == updater.SUPERVISOR else original(args, **kwargs))
    with pytest.raises(updater.UpdateRefused, match="STOP_NOT_CONFIRMED"):
        updater.apply_update(before, target)
    assert raw_git(repo, "rev-parse", "HEAD") == before


def test_dirty_worktree_after_check_prevents_stop(deployment):
    repo, developer, before, events = deployment
    target = publish(developer)
    updater.preflight()
    (repo / "uncommitted.py").write_text("preserve", encoding="utf-8")
    with pytest.raises(updater.UpdateRefused, match="DIRTY_WORKTREE"):
        updater.apply_update(before, target)
    assert "stop" not in events


def test_command_errors_do_not_disclose_stderr_or_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "ROOT", tmp_path)
    with pytest.raises(updater.UpdateRefused) as error:
        updater.command([sys.executable, "-I", "-c", "import sys; sys.stderr.write('secret-token'); sys.exit(2)"])
    assert "secret-token" not in str(error.value)


def test_apply_requires_a_reviewed_full_commit_before_any_work():
    with pytest.raises(SystemExit) as error:
        updater.main(["apply", "--target", "HEAD"])
    assert error.value.code == 2


@pytest.mark.parametrize("issue", [None, "old-entry", "wrong-directory", "root-user", "not-running", "missing-pid", "exited"])
def test_running_process_must_match_source_entry_and_service_account(monkeypatch, issue):
    expected = [os.fsencode(updater.PYTHON), b"-I", b"-B", os.fsencode(updater.LAUNCHER)]
    args = expected if issue != "old-entry" else [expected[0], b"-m", b"personal_assistant.server_entry"]
    cwd = updater.ROOT if issue != "wrong-directory" else updater.ROOT.parent
    uid = 1001 if issue != "root-user" else 0
    def read_cmdline():
        if issue == "exited":
            raise FileNotFoundError()
        return b"\0".join(args) + b"\0"

    proc = SimpleNamespace(
        joinpath=lambda name: SimpleNamespace(read_bytes=read_cmdline, resolve=lambda: cwd.resolve()),
        stat=lambda: SimpleNamespace(st_uid=uid),
    )

    class FakeProcRoot:
        def __truediv__(self, pid):
            assert pid == "123"
            return proc

    def supervisor(args, **kwargs):
        assert args[-1] == "private-agent"
        if args[-2] == "pid":
            return "0" if issue == "missing-pid" else "123"
        return "private-agent FATAL" if issue == "not-running" else "private-agent RUNNING pid 123"

    monkeypatch.setattr(updater, "Path", lambda value: FakeProcRoot())
    monkeypatch.setattr(updater, "command", supervisor)
    monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace(getpwnam=lambda name: SimpleNamespace(pw_uid=1001)))
    if issue is None:
        updater.require_running_source()
    else:
        with pytest.raises(updater.UpdateRefused):
            updater.require_running_source()


@pytest.mark.parametrize("output", ["not-json", "null", '{"status":"SOURCE_ENTRY_OK","package":null}', '{"status":"SOURCE_ENTRY_OK","package":"/wrong"}'])
def test_source_probe_rejects_invalid_or_wrong_origin_report(monkeypatch, output):
    monkeypatch.setattr(updater, "command", lambda *args, **kwargs: output)
    with pytest.raises(updater.UpdateRefused, match="SOURCE_CHECK_FAILED"):
        updater.source_check()


@pytest.mark.parametrize("interrupted", [False, True])
def test_timeout_or_interrupt_kills_linux_command_group(monkeypatch, interrupted):
    killed = []

    class PendingCommand:
        pid = 987
        returncode = -9
        calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                if interrupted:
                    raise KeyboardInterrupt()
                raise subprocess.TimeoutExpired(["test"], timeout)
            return b"", b""

    monkeypatch.setattr(updater.subprocess, "Popen", lambda *args, **kwargs: PendingCommand())
    monkeypatch.setattr(updater.sys, "platform", "linux")
    monkeypatch.setattr(updater.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(updater.os, "killpg", lambda pid, sig: killed.append(pid), raising=False)
    with pytest.raises(KeyboardInterrupt if interrupted else updater.UpdateRefused):
        updater.command(["test"])
    assert killed == [987]


@pytest.mark.parametrize("relative", [
    "scripts/build-client.cjs", "scripts/build-remote-client.cjs", "scripts/build-remote-client.test.cjs",
    "scripts/verify-unified-client.py", "apps/desktop/src/App.vue", "src/private_agent_local/app.py",
    "docs/update.md", "tests/unit/test_example.py", "README.md",
])
def test_client_or_documentation_changes_sync_without_stopping_service(deployment, relative):
    repo, developer, before, events = deployment
    target = publish(developer, relative)
    assert updater.preflight() == (before, target, [relative])
    assert "dependencies-check" not in events
    assert updater.apply_update(before, target) == "CODE_SYNCED_NO_RESTART"
    assert "stop" not in events and "start" not in events and "stable-check" not in events
    assert raw_git(repo, "rev-parse", "HEAD") == target


def test_shared_core_update_requires_dependencies_and_restart(deployment):
    _, developer, before, events = deployment
    target = publish(developer, "src/private_agent_core/runtime.py")
    updater.preflight()
    assert "dependencies-check" in events
    assert updater.apply_update(before, target) == "PROCESS_RUNNING_REQUIRES_ACCEPTANCE"
    assert events.index("source-backup") < events.index("stop") < events.index("start") < events.index("stable-check")


def test_backup_contains_old_commit_and_hash_but_not_ignored_environment(deployment):
    repo, developer, before, _ = deployment
    (repo / ".env").write_text("isolated fixture, never archive working files", encoding="utf-8")
    target = publish(developer)
    updater.preflight()
    updater.apply_update(before, target)
    directories = list(updater.BACKUPS.iterdir())
    assert len(directories) == 1
    directory = directories[0]
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["before"] == before and manifest["target"] == target
    assert manifest["database_backup"] is False
    assert manifest["source_archive_sha256"] == hashlib.sha256((directory / "source.tar").read_bytes()).hexdigest()
    with tarfile.open(directory / "source.tar") as archive:
        names = archive.getnames()
        assert ".env" not in names and "src/personal_assistant/feature.py" not in names
        expected = subprocess.run(["git", "-C", str(repo), "show", f"{before}:README.md"],
                                  capture_output=True, timeout=15, check=True).stdout
        assert archive.extractfile("README.md").read() == expected
    stages = [json.loads(line)["stage"] for line in (directory / "events.jsonl").read_text().splitlines()]
    assert stages == ["creating_source_backup", "backup_ready", "stopping_service", "fast_forwarding",
                      "starting_service", "verifying_process", "PROCESS_RUNNING_REQUIRES_ACCEPTANCE"]


def test_backup_failure_prevents_stop_and_checkout(deployment, monkeypatch):
    repo, developer, before, events = deployment
    target = publish(developer)
    updater.preflight()
    original = updater.command

    def disk_full(args, **kwargs):
        if "archive" in args:
            kwargs["stdout_file"].write(b"partial archive")
            raise OSError("isolated disk full")
        return original(args, **kwargs)

    monkeypatch.setattr(updater, "command", disk_full)
    with pytest.raises(OSError):
        updater.apply_update(before, target)
    assert "stop" not in events and raw_git(repo, "rev-parse", "HEAD") == before
    directory = next(updater.BACKUPS.iterdir())
    assert not (directory / "manifest.json").exists()
    assert "backup_ready" not in (directory / "events.jsonl").read_text()


def test_change_during_backup_prevents_stop(deployment, monkeypatch):
    repo, developer, before, events = deployment
    target = publish(developer)
    updater.preflight()
    original = updater.create_backup

    def concurrent_edit(*args):
        backup = original(*args)
        (repo / "local-note.txt").write_text("preserve", encoding="utf-8")
        return backup

    monkeypatch.setattr(updater, "create_backup", concurrent_edit)
    with pytest.raises(updater.UpdateRefused, match="DIRTY_WORKTREE"):
        updater.apply_update(before, target)
    assert "stop" not in events and raw_git(repo, "rev-parse", "HEAD") == before


@pytest.mark.parametrize("content", ["def broken(\n", "    unexpected_indent = 1\n"])
def test_invalid_target_python_is_rejected_before_backup_or_stop(deployment, content):
    repo, developer, before, events = deployment
    publish(developer, content=content)
    with pytest.raises(updater.UpdateRefused, match="SOURCE_SYNTAX_INVALID"):
        updater.preflight()
    assert raw_git(repo, "rev-parse", "HEAD") == before
    assert "stop" not in events and not updater.BACKUPS.exists()


def test_removing_package_entry_is_rejected_before_stop(deployment):
    _, developer, _, events = deployment
    raw_git(developer, "rm", "src/private_agent_core/__init__.py")
    raw_git(developer, "commit", "-m", "remove entry")
    raw_git(developer, "push", "origin", updater.BRANCH)
    with pytest.raises(updater.UpdateRefused, match="SOURCE_ENTRY_MISSING"):
        updater.preflight()
    assert "stop" not in events


@pytest.mark.parametrize("path", ["src/personal_assistant/link.py", "docs/link", "apps/desktop/link"])
def test_symlink_git_tree_is_rejected_even_for_client_only_changes(deployment, path):
    _, developer, _, events = deployment
    blob = raw_git(developer, "hash-object", "-w", "README.md")
    raw_git(developer, "update-index", "--add", "--cacheinfo", f"120000,{blob},{path}")
    raw_git(developer, "commit", "-m", "unsafe link fixture")
    raw_git(developer, "push", "origin", updater.BRANCH)
    with pytest.raises(updater.UpdateRefused, match="UNSAFE_SOURCE_TREE"):
        updater.preflight()
    assert "stop" not in events


def test_dependency_failure_prevents_backup_and_stop(deployment, monkeypatch):
    repo, developer, before, events = deployment
    publish(developer)
    original = updater.command

    def inconsistent_dependencies(args, **kwargs):
        if args[-3:] == ["-m", "pip", "check"]:
            raise updater.UpdateRefused("COMMAND_FAILED：依赖检查失败")
        return original(args, **kwargs)

    monkeypatch.setattr(updater, "command", inconsistent_dependencies)
    with pytest.raises(updater.UpdateRefused, match="COMMAND_FAILED"):
        updater.preflight()
    assert "stop" not in events and raw_git(repo, "rev-parse", "HEAD") == before
    assert not updater.BACKUPS.exists()


def test_start_failure_keeps_target_and_records_last_stage(deployment, monkeypatch):
    repo, developer, before, events = deployment
    target = publish(developer)
    updater.preflight()

    def startup_failed():
        raise updater.UpdateRefused("START_TIMEOUT：isolated fixture")

    monkeypatch.setattr(updater, "wait_running_source", startup_failed)
    with pytest.raises(updater.UpdateRefused, match="START_TIMEOUT"):
        updater.apply_update(before, target)
    assert raw_git(repo, "rev-parse", "HEAD") == target
    assert events.count("start") == 1
    stages = (next(updater.BACKUPS.iterdir()) / "events.jsonl").read_text().splitlines()
    assert json.loads(stages[-1])["stage"] == "verifying_process"


def fake_clock(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(updater.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(updater.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    return clock


def test_startup_wait_requires_continuous_same_pid(monkeypatch):
    clock = fake_clock(monkeypatch)
    sequence = iter([None, 11, 11, 12, 12, 12, 12])

    def process():
        pid = next(sequence)
        if pid is None:
            raise updater.UpdateRefused("SERVICE_NOT_RUNNING：尚在启动")
        return pid

    monkeypatch.setattr(updater, "require_running_source", process)
    updater.wait_running_source(timeout=8, stable_seconds=3)
    assert clock[0] == 6


def test_restarting_process_never_passes_readiness(monkeypatch):
    clock = fake_clock(monkeypatch)
    monkeypatch.setattr(updater, "require_running_source", lambda: int(clock[0]) + 100)
    with pytest.raises(updater.UpdateRefused, match="START_TIMEOUT"):
        updater.wait_running_source(timeout=5, stable_seconds=3)
    assert clock[0] == 5


def test_wrong_runtime_fails_readiness_without_retries(monkeypatch):
    clock = fake_clock(monkeypatch)

    def wrong_runtime():
        raise updater.UpdateRefused("SOURCE_MIGRATION_REQUIRED：入口不符")

    monkeypatch.setattr(updater, "require_running_source", wrong_runtime)
    with pytest.raises(updater.UpdateRefused, match="SOURCE_MIGRATION_REQUIRED"):
        updater.wait_running_source()
    assert clock[0] == 0


@pytest.mark.parametrize("args, applies", [([], True), (["update"], True), (["check"], False), (["apply", "--target", "b" * 40], True)])
def test_cli_single_command_and_legacy_modes(monkeypatch, capsys, args, applies):
    calls = []
    monkeypatch.setattr(updater.sys, "platform", "linux")
    monkeypatch.setattr(updater.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(updater, "ROOT", ROOT)
    monkeypatch.setattr(updater, "PYTHON", Path(sys.executable))
    monkeypatch.setattr(updater, "deployment_lock", nullcontext)
    monkeypatch.setattr(updater, "preflight", lambda target: ("a" * 40, "b" * 40, ["docs/readme.md"]))
    monkeypatch.setattr(updater, "apply_update", lambda *values: calls.append(values) or "CODE_SYNCED_NO_RESTART")
    assert updater.main(args) == 0
    assert bool(calls) is applies
    output = capsys.readouterr().out
    assert json.loads(output.splitlines()[0])["restart_required"] is False
    assert ("CODE_SYNCED_NO_RESTART" if applies else "CHECK_PASSED") in output


def test_command_streams_binary_backup_without_decoding(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "ROOT", tmp_path)
    target = tmp_path / "bytes.bin"
    with target.open("wb") as stream:
        assert updater.command([sys.executable, "-I", "-c", "import sys; sys.stdout.buffer.write(bytes([255,0,128]))"], stdout_file=stream) == ""
    assert target.read_bytes() == bytes([255, 0, 128])
