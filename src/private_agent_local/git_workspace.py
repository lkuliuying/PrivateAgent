"""仅在已授权项目根目录内读取和切换本地 Git 分支。"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import files

MAX_GIT_OUTPUT = 128_000


def _git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command, environment = files.prepare_process([
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.pager=cat",
        "-c",
        f"core.hooksPath={os.devnull}",
        *arguments,
    ])
    try:
        result = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError("Git 操作超时，未改变当前分支") from error
    if len(result.stdout) > MAX_GIT_OUTPUT or len(result.stderr) > MAX_GIT_OUTPUT:
        raise ValueError("Git 输出超出限制，未继续操作")
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "Git 操作失败"
        raise ValueError(message[:1000])
    return result


def inspect(root: Path) -> dict:
    """返回项目根目录自己的本地分支；父目录仓库不算当前项目仓库。"""
    try:
        top = _git(root, "rev-parse", "--show-toplevel", check=False)
    except ValueError:
        return {"is_git": False, "current_branch": None, "head_sha": None, "dirty": False, "branches": []}
    if top.returncode != 0:
        return {"is_git": False, "current_branch": None, "head_sha": None, "dirty": False, "branches": []}
    try:
        repository_root = Path(top.stdout.strip()).resolve(strict=True)
    except (OSError, ValueError):
        return {"is_git": False, "current_branch": None, "head_sha": None, "dirty": False, "branches": []}
    if repository_root != root:
        return {"is_git": False, "current_branch": None, "head_sha": None, "dirty": False, "branches": []}

    current_result = _git(root, "branch", "--show-current", check=False)
    current = current_result.stdout.strip() if current_result.returncode == 0 else ""
    head_result = _git(root, "rev-parse", "--verify", "HEAD", check=False)
    head_sha = head_result.stdout.strip() if head_result.returncode == 0 else None
    dirty_result = _git(root, "status", "--porcelain=v1", "--untracked-files=normal")
    refs = _git(
        root,
        "for-each-ref",
        "--sort=refname",
        "--format=%(refname:short)%09%(objectname)",
        "refs/heads",
    )
    branches = []
    for line in refs.stdout.splitlines():
        name, separator, sha = line.partition("\t")
        if name:
            branches.append({"name": name, "head_sha": sha if separator else None, "current": name == current})
    return {
        "is_git": True,
        "current_branch": current or None,
        "head_sha": head_sha,
        "dirty": bool(dirty_result.stdout),
        "branches": branches,
    }


def switch(root: Path, branch_name: str, before: dict | None = None) -> dict:
    before = before or inspect(root)
    if not before["is_git"]:
        raise ValueError("所选目录本身不是 Git 仓库")
    available = {item["name"] for item in before["branches"]}
    if branch_name not in available:
        raise ValueError("只能切换到当前项目已存在的本地 Git 分支")
    if before["current_branch"] == branch_name:
        return before
    if before["dirty"]:
        raise ValueError("当前分支存在未提交改动，为避免覆盖用户工作，未执行分支切换")
    _git(root, "switch", "--no-guess", branch_name)
    after = inspect(root)
    if after["current_branch"] != branch_name:
        raise ValueError("Git 未切换到所选分支，请检查仓库状态")
    return after
