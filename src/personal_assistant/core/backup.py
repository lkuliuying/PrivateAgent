"""第四阶段 M6：本地数据备份、恢复预览与低风险设置恢复。"""
from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import __version__
from ..config import settings
from .models import DocChunk, Setting
from .settings import PROVIDER_SECRET_REFS, is_provider_secret_reference
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
    # 第六阶段：主动个人中枢
    "inbox_items",
    "reminders",
    "personal_goals",
    "goal_links",
    "goal_checkins",
    "briefings",
    "provider_call_audits",
    # 第七阶段：可信赖日常操作层
    "app_notifications",
    "capture_items",
    "ocr_jobs",
    "diagnostic_runs",
    "data_integrity_findings",
    "search_recent_items",
    # 第八阶段：本地集成与扩展注册（test_runs/release_artifacts/upgrade_smoke_runs 可重建，不备份）
    "integration_sources",
    "integration_imports",
    "extension_registry_items",
    # Modern Agent Runtime, durable approvals, structured memory, and versioned RAG.
    # Missing additive tables on a pre-upgrade database are exported as empty lists.
    "agent_runs",
    "run_steps",
    "agent_run_events",
    "tool_approvals",
    "agent_run_checkpoints",
    "agent_tool_executions",
    "memory_facts",
    "memory_fact_versions",
    "document_index_versions",
    "document_index_chunks",
    "document_index_heads",
    # MCP registry configuration and metadata-only audit. OS credentials are excluded.
    "mcp_servers",
    "mcp_call_logs",
]


