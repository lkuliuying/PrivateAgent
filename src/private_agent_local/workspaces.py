"""规范工作区协调及受管理 worktree；不按租约超时推断进程结束。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import files, git_workspace
from .store import encode, now


class FileLock:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT, 0o600), "r+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise ValueError("工作区或恢复协调器由另一执行器持有") from None

    def read(self):
        self.stream.seek(1)
        raw = self.stream.read(4096)
        return json.loads(raw) if raw else None

    def write(self, value):
        self.stream.seek(0)
        self.stream.write(b" " + (encode(value).encode() if value else b""))
        self.stream.truncate()
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def close(self):
        if self.stream.closed:
            return
        if os.name == "nt":
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        self.stream.close()


def workspace_key(root):
    root = root.resolve(strict=True)
    try:
        top = git_workspace._git(root, "rev-parse", "--show-toplevel", check=False)
        if top.returncode == 0:
            root = Path(top.stdout.strip()).resolve(strict=True)
    except (OSError, ValueError):
        pass
    identity = files.file_identity(root)
    return hashlib.sha256(encode({"canonical": os.path.normcase(str(root)), **identity}).encode()).hexdigest()


class Workspaces:
    def __init__(self, owner):
        self.owner, self.store = owner, owner.store
        self.instance = uuid.uuid4().hex
        self.account = hashlib.sha256(str(self.store.path.resolve()).encode()).hexdigest()
        self.directory = self.store.path.parent.parent / "workspace-coordination"
        self.held = {}
        self.waiting = []
        self.limit = 2

    def _take(self, run, root):
        key = run["workspace_key"]
        if key in self.held:
            return False, "同一真实工作区已有任务或保留进程"
        try:
            lock = FileLock(self.directory / (key + ".lock"))
        except ValueError:
            return False, "另一执行器持有工作区；等待核对"
        try:
            previous = lock.read()
            if previous:
                if previous.get("account") != self.account:
                    return False, "另一账号留下未核实操作，请由原账号核对"
                try:
                    old = self.store.run(previous["run_id"])
                    report = self.owner.recovery.inspect(old, for_lease=True)
                except (KeyError, ValueError, OSError):
                    return False, "原持有者现场不可核实"
                if report["blockers"]:
                    return False, "原持有者有未核实副作用，工作区保持锁定"
            row = self.store.db.execute("SELECT generation FROM workspace_leases WHERE workspace_key=?", (key,)).fetchone()
            generation = row[0] + 1 if row else 1
            lock.write({"account": self.account, "run_id": run["id"], "owner": self.instance, "generation": generation})
            with self.store.transaction():
                self.store.db.execute("INSERT INTO workspace_leases VALUES (?,?,?,?,?,?) ON CONFLICT(workspace_key) DO UPDATE SET run_id=excluded.run_id,owner=excluded.owner,generation=excluded.generation,state=excluded.state,updated_at=excluded.updated_at",
                    (key, run["id"], self.instance, generation, "held", now()))
            self.held[key] = {"run_id": run["id"], "lock": lock, "generation": generation}
            run.update(workspace_key=key, lease_generation=generation)
            lock = None
            return True, None
        finally:
            if lock:
                lock.close()

    async def acquire(self, run, root):
        self.waiting.append(run["id"])
        try:
            while True:
                if run.get("cancel_requested_at"):
                    raise asyncio.CancelledError
                acquired, reason = False, "账号并发上限为 2 个工作区"
                if run.get("pause_requested"):
                    await self.owner.controls.boundary(run)
                prior_same_workspace = any(self.owner.live.get(identifier, {}).get("workspace_key") == run["workspace_key"]
                    for identifier in self.waiting[:self.waiting.index(run["id"])])
                if len(self.held) < self.limit and not prior_same_workspace:
                    acquired, reason = self._take(run, root)
                if acquired:
                    run.update(queue_reason=None, queue_position=None)
                    self.owner.event(run, "workspace.acquired", workspace_key=run["workspace_key"], generation=run["lease_generation"])
                    return
                if run.get("recovery_contract_version") != "1.0":
                    raise ValueError(reason)
                position = self.waiting.index(run["id"]) + 1
                if run.get("queue_reason") != reason or run.get("queue_position") != position:
                    run.update(status="queued", queue_reason=reason, queue_position=position)
                    self.owner.event(run, "run.queued", reason=reason, position=position)
                await asyncio.sleep(0.1)
        finally:
            self.waiting.remove(run["id"])

    def release(self, run):
        key = run.get("workspace_key")
        slot = self.held.get(key)
        if not slot or slot["run_id"] != run["id"]:
            return
        if any(s["record"]["run_id"] == run["id"] for s in self.owner.execution_sessions.slots.values()):
            return
        unknown = bool(run.get("uncertain_operations")) or any(
            e["status"] == "unknown" or e.get("error_code") == "execution_unknown" for e in self.store.run(run["id"])["executions"])
        unknown |= any(record["status"] == "unknown" or not record.get("stopped")
            for record in self.store.execution_sessions.list(run["session_id"]) if record["run_id"] == run["id"])
        for patch in self.owner.patches.list(run["id"]):
            latest = {item["change_id"]: item for item in patch["journal"]}
            unknown |= any(item["status"] == "applying" for item in latest.values())
        try:
            if not unknown:
                slot["lock"].write(None)
            with self.store.transaction():
                self.store.db.execute("UPDATE workspace_leases SET state=?,updated_at=? WHERE workspace_key=? AND owner=? AND generation=?",
                    ("reconcile" if unknown else "released", now(), key, self.instance, slot["generation"]))
        finally:
            slot["lock"].close()
            self.held.pop(key, None)

    def assert_idle(self, root):
        key = workspace_key(root)
        row = self.store.db.execute("SELECT state FROM workspace_leases WHERE workspace_key=?", (key,)).fetchone()
        if key in self.held or row and row[0] != "released":
            raise ValueError("工作区仍有活动任务、保留进程或未核实副作用")

    @contextmanager
    def exclusive(self, root):
        """界面直接变更同样使用跨执行器锁，不能绕过任务调度。"""
        self.assert_idle(root)
        key = workspace_key(root)
        lock = FileLock(self.directory / (key + ".lock"))
        try:
            if lock.read():
                raise ValueError("工作区有未核实的原持有者，操作未执行")
            yield
        finally:
            lock.close()

    def create_worktree(self, project_id, ref, request_id):
        self.store.get("project", project_id)
        candidates = [w for w in self.store.list("workspace") if w["project_id"] == project_id]
        prior = next((w for w in candidates if w.get("worktree_request_id") == request_id), None)
        if prior:
            if prior.get("selected_ref") != ref:
                raise ValueError("worktree 请求标识已用于其他起点")
            if prior.get("worktree_state") != "ready":
                raise ValueError("该创建请求尚未核实完成；目录与记录已保留，请核对后使用新的请求")
            return prior
        main = next(w for w in candidates if w["kind"] == "root")
        root = self.owner.root(project_id, main["id"])
        self.assert_idle(root)
        if not git_workspace.inspect(root)["is_git"]:
            raise ValueError("所选目录不是可用的 Git 工作树")
        if ref.startswith("-") or any(c in ref for c in "\x00\r\n"):
            raise ValueError("Git 起点无效")
        selected = git_workspace._git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").stdout.strip()
        parent = self.store.path.parent.parent / "worktrees" / self.account[:16]
        parent.mkdir(parents=True, exist_ok=True)
        if parent.resolve() != parent.absolute() or shutil.disk_usage(parent).free < 256 * 1024 * 1024:
            raise ValueError("worktree 目录不安全或可用空间不足 256 MiB")
        target = parent / uuid.uuid4().hex[:12]
        record = self.store.create("workspace", {"project_id": project_id, "kind": "git_worktree", "root_path": str(target),
            "main_root": str(root), "selected_ref": ref, "head_sha": selected, "branch_name": None,
            "worktree_request_id": request_id, "managed": True, "status": "conflict", "worktree_state": "creating", "last_used_at": now()})
        try:
            with self.exclusive(root):
                git_workspace._git(root, "worktree", "add", "--detach", "--", str(target), selected)
            if git_workspace.inspect(target)["head_sha"] != selected:
                raise ValueError("worktree 起点验证失败")
            common = git_workspace._git(target, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
            return self.store.update("workspace", record["id"], status="active", worktree_state="ready", root_identity=files.file_identity(target), git_common_dir=common)
        except (ValueError, OSError):
            self.store.update("workspace", record["id"], status="conflict", worktree_state="error")
            raise

    def remove_worktree(self, project_id, workspace_id):
        record = self.store.get("workspace", workspace_id)
        if record["project_id"] != project_id or not record.get("managed") or record["kind"] != "git_worktree":
            raise ValueError("只能清理本应用创建的 worktree")
        if record.get("worktree_state") == "removed":
            return record
        root = self.owner.root(project_id, workspace_id)
        parent = (self.store.path.parent.parent / "worktrees" / self.account[:16]).resolve()
        if root.parent != parent or files.file_identity(root) != record.get("root_identity"):
            raise ValueError("worktree 路径或身份已变化")
        self.assert_idle(root)
        if any(r["workspace_id"] == workspace_id for r in self.store.runs(active_only=True)):
            raise ValueError("worktree 仍有排队或暂停的任务")
        common = git_workspace._git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        if common != record.get("git_common_dir"):
            raise ValueError("worktree Git 归属已变化")
        if git_workspace._git(root, "status", "--porcelain=v1", "--untracked-files=all", "--ignored").stdout:
            raise ValueError("worktree 存在修改、未跟踪或忽略文件，已保留")
        if git_workspace.inspect(root)["head_sha"] != record["head_sha"]:
            raise ValueError("worktree 出现后续提交，已保留")
        with self.exclusive(root):
            git_workspace._git(Path(record["main_root"]), "worktree", "remove", "--", str(root))
        return self.store.update("workspace", workspace_id, status="archived", worktree_state="removed")
