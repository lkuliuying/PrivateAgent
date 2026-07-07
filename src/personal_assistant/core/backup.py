"""第四阶段 M6：本地数据备份、恢复预览与低风险设置恢复。"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from .models import Setting
from .timeutil import utcnow


BACKUP_TABLES = [
    "settings",
    "trusted_paths",
    "sessions",
    "messages",
    "documents",
    "doc_chunks",
    "projects",
    "learning_topics",
    "learning_nodes",
    "learning_notes",
    "learning_quizzes",
    "learning_quiz_attempts",
    "learning_cards",
    "learning_reviews",
    "agent_tasks",
    "agent_task_steps",
    "agent_evidence",
    "memory_items",
    "memory_events",
    "document_collections",
    "document_collection_items",
    "document_extractions",
    "project_command_profiles",
    "patch_sets",
    "patch_files",
]


class BackupService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.backup_dir = settings.data_dir / "backups"

    async def list(self) -> dict:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        items = []
        for p in sorted(self.backup_dir.glob("*.zip"), reverse=True):
            stat = p.stat()
            items.append(
                {
                    "path": str(p),
                    "name": p.name,
                    "size_bytes": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
            )
        return {"items": items, "last_backup_at": items[0]["created_at"] if items else None}

    async def export(self) -> dict:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = utcnow().strftime("%Y%m%d-%H%M%S")
        path = self.backup_dir / f"personal-assistant-backup-{stamp}.zip"
        tables: dict[str, list[dict[str, Any]]] = {}
        counts: dict[str, int] = {}
        for table in BACKUP_TABLES:
            rows = await self._dump_table(table)
            tables[table] = rows
            counts[table] = len(rows)

        manifest = {
            "version": 1,
            "created_at": utcnow().isoformat(),
            "tables": counts,
            "includes": {
                "mysql_business_data": True,
                "settings": True,
                "chroma_path": str(settings.chroma_dir),
                "chroma_files_embedded": False,
            },
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            zf.writestr(
                "tables.json", json.dumps(tables, ensure_ascii=False, indent=2, default=str)
            )
        return {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "created_at": manifest["created_at"],
            "tables": counts,
        }

    async def restore_preview(self, backup_path: str) -> dict:
        manifest, tables = self._read_backup(backup_path)
        return {
            "path": backup_path,
            "created_at": manifest.get("created_at"),
            "tables": manifest.get("tables") or {
                k: len(v) for k, v in tables.items() if isinstance(v, list)
            },
            "will_restore": ["settings"],
            "preview_only": [
                t for t in (manifest.get("tables") or {}).keys() if t != "settings"
            ],
            "note": "业务数据仅做预览；当前执行恢复只覆盖 settings，避免误删长期资料。",
        }

    async def restore(self, backup_path: str) -> dict:
        manifest, tables = self._read_backup(backup_path)
        restored = 0
        for row in tables.get("settings", []):
            key = str(row.get("key") or "")
            if not key:
                continue
            existing = await self.db.get(Setting, key)
            if existing:
                existing.value = row.get("value")
            else:
                self.db.add(Setting(key=key, value=row.get("value")))
            restored += 1
        await self.db.commit()
        return {
            "path": backup_path,
            "created_at": manifest.get("created_at"),
            "restored": {"settings": restored},
        }

    async def _dump_table(self, table: str) -> list[dict[str, Any]]:
        try:
            result = await self.db.execute(text(f"SELECT * FROM {table}"))
        except Exception:  # noqa: BLE001
            return []
        return [dict(row) for row in result.mappings().all()]

    @staticmethod
    def _read_backup(backup_path: str) -> tuple[dict, dict]:
        path = Path(backup_path)
        if not path.exists() or path.suffix.lower() != ".zip":
            raise FileNotFoundError(f"备份包不存在: {backup_path}")
        with zipfile.ZipFile(path) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            tables = json.loads(zf.read("tables.json").decode("utf-8"))
        return manifest, tables
