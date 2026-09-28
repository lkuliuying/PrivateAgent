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
            self.db.execute("PRAGMA busy_timeout=5000")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1}:
                raise ValueError("记忆数据库需要更新版本的客户端")
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
            stable_key=None, sources=(), source_session_id=None, source_project_id=None, source_updated_at=None) -> dict | None:
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
                 "source_item_ids": list(sources) if not identifier else previous["source_item_ids"]}
        with self.transaction():
            self.db.execute("INSERT INTO memories VALUES (?,?,?,?,0,?) ON CONFLICT(id) DO UPDATE SET fingerprint=excluded.fingerprint, data=excluded.data", (value["id"], scope_id, key, digest, encode(value)))
        return value

    def forget(self, project_id: int, identifier: str, expected_version: int):
        value = self.get(project_id, identifier)
        if value["version"] != expected_version:
            raise MemoryConflict("记忆已变化，请刷新后重新删除")
        # 清除正文但保留去重墓碑，避免同一历史在下一轮重新生成已遗忘内容。
        value.update(title="", content="", source_item_ids=[], version=value["version"] + 1, updated_at=now())
        with self.transaction():
            self.db.execute("UPDATE memories SET deleted=1,data=? WHERE id=?", (encode(value), identifier))

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
            for table in ("session_settings", "extractions"):
                for (session_id,) in self.db.execute(f"SELECT session_id FROM {table}").fetchall():
                    if session_id not in sessions:
                        self.db.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))

    def close(self):
        self.db.close()
