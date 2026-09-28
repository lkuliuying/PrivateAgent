"""本机补丁应用服务：持久化意图先于副作用，逐文件验证，保护后续编辑。"""
from __future__ import annotations

import asyncio
import difflib
import os
import tempfile
import uuid
from pathlib import Path

from private_agent_core.patches import (
    MAX_PATCH_BYTES,
    PatchOperation,
    PatchProposal,
    updated_bytes,
)

from . import files, policy, task_constraints
from .repository import Repository
from .store import encode, now


def state(root: Path, relative: str) -> dict:
    policy.file_scope(root, relative, "readonly")
    target = files.within(root, relative, allow_missing=True)
    if not target.exists():
        return {"kind": "missing"}
    if target.is_dir():
        return {"kind": "directory", "identity": files.file_identity(target)}
    raw, identity = files.safe_bytes(root, relative)
    return {"kind": "file", "sha256": files.digest(raw), "text": raw.decode("utf-8"), "identity": identity}


def matches(actual: dict, expected: dict, *, identity=True) -> bool:
    return (actual["kind"] == expected["kind"] and actual.get("sha256") == expected.get("sha256")
            and (not identity or not expected.get("identity") or actual.get("identity") == expected["identity"]))


def _text_state(data: bytes, mode: int | None = None) -> dict:
    result = {"kind": "file", "sha256": files.digest(data), "text": data.decode("utf-8")}
    if mode is not None:
        result["mode"] = mode
    return result


def _diff(relative: str, before: dict, after: dict) -> str:
    if before["kind"] == "directory" or after["kind"] == "directory":
        return ("+" if after["kind"] == "directory" else "-") + relative + "/\n"
    return "".join(difflib.unified_diff(before.get("text", "").splitlines(True), after.get("text", "").splitlines(True),
                                         fromfile="a/" + relative, tofile="b/" + relative))


def _line_stats(before: dict, after: dict) -> dict[str, int]:
    """按完整版本统计文本行，避免预览截断、无末尾换行和 diff 头部影响计数。"""
    matcher = difflib.SequenceMatcher(None, before.get("text", "").splitlines(True),
                                     after.get("text", "").splitlines(True))
    additions = deletions = 0
    for operation, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if operation in {"insert", "replace"}:
            additions += new_end - new_start
        if operation in {"delete", "replace"}:
            deletions += old_end - old_start
    return {"additions": additions, "deletions": deletions}


def preview_hash(patch: dict) -> str:
    return files.digest(encode({key: value for key, value in patch.items() if key not in {"status", "error", "preview_sha256"}}).encode())


