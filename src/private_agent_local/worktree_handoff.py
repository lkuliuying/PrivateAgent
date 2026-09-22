"""以共同起点核对两端文件，保留源 worktree 的可复查交接。"""
from __future__ import annotations

import difflib
from contextlib import ExitStack
from pathlib import Path

from . import files, git_tools, git_workspace
from .patchsets import matches, replace_one, state
from .store import encode, now


class WorktreeHandoff:
    def __init__(self, owner):
        self.owner = owner

    def roots(self, project_id, workspace_id):
        workspaces = [w for w in self.owner.store.list("workspace") if w["project_id"] == project_id]
        source = next((w for w in workspaces if w["id"] == workspace_id), None)
        target = next((w for w in workspaces if w["kind"] == "root"), None)
        if not source or source["kind"] != "git_worktree" or not source.get("managed") or not target:
            raise ValueError("只能将本应用管理的 worktree 交接到所属项目根目录")
        roots = [self.owner.root(project_id, item["id"]) for item in (source, target)]
        if any(run["workspace_id"] in {source["id"], target["id"]} for run in self.owner.store.runs(active_only=True)):
            raise ValueError("请先结束两端的运行、暂停和排队任务")
        if files.file_identity(roots[0]) != source.get("root_identity") or Path(source["main_root"]) != roots[1]:
            raise ValueError("worktree 身份或所属目录已变化")
        common = git_workspace._git(roots[0], "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        target_common = git_workspace._git(roots[1], "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        if common != source.get("git_common_dir") or common != target_common:
            raise ValueError("worktree Git 归属已变化")
        for root in roots:
            self.owner.workspaces.assert_idle(root)
        return source, target, roots

    async def preview(self, project_id, workspace_id):
        source, target, (source_root, target_root) = self.roots(project_id, workspace_id)
        base = source["head_sha"]
        changed = await git_tools.git(source_root, "diff", "--name-only", "--no-renames", "-z", base, "--")
        untracked = await git_tools.git(source_root, "ls-files", "--others", "--exclude-standard", "-z")
        if changed["returncode"] or untracked["returncode"]:
            raise ValueError("无法读取 worktree 相对起点的变更")
        paths = sorted(set(filter(None, (changed["stdout"] + untracked["stdout"]).split("\0"))))
        if len(paths) > 200:
            raise ValueError("一次交接最多 200 个文件，请拆分变更")
        changes, conflicts, total = [], [], 0
        for relative in paths:
            try:
                before, after = state(target_root, relative), state(source_root, relative)
                if matches(before, after, identity=False):
                    continue
                if before["kind"] == "directory" or after["kind"] == "directory":
                    raise ValueError("不支持目录与文件类型替换")
                tree = await git_tools.git(source_root, "ls-tree", base, "--", relative)
                mode = tree["stdout"].split(" ", 1)[0]
                if mode and mode not in {"100644", "100755"}:
                    raise ValueError("不支持链接或子模块交接")
                original = await git_tools.git(source_root, "show", f"{base}:{relative}", limit=files.MAX_FILE_BYTES) if tree["stdout"] else None
                if original and original["returncode"]:
                    raise ValueError("无法读取共同起点")
                base_state = {"kind": "file", "sha256": files.digest(original["stdout"].encode("utf-8"))} if original else {"kind": "missing"}
                # Git 对象通常保存 LF；只容许 Windows 检出引入的 CRLF 差别，其他本地改动仍阻止交接。
                equivalent = (original is not None and before["kind"] == "file"
                              and before["text"].replace("\r\n", "\n") == original["stdout"].replace("\r\n", "\n"))
                if not matches(before, base_state, identity=False) and not equivalent:
                    raise ValueError("本地目录已有不同修改，保留两端并停止交接")
                if after["kind"] == "file" and mode == "100755":
                    after["mode"] = 0o755
                total += len(before.get("text", "").encode()) + len(after.get("text", "").encode())
                if total > 8 * 1024 * 1024:
                    raise ValueError("交接正文超过 8 MiB 上限")
                changes.append({"rel_path": relative, "before": before, "after": after})
            except (ValueError, OSError, UnicodeError) as error:
                conflicts.append({"rel_path": relative, "reason": str(error) if isinstance(error, ValueError) else "文件读取失败"})
        directories = {}
        for item in changes:
            if item["after"]["kind"] != "file":
                continue
            for parent in Path(item["rel_path"]).parents:
                relative = parent.as_posix()
                if relative == ".":
                    continue
                before = state(target_root, relative)
                if before["kind"] == "missing":
                    directories[relative] = {"rel_path": relative, "before": before, "after": {"kind": "directory"}}
        changes = sorted(directories.values(), key=lambda item: item["rel_path"].count("/")) + changes
        version = files.digest(encode({"source": source["id"], "target": target["id"], "base": base,
                                       "changes": changes, "conflicts": conflicts}).encode())
        return {"version": version, "source_workspace_id": source["id"], "target_workspace_id": target["id"],
                "base_head": base, "changes": changes, "conflicts": conflicts}

    @staticmethod
    def public(preview):
        return {**preview, "changes": [{"rel_path": item["rel_path"], "operation": "mkdir" if item["after"]["kind"] == "directory" else "create" if item["before"]["kind"] == "missing" else "delete" if item["after"]["kind"] == "missing" else "update",
                  "diff": "".join(difflib.unified_diff(item["before"].get("text", "").splitlines(True), item["after"].get("text", "").splitlines(True), fromfile="a/" + item["rel_path"], tofile="b/" + item["rel_path"]))[:16000]}
                 for item in preview["changes"]]}

    async def apply(self, project_id, workspace_id, version, request_id, session_id):
        store = self.owner.store
        project = store.get("project", project_id)
        records = project.get("worktree_handoffs", [])
        previous = next((record for record in records if record["request_id"] == request_id), None)
        if previous:
            if previous["version"] != version or previous["source_workspace_id"] != workspace_id or previous["session_id"] != session_id:
                raise ValueError("重复请求与原交接不一致")
            return previous
        if len(records) >= 100:
            raise ValueError("交接记录已达 100 次上限，请先核对历史")
        preview = await self.preview(project_id, workspace_id)
        if preview["version"] != version or preview["conflicts"]:
            raise ValueError("两端文件已变化或存在冲突，请重新预览")
        source, target, roots = self.roots(project_id, workspace_id)
        session = store.get("session", session_id)
        if session["project_id"] != project_id or session["workspace_id"] != workspace_id:
            raise ValueError("交接任务不属于该 worktree")
        record = {"request_id": request_id, "version": version, "source_workspace_id": workspace_id,
                  "target_workspace_id": target["id"], "session_id": session_id, "state": "applying", "files": [], "created_at": now()}
        with ExitStack() as stack:
            for root in sorted(roots, key=str):
                stack.enter_context(self.owner.workspaces.exclusive(root))
            self.owner.patches.preflight(roots[1], preview["changes"])
            records.append(record)
            store.update("project", project_id, worktree_handoffs=records)
            try:
                for item in preview["changes"]:
                    if not matches(state(roots[0], item["rel_path"]), item["after"]):
                        raise ValueError("源文件在交接期间发生变化")
                    entry = {"rel_path": item["rel_path"], "state": "writing", "before_sha256": item["before"].get("sha256"), "after_sha256": item["after"].get("sha256")}
                    record["files"].append(entry)
                    store.update("project", project_id, worktree_handoffs=records)
                    replace_one(roots[1], item)
                    entry["state"] = "applied"
                    store.update("project", project_id, worktree_handoffs=records)
                record["state"] = "applied"
                with store.transaction():
                    store.update("session", session_id, workspace_id=target["id"])
                    store.update("project", project_id, worktree_handoffs=records)
            except (ValueError, OSError):
                record.update(state="interrupted", error="交接部分完成或结果未确认，请核对逐文件记录；源 worktree 已保留。")
                store.update("project", project_id, worktree_handoffs=records)
        return record
