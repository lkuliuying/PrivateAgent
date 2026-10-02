"""本机长期记忆的事实存储、使用策略与遗忘标记。"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .store import encode, now


class MemorySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = False
    use_memories: bool = True
    generate_memories: bool = True
    exclude_external_context: bool = True
    model_profile_id: str | None = Field(default=None, min_length=1, max_length=128)
    idle_seconds: int = Field(default=300, ge=30, le=86400)
    max_calls_per_day: int = Field(default=12, ge=1, le=100)


class MemoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    scope: Literal["project", "user"] = "project"
    kind: Literal["preference", "project", "workflow", "reference"] = "project"
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=1600)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope == "user" and self.kind != "preference":
            raise ValueError("跨项目记忆仅支持用户偏好")
        validate_text(self.title + "\n" + self.content)
        return self


SECRET_PATTERN = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----|\b(?:sk-(?:ant-)?|ghp_|github_pat_|AKIA)[A-Za-z0-9_-]{12,}"
    r"|\bBearer\s+[A-Za-z0-9_.-]{8,}"
    r"|(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret|密码|密钥|令牌)"
    r"\s*[=:：]\s*[^\s,，;；]{4,}", re.IGNORECASE,
)


def sensitive(text: str, secrets=()) -> bool:
    return bool(SECRET_PATTERN.search(text) or any(value and len(value) >= 6 and value in text for value in secrets))


def validate_text(text: str):
    if sensitive(text) or any(ord(char) < 32 and char not in "\n\r\t" for char in text):
        raise ValueError("记忆含疑似凭据或无效字符，未保存")


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()


class MemoryConflict(ValueError):
    """版本变化时拒绝覆盖用户的并发编辑。"""


class MemoryStore:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, timeout=5)
        try:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1, 2}:
                raise ValueError("记忆数据库需要更新版本的客户端")
            self.db.execute("PRAGMA busy_timeout=5000")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            if version == 0:
                with self.transaction():
                    self.db.execute("CREATE TABLE settings(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
                    self.db.execute("CREATE TABLE session_settings(session_id INTEGER PRIMARY KEY, data TEXT NOT NULL)")
                    self.db.execute("CREATE TABLE memories(id TEXT PRIMARY KEY, scope_id INTEGER NOT NULL, stable_key TEXT NOT NULL, fingerprint TEXT NOT NULL, deleted INTEGER NOT NULL, data TEXT NOT NULL, UNIQUE(scope_id,stable_key))")
                    self.db.execute("CREATE INDEX memory_scope ON memories(scope_id,deleted)")
                    self.db.execute("CREATE TABLE extractions(session_id INTEGER PRIMARY KEY, through_ordinal INTEGER NOT NULL, data TEXT NOT NULL)")
                    self.db.execute("CREATE TABLE attempts(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, data TEXT NOT NULL)")
                    self.db.execute("INSERT INTO settings VALUES (1,?)", (encode({**MemorySettings().model_dump(), "version": 1, "generation_since": now()}),))
                    self.db.execute("PRAGMA user_version=1")
            if version < 2:
                if version == 1:
                    # 只备份旧版本；迁移失败保留原库和可恢复副本，不覆盖历史备份。
                    backup = path.with_name(path.name + ".schema1-" + uuid.uuid4().hex + ".bak")
                    target = sqlite3.connect(backup)
                    try:
                        self.db.backup(target)
                    finally:
                        target.close()
                self._upgrade_v2()
            # 原进程退出后不存在仍在运行的生成任务，避免界面永久显示“生成中”。
            with self.transaction():
                for identifier, raw in self.db.execute("SELECT id,data FROM attempts").fetchall():
                    value = json.loads(raw)
                    if value["state"] == "running":
                        value.update(state="cancelled", error="上次生成被进程退出中断")
                        self.db.execute("UPDATE attempts SET data=? WHERE id=?", (encode(value), identifier))
        except BaseException:
            self.db.close()
            raise

    def _upgrade_v2(self):
        with self.transaction():
            self.db.execute("CREATE TABLE memory_revisions(memory_id TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(memory_id,version))")
            self.db.execute("CREATE TABLE memory_receipts(run_id TEXT NOT NULL, call_id TEXT NOT NULL, request_sha256 TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(run_id,call_id))")
            for identifier, raw in self.db.execute("SELECT id,data FROM memories").fetchall():
                value = json.loads(raw)
                value.update(status="active", review_reason=None, supersedes_id=None, topic_key=value["stable_key"], legacy=value["origin"] == "generated")
                self.db.execute("UPDATE memories SET data=? WHERE id=?", (encode(value), identifier))
                self._revision(value, "migration")
            self.db.execute("PRAGMA user_version=2")

    def _revision(self, value: dict, reason: str):
        self.db.execute("INSERT INTO memory_revisions VALUES (?,?,?)", (
            value["id"], value["version"], encode({**value, "revision_reason": reason})))

    def revisions(self, project_id: int, identifier: str) -> list[dict]:
        self.get(project_id, identifier)
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT data FROM memory_revisions WHERE memory_id=? ORDER BY version DESC LIMIT 100", (identifier,))]

    def receipt(self, run_id: str, call_id: str, digest: str) -> dict | None:
        row = self.db.execute("SELECT request_sha256,data FROM memory_receipts WHERE run_id=? AND call_id=?", (run_id, call_id)).fetchone()
        if row and row[0] != digest:
            raise MemoryConflict("记忆操作标识已用于不同请求，未重复执行")
        return json.loads(row[1]) if row else None

    def save_receipt(self, run_id: str, call_id: str, digest: str, result: dict):
        # 回执只保存标识和版本，不保留可绕过遗忘的正文副本。
        self.db.execute("INSERT INTO memory_receipts VALUES (?,?,?,?)", (run_id, call_id, digest, encode(result)))

    @contextmanager
    def transaction(self):
        name = "memory_" + uuid.uuid4().hex
        self.db.execute(f"SAVEPOINT {name}")
        try:
            yield
            self.db.execute(f"RELEASE SAVEPOINT {name}")
        except BaseException:
            self.db.execute(f"ROLLBACK TO SAVEPOINT {name}")
            self.db.execute(f"RELEASE SAVEPOINT {name}")
            raise

    def settings(self) -> dict:
        return json.loads(self.db.execute("SELECT data FROM settings WHERE id=1").fetchone()[0])

    def save_settings(self, data: MemorySettings, expected_version: int) -> dict:
        current = self.settings()
        if current["version"] != expected_version:
            raise MemoryConflict("记忆设置已变化，请刷新后重试")
        enabled_before = current["enabled"] and current["generate_memories"]
        generation_since = current["generation_since"]
        if data.enabled and data.generate_memories and not enabled_before:
            generation_since = now()
        value = {**data.model_dump(), "version": current["version"] + 1, "generation_since": generation_since}
        with self.transaction():
            self.db.execute("UPDATE settings SET data=? WHERE id=1", (encode(value),))
        return value

    def session(self, session_id: int) -> dict:
        row = self.db.execute("SELECT data FROM session_settings WHERE session_id=?", (session_id,)).fetchone()
        return json.loads(row[0]) if row else {"use_memories": True, "generate_memories": True, "version": 1, "generation_since": ""}

    def save_session(self, session_id: int, use: bool, generate: bool, expected_version: int) -> dict:
        current = self.session(session_id)
        if current["version"] != expected_version:
            raise MemoryConflict("会话记忆设置已变化，请刷新后重试")
        value = {"use_memories": use, "generate_memories": generate, "version": current["version"] + 1,
                 "generation_since": now() if generate and not current["generate_memories"] else current["generation_since"]}
        with self.transaction():
            self.db.execute("INSERT INTO session_settings VALUES (?,?) ON CONFLICT(session_id) DO UPDATE SET data=excluded.data", (session_id, encode(value)))
        return value

    def list(self, project_id: int, *, limit=400) -> list[dict]:
        rows = self.db.execute("SELECT data FROM memories WHERE scope_id IN (0,?) AND deleted=0 ORDER BY rowid DESC LIMIT ?", (project_id, limit))
        return [json.loads(row[0]) for row in rows]

    def get(self, project_id: int, identifier: str) -> dict:
        row = self.db.execute("SELECT data FROM memories WHERE id=? AND scope_id IN (0,?) AND deleted=0", (identifier, project_id)).fetchone()
        if not row:
            raise KeyError("记忆不存在或不属于当前项目")
        return json.loads(row[0])

    def put(self, project_id: int, data: MemoryInput, *, identifier=None, expected_version=None,
            stable_key=None, sources=(), source_session_id=None, source_project_id=None, source_updated_at=None,
            status="active", review_reason=None, supersedes_id=None, supersedes_version=None, topic_key=None) -> dict | None:
        scope_id = 0 if data.scope == "user" else project_id
        digest = fingerprint(data.content)
        key = stable_key or uuid.uuid4().hex
        origin = "generated" if stable_key else "user"
        previous = None
        if identifier:
            previous = self.get(project_id, identifier)
            if previous["version"] != expected_version:
                raise MemoryConflict("记忆已变化，请刷新后重新编辑")
            if data.scope != previous["scope"]:
                raise ValueError("修改范围请另建记忆，避免意外跨项目共享")
            key = previous["stable_key"]
        elif stable_key:
            row = self.db.execute("SELECT data,deleted FROM memories WHERE scope_id=? AND stable_key=?", (scope_id, key)).fetchone()
            if row:
                previous = json.loads(row[0])
                if row[1] or previous["origin"] == "user" or (previous.get("source_updated_at", "") >= (source_updated_at or "")):
                    return None
            duplicate = self.db.execute("SELECT id FROM memories WHERE scope_id=? AND fingerprint=?", (scope_id, digest)).fetchone()
            if duplicate:
                return None
        if not previous and self.db.execute("SELECT COUNT(*) FROM memories WHERE scope_id=? AND deleted=0", (scope_id,)).fetchone()[0] >= 200:
            raise ValueError("此范围已达到 200 条记忆，请整理后重试")
        value = {**data.model_dump(), "id": identifier or (previous or {}).get("id") or uuid.uuid4().hex,
                 "project_id": scope_id or None, "stable_key": key, "origin": origin,
                 "version": (previous or {}).get("version", 0) + 1, "created_at": (previous or {}).get("created_at", now()),
                 "updated_at": now(), "source_session_id": source_session_id if not identifier else previous["source_session_id"],
                 "source_project_id": source_project_id if not identifier else previous["source_project_id"],
                 "source_updated_at": source_updated_at or (previous or {}).get("source_updated_at", ""),
                  "source_item_ids": list(sources) if sources else (previous or {}).get("source_item_ids", []),
                  "status": status, "review_reason": review_reason, "supersedes_id": supersedes_id,
                  "supersedes_version": supersedes_version,
                  "topic_key": topic_key or (previous or {}).get("topic_key", key)}
        value["legacy"] = False
        if identifier and source_session_id is not None:
            value.update(source_session_id=source_session_id, source_project_id=source_project_id)
        with self.transaction():
            self.db.execute("INSERT INTO memories VALUES (?,?,?,?,0,?) ON CONFLICT(id) DO UPDATE SET fingerprint=excluded.fingerprint, data=excluded.data", (value["id"], scope_id, key, digest, encode(value)))
            self._revision(value, "edited" if identifier else "generated" if stable_key else "created")
        return value

    def propose(self, project_id: int, data: MemoryInput, *, stable_key: str, auto_activate: bool = False, pending_reason="needs_confirmation", **source) -> dict | None:
        """后台纠正保留旧事实和新候选，不能静默覆盖用户确认内容。"""
        scope_id = 0 if data.scope == "user" else project_id
        row = self.db.execute("SELECT data,deleted FROM memories WHERE scope_id=? AND stable_key=?", (scope_id, stable_key)).fetchone()
        previous = json.loads(row[0]) if row else None
        if row and (row[1] or previous.get("source_updated_at", "") >= source.get("source_updated_at", "")):
            return None
        if self.db.execute("SELECT 1 FROM memories WHERE scope_id=? AND fingerprint=?", (scope_id, fingerprint(data.content))).fetchone():
            return None
        pending = next((item for item in self.list(project_id) if item.get("topic_key") == stable_key and item.get("status") == "pending_review"), None)
        if pending:
            return None
        reason = "conflict" if previous else None if auto_activate else pending_reason
        with self.transaction():
            result = self.put(project_id, data, stable_key=stable_key if not previous else "candidate:" + uuid.uuid4().hex,
                              status="pending_review" if reason else "active", review_reason=reason,
                              supersedes_id=previous["id"] if previous else None,
                              supersedes_version=(previous["version"] + (previous.get("status", "active") == "active")) if previous else None,
                              topic_key=stable_key, **source)
            if result and previous and previous.get("status", "active") == "active":
                self.set_state(project_id, previous["id"], previous["version"], "stale", "conflict")
            return result

    def set_state(self, project_id: int, identifier: str, expected_version: int, status: str, reason=None) -> dict:
        if status not in {"active", "pending_review", "stale"}:
            raise ValueError("记忆状态无效")
        value = self.get(project_id, identifier)
        if value["version"] != expected_version:
            raise MemoryConflict("记忆已变化，请刷新后重试")
        value.update(status=status, review_reason=reason, version=value["version"] + 1, updated_at=now())
        with self.transaction():
            self.db.execute("UPDATE memories SET data=? WHERE id=?", (encode(value), identifier))
            self._revision(value, "state_changed")
        return value

    def review(self, project_id: int, identifier: str, expected_version: int, decision: str) -> dict:
        candidate = self.get(project_id, identifier)
        if candidate["version"] != expected_version:
            raise MemoryConflict("记忆已变化，请刷新后重试")
        if decision not in {"accept", "reject", "stale"}:
            raise ValueError("记忆复核操作无效")
        if decision == "stale":
            return self.set_state(project_id, identifier, expected_version, "stale", "user_marked")
        if candidate.get("status") not in {"pending_review", "stale"}:
            raise ValueError("该记忆无需复核")
        with self.transaction():
            prior_id = candidate.get("supersedes_id")
            prior = self.get(project_id, prior_id) if prior_id else None
            if decision == "reject":
                self.forget(project_id, identifier, expected_version)
                if prior and prior["version"] == candidate.get("supersedes_version") and prior.get("status") == "stale" and prior.get("review_reason") == "conflict":
                    return self.set_state(project_id, prior_id, prior["version"], "active")
                return {"id": identifier, "status": "forgotten", "version": expected_version + 1}
            if prior and prior["version"] != candidate.get("supersedes_version"):
                raise MemoryConflict("候选对应的旧记忆已变化，请刷新后编辑解决冲突")
            if not prior and candidate.get("review_reason") == "conflict":
                related = [item for item in self.list(project_id) if item.get("supersedes_id") == identifier]
                if any(item.get("supersedes_version") != expected_version for item in related):
                    raise MemoryConflict("关联候选已变化，请刷新后编辑解决冲突")
                # 确认旧值等同保留旧值，结束整组冲突并移除新候选正文。
                for item in related:
                    self.forget(project_id, item["id"], item["version"])
            target = prior or candidate
            data = MemoryInput.model_validate({key: candidate[key] for key in MemoryInput.model_fields})
            result = self.put(project_id, data, identifier=target["id"], expected_version=target["version"],
                              sources=candidate["source_item_ids"], source_session_id=candidate["source_session_id"],
                              source_project_id=candidate["source_project_id"], source_updated_at=candidate["source_updated_at"])
            if prior:
                self.forget(project_id, identifier, expected_version)
            return result

    def forget(self, project_id: int, identifier: str, expected_version: int):
        value = self.get(project_id, identifier)
        if value["version"] != expected_version:
            raise MemoryConflict("记忆已变化，请刷新后重新删除")
        # 清除正文但保留去重墓碑，避免同一历史在下一轮重新生成已遗忘内容。
        value.update(title="", content="", source_item_ids=[], version=value["version"] + 1, updated_at=now())
        with self.transaction():
            self.db.execute("UPDATE memories SET deleted=1,data=? WHERE id=?", (encode(value), identifier))
            # 遗忘包含旧版本正文；仅保留无正文墓碑和独立的操作回执。
            self.db.execute("DELETE FROM memory_revisions WHERE memory_id=?", (identifier,))
            for related in self.list(project_id):
                if related.get("supersedes_id") == identifier:
                    self.forget(project_id, related["id"], related["version"])

    def cursor(self, session_id: int) -> int:
        row = self.db.execute("SELECT through_ordinal FROM extractions WHERE session_id=?", (session_id,)).fetchone()
        return row[0] if row else 0

    def extracted(self, session_id: int, through: int, details: dict):
        self.db.execute("INSERT INTO extractions VALUES (?,?,?) ON CONFLICT(session_id) DO UPDATE SET through_ordinal=excluded.through_ordinal,data=excluded.data", (session_id, through, encode(details)))

    def begin_attempt(self, session_id: int, limit: int) -> str:
        today = now()[:10]
        if self.db.execute("SELECT COUNT(*) FROM attempts WHERE created_at>=?", (today,)).fetchone()[0] >= limit:
            raise ValueError("记忆生成已达到今日调用上限")
        identifier = uuid.uuid4().hex
        with self.transaction():
            self.db.execute("INSERT INTO attempts VALUES (?,?,?)", (identifier, now(), encode({"session_id": session_id, "state": "running"})))
        return identifier

    def finish_attempt(self, identifier: str, details: dict):
        with self.transaction():
            self.db.execute("UPDATE attempts SET data=? WHERE id=?", (encode(details), identifier))

    def status(self) -> dict:
        row = self.db.execute("SELECT created_at,data FROM attempts ORDER BY rowid DESC LIMIT 1").fetchone()
        calls = self.db.execute("SELECT COUNT(*) FROM attempts WHERE created_at>=?", (now()[:10],)).fetchone()[0]
        return {"last_attempt": {"created_at": row[0], **json.loads(row[1])} if row else None, "calls_today": calls}

    def reconcile(self, projects: set[int], sessions: set[int]):
        """清理已删除项目及自动来源；手动确认的全局偏好独立保留。"""
        with self.transaction():
            for identifier, scope, deleted, raw in self.db.execute("SELECT id,scope_id,deleted,data FROM memories").fetchall():
                item = json.loads(raw)
                if ((scope and scope not in projects) or (not deleted and item["origin"] == "generated"
                        and (item.get("source_session_id") not in sessions or item.get("source_project_id") not in projects))):
                    self.db.execute("DELETE FROM memories WHERE id=?", (identifier,))
                    self.db.execute("DELETE FROM memory_revisions WHERE memory_id=?", (identifier,))
            for table in ("session_settings", "extractions"):
                for (session_id,) in self.db.execute(f"SELECT session_id FROM {table}").fetchall():
                    if session_id not in sessions:
                        self.db.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))

    def close(self):
        self.db.close()
