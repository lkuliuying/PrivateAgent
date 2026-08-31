"""固定部署目录的保守更新工具：检查、停服、快进源码、启动单个服务。"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path("/opt/private-agent/current")
PYTHON = Path("/opt/private-agent/venv/bin/python")
LAUNCHER = ROOT / "scripts/start-connected-server.py"
BRANCH = "dev/1.0.0"
ACCOUNT = "privateagent"
SERVICE = "private-agent"
SUPERVISOR = ["supervisorctl", "-c", "/etc/supervisord.conf"]


class UpdateRefused(RuntimeError):
    """更新条件不满足时，返回固定说明而不输出命令中的敏感信息。"""


def command(args: list[str], *, accepted: tuple[int, ...] = (0,)) -> str:
    env = os.environ.copy()
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", GIT_MERGE_AUTOEDIT="no")
    with subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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
    return stdout.decode("utf-8", errors="strict")


def git(*args: str, accepted: tuple[int, ...] = (0,)) -> str:
    output = command(["runuser", "-u", ACCOUNT, "--", "git", "-C", str(ROOT), *args], accepted=accepted)
    return output if "-z" in args else output.strip()


def clean_head() -> str:
    if Path(git("rev-parse", "--show-toplevel")).resolve() != ROOT.resolve():
        raise UpdateRefused("WRONG_REPOSITORY：部署目录不是预期 Git 根目录")
    if git("branch", "--show-current") != BRANCH:
        raise UpdateRefused(f"WRONG_BRANCH：必须位于 {BRANCH}")
    git_dir = Path(git("rev-parse", "--absolute-git-dir"))
    if any((git_dir / name).exists() for name in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD", "sequencer", "index.lock")):
        raise UpdateRefused("GIT_OPERATION_PENDING：先完成或人工处理当前 Git 操作")
    if git("status", "--porcelain=v1", "--untracked-files=all"):
        raise UpdateRefused("DIRTY_WORKTREE：存在未提交或未跟踪文件，不会自动暂存、覆盖或清理")
    return git("rev-parse", "HEAD")


def manual_paths(paths: list[str]) -> list[str]:
    manual = []
    for path in paths:
        if path in {"src/personal_assistant/config.py", "src/personal_assistant/server_entry.py"}:
            manual.append(path)
        elif path.startswith("src/personal_assistant/") and path.endswith(".py"):
            continue
        elif path.startswith(("docs/", "tests/", "apps/desktop/", "src/private_agent_local/")) or path == "README.md":
            continue
        else:
            # 依赖、数据库迁移、部署脚本及未知资源一律交给专项更新流程。
            manual.append(path)
    return manual


def source_check() -> None:
    raw = command(["runuser", "-u", ACCOUNT, "--", str(PYTHON), "-I", "-B", str(LAUNCHER), "--check"])
    try:
        report = json.loads(raw)
    except (ValueError, TypeError):
        raise UpdateRefused("SOURCE_CHECK_FAILED：启动入口检查结果无效") from None
    if not isinstance(report, dict) or report.get("status") != "SOURCE_ENTRY_OK" or not isinstance(report.get("package"), str) or Path(report["package"]).resolve() != (ROOT / "src/personal_assistant").resolve():
        raise UpdateRefused("SOURCE_CHECK_FAILED：未确认仓库源码入口")


def require_running_source() -> None:
    import pwd

    pid_text = command([*SUPERVISOR, "pid", SERVICE]).strip()
    if not pid_text.isdecimal() or int(pid_text) <= 1:
        raise UpdateRefused("SERVICE_NOT_RUNNING：先核对单个服务状态")
    proc = Path("/proc") / pid_text
    args = proc.joinpath("cmdline").read_bytes().rstrip(b"\0").split(b"\0")
    expected = [os.fsencode(PYTHON), b"-I", b"-B", os.fsencode(LAUNCHER)]
    if args != expected or proc.joinpath("cwd").resolve() != ROOT.resolve() or proc.stat().st_uid != pwd.getpwnam(ACCOUNT).pw_uid:
        raise UpdateRefused("SOURCE_MIGRATION_REQUIRED：运行进程尚未使用约定的源码启动方式")
    status = command([*SUPERVISOR, "status", SERVICE])
    if not re.match(r"^private-agent\s+RUNNING\b", status):
        raise UpdateRefused("SERVICE_NOT_RUNNING：服务尚未进入 RUNNING")


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
    paths = [name for name in git("diff", "--name-only", "--no-renames", "-z", before, target).split("\0") if name]
    if manual := manual_paths(paths):
        raise UpdateRefused("MANUAL_UPDATE_REQUIRED：以下变更需专项检查：" + json.dumps(manual, ensure_ascii=False))
    # Git 支持将普通文件替换为链接，例行更新不得将源码重定向到外部路径。
    for record in git("ls-tree", "-r", "-z", target, "--", "src/personal_assistant").split("\0"):
        if record and not record.startswith(("100644 blob ", "100755 blob ")):
            raise UpdateRefused("UNSAFE_SOURCE_TREE：目标源码存在符号链接或子模块")
    if clean_head() != before:
        raise UpdateRefused("CHECKOUT_CHANGED：检查期间工作区发生变化")
    return before, target, paths


def apply_update(before: str, target: str) -> str:
    if clean_head() != before:
        raise UpdateRefused("CHECKOUT_CHANGED：停服前提交已变化")
    require_running_source()
    if before == target:
        return "ALREADY_CURRENT"
    command([*SUPERVISOR, "stop", SERVICE])
    status = command([*SUPERVISOR, "status", SERVICE], accepted=(0, 3))
    if not re.match(r"^private-agent\s+STOPPED\b", status):
        raise UpdateRefused("STOP_NOT_CONFIRMED：未确认 STOPPED，不会更新代码")
    # 停服后的失败保持现状，不擅自重置 Git 或自动回退数据库。
    if clean_head() != before:
        raise UpdateRefused("CHECKOUT_CHANGED：停服后工作区发生变化，服务保持停止")
    git("merge", "--ff-only", "--no-edit", target)
    if clean_head() != target:
        raise UpdateRefused("UPDATE_NOT_VERIFIED：更新后提交或工作区不符，服务保持停止")
    source_check()
    command([*SUPERVISOR, "start", SERVICE])
    require_running_source()
    return "PROCESS_RUNNING_REQUIRES_ACCEPTANCE"


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
    parser.add_argument("mode", choices=("check", "apply"))
    parser.add_argument("--target", help="apply 必填：check 输出的完整目标提交 SHA")
    args = parser.parse_args(argv)
    if args.mode == "apply" and (args.target is None or not re.fullmatch(r"[0-9a-f]{40}", args.target)):
        parser.error("apply 需要 --target 和已核对的 40 位提交 SHA")
    try:
        if sys.platform != "linux" or os.geteuid() != 0:
            raise UpdateRefused("PLATFORM_REQUIRED：仅限指定 Linux 服务器的 root 运维会话")
        if Path(__file__).resolve().parent.parent != ROOT.resolve() or not PYTHON.is_file():
            raise UpdateRefused("LAYOUT_REQUIRED：仓库或虚拟环境位置与约定不符")
        with deployment_lock():
            before, target, paths = preflight(args.target)
            print(json.dumps({"before": before, "target": target, "paths": paths}, ensure_ascii=False), flush=True)
            result = apply_update(before, target) if args.mode == "apply" else "CHECK_PASSED"
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
