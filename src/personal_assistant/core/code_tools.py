"""代码工作区只读工具：文件搜索、内容 grep、读取片段、git 状态/diff。

纯函数：接收 db，抛领域异常（ProjectNotFound / PermissionError_ / ValueError）。
供 api/routes_projects.py（用户直接调用）与 core/tools.py（LLM 触发的工具）复用。
不在此处写文件、不跑写命令——M1 严格只读。

git 通过 asyncio subprocess 调用，只读子命令（status/diff），带超时。
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import shlex
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from .permissions import PermissionError_
from .projects import (
    ProjectService,
    language_for_ext,
    resolve_within,
)

# 读取单文件大小上限
MAX_READ_FILE_BYTES = 5 * 1024 * 1024  # 5MB
DEFAULT_READ_LINES = 2000
GIT_TIMEOUT = 15.0
GIT_DIFF_MAX_CHARS = 20000  # diff 输出截断上限
PATCH_MAX_CHARS = 500000
PATCH_DIFF_MAX_CHARS = 200000
COMMAND_TIMEOUT = 120.0
COMMAND_OUTPUT_MAX_CHARS = 30000

WHITELISTED_COMMAND_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("py", "-m", "pytest"),
    ("uv", "run", "pytest"),
    ("npm", "test"),
    ("npm", "run", "test"),
    ("npm", "run", "build"),
    ("cargo", "check"),
    ("cargo", "test"),
)


async def _run_git(
    root: str, args: list[str], timeout: float = GIT_TIMEOUT
) -> tuple[int, str, str]:
    """在 root 目录运行 git 只读子命令，返回 (returncode, stdout, stderr)。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            root,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise RuntimeError("未找到 git 可执行文件") from e
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise TimeoutError(f"git 命令超时（{timeout}s）")
    return (
        proc.returncode or 0,
        stdout_b.decode("utf-8", errors="ignore"),
        stderr_b.decode("utf-8", errors="ignore"),
    )


async def search_files(
    db: AsyncSession, project_id: int, query: str, limit: int = 50
) -> dict:
    """按文件名/相对路径搜索已索引文件。"""
    if not query:
        raise ValueError("query 不能为空")
    files = await ProjectService(db).search_name(project_id, query, limit=limit)
    return {
        "results": [
            {
                "rel_path": f.rel_path,
                "name": Path(f.rel_path).name,
                "language": f.language,
                "size_bytes": f.size_bytes,
            }
            for f in files
        ],
        "count": len(files),
    }


async def grep_code(db: AsyncSession, project_id: int, pattern: str) -> dict:
    """在项目文本文件中搜索内容，返回 path/line/上下文。pattern 为正则。"""
    if not pattern:
        raise ValueError("pattern 不能为空")
    return await ProjectService(db).search_content(project_id, pattern)


async def read_code_file(
    db: AsyncSession,
    project_id: int,
    rel_path: str,
    start_line: int = 1,
    max_lines: int = DEFAULT_READ_LINES,
) -> dict:
    """读取授权项目内的文件片段（按行分页）。rel_path 必须在项目根下。"""
    project = await ProjectService(db).get(project_id)
    full = resolve_within(project.root_path, rel_path)
    if not full.exists() or not full.is_file():
        raise FileNotFoundError(f"文件不存在: {rel_path}")
    size = full.stat().st_size
    if size > MAX_READ_FILE_BYTES:
        raise ValueError(f"文件过大（{size} 字节，上限 {MAX_READ_FILE_BYTES} 字节）")

    def _read() -> str:
        return full.read_text(encoding="utf-8", errors="ignore")

    text = await asyncio.to_thread(_read)
    lines = text.splitlines()
    total = len(lines)
    start = max(1, start_line)
    end = min(total + 1, start + max(1, max_lines))
    selected = lines[start - 1 : end - 1]
    content = "\n".join(selected)
    truncated = end - 1 < total
    return {
        "path": rel_path,
        "content": content,
        "language": language_for_ext(full.suffix),
        "start_line": start,
        "line_count": total,
        "size_bytes": size,
        "truncated": truncated,
    }