def replace_one(root: Path, change: dict) -> dict:
    """单文件原子替换；跨文件不具有事务性。每个外部副作用紧邻最后一次版本核对。"""
    relative, before, after = change["rel_path"], change["before"], change["after"]
    target = files.within(root, relative, allow_missing=True)
    if not matches(state(root, relative), before):
        raise ValueError("文件在落盘前变化，已停止操作")
    if after["kind"] == "directory":
        target.mkdir()
    elif after["kind"] == "missing":
        if before["kind"] == "directory":
            target.rmdir()
        else:
            target.unlink()
    else:
        if not target.parent.is_dir():
            raise ValueError("父目录不存在，必须在同一补丁中明确创建")
        descriptor, name = tempfile.mkstemp(prefix=".privateagent-write-", dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(after["text"].encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            mode = after.get("mode", before.get("identity", {}).get("mode"))
            if mode is not None:
                os.chmod(temporary, mode)
            target = files.within(root, relative, allow_missing=True)
            if not matches(state(root, relative), before):
                raise ValueError("文件在写入前发生变化，已取消")
            if before["kind"] == "missing":
                os.link(temporary, target)
                temporary.unlink()
            else:
                os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    actual = state(root, relative)
    if not matches(actual, after, identity=False):
        raise ValueError("落盘后文件校验失败，请检查操作日志")
    return actual


class PatchService:
    def __init__(self, store):
        self.store = store
        self.repository = Repository(store)
        self.lock = asyncio.Lock()

    def save(self, patch: dict):
        with self.store.transaction():
            self.store.db.execute("INSERT INTO patch_sets VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,data=excluded.data",
                                  (patch["patch_set_id"], patch["run_id"], patch["operation_id"], patch["status"], self.store._pack(patch)))

    def journal(self, patch: dict, change: dict, status: str, **facts):
        value = {"change_id": change["change_id"], "rel_path": change["rel_path"], "status": status, "created_at": now(), **facts}
        with self.store.transaction():
            sequence = self.store.db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM patch_journal WHERE patch_set_id=?", (patch["patch_set_id"],)).fetchone()[0]
            self.store.db.execute("INSERT INTO patch_journal VALUES (?,?,?)", (patch["patch_set_id"], sequence, self.store._pack(value)))
        return value

    def get(self, run_id: str, patch_id: str) -> dict:
        row = self.store.db.execute("SELECT data FROM patch_sets WHERE id=? AND run_id=?", (patch_id, run_id)).fetchone()
        if not row:
            raise ValueError("补丁不存在或不属于当前任务")
        return self.store._unpack(row[0])

    def logs(self, patch_id: str) -> list[dict]:
        return [self.store._unpack(row[0]) for row in self.store.db.execute("SELECT data FROM patch_journal WHERE patch_set_id=? ORDER BY sequence", (patch_id,))]

    def list(self, run_id: str) -> list[dict]:
        return [self.public(self.store._unpack(row[0])) for row in self.store.db.execute("SELECT data FROM patch_sets WHERE run_id=? ORDER BY rowid", (run_id,))]

    def public(self, patch: dict) -> dict:
        changes = [{"change_id": item["change_id"], "operation": item["operation"], "rel_path": item["rel_path"],
                    "creates_file": item["before"]["kind"] == "missing" and item["after"]["kind"] == "file",
                    "before_kind": item["before"]["kind"], "after_kind": item["after"]["kind"],
                    "old_sha256": item["before"].get("sha256"), "new_sha256": item["after"].get("sha256"),
                    "diff_chars": len(item["diff"]), **_line_stats(item["before"], item["after"])} for item in patch["changes"]]
        full = "\n".join(item["diff"] for item in patch["changes"])
        return {"patch_set_id": patch["patch_set_id"], "run_id": patch["run_id"], "operation_id": patch["operation_id"],
                "preview_sha256": patch["preview_sha256"], "status": patch["status"], "kind": patch["kind"],
                "rollback_of": patch.get("rollback_of"), "previewable": True, "tool_name": "apply_project_patch",
                "diff": full[:files.MAX_OUTPUT], "truncated": len(full) > files.MAX_OUTPUT,
                "changes": changes, "conflicts": patch.get("conflicts", []), "error": patch.get("error"),
                "journal": [{k: v for k, v in row.items() if k != "after"} for row in self.logs(patch["patch_set_id"])],
                **({k: changes[0].get(k) for k in ("rel_path", "creates_file", "old_sha256", "new_sha256")} if len(changes) == 1 else {})}

    def diff_page(self, run_id: str, patch_id: str, change_id: str, offset: int, limit: int) -> dict:
        patch = self.get(run_id, patch_id)
        change = next((item for item in patch["changes"] if item["change_id"] == change_id), None)
        if not change or not 0 <= offset <= len(change["diff"]) or not 1 <= limit <= 16000:
            raise ValueError("补丁内容引用或读取范围无效")
        text = change["diff"]
        end = min(offset + limit, len(text))
        return {"content": text[offset:end], "offset": offset, "next_offset": end if end < len(text) else None,
                "total_chars": len(text), "preview_sha256": patch["preview_sha256"]}

    def _new(self, run: dict, root: Path, changes: list, operation_id: str, **extra) -> dict:
        if self.store.db.execute("SELECT COUNT(*) FROM patch_sets WHERE run_id=?", (run["id"],)).fetchone()[0] >= 256:
            raise ValueError("单次任务补丁记录达到 256 组上限，请先核对已有变更")
        if sum(len(encode(item).encode()) for item in changes) > MAX_PATCH_BYTES * 3:
            raise ValueError("补丁恢复内容和差异超过 12 MiB 上限")
        patch = {"patch_set_id": str(uuid.uuid4()), "run_id": run["id"], "operation_id": operation_id,
                 "workspace_id": run["workspace_id"], "root_path": str(root), "root_identity": files.file_identity(root),
                 "base_revision": run.get("base_head_sha"), "permission_mode": run["permission_mode"],
                 "grant_id": run.get("full_access_grant_id"), "kind": "patch", "changes": changes,
                 "created_at": now(), **extra}
        patch["preview_sha256"] = preview_hash(patch)
        patch["status"] = "validated"
        self.save(patch)
        return patch

    def propose(self, run: dict, root: Path, proposal: PatchProposal, operation_id: str) -> dict:
        changes = []
        for op in sorted(proposal.operations, key=lambda item: (item.operation != "mkdir", item.rel_path.count("/"))):
            group_id = str(uuid.uuid4())
            before = state(root, op.rel_path)
            if op.snapshot_id:
                snapshot = self.repository.snapshot(run["id"], op.snapshot_id)
                if (snapshot["root_path"] != str(root) or snapshot["root_identity"] != files.file_identity(root)
                        or snapshot["rel_path"] != op.rel_path or before["kind"] != "file"
                        or snapshot["sha256"] != before["sha256"] or snapshot["identity"] != before["identity"]):
                    raise ValueError("文件自模型读取后已变化，请重新读取并生成补丁")
            elif before["kind"] != "missing":
                raise ValueError("新增目标已存在，不能覆盖")
            if op.operation == "move":
                destination = state(root, op.new_rel_path)
                if destination["kind"] != "missing":
                    raise ValueError("移动目标已存在")
                pairs = [(op.new_rel_path, destination, _text_state(before["text"].encode(), before["identity"]["mode"])),
                         (op.rel_path, before, {"kind": "missing"})]
            else:
                after = ({"kind": "directory"} if op.operation == "mkdir" else {"kind": "missing"} if op.operation == "delete"
                         else _text_state(updated_bytes(before.get("text", "").encode(), op)))
                pairs = [(op.rel_path, before, after)]
            for relative, old, new in pairs:
                changes.append({"change_id": str(uuid.uuid4()), "operation": op.operation, "rel_path": relative,
                                "before": old, "after": new, "diff": _diff(relative, old, new), "group_id": group_id})
        self.preflight(root, changes)
        return self._new(run, root, changes, operation_id)

    def legacy(self, run: dict, root: Path, relative: str, content: str, operation_id: str) -> dict:
        exists = files.within(root, relative, allow_missing=True).exists()
        op = PatchOperation(operation="update" if exists else "create", rel_path=relative, content=content,
                            snapshot_id=self.repository.latest(run["id"], relative) if exists else None)
        return self.propose(run, root, PatchProposal(operations=[op]), operation_id)

    def preflight(self, root: Path, changes: list):
        created_directories = set()
        for change in changes:
            relative = change["rel_path"]
            if not matches(state(root, relative), change["before"]):
                raise ValueError("补丁基准或目标存在状态已变化，请重新预览")
            parent = Path(relative).parent.as_posix()
            path = files.within(root, relative, allow_missing=True)
            if change["after"]["kind"] != "missing" and not path.parent.is_dir() and parent not in created_directories:
                raise ValueError("补丁缺少父目录创建操作")
            if change["after"]["kind"] == "directory":
                created_directories.add(relative)

    def validate_binding(self, run: dict, root: Path, patch: dict, preview_sha256: str):
        if (patch["preview_sha256"] != preview_sha256 or preview_hash(patch) != preview_sha256 or patch["root_path"] != str(root)
                or patch["root_identity"] != files.file_identity(root) or patch["workspace_id"] != run["workspace_id"]
                or patch["permission_mode"] != run["permission_mode"] or patch["grant_id"] != run.get("full_access_grant_id")):
            raise ValueError("批准绑定的内容、权限或工作区已变化")
        if run["permission_mode"] == "readonly" or run.get("completion_policy", {}).get("preview_only"):
            raise ValueError("当前任务只允许预览，不能落盘")
        task_constraints.refresh_interpretation(run)
        task_constraints.guard_paths(run, root, [item["rel_path"] for item in patch["changes"]], write=True)

    async def apply(self, run: dict, root: Path, patch_id: str, preview_sha256: str, guard) -> dict:
        async with self.lock:
            await guard()
            patch = self.get(run["id"], patch_id)
            self.validate_binding(run, root, patch, preview_sha256)
            if patch["status"] == "applied":
                return self.public(patch)
            if patch["status"] != "validated":
                raise ValueError("补丁已终止、冲突或部分执行，不能重复应用")
            applied = 0
            try:
                self.preflight(root, patch["changes"])
                patch["status"] = "applying"
                self.save(patch)
                for change in patch["changes"]:
                    await guard()
                    self.validate_binding(run, root, patch, preview_sha256)
                    self.journal(patch, change, "applying")
                    replace_one(root, change)
                    actual = state(root, change["rel_path"])
                    if not matches(actual, change["after"], identity=False):
                        raise ValueError("独立磁盘回读未确认落盘，不能采信文件函数成功标记")
                    self.journal(patch, change, "applied", after=actual)
                    applied += 1
                patch["status"] = "applied"
                self.save(patch)
            except BaseException as error:
                patch.update(status="partially_applied" if applied else "conflicted" if patch["status"] == "validated" and isinstance(error, ValueError) else "failed",
                             error="补丁执行被取消" if isinstance(error, asyncio.CancelledError) else
                             str(error) if isinstance(error, ValueError) else "文件系统或日志故障，请核对逐项结果；未自动重放")
                # 日志落盘失败时不能把刚发生的副作用说成未执行；保留原 applying 意图。
                self.save(patch)
                if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                    raise
            return self.public(patch)

    def rollback_preview(self, run: dict, root: Path, patch_id: str, operation_id: str) -> dict:
        prior = self.store.db.execute("SELECT data FROM patch_sets WHERE operation_id=?", (operation_id,)).fetchone()
        if prior:
            patch = self.store._unpack(prior[0])
            if patch["run_id"] != run["id"] or patch.get("rollback_of") != patch_id:
                raise ValueError("回滚操作标识已用于其他请求")
            return self.public(patch)
        original = self.get(run["id"], patch_id)
        if original["kind"] == "rollback" or original["status"] not in {"applied", "partially_applied", "failed", "interrupted"}:
            raise ValueError("该补丁尚无可回滚的落盘记录")
        if original["root_path"] != str(root) or original["root_identity"] != files.file_identity(root):
            raise ValueError("工作区根身份已变化，禁止回滚")
        logs = {row["change_id"]: row for row in self.logs(patch_id)}
        changes, conflicts = [], []
        blocked_moves = set()
        for change in original["changes"]:
            if change["operation"] != "move":
                continue
            log = logs.get(change["change_id"])
            try:
                if not log or log["status"] != "applied" or not matches(state(root, change["rel_path"]), log["after"]):
                    blocked_moves.add(change["group_id"])
            except (ValueError, OSError):
                blocked_moves.add(change["group_id"])
        for change in reversed(original["changes"]):
            log = logs.get(change["change_id"])
            if not log:
                continue
            try:
                if change.get("group_id") in blocked_moves:
                    raise ValueError("移动的源或目标存在冲突/未知状态，成对保留")
                actual = state(root, change["rel_path"])
                if log["status"] != "applied" or not matches(actual, log["after"]):
                    raise ValueError("当前内容与写后记录不同或执行结果未知，已保留")
                if actual["kind"] == "directory":
                    descendants = {item["rel_path"] for item in changes if item["after"]["kind"] == "missing"}
                    if any(child.relative_to(root).as_posix() not in descendants for child in files.within(root, change["rel_path"]).iterdir()):
                        raise ValueError("目录含后续文件，已保留")
                after = {k: v for k, v in change["before"].items() if k != "identity"}
                if change["before"].get("identity", {}).get("mode") is not None:
                    after["mode"] = change["before"]["identity"]["mode"]
                changes.append({"change_id": str(uuid.uuid4()), "operation": "rollback", "rel_path": change["rel_path"],
                                "before": actual, "after": after, "diff": _diff(change["rel_path"], actual, after)})
            except (ValueError, OSError) as error:
                conflicts.append({"rel_path": change["rel_path"], "reason": str(error) if isinstance(error, ValueError) else "文件不可访问"})
        if not changes:
            return {"patch_set_id": None, "status": "conflicted", "conflicts": conflicts, "changes": [], "rollback_of": patch_id}
        return self.public(self._new(run, root, changes, operation_id, kind="rollback", rollback_of=patch_id, conflicts=conflicts))

    def facts(self, run_id: str, patch_id: str, root: Path) -> list[dict]:
        patch = self.get(run_id, patch_id)
        logs = {row["change_id"]: row for row in self.logs(patch_id)}
        result = []
        for change in patch["changes"]:
            log = logs.get(change["change_id"])
            try:
                actual = state(root, change["rel_path"])
                verified = bool(log and log["status"] == "applied" and matches(actual, log["after"]))
                observation = "matches_after" if matches(actual, change["after"], identity=False) else "matches_before" if matches(actual, change["before"]) else "conflict"
            except (ValueError, OSError):
                verified, observation = False, "unreadable"
            result.append({"rel_path": change["rel_path"], "verified": verified,
                           "changed": not matches(change["before"], change["after"], identity=False),
                           "kind": change["after"]["kind"], "sha256": change["after"].get("sha256"),
                           "journal_status": log["status"] if log else "not_started", "observation": observation})
        return result
