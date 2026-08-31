"""在临时仓库和伪服务中验证更新边界，不加载生产配置或连接数据库。"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
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
    return result.stdout if "-z" in args else result.stdout.strip()


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
    raw_git(repo, "add", "README.md")
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
    monkeypatch.setattr(updater, "git", lambda *args, **kwargs: raw_git(repo, *args))
    monkeypatch.setattr(updater, "source_check", lambda: events.append("source-check"))
    monkeypatch.setattr(updater, "require_running_source", lambda: events.append("running-check"))

    def supervisor(args, **kwargs):
        assert args[:3] == updater.SUPERVISOR
        assert args[-1] == "private-agent"
        events.append(args[-2])
        return "private-agent STOPPED\n" if args[-2] == "status" else ""

    monkeypatch.setattr(updater, "command", supervisor)
    return repo, developer, before, events


def publish(developer, relative="src/personal_assistant/feature.py"):
    path = developer / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("value = 1\n", encoding="utf-8")
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
    events.clear()
    assert updater.apply_update(before, target) == "PROCESS_RUNNING_REQUIRES_ACCEPTANCE"
    assert events == ["running-check", "stop", "status", "source-check", "start", "running-check"]
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


@pytest.mark.parametrize("relative", ["pyproject.toml", "uv.lock", "requirements.txt", "alembic/versions/new.py", "scripts/update-connected-server.py", "src/personal_assistant/config.py", "src/personal_assistant/server_entry.py", "src/personal_assistant/schema.json"])
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
    monkeypatch.setattr(updater, "command", lambda *args, **kwargs: "private-agent RUNNING pid 123\n")
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


@pytest.mark.parametrize("issue", [None, "old-entry", "wrong-directory", "root-user", "not-running", "missing-pid"])
def test_running_process_must_match_source_entry_and_service_account(monkeypatch, issue):
    expected = [os.fsencode(updater.PYTHON), b"-I", b"-B", os.fsencode(updater.LAUNCHER)]
    args = expected if issue != "old-entry" else [expected[0], b"-m", b"personal_assistant.server_entry"]
    cwd = updater.ROOT if issue != "wrong-directory" else updater.ROOT.parent
    uid = 1001 if issue != "root-user" else 0
    proc = SimpleNamespace(
        joinpath=lambda name: SimpleNamespace(read_bytes=lambda: b"\0".join(args) + b"\0", resolve=lambda: cwd.resolve()),
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