def _parse_git_porcelain(text: str) -> dict:
    """解析 `git status --porcelain=v1 -b` 输出。"""
    lines = text.splitlines()
    branch: str | None = None
    upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    changed: list[dict] = []
    for line in lines:
        if line.startswith("## "):
            rest = line[3:]
            # 形如 main...origin/main [ahead 1, behind 2]
            head = rest.split(" ", 1)[0]
            if "..." in head:
                branch, upstream = head.split("...", 1)
            else:
                branch = head
            if "[" in rest:
                bracket = rest[rest.index("[") + 1 : rest.rindex("]")]
                for token in bracket.split(","):
                    token = token.strip()
                    if token.startswith("ahead "):
                        ahead = int(token[6:])
                    elif token.startswith("behind "):
                        behind = int(token[7:])
            continue
        if len(line) < 3:
            continue
        xy = line[:2]
        path = line[3:]
        # 重命名形如 R  old -> new
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed.append({"status": xy, "path": path})
    return {
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "clean": len(changed) == 0,
        "changed": changed,
    }


async def get_git_status(db: AsyncSession, project_id: int) -> dict:
    """读取项目 git 状态（分支/改动文件）。不修改任何文件。"""
    project = await ProjectService(db).get(project_id)
    rc, out, err = await _run_git(
        project.root_path, ["status", "--porcelain=v1", "-b"]
    )
    if rc != 0:
        raise RuntimeError(f"git status 失败: {err.strip() or out.strip()}")
    return _parse_git_porcelain(out)


async def get_git_diff(
    db: AsyncSession, project_id: int, *, cached: bool = False, max_chars: int = GIT_DIFF_MAX_CHARS
) -> dict:
    """读取项目 git diff（未暂存或已暂存）。只读。"""
    project = await ProjectService(db).get(project_id)
    args = ["diff", "--stat"]
    if cached:
        args.append("--cached")
    rc, out, err = await _run_git(project.root_path, args)
    if rc != 0:
        raise RuntimeError(f"git diff 失败: {err.strip() or out.strip()}")
    # 再取完整 diff 文本（带行级改动），截断保护
    args_full = ["diff"]
    if cached:
        args_full.append("--cached")
    rc2, out2, err2 = await _run_git(project.root_path, args_full)
    if rc2 != 0:
        raise RuntimeError(f"git diff 失败: {err2.strip() or out2.strip()}")
    diff = out2
    truncated = len(diff) > max_chars
    if truncated:
        diff = diff[:max_chars] + "\n…（diff 已截断）"
    return {"stat": out, "diff": diff, "truncated": truncated}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_text_or_empty(path: Path, *, create: bool) -> str:
    if not path.exists():
        if create:
            return ""
        raise FileNotFoundError(f"文件不存在: {path.name}")
    if not path.is_file():
        raise ValueError(f"不是文件: {path.name}")
    size = path.stat().st_size
    if size > MAX_READ_FILE_BYTES:
        raise ValueError(f"文件过大（{size} 字节，上限 {MAX_READ_FILE_BYTES} 字节）")
    return path.read_text(encoding="utf-8", errors="ignore")


async def propose_patch(
    db: AsyncSession,
    project_id: int,
    rel_path: str,
    new_content: str,
    *,
    create: bool = False,
) -> dict:
    """Generate a unified diff preview for replacing one project file."""
    if not isinstance(new_content, str):
        raise ValueError("new_content 必须为字符串")
    if len(new_content) > PATCH_MAX_CHARS:
        raise ValueError(f"new_content 过大（上限 {PATCH_MAX_CHARS} 字符）")
    project = await ProjectService(db).get(project_id)
    full = resolve_within(project.root_path, rel_path)

    def _preview() -> dict:
        old = _read_text_or_empty(full, create=create)
        old_lines = old.splitlines()
        new_lines = new_content.splitlines()
        diff = "\n".join(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
                lineterm="",
            )
        )
        if diff:
            diff += "\n"
        truncated = len(diff) > PATCH_DIFF_MAX_CHARS
        if truncated:
            diff = diff[:PATCH_DIFF_MAX_CHARS] + "\n…（diff 已截断）"
        return {
            "project_id": project_id,
            "rel_path": rel_path,
            "diff": diff,
            "old_sha256": _sha256_text(old),
            "new_sha256": _sha256_text(new_content),
            "creates_file": not full.exists(),
            "changed": old != new_content,
            "truncated": truncated,
        }

    return await asyncio.to_thread(_preview)


