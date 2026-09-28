"""受控的只读 Git 工具；不接受任意 Git 参数或外部执行器。"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from private_agent_core.tool_specs import ToolFailure, ToolSpec, object_output

from . import files, policy, repository, task_constraints


class GitStatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    rel_path: str = Field(default=".", min_length=1, max_length=1024)
    cursor: str | None = Field(default=None, max_length=1024)
    limit: int = Field(default=100, ge=1, le=200)


class GitDiffArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    rel_path: str = Field(min_length=1, max_length=1024)
    staged: bool = False
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=16000, ge=1, le=32000)
    expected_version: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


SPECS = (
    ToolSpec("get_git_status", GitStatusArgs,
             "Preferred read-only Git status. Returns bounded project-relative changes, without running project scripts. Scope rel_path to the allowed directory.",
             capabilities=("repository.read",), parallel_safe=True, supports_cancellation=True,
             output_schema=object_output(is_git="boolean", entries="array", query_version="string")),
    ToolSpec("get_git_diff", GitDiffArgs,
             "Preferred read-only diff of one previously identified file (rel_path, never '.'). staged=false compares worktree to index; staged=true compares index to HEAD. Continue with next_offset and expected_version=version. Never reads credential files.",
             capabilities=("repository.read",), parallel_safe=True, supports_cancellation=True,
             output_schema=object_output(rel_path="string", diff="string", version="string", truncated="boolean")),
)
TOOLS = {spec.name: (spec.input_model, spec.description) for spec in SPECS}


async def git(root: Path, *arguments: str, limit=512_000) -> dict:
    try:
        result = await files.run_process(root, [
            "git", "--literal-pathspecs", "-c", "core.fsmonitor=false", "-c", "core.pager=cat",
            "-c", f"core.hooksPath={os.devnull}", "-c", "diff.external=",
            *arguments,
        ], timeout=10, output_limit=limit)
    except TimeoutError as error:
        raise ToolFailure("command_timed_out", "Git 查询超时，进程已停止", retryable=True) from error
    if result["truncated"]:
        raise ToolFailure("tool_output_too_large", "Git 查询超出上限，请缩小文件或目录范围")
    return result


async def execute(run: dict, root: Path, name: str, arguments: dict) -> dict:
    spec = next(item for item in SPECS if item.name == name)
    args = spec.input_model.model_validate(arguments)
    task_constraints.guard_paths(run, root, [args.rel_path])
    target = files.within(root, args.rel_path, allow_missing=True)
    policy.file_scope(root, args.rel_path, run["permission_mode"])
    top = await git(root, "rev-parse", "--show-toplevel")
    if top["returncode"] != 0 or Path(top["stdout"].strip()).resolve() != root:
        if name == "get_git_status":
            return {"is_git": False, "entries": [], "query_version": files.digest(b"no-git"),
                    "next_cursor": None, "truncated": False, "count": 0, "total": 0}
        raise ToolFailure("not_git_repository", "所选项目不是 Git 仓库")
    if name == "get_git_status":
        result = await git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", args.rel_path)
        if result["returncode"] != 0:
            raise ToolFailure("git_query_failed", "Git 状态查询失败")
        entries = []
        tokens = iter(result["stdout"].split("\0"))
        for token in tokens:
            if not token:
                continue
            entry = {"status": token[:2], "rel_path": token[3:]}
            if "R" in entry["status"] or "C" in entry["status"]:
                entry["original_path"] = next(tokens, "")
            try:
                task_constraints.guard_paths(run, root, [entry["rel_path"], *([entry["original_path"]] if "original_path" in entry else [])])
            except ValueError:
                continue
            entries.append(entry)
        version = files.digest(result["stdout"].encode("utf-8"))
        result_page = repository.page(entries, {"kind": name, "root": str(root), "path": args.rel_path}, version, args.cursor, args.limit)
        entries_page = result_page.pop("items")
        return {"is_git": True, **result_page, "entries": entries_page}
    if args.rel_path == "." or target.is_dir():
        raise ToolFailure("invalid_tool_arguments", "diff 须指定状态查询返回的单个文件路径")
    if target.exists() and target.stat().st_nlink > 1:
        raise ToolFailure("permission_blocked", "不能读取具有多个硬链接的文件")
    result = await git(root, "diff", *(["--cached"] if args.staged else []), "--no-ext-diff", "--no-textconv",
                       "--no-renames", "--no-color", "--unified=3", "--", args.rel_path, limit=512_000)
    if result["returncode"] != 0:
        raise ToolFailure("git_query_failed", "Git diff 查询失败")
    diff = result["stdout"]
    version = files.digest(diff.encode("utf-8"))
    if args.expected_version and args.expected_version != version:
        raise ToolFailure("stale_tool_input", "diff 已变化，请从 offset=0 重新读取", retryable=True)
    if args.offset > len(diff):
        raise ToolFailure("invalid_tool_arguments", "diff 偏移超过结果末尾")
    end = min(len(diff), args.offset + args.limit)
    return {"rel_path": args.rel_path, "staged": args.staged, "diff": diff[args.offset:end],
            "version": version, "next_offset": end if end < len(diff) else None, "truncated": end < len(diff)}
