"""Account-scoped SQLite storage owned by the desktop installation."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS objects (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, data TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.db.commit()
        # A process restart must never replay an uncertain write or command.
        for run in self.runs():
            if run["status"] in {"created", "running", "waiting_approval"}:
                run.update(status="failed", active_in_process=False, error_code="desktop_restarted",
                           error_message="本机执行服务已重启；未自动重放操作，请检查项目后重试", completed_at=now())
                for approval in run.get("approvals", []):
                    if approval["status"] == "pending":
                        approval["status"] = "cancelled"
                self.save_run(run)

    def create(self, kind: str, data: dict) -> dict:
        value = {"created_at": now(), "updated_at": now(), **data}
        with self.db:
            cursor = self.db.execute("INSERT INTO objects(kind,data) VALUES (?,?)", (kind, json.dumps(value)))
            value["id"] = cursor.lastrowid
            self.db.execute("UPDATE objects SET data=? WHERE id=?", (json.dumps(value), value["id"]))
        return value

    def get(self, kind: str, item_id: int) -> dict:
        row = self.db.execute("SELECT data FROM objects WHERE kind=? AND id=?", (kind, item_id)).fetchone()
        if row is None:
            raise KeyError("本机记录不存在")
        return json.loads(row[0])

    def list(self, kind: str) -> list[dict]:
        return [json.loads(row[0]) for row in self.db.execute("SELECT data FROM objects WHERE kind=? ORDER BY id DESC", (kind,))]

    def update(self, kind: str, item_id: int, **changes) -> dict:
        item = self.get(kind, item_id)
        item.update(changes, updated_at=now())
        with self.db:
            self.db.execute("UPDATE objects SET data=? WHERE kind=? AND id=?", (json.dumps(item), kind, item_id))
        return item

    def save_run(self, run: dict) -> None:
        run["updated_at"] = now()
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO runs(id,data) VALUES (?,?)", (run["id"], json.dumps(run)))

    def run(self, run_id: str) -> dict:
        row = self.db.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("本机任务不存在")
        return json.loads(row[0])

    def runs(self) -> list[dict]:
        return [json.loads(row[0]) for row in self.db.execute("SELECT data FROM runs ORDER BY rowid DESC")]
