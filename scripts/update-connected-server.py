"""固定部署目录的一键更新：检查、备份、快进源码，仅在后端变化时重启单个服务。"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

ROOT = Path("/opt/private-agent/current")
PYTHON = Path("/opt/private-agent/venv/bin/python")
LAUNCHER = ROOT / "scripts/start-connected-server.py"
BRANCH = "dev/1.0.0"
ACCOUNT = "privateagent"
SERVICE = "private-agent"
SUPERVISOR = ["supervisorctl", "-c", "/etc/supervisord.conf"]
BACKUPS = Path("/opt/private-agent/code-update-backups")
SERVER_PACKAGES = ("src/personal_assistant/", "src/private_agent_core/")
MANUAL_FILES = {
    "src/personal_assistant/config.py", "src/personal_assistant/server_entry.py",
    "src/personal_assistant/core/models.py", "src/personal_assistant/core/settings.py",
}
CLIENT_SCRIPTS = {
    "scripts/build-client.cjs", "scripts/build-client.cmd",
    "scripts/build-remote-client.cjs", "scripts/build-remote-client.cmd",
    "scripts/build-remote-client.test.cjs", "scripts/verify-unified-client.py",
}


class UpdateRefused(RuntimeError):
    """更新条件不满足时，返回固定说明而不输出命令中的敏感信息。"""


def command(args: list[str], *, accepted: tuple[int, ...] = (0,), stdout_file: BinaryIO | None = None) -> str:
    env = os.environ.copy()
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", GIT_MERGE_AUTOEDIT="no")
    with subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                          stdout=stdout_file if stdout_file is not None else subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=sys.platform == "linux") as process:
        try:
            stdout, _ = process.communicate(timeout=45)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            # 同时终止 runuser 启动的 Git 子进程，避免超时后后台继续修改仓库。
            if sys.platform == "linux":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.communicate()
            if isinstance(exc, KeyboardInterrupt):
                raise
            raise UpdateRefused("COMMAND_TIMEOUT：操作超时；先核对 Git 和服务状态，不要直接重试") from None
    if process.returncode not in accepted:
        # Git 远程地址、凭据助手及服务错误正文可能包含秘密，不原样回显。
        raise UpdateRefused(f"COMMAND_FAILED：{Path(args[0]).name} 返回 {process.returncode}；请在服务器本机排查")
    return (stdout or b"").decode("utf-8", errors="strict")


def git(*args: str, accepted: tuple[int, ...] = (0,)) -> str:
    output = command(["runuser", "-u", ACCOUNT, "--", "git", "-C", str(ROOT), *args], accepted=accepted)
    return output if "-z" in args or args[:2] == ("cat-file", "blob") else output.strip()


def clean_head() -> str:
    if Path(git("rev-parse", "--show-toplevel")).resolve() != ROOT.resolve():
        raise UpdateRefused("WRONG_REPOSITORY：部署目录不是预期 Git 根目录")
    if git("branch", "--show-current") != BRANCH:
        raise UpdateRefused(f"WRONG_BRANCH：必须位于 {BRANCH}")
    git_dir = Path(git("rev-parse", "--absolute-git-dir"))
    if any((git_dir / name).exists() for name in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD", "sequencer", "index.lock")):
        raise UpdateRefused("GIT_OPERATION_PENDING：先完成或人工处理当前 Git 操作")
    if git("status", "--porcelain=v1", "--untracked-files=all"):
        raise UpdateRefused("DIRTY_WORKTREE：存在未提交或未跟踪文件；请运行 runuser -u privateagent -- git -C /opt/private-agent/current status --short --untracked-files=all 查看文件名；不会自动暂存、覆盖或清理")
    return git("rev-parse", "HEAD")


def manual_paths(paths: list[str]) -> list[str]:
    manual = []
    for path in paths:
        if path in MANUAL_FILES:
            manual.append(path)
        elif path.startswith(SERVER_PACKAGES) and path.endswith(".py"):
            continue
        elif path.startswith(("docs/", "tests/", "apps/desktop/", "src/private_agent_local/")) or path == "README.md" or path in CLIENT_SCRIPTS:
            continue
        else:
            # 依赖、数据库迁移、部署脚本及未知资源一律交给专项更新流程。
            manual.append(path)
    return manual


def changed_paths(before: str, target: str) -> list[str]:
    return [name for name in git("diff", "--name-only", "--no-renames", "-z", before, target).split("\0") if name]


def needs_restart(paths: list[str]) -> bool:
    return any(path.startswith(SERVER_PACKAGES) for path in paths)


def validate_target(target: str, paths: list[str]) -> None:
    # 检查整个目标树，避免客户端或文档目录中的链接在同步时覆盖仓库外文件。
    entries = {}
    for record in git("ls-tree", "-r", "-z", target).split("\0"):
        if not record:
            continue
        metadata, name = record.split("\t", 1)
        if not metadata.startswith(("100644 blob ", "100755 blob ")):
            raise UpdateRefused("UNSAFE_SOURCE_TREE：目标存在符号链接或子模块，需人工检查")
        entries[name] = metadata.split()[2]
    required = ("src/personal_assistant/__init__.py", "src/personal_assistant/server_entry.py", "src/private_agent_core/__init__.py")
    if any(name not in entries for name in required):
        raise UpdateRefused("SOURCE_ENTRY_MISSING：目标缺少后端或共享核心入口")
    for name in paths:
        if name not in entries or not name.startswith(SERVER_PACKAGES) or not name.endswith(".py"):
            continue
        if int(git("cat-file", "-s", entries[name])) > 4 * 1024 * 1024:
            raise UpdateRefused("SOURCE_TOO_LARGE：目标 Python 文件超过检查上限")
        try:
            ast.parse(git("cat-file", "blob", entries[name]), filename=name)
        except (SyntaxError, ValueError):
            raise UpdateRefused("SOURCE_SYNTAX_INVALID：目标 Python 语法检查失败：" + json.dumps(name, ensure_ascii=False)) from None


def source_check() -> None:
    raw = command(["runuser", "-u", ACCOUNT, "--", str(PYTHON), "-I", "-B", str(LAUNCHER), "--check"])
    try:
        report = json.loads(raw)
    except (ValueError, TypeError):
        raise UpdateRefused("SOURCE_CHECK_FAILED：启动入口检查结果无效") from None
    if not isinstance(report, dict) or report.get("status") != "SOURCE_ENTRY_OK" or not isinstance(report.get("package"), str) or Path(report["package"]).resolve() != (ROOT / "src/personal_assistant").resolve():
        raise UpdateRefused("SOURCE_CHECK_FAILED：未确认仓库源码入口")


def require_running_source() -> int:
    import pwd

    pid_text = command([*SUPERVISOR, "pid", SERVICE]).strip()
    if not pid_text.isdecimal() or int(pid_text) <= 1:
        raise UpdateRefused("SERVICE_NOT_RUNNING：先核对单个服务状态")
    proc = Path("/proc") / pid_text
    try:
        args = proc.joinpath("cmdline").read_bytes().rstrip(b"\0").split(b"\0")
        cwd, uid = proc.joinpath("cwd").resolve(), proc.stat().st_uid
    except FileNotFoundError:
        raise UpdateRefused("SERVICE_NOT_RUNNING：检查期间进程已退出") from None
    expected = [os.fsencode(PYTHON), b"-I", b"-B", os.fsencode(LAUNCHER)]
    if args != expected or cwd != ROOT.resolve() or uid != pwd.getpwnam(ACCOUNT).pw_uid:
        raise UpdateRefused("SOURCE_MIGRATION_REQUIRED：运行进程尚未使用约定的源码启动方式")
    status = command([*SUPERVISOR, "status", SERVICE], accepted=(0, 3))
    if not re.match(r"^private-agent\s+RUNNING\b", status):
        raise UpdateRefused("SERVICE_NOT_RUNNING：服务尚未进入 RUNNING")
    return int(pid_text)


def wait_running_source(*, timeout: float = 60, stable_seconds: float = 10) -> None:
    deadline = time.monotonic() + timeout
    previous_pid = None
    stable_since = None
    while True:
        try:
            pid = require_running_source()
        except UpdateRefused as exc:
            if not str(exc).startswith("SERVICE_NOT_RUNNING："):
                raise
            previous_pid = stable_since = None
        else:
            now = time.monotonic()
            if pid != previous_pid:
                previous_pid, stable_since = pid, now
            if stable_since is not None and now - stable_since >= stable_seconds:
                return
        if time.monotonic() >= deadline:
            raise UpdateRefused("START_TIMEOUT：未确认同一源码进程持续 RUNNING；请检查单个服务，不会自动回退代码或数据库")
        time.sleep(1)


def preflight(expected_target: str | None = None) -> tuple[str, str, list[str]]:
    before = clean_head()
    source_check()
    require_running_source()
    git("fetch", "--no-tags", "origin", f"refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")
    target = git("rev-parse", f"refs/remotes/origin/{BRANCH}")
    if expected_target is not None and target != expected_target:
        raise UpdateRefused("TARGET_CHANGED：远端提交与已核对目标不同，请重新 check")
    if git("merge-base", before, target) != before:
        raise UpdateRefused("NOT_FAST_FORWARD：本机有独有提交或分支已分叉，先在开发机整理共享历史")
    paths = changed_paths(before, target)
    if manual := manual_paths(paths):
        raise UpdateRefused("MANUAL_UPDATE_REQUIRED：以下变更需专项检查：" + json.dumps(manual, ensure_ascii=False))
    validate_target(target, paths)
    if needs_restart(paths):
        command(["runuser", "-u", ACCOUNT, "--", str(PYTHON), "-I", "-B", "-m", "pip", "check"])
    if clean_head() != before:
        raise UpdateRefused("CHECKOUT_CHANGED：检查期间工作区发生变化")
    return before, target, paths


def record_stage(directory: Path, stage: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(directory / "events.jsonl", flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(json.dumps({"time": datetime.now(UTC).isoformat(), "stage": stage}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def create_backup(before: str, target: str, restart: bool) -> Path:
    BACKUPS.mkdir(mode=0o700, parents=False, exist_ok=True)
    info = BACKUPS.lstat()
    if not stat.S_ISDIR(info.st_mode) or BACKUPS.resolve() != BACKUPS.absolute():
        raise UpdateRefused("UNSAFE_BACKUP_DIRECTORY：备份目录不能是符号链接")
    if sys.platform == "linux" and (info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077):
        raise UpdateRefused("UNSAFE_BACKUP_DIRECTORY：备份目录必须由 root 所有且权限为 0700")
    directory = Path(tempfile.mkdtemp(prefix=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + before[:12] + "-", dir=BACKUPS))
    print("BACKUP_DIR=" + str(directory), flush=True)
    record_stage(directory, "creating_source_backup")
    archive = directory / "source.tar"
    fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        # Git 仍以服务账号执行；只归档旧提交，不读取工作区环境、日志或数据库。
        command(["runuser", "-u", ACCOUNT, "--", "git", "-C", str(ROOT), "archive", "--format=tar", before], stdout_file=stream)
        stream.flush()
        os.fsync(stream.fileno())
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with (directory / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump({"before": before, "target": target, "restart_required": restart,
                   "source_archive_sha256": digest, "database_backup": False}, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    record_stage(directory, "backup_ready")
    return directory


def apply_update(before: str, target: str) -> str:
    if clean_head() != before:
        raise UpdateRefused("CHECKOUT_CHANGED：停服前提交已变化")
    require_running_source()
    if before == target:
        return "ALREADY_CURRENT"
    paths = changed_paths(before, target)
    if manual := manual_paths(paths):
        raise UpdateRefused("MANUAL_UPDATE_REQUIRED：以下变更需专项检查：" + json.dumps(manual, ensure_ascii=False))
    restart = needs_restart(paths)
    directory = create_backup(before, target, restart)
    if clean_head() != before:
        raise UpdateRefused("CHECKOUT_CHANGED：备份期间工作区变化，不会更新或停服")
    require_running_source()
    if restart:
        record_stage(directory, "stopping_service")
        command([*SUPERVISOR, "stop", SERVICE])
        status = command([*SUPERVISOR, "status", SERVICE], accepted=(0, 3))
        if not re.match(r"^private-agent\s+STOPPED\b", status):
            raise UpdateRefused("STOP_NOT_CONFIRMED：未确认 STOPPED，不会更新代码")
    # 停服后的失败保持现状，不擅自重置 Git 或自动回退数据库。
    if clean_head() != before:
        raise UpdateRefused("CHECKOUT_CHANGED：工作区发生变化；停止后续操作，请核对 Git 和单个服务状态")
    record_stage(directory, "fast_forwarding")
    git("merge", "--ff-only", "--no-edit", target)
    if clean_head() != target:
        raise UpdateRefused("UPDATE_NOT_VERIFIED：更新后提交或工作区不符；停止后续操作，请核对单个服务状态")
    source_check()
    if restart:
        record_stage(directory, "starting_service")
        command([*SUPERVISOR, "start", SERVICE])
        record_stage(directory, "verifying_process")
        wait_running_source()
    else:
        require_running_source()
    if clean_head() != target:
        raise UpdateRefused("UPDATE_NOT_VERIFIED：最终提交或工作区不符，请核对 Git 和单个服务状态")
    result = "PROCESS_RUNNING_REQUIRES_ACCEPTANCE" if restart else "CODE_SYNCED_NO_RESTART"
    record_stage(directory, result)
    return result


@contextmanager
def deployment_lock():
    import fcntl

    fd = os.open("/run/private-agent-code-update.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UpdateRefused("UPDATE_BUSY：另一个更新工具正在运行") from None
        yield
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("update", "check", "apply"), nargs="?", default="update",
                        help="默认 update 一次完成检查和更新；check 只检查；apply 锁定手工核对的 target")
    parser.add_argument("--target", help="apply 必填：check 输出的完整目标提交 SHA")
    args = parser.parse_args(argv)
    if (args.mode == "apply" and args.target is None) or (args.target is not None and not re.fullmatch(r"[0-9a-f]{40}", args.target)):
        parser.error("apply 需要 --target 和已核对的 40 位提交 SHA")
    try:
        if sys.platform != "linux" or os.geteuid() != 0:
            raise UpdateRefused("PLATFORM_REQUIRED：仅限指定 Linux 服务器的 root 运维会话")
        if Path(__file__).resolve().parent.parent != ROOT.resolve() or not PYTHON.is_file():
            raise UpdateRefused("LAYOUT_REQUIRED：仓库或虚拟环境位置与约定不符")
        with deployment_lock():
            before, target, paths = preflight(args.target)
            print(json.dumps({"before": before, "target": target, "paths": paths,
                              "restart_required": needs_restart(paths)}, ensure_ascii=False), flush=True)
            result = "CHECK_PASSED" if args.mode == "check" else apply_update(before, target)
            print(result, flush=True)
        return 0
    except UpdateRefused as exc:
        print(f"UPDATE_REFUSED: {exc}", file=sys.stderr)
    except (OSError, UnicodeError, KeyError) as exc:
        print(f"UPDATE_REFUSED: {type(exc).__name__}；请核对服务、权限及 Git 状态", file=sys.stderr)
    except KeyboardInterrupt:
        print("UPDATE_INTERRUPTED：请先核对 Git 和服务状态，不能假定仍在运行", file=sys.stderr)
        return 130
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