# 迁移失败 runbook（第八阶段 M9）：诊断中心 / 发布前检查可引用。
MIGRATION_RUNBOOK = {
    "mysql_unavailable": (
        "确认 MySQL 8.0+ 服务已启动；检查 .env 的 PA_DB_URL 用户名/密码/端口；"
        "库 personal_assistant 需 utf8mb4_unicode_ci。"
    ),
    "alembic_failed": (
        "uv run alembic current 查看当前 head；uv run alembic upgrade head 重试；"
        "失败时检查迁移脚本语法；必要时 uv run alembic downgrade <prev> 回退一格。"
    ),
    "chroma_inconsistent": (
        "运行数据完整性体检（POST /maintenance/integrity/run）；"
        "mysql_only 切片在知识库页重建索引；chroma_only 孤立向量用修复计划删除。"
    ),
    "backup_incompatible": (
        "备份包 manifest 缺 schema_head/checksum 或校验失败时，不要强制恢复业务数据；"
        "用 POST /backup/restore/drill 预览；仅恢复 settings，业务数据手动迁移或重建。"
    ),
}


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

        # checksum 基于 tables.json 的确切字节（写入与校验用同一份字符串，保证可复现）。
        tables_json_str = json.dumps(
            tables, ensure_ascii=False, indent=2, default=str
        )
        checksum = hashlib.sha256(tables_json_str.encode("utf-8")).hexdigest()
        schema_head = await self._schema_head()
        manifest = {
            "version": 2,
            "created_at": utcnow().isoformat(),
            "app_version": __version__,
            "schema_head": schema_head,
            "modules": list(counts.keys()),
            "tables": counts,
            "checksum": checksum,
            "checksum_algorithm": "sha256",
            "includes": {
                "mysql_business_data": True,
                "settings": True,
                "os_credentials": False,
                "chroma_path": str(settings.chroma_dir),
                "chroma_files_embedded": False,
            },
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
            )
            zf.writestr("tables.json", tables_json_str)
        return {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "created_at": manifest["created_at"],
            "app_version": __version__,
            "schema_head": schema_head,
            "tables": counts,
            "checksum": checksum,
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
            if key in PROVIDER_SECRET_REFS:
                # Credentials are restored only through the OS credential store.
                # This also prevents old backups from reintroducing plaintext rows.
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

    async def _schema_head(self) -> str | None:
        """读取当前 alembic head（与 diagnostics._migration_head 同源）。"""
        try:
            result = await self.db.execute(text("SELECT version_num FROM alembic_version"))
            row = result.first()
            return row[0] if row else None
        except Exception:  # noqa: BLE001
            return None

    async def validate_manifest(self, backup_path: str) -> dict:
        """校验备份 manifest：app_version / schema_head / checksum（sha256 of tables.json 字节）。"""
        path = Path(backup_path)
        if not path.exists() or path.suffix.lower() != ".zip":
            raise FileNotFoundError(f"备份包不存在: {backup_path}")
        _empty = {
            "valid": False,
            "issues": [],
            "app_version": None,
            "schema_head": None,
            "checksum": None,
            "manifest_version": None,
        }
        issues: list[str] = []
        manifest: dict = {}
        raw_tables = b""
        try:
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
                if "manifest.json" not in names:
                    _empty["issues"] = ["missing manifest.json"]
                    return _empty
                if "tables.json" not in names:
                    _empty["issues"] = ["missing tables.json"]
                    return _empty
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                raw_tables = zf.read("tables.json")
        except (json.JSONDecodeError, KeyError, zipfile.BadZipFile) as e:
            _empty["issues"] = [f"corrupt backup: {e}"]
            return _empty
        if "app_version" not in manifest:
            issues.append("missing app_version")
        if "schema_head" not in manifest:
            issues.append("missing schema_head")
        if "checksum" not in manifest:
            issues.append("missing checksum")
        else:
            actual = hashlib.sha256(raw_tables).hexdigest()
            if actual != manifest.get("checksum"):
                issues.append("checksum mismatch")
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "app_version": manifest.get("app_version"),
            "schema_head": manifest.get("schema_head"),
            "checksum": manifest.get("checksum"),
            "manifest_version": manifest.get("version"),
        }

    async def restore_drill(self, backup_path: str) -> dict:
        """恢复演练：恢复预览 + manifest 校验 + 现有完整性发现 + Chroma/MySQL 一致性。

        不执行实际恢复，不重新跑体检（避免副作用），只汇总可恢复性与一致性状态。
        对齐 docs/phase8-requirements.md §5.9（恢复预览 + 完整性体检路径）。
        """
        preview = await self.restore_preview(backup_path)
        validation = await self.validate_manifest(backup_path)
        from .integrity import IntegrityService  # 延迟导入避免循环

        open_findings = await IntegrityService(self.db).list_findings(status="open")
        chroma = await self._chroma_mysql_summary()
        return {
            "preview": preview,
            "manifest_validation": validation,
            "open_integrity_findings": len(open_findings),
            "chroma_mysql": chroma,
            "ready": validation["valid"],
        }

    async def _chroma_mysql_summary(self) -> dict:
        """Chroma/MySQL 切片一致性摘要（consistent = 无缺失向量）。"""
        try:
            from .store_chroma import chroma_store

            mysql_ids = set((await self.db.execute(select(DocChunk.id))).scalars().all())
            chroma_ids = set(await chroma_store.list_ids())
            return {
                "mysql_count": len(mysql_ids),
                "chroma_count": len(chroma_ids),
                "missing_vectors": len(mysql_ids - chroma_ids),
                "orphan_vectors": len(chroma_ids - mysql_ids),
                "consistent": not (mysql_ids - chroma_ids),
            }
        except Exception:  # noqa: BLE001
            return {"consistent": False, "error": "chroma/mysql 检查失败"}

    async def _dump_table(self, table: str) -> list[dict[str, Any]]:
        try:
            # stream_results=True 用服务端游标分批拉取，降低大表单次内存峰值（第八阶段审查）。
            result = await self.db.stream(
                text(f"SELECT * FROM {table}").execution_options(stream_results=True)
            )
        except Exception:  # noqa: BLE001
            return []
        rows = [dict(row) async for row in result.mappings()]
        if table == "settings":
            for row in rows:
                key = str(row.get("key") or "")
                value = row.get("value")
                if key in PROVIDER_SECRET_REFS and not is_provider_secret_reference(
                    key, str(value) if value is not None else None
                ):
                    row["value"] = ""
        elif table == "mcp_servers":
            # Preserve environment variable names but never copy their plaintext
            # values into an unencrypted backup archive. Secret refs are identifiers.
            for row in rows:
                environment = row.get("env_json")
                if isinstance(environment, str):
                    try:
                        environment = json.loads(environment)
                    except json.JSONDecodeError:
                        environment = {}
                if isinstance(environment, dict):
                    row["env_json"] = {str(name): "" for name in environment}
        return rows

    @staticmethod
    def _read_backup(backup_path: str) -> tuple[dict, dict]:
        path = Path(backup_path)
        if not path.exists() or path.suffix.lower() != ".zip":
            raise FileNotFoundError(f"备份包不存在: {backup_path}")
        with zipfile.ZipFile(path) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            tables = json.loads(zf.read("tables.json").decode("utf-8"))
        return manifest, tables
