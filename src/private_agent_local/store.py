"""按本机数据所有者隔离的 SQLite 存储和可回退迁移。"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 3
TABLES = {"project": "projects", "workspace": "workspaces", "session": "sessions", "message": "messages"}
COLLECTIONS = {"events": "sequence", "approvals": "id", "executions": "id"}
INLINE_BYTES = 32 * 1024


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.blobs = path.parent / "artifacts"
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=5)
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA busy_timeout=5000")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self._migrate()
            self._recover()
        except BaseException:
            self.db.close()
            raise

    @contextmanager
    def transaction(self):
        """保存点允许消息、运行和首个事件共享一个事务。"""
        name = "tx_" + uuid.uuid4().hex
        self.db.execute(f"SAVEPOINT {name}")
        try:
            yield
            self.db.execute(f"RELEASE SAVEPOINT {name}")
        except BaseException:
            self.db.execute(f"ROLLBACK TO SAVEPOINT {name}")
            self.db.execute(f"RELEASE SAVEPOINT {name}")
            raise

    def _backup(self) -> dict:
        backup = self.path.with_name(f"{self.path.stem}.pre-v2-{uuid.uuid4().hex}.sqlite3")
        target = sqlite3.connect(backup)
        try:
            self.db.backup(target)
            if target.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise ValueError("迁移备份校验失败，未修改原始记录")
        finally:
            target.close()
        return {"filename": backup.name, "sha256": hashlib.sha256(backup.read_bytes()).hexdigest()}

    def _migrate(self):
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise ValueError("本机数据库由更新版本创建，请升级客户端，不要降级写入")
        if version == SCHEMA_VERSION:
            return
        if version == 2:
            backup = self._backup()
            with self.transaction():
                self._history_schema()
                self.db.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (SCHEMA_VERSION, now(), encode({"backup": backup, "change": "history_imports"})))
                self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            return
        names = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        legacy = "objects" in names
        if legacy != ("runs" in names):
            raise ValueError("旧版本机数据库结构不完整，未执行迁移")
        backup = self._backup() if legacy else None
        with self.transaction():
            if legacy:
                self.db.execute("ALTER TABLE objects RENAME TO legacy_objects_v1")
                self.db.execute("ALTER TABLE runs RENAME TO legacy_runs_v1")
            self.db.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, evidence TEXT NOT NULL)")
            self.db.execute("CREATE TABLE record_ids(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL)")
            for table in TABLES.values():
                self.db.execute(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY REFERENCES record_ids(id), project_id INTEGER, session_id INTEGER, data TEXT NOT NULL)")
                self.db.execute(f"CREATE INDEX {table}_project ON {table}(project_id,id)")
                self.db.execute(f"CREATE INDEX {table}_session ON {table}(session_id,id)")
            self.db.execute("CREATE TABLE runs(id TEXT PRIMARY KEY, session_id INTEGER, project_id INTEGER, status TEXT NOT NULL, client_request_id TEXT UNIQUE, data TEXT NOT NULL)")
            self.db.execute("CREATE INDEX runs_session ON runs(session_id)")
            self.db.execute("CREATE INDEX runs_status ON runs(status)")
            for table, key in COLLECTIONS.items():
                column_type = "INTEGER" if key == "sequence" else "TEXT"
                self.db.execute(f"CREATE TABLE {table}(run_id TEXT NOT NULL REFERENCES runs(id), {key} {column_type} NOT NULL, data TEXT NOT NULL, PRIMARY KEY(run_id,{key}))")
            self.db.execute("CREATE TABLE grants(id TEXT PRIMARY KEY, session_id INTEGER NOT NULL, project_id INTEGER NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT, data TEXT NOT NULL)")
            self.db.execute("CREATE INDEX grants_session ON grants(session_id,expires_at)")
            self.db.execute("CREATE TABLE audit_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL)")
            self._history_schema()
            counts = {"objects": 0, "runs": 0}
            if legacy:
                for item_id, kind, data in self.db.execute("SELECT id,kind,data FROM legacy_objects_v1 ORDER BY id").fetchall():
                    value = json.loads(data)
                    if kind not in TABLES or value.get("id") != item_id:
                        raise ValueError("旧版记录类型或标识异常，迁移已回滚")
                    self.db.execute("INSERT INTO record_ids(id,kind) VALUES (?,?)", (item_id, kind))
                    self._put_object(kind, value)
                    if self.get(kind, item_id) != value:
                        raise ValueError("旧版记录迁移内容校验失败")
                    counts["objects"] += 1
                for run_id, data in self.db.execute("SELECT id,data FROM legacy_runs_v1 ORDER BY rowid").fetchall():
                    value = json.loads(data)
                    if value.get("id") != run_id:
                        raise ValueError("旧版运行标识异常，迁移已回滚")
                    self._save_run(value)
                    if self.run(run_id) != {**value, **{key: value.get(key, []) for key in COLLECTIONS}}:
                        raise ValueError("旧版运行迁移内容校验失败")
                    counts["runs"] += 1
            self.db.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (SCHEMA_VERSION, now(), encode({"backup": backup, "counts": counts})))
            self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _history_schema(self):
        self.db.execute("CREATE TABLE history_imports(id TEXT PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL, data TEXT NOT NULL, archive TEXT NOT NULL)")

    def _recover(self):
        """重启关闭授权并记录不确定的外部副作用，绝不重放命令或文件写入。"""
        with self.transaction():
            for run in self.runs(active_only=True):
                run.update(status="failed", active_in_process=False, error_code="desktop_restarted",
                           error_message="本机执行服务已重启；未自动重放操作，请检查项目后重试", completed_at=now())
                for approval in run["approvals"]:
                    if approval["status"] == "pending":
                        approval["status"] = "cancelled"
                for execution in run["executions"]:
                    if execution["status"] == "running":
                        execution.update(status="unknown", error_code="desktop_restarted", completed_at=now())
                sequence = len(run["events"]) + 1
                run["events"].append({"sequence": sequence, "type": "run.failed", "step_id": None, "created_at": now(),
                                      "payload": {"error_code": "desktop_restarted", "replayed": False}})
                run["last_event_sequence"] = sequence
                self.save_run(run)
            for (grant_id,) in self.db.execute("SELECT id FROM grants WHERE revoked_at IS NULL").fetchall():
                self.revoke_grant(grant_id, "app_exit")

    def _pack(self, value: dict) -> str:
        data = encode(value)
        content = data.encode("utf-8")
        if len(content) <= INLINE_BYTES:
            return data
        digest = hashlib.sha256(content).hexdigest()
        self.blobs.mkdir(exist_ok=True)
        target = self.blobs / digest
        if not target.exists():
            temporary = self.blobs / f".{uuid.uuid4().hex}.tmp"
            try:
                with temporary.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return encode({"$artifact": digest, "bytes": len(content)})

    def _unpack(self, data: str) -> dict:
        value = json.loads(data)
        if set(value) == {"$artifact", "bytes"}:
            digest = value["$artifact"]
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("本机内容引用无效")
            content = (self.blobs / digest).read_bytes()
            if len(content) != value["bytes"] or hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("本机内容 SHA-256 校验失败")
            return json.loads(content)
        return value

    def _put_object(self, kind: str, value: dict):
        self.db.execute(f"INSERT INTO {TABLES[kind]}(id,project_id,session_id,data) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id,session_id=excluded.session_id,data=excluded.data",
                        (value["id"], value.get("project_id"), value.get("session_id"), self._pack(value)))

    def create(self, kind: str, data: dict) -> dict:
        if kind not in TABLES:
            raise ValueError("不支持的本机记录类型")
        value = {"created_at": now(), "updated_at": now(), **data}
        with self.transaction():
            value["id"] = self.db.execute("INSERT INTO record_ids(kind) VALUES (?)", (kind,)).lastrowid
            self._put_object(kind, value)
        return value

    def get(self, kind: str, item_id: int) -> dict:
        row = self.db.execute(f"SELECT data FROM {TABLES[kind]} WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise KeyError("本机记录不存在")
        return self._unpack(row[0])

    def list(self, kind: str, *, session_id: int | None = None) -> list[dict]:
        clause = " WHERE session_id=?" if session_id is not None else ""
        rows = self.db.execute(f"SELECT data FROM {TABLES[kind]}{clause} ORDER BY id DESC", (session_id,) if clause else ())
        return [self._unpack(row[0]) for row in rows]

    def update(self, kind: str, item_id: int, **changes) -> dict:
        with self.transaction():
            item = self.get(kind, item_id)
            item.update(changes, updated_at=now())
            self._put_object(kind, item)
        return item

    def _save_run(self, run: dict, *, appended_event: dict | None = None):
        value = {key: value for key, value in run.items() if key not in COLLECTIONS}
        self.db.execute("INSERT INTO runs(id,session_id,project_id,status,client_request_id,data) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,data=excluded.data",
                        (run["id"], run.get("session_id"), run.get("project_id"), run["status"], run.get("client_request_id") or None, self._pack(value)))
        for table, key in COLLECTIONS.items():
            items = [appended_event] if table == "events" and appended_event is not None else run.get(table, [])
            for index, item in enumerate(items, 1):
                identifier = item.get(key, f"legacy-{index}")
                data = self._pack(item)
                prior = self.db.execute(f"SELECT data FROM {table} WHERE run_id=? AND {key}=?", (run["id"], identifier)).fetchone()
                if prior and prior[0] == data:
                    continue
                if prior and table == "events":
                    raise ValueError("已保存的运行事件不可修改")
                self.db.execute(f"INSERT INTO {table}(run_id,{key},data) VALUES (?,?,?) ON CONFLICT(run_id,{key}) DO UPDATE SET data=excluded.data", (run["id"], identifier, data))

    def save_run(self, run: dict) -> None:
        run["updated_at"] = now()
        with self.transaction():
            self._save_run(run)

    def append_event(self, run: dict, event: dict) -> None:
        """运行中的热路径只追加新事件，避免每次事件都重读整条历史。"""
        run["updated_at"] = now()
        with self.transaction():
            prior = self.db.execute("SELECT COALESCE(MAX(sequence),0) FROM events WHERE run_id=?", (run["id"],)).fetchone()[0]
            if event["sequence"] != prior + 1:
                raise ValueError("运行事件序号不连续，未覆盖历史")
            self._save_run(run, appended_event=event)

    def run_state(self, run_id: str) -> dict:
        row = self.db.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("本机任务不存在")
        return self._unpack(row[0])

    def run(self, run_id: str) -> dict:
        value = self.run_state(run_id)
        for table in COLLECTIONS:
            value[table] = [self._unpack(row[0]) for row in self.db.execute(f"SELECT data FROM {table} WHERE run_id=? ORDER BY rowid", (run_id,))]
        return value

    def find_request(self, request_id: str | None) -> dict | None:
        if not request_id:
            return None
        row = self.db.execute("SELECT data FROM runs WHERE client_request_id=?", (request_id,)).fetchone()
        return self._unpack(row[0]) if row else None

    def has_active_run(self) -> bool:
        return self.db.execute("SELECT 1 FROM runs WHERE status IN ('created','running','waiting_approval') LIMIT 1").fetchone() is not None

    def events(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict]:
        return [self._unpack(row[0]) for row in self.db.execute("SELECT data FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?", (run_id, after, limit))]

    def runs(self, *, active_only=False) -> list[dict]:
        clause = " WHERE status IN ('created','running','waiting_approval')" if active_only else ""
        ids = self.db.execute(f"SELECT id FROM runs{clause} ORDER BY rowid DESC").fetchall()
        return [self.run(row[0]) for row in ids]

    def session_run_states(self, session_id: int):
        """逐条读取会话运行摘要，不加载工具事件与文件正文集合。"""
        for row in self.db.execute("SELECT data FROM runs WHERE session_id=? ORDER BY rowid DESC", (session_id,)):
            yield self._unpack(row[0])

    def audit(self, kind: str, **data):
        with self.transaction():
            self.db.execute("INSERT INTO audit_events(created_at,kind,data) VALUES (?,?,?)", (now(), kind, encode(data)))

    def grant(self, session_id: int, project_id: int, expires_at: str) -> dict:
        with self.transaction():
            grant = {"id": str(uuid.uuid4()), "session_id": session_id, "project_id": project_id, "granted_at": now(),
                     "expires_at": expires_at, "revoked_at": None, "revoke_reason": None}
            self.db.execute("INSERT INTO grants VALUES (?,?,?,?,?,?)", (grant["id"], session_id, project_id, expires_at, None, encode(grant)))
            self.audit("full_access.granted", grant_id=grant["id"], session_id=session_id, project_id=project_id, expires_at=expires_at)
        return grant

    def active_grant(self, session_id: int) -> dict | None:
        row = self.db.execute("SELECT data FROM grants WHERE session_id=? AND revoked_at IS NULL AND expires_at>? ORDER BY rowid DESC LIMIT 1", (session_id, now())).fetchone()
        return json.loads(row[0]) if row else None

    def revoke_grant(self, grant_id: str, reason: str) -> bool:
        with self.transaction():
            row = self.db.execute("SELECT data FROM grants WHERE id=? AND revoked_at IS NULL", (grant_id,)).fetchone()
            if row is None:
                return False
            grant = json.loads(row[0])
            grant.update(revoked_at=now(), revoke_reason=reason)
            self.db.execute("UPDATE grants SET revoked_at=?,data=? WHERE id=?", (grant["revoked_at"], encode(grant), grant_id))
            self.audit("full_access.revoked", grant_id=grant_id, reason=reason)
        return True
