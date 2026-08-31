"""显式迁移历史，保留原始记录与备份；不恢复授权、不重放副作用。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections import defaultdict
from pathlib import Path

from private_agent_core.history import (
    FIELDS,
    FORMAT,
    MAX_BYTES,
    encode_archive,
    validate_archive,
)

from . import files
from .store import Store, encode, now


def _unpack_legacy(source: Path, value: str):
    if len(value.encode("utf-8")) > MAX_BYTES:
        raise ValueError("旧记录正文超过大小限制")
    data = json.loads(value)
    if isinstance(data, dict) and set(data) == {"$artifact", "bytes"}:
        digest = data["$artifact"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("旧记录内容引用无效")
        blob = files.within(source.parent, f"artifacts/{digest}")
        if blob.stat().st_size > MAX_BYTES:
            raise ValueError("旧记录内容过大")
        with blob.open("rb") as stream:
            content = stream.read(MAX_BYTES + 1)
        if len(content) != data["bytes"] or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("旧记录内容 SHA-256 校验失败")
        return json.loads(content)
    return data


def archive_sqlite(path: Path, *, authority: str, owner_id: int) -> dict:
    expected = hashlib.sha256(f"{authority}\0{owner_id}".encode()).hexdigest()
    if path.parent.name != expected:
        raise ValueError("SQLite 所在账号目录与当前身份不匹配，不允许猜测或合并账号")
    records = {key: [] for key in FIELDS}
    count, size = 0, 0

    def append(kind, row):
        nonlocal count, size
        filtered = {key: row[key] for key in FIELDS[kind] if key in row}
        count += 1
        size += len(encode_archive(filtered))
        if count > 50000 or size > MAX_BYTES:
            raise ValueError("历史超过 50000 条或 64 MiB，请分批迁移")
        records[kind].append(filtered)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        if db.execute("PRAGMA user_version").fetchone()[0] not in {0, 2, 3}:
            raise ValueError("SQLite 来自不支持的版本，请使用该版本的导出功能")
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("旧 SQLite 完整性校验失败")
        tables = {"project": "projects", "workspace": "workspaces", "session": "sessions", "message": "messages"}
        if "objects" in names:
            for kind, raw in db.execute(f"SELECT kind,substr(data,1,{MAX_BYTES + 1}) FROM objects ORDER BY id LIMIT 50001"):
                if kind not in tables:
                    raise ValueError("旧 SQLite 存在未知记录类型")
                append(tables[kind], _unpack_legacy(path, raw))
        else:
            if not set(tables.values()) <= names:
                raise ValueError("不支持的 SQLite 结构")
            for table in tables.values():
                for row in db.execute(f"SELECT substr(data,1,{MAX_BYTES + 1}) FROM {table} ORDER BY id LIMIT 50001"):
                    append(table, _unpack_legacy(path, row[0]))
        for (raw,) in db.execute(f"SELECT substr(data,1,{MAX_BYTES + 1}) FROM runs ORDER BY id LIMIT 50001"):
            run = _unpack_legacy(path, raw)
            append("runs", run)
            for ordinal, step in enumerate(run.get("steps", []), 1):
                append("run_steps", {**step, "id": step.get("id") or f"{run['id']}:step:{ordinal}",
                    "run_id": run["id"], "ordinal": step.get("ordinal", ordinal),
                    "error_message": step.get("error_message", step.get("error"))})
            for kind in ("events", "approvals", "executions"):
                values = run.get(kind, []) if "objects" in names else (_unpack_legacy(path, row[0]) for row in db.execute(f"SELECT substr(data,1,{MAX_BYTES + 1}) FROM {kind} WHERE run_id=? ORDER BY rowid LIMIT 50001", (run["id"],)))
                for item in values:
                    item = {**item, "run_id": run["id"]}
                    if kind == "events":
                        item.update(id=f"{run['id']}:{item['sequence']}", event_type=item.get("type"), payload_json=item.get("payload", {}))
                    elif kind == "approvals":
                        item["arguments_json"] = item.get("arguments", {})
                    else:
                        item["output_json"] = item.get("output")
                    append(kind, item)
    finally:
        db.close()
    archive = {"format": FORMAT, "source": {"authority": authority, "owner_id": owner_id}, "records": records}
    return validate_archive(archive, authority=authority, owner_id=owner_id)


def load_history(source: str, *, authority: str, owner_id: int) -> tuple[dict, str]:
    path = Path(source)
    if not path.is_absolute() or path.resolve() != path or path.is_symlink() or files.secret_path(path):
        raise ValueError("请选择普通本机历史 JSON 或账号 SQLite 文件，不接受链接或凭据文件")
    if path.suffix.lower() in {".sqlite3", ".sqlite", ".db"}:
        archive = archive_sqlite(path, authority=authority, owner_id=owner_id)
        content = encode_archive(archive)
    else:
        if path.suffix.lower() != ".json" or path.stat().st_size > MAX_BYTES:
            raise ValueError("历史包必须为不超过 64 MiB 的 JSON 文件")
        with path.open("rb") as stream:
            content = stream.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError("历史包超过 64 MiB")
        archive = json.loads(content)
    validate_archive(archive, authority=authority, owner_id=owner_id)
    return archive, hashlib.sha256(content).hexdigest()


def preview_history(source: str, *, authority: str, owner_id: int) -> dict:
    archive, digest = load_history(source, authority=authority, owner_id=owner_id)
    return {"sha256": digest, "source": archive["source"],
            "counts": {kind: len(rows) for kind, rows in archive["records"].items()},
            "projects": archive["records"]["projects"], "requires_directory_mapping": True,
            "warnings": ["AgentTask 计划及非 Coding 会话保留为只读历史，不转换为 AgentRun", "旧审批、完全访问授权和运行中的命令不会恢复", "迁移包包含聊天与代码片段，请妥善保管"]}


def fingerprint(store: Store) -> str:
    digest = hashlib.sha256()
    for table in ("record_ids", "projects", "workspaces", "sessions", "messages", "runs", "events", "approvals", "executions", "grants", "audit_events", "schema_migrations", "sqlite_sequence"):
        digest.update(table.encode())
        for row in store.db.execute(f"SELECT * FROM {table} ORDER BY rowid"):
            digest.update(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode())
    return digest.hexdigest()


def apply_history(store: Store, source: str, digest: str, mappings: dict[str, str], *, authority: str, owner_id: int) -> dict:
    archive, current_digest = load_history(source, authority=authority, owner_id=owner_id)
    if digest != current_digest:
        raise ValueError("预览后的历史包已变化，请重新预览；未导入记录")
    prior = store.db.execute("SELECT data FROM history_imports WHERE sha256=?", (digest,)).fetchone()
    if prior:
        return json.loads(prior[0])
    if store.has_active_run():
        raise ValueError("请先停止当前本机任务，再迁移历史")
    records = archive["records"]
    project_ids = {str(p["id"]) for p in records["projects"]}
    if set(mappings) - project_ids:
        raise ValueError("目录映射包含未知项目")
    roots = {key: str(files.authorize_root(value)) for key, value in mappings.items()}
    backup = store._backup()
    imported = {"id": str(uuid.uuid4()), "sha256": digest, "source": archive["source"], "created_at": now(),
                "backup": backup, "counts": {kind: len(rows) for kind, rows in records.items()}, "imported_counts": {}}
    maps: dict[str, dict] = {kind: {} for kind in ("projects", "workspaces", "sessions", "messages", "runs")}
    related = {kind: defaultdict(list) for kind in ("events", "approvals", "executions")}
    for kind in related:
        for item in records[kind]:
            related[kind][item["run_id"]].append(item)
    with store.transaction():
        for item in records["projects"]:
            root = roots.get(str(item["id"]))
            if root:
                value = store.create("project", {"name": item.get("name") or "导入项目", "root_path": root, "status": "active", "authorized": True, "import_id": imported["id"]})
                maps["projects"][item["id"]] = value["id"]
        for item in records["workspaces"]:
            project = maps["projects"].get(item.get("project_id"))
            if project and item.get("kind") == "root":
                value = store.create("workspace", {"project_id": project, "kind": "root", "root_path": roots[str(item["project_id"])], "branch_name": None, "head_sha": None, "status": "active", "last_used_at": None})
                maps["workspaces"][item["id"]] = value["id"]
        for item in records["sessions"]:
            project, workspace = maps["projects"].get(item.get("project_id")), maps["workspaces"].get(item.get("workspace_id"))
            if item.get("kind") == "coding" and project and workspace:
                if store.get("workspace", workspace)["project_id"] != project:
                    raise ValueError("会话项目与工作区不匹配")
                value = store.create("session", {"project_id": project, "workspace_id": workspace, "kind": "coding", "title": item.get("title") or "导入任务", "last_run_id": None,
                    "pinned_at": item.get("pinned_at"), "archived_at": item.get("archived_at"), "created_at": item.get("created_at") or now()})
                maps["sessions"][item["id"]] = value["id"]
        for item in records["messages"]:
            session = maps["sessions"].get(item.get("session_id"))
            if session:
                if item.get("role") not in {"user", "assistant", "system"} or not isinstance(item.get("content"), str):
                    raise ValueError("消息角色或内容无效")
                value = store.create("message", {"session_id": session, "role": item["role"], "content": item["content"], "created_at": item.get("created_at") or now()})
                maps["messages"][item["id"]] = value["id"]
        for item in records["runs"]:
            session = maps["sessions"].get(item.get("session_id"))
            if not session:
                continue
            binding = store.get("session", session)
            run_id = str(uuid.uuid4())
            status = item.get("status")
            terminal = status in {"completed", "failed", "cancelled", "timed_out", "limit_exceeded"}
            run = {**item, "id": run_id, "session_id": session, "project_id": binding["project_id"], "workspace_id": binding["workspace_id"],
                   "status": status if terminal else "failed", "permission_mode": "confirm", "full_access_grant_id": None,
                   "active_in_process": False, "client_request_id": None, "steps": [], "plan": None, "artifacts": [],
                   "events": [], "approvals": [], "executions": [], "cancel_requested_at": None, "cost_usd": item.get("cost_usd"),
                   "base_head_sha": None, "base_branch_name": None, "base_git_dirty": None, "output": item.get("output"),
                   "completed_at": item.get("completed_at") or now(), "created_at": item.get("created_at") or now(),
                   "error_code": item.get("error_code") if terminal else "history_import_interrupted",
                   "error_message": item.get("error_message") if terminal else "旧运行只保留历史，未重放任何操作"}
            for key in ("input_tokens", "output_tokens", "cached_tokens", "tool_call_count"):
                value = item.get(key) or 0
                if type(value) is not int or value < 0:
                    raise ValueError("运行计量无效")
                run[key] = value
            for event in sorted(related["events"][item["id"]], key=lambda e: e["sequence"]):
                run["events"].append({"sequence": len(run["events"]) + 1, "type": event["event_type"], "payload": event.get("payload_json") or {}, "step_id": None, "created_at": event.get("created_at") or now()})
            run["events"].append({"sequence": len(run["events"]) + 1, "type": "history.imported", "payload": {"original_run_id": item["id"], "replayed": False}, "step_id": None, "created_at": now()})
            run["last_event_sequence"] = len(run["events"])
            for approval in related["approvals"][item["id"]]:
                run["approvals"].append({**approval, "id": str(uuid.uuid4()), "run_id": run_id, "status": "cancelled" if approval.get("status") == "pending" else approval.get("status"), "arguments": approval.get("arguments_json") or {}})
            for execution in related["executions"][item["id"]]:
                run["executions"].append({**execution, "id": str(uuid.uuid4()), "run_id": run_id, "status": "unknown" if execution.get("status") in {"running", "claimed", "pending"} else execution.get("status"), "output": execution.get("output_json")})
            store.save_run(run)
            maps["runs"][item["id"]] = run_id
        for item in records["sessions"]:
            session, run_id = maps["sessions"].get(item["id"]), maps["runs"].get(item.get("last_run_id"))
            if session and run_id:
                store.update("session", session, last_run_id=run_id)
        imported["imported_counts"] = {kind: len(values) for kind, values in maps.items()}
        store.audit("history.imported", import_id=imported["id"], sha256=digest, counts=imported["imported_counts"])
        imported["rollback_fingerprint"] = fingerprint(store)
        store.db.execute("INSERT INTO history_imports VALUES (?,?,?,?)", (imported["id"], digest, encode(imported), store._pack(archive)))
    return imported


def rollback_history(store: Store, import_id: str) -> dict:
    row = store.db.execute("SELECT data FROM history_imports WHERE id=?", (import_id,)).fetchone()
    if not row:
        raise KeyError("迁移记录不存在")
    imported = json.loads(row[0])
    if store.has_active_run() or fingerprint(store) != imported["rollback_fingerprint"]:
        raise ValueError("迁移后已有其他修改，不能自动回滚；请先导出新记录并人工核对备份")
    backup = files.within(store.path.parent, imported["backup"]["filename"])
    if hashlib.sha256(backup.read_bytes()).hexdigest() != imported["backup"]["sha256"]:
        raise ValueError("迁移备份校验失败，未回滚")
    source = sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True)
    try:
        source.backup(store.db)
    finally:
        source.close()
    return {"rolled_back": True, "retained_backup": backup.name}