async def apply_patch_to_workspace(
    db: AsyncSession,
    project_id: int,
    rel_path: str,
    new_content: str,
    *,
    expected_old_sha256: str | None = None,
    create: bool = False,
) -> dict:
    """Replace one authorized project file after approval."""
    preview = await propose_patch(
        db, project_id, rel_path, new_content, create=create
    )
    if expected_old_sha256 and preview["old_sha256"] != expected_old_sha256:
        raise RuntimeError("文件内容已变化，拒绝应用过期补丁")
    project = await ProjectService(db).get(project_id)
    full = resolve_within(project.root_path, rel_path)

    def _write() -> int:
        if not full.parent.exists():
            if not create:
                raise FileNotFoundError(f"父目录不存在: {full.parent.name}")
            full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(new_content, encoding="utf-8", newline="")
        return full.stat().st_size

    size = await asyncio.to_thread(_write)
    return {
        "project_id": project_id,
        "rel_path": rel_path,
        "old_sha256": preview["old_sha256"],
        "new_sha256": preview["new_sha256"],
        "size_bytes": size,
        "diff": preview["diff"],
        "truncated": preview["truncated"],
    }


def parse_command(command: str | list[str]) -> list[str]:
    if isinstance(command, list):
        args = [str(x) for x in command if str(x)]
    elif isinstance(command, str):
        args = shlex.split(command, posix=False)
    else:
        raise ValueError("command 必须为字符串或参数数组")
    if not args:
        raise ValueError("command 不能为空")
    bad_tokens = {"&&", "||", ";", "|", ">", ">>", "<"}
    if any(a in bad_tokens for a in args):
        raise ValueError("命令不能包含 shell 控制符")
    return args


def is_whitelisted_command(args: list[str]) -> bool:
    lowered = [a.lower() for a in args]
    for prefix in WHITELISTED_COMMAND_PREFIXES:
        if lowered[: len(prefix)] == list(prefix):
            return True
    return False


async def _execute_command(
    args: list[str], cwd: str, *, timeout: float = COMMAND_TIMEOUT
) -> dict:
    """在 cwd 运行 args（已通过权限/配置校验），返回结果 dict。

    供 run_whitelisted_command（全局白名单）与项目命令配置（预授权）复用。
    """
    timeout = max(1.0, min(float(timeout or COMMAND_TIMEOUT), COMMAND_TIMEOUT))
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"未找到命令: {args[0]}") from e
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise TimeoutError(f"命令超时（{timeout}s）")
    stdout = stdout_b.decode("utf-8", errors="ignore")
    stderr = stderr_b.decode("utf-8", errors="ignore")
    combined = (stdout + ("\n" if stdout and stderr else "") + stderr).strip()
    truncated = len(combined) > COMMAND_OUTPUT_MAX_CHARS
    if truncated:
        combined = combined[:COMMAND_OUTPUT_MAX_CHARS] + "\n... output truncated"
    return {
        "args": args,
        "cwd": cwd,
        "returncode": proc.returncode,
        "stdout": stdout[:COMMAND_OUTPUT_MAX_CHARS],
        "stderr": stderr[:COMMAND_OUTPUT_MAX_CHARS],
        "output": combined,
        "truncated": truncated,
        "succeeded": proc.returncode == 0,
    }


async def run_whitelisted_command(
    db: AsyncSession,
    project_id: int,
    command: str | list[str],
    *,
    timeout: float = COMMAND_TIMEOUT,
) -> dict:
    """Run an approved command in the project root if it matches the whitelist."""
    project = await ProjectService(db).get(project_id)
    args = parse_command(command)
    if not is_whitelisted_command(args):
        raise PermissionError_("非白名单命令，已拒绝执行")
    result = await _execute_command(args, project.root_path, timeout=timeout)
    result["project_id"] = project_id
    return result
