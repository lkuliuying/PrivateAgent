"""诊断中心服务（第七阶段 M5）。

聚合运行时状态供「诊断中心」一屏排障，并生成脱敏诊断包。
诊断包只用于排障，必须脱敏（API key / DB 密码 / Provider key / 聊天全文 / 文档原文 / 敏感记忆）。

聚合来源（对齐 docs/phase7-requirements.md §5.5）：
- /health 四项状态（HealthService.check_all）
- 版本 / git commit / 构建时间 / migration head
- 最近错误日志摘要（解析 rotating log 尾部）
- 最近失败活动（ActivityService status=failed）
- Provider 调用失败（provider_call_audits status=failed）
- 提醒 tick 状态 / 导入队列 / 备份状态 / 数据体检摘要
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import __version__
from ..config import settings as cfg
from .activities import ActivityService
from .backup import BackupService
from .health import HealthService
from .models import (
    Activity,
    AgentEvidence,
    DiagnosticRun,
    Document,
    ProviderCallAudit,
    Reminder,
)
from .repo_privacy import ProviderCallAuditRepository
from .settings import SettingsService
from .timeutil import utcnow
from .extensions import ExtensionDescriptor, ExtensionKind, extension_registry

_RECENT_ERROR_LINES = 80
_LOG_ERROR_RE = re.compile(r"\[(ERROR|WARNING)\]")
# 疑似密钥字段名模式（第八阶段审查：按 key 名脱敏，而非硬编码两个 key）。
_SECRET_KEY_RE = re.compile(r"(key|secret|password|token|cred|pwd)", re.IGNORECASE)
# 日志中 sk- 令牌（OpenAI/Claude 风格）。
_SK_TOKEN_RE = re.compile(r"sk-[A-Za-z0-9_-]{6,}")


def _mask(value: str | None, visible: int = 4) -> str:
    """脱敏密钥：保留前 visible 位 + ***，空值返回 '<empty>'。"""
    if not value:
        return "<empty>"
    if len(value) <= visible:
        return "***"
    return value[:visible] + "***"


def redact_db_url(url: str) -> str:
    """脱敏 db_url 中的密码（mysql+aiomysql://user:pass@host/db）。"""
    if not url:
        return url
    return re.sub(r":([^:@/]+)@", r":***@", url)


def redact_settings(all_settings: dict[str, str]) -> dict[str, str]:
    """脱敏 settings：按 key 名模式掩码疑似密钥字段（key/secret/password/token/cred/pwd）。"""
    redacted: dict[str, str] = {}
    for k, v in all_settings.items():
        if v and _SECRET_KEY_RE.search(k):
            redacted[k] = _mask(v)
        else:
            redacted[k] = v
    return redacted


def _scrub_log_line(line: str) -> str:
    """脱敏日志行：替换 db_url 中的密码 + 掩码 sk- 令牌（第八阶段审查）。"""
    try:
        line = line.replace(cfg.db_url, redact_db_url(cfg.db_url))
    except Exception:  # noqa: BLE001
        pass
    return _SK_TOKEN_RE.sub("sk-***", line)


class DiagnosticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def snapshot(self) -> dict[str, Any]:
        """诊断中心快照（不含敏感正文）。"""
        health = await HealthService().check_all()
        settings_all = await SettingsService(self.db).get_all()
        backup = await BackupService(self.db).list()
        failed_activities = await ActivityService(self.db).list(status="failed")
        provider_failures = await ProviderCallAuditRepository(self.db).list(
            remote=True, limit=20
        )
        migration_head = await self._migration_head()
        import_queue = await self._import_queue()
        reminder_tick = await self._reminder_tick_status()
        orphan_evidence = await self._orphan_evidence_count()
        recent_errors = self._recent_log_errors()

        # 第八阶段 M7：注册的 diagnostic_check 列表（出现在诊断中心 + 诊断包）。
        # 带 runner 的 diagnostic_check 输出自动并入快照（新增检查不需改 snapshot）。
        diag_checks: list[dict] = []
        extra: dict[str, Any] = {}
        for desc in extension_registry.list(kind=ExtensionKind.DIAGNOSTIC_CHECK):
            enabled = await extension_registry.is_enabled(self.db, desc.id)
            diag_checks.append(
                {
                    "id": desc.id,
                    "title": desc.title,
                    "risk_level": desc.risk_level,
                    "enabled": enabled,
                }
            )
            if enabled and desc.runner is not None:
                try:
                    extra.update(await desc.runner(self.db))
                except Exception:  # noqa: BLE001
                    continue

        snap = {
            "generated_at": utcnow().isoformat(),
            "version": __version__,
            "migration_head": migration_head,
            "health": health,
            "backup": {
                "last_backup_at": backup.get("last_backup_at"),
                "count": len(backup.get("items") or []),
            },
            "failed_activities": [
                {
                    "id": a.id,
                    "title": a.title,
                    "kind": a.kind,
                    "error_message": (a.error_message or "")[:200],
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in failed_activities[:20]
            ],
            "provider_failures": [
                {
                    "id": p.id,
                    "provider_type": p.provider_type,
                    "status": p.status,
                    "error_code": p.error_code,
                    "error_message": (p.error_message or "")[:200],
                    "fallback_used": p.fallback_used,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in provider_failures
                if p.status == "failed"
            ],
            "reminder_tick": reminder_tick,
            "import_queue": import_queue,
            "integrity_summary": {
                "orphan_evidence": orphan_evidence,
            },
            "recent_errors": recent_errors,
            "settings_redacted": redact_settings(settings_all),
            "db_url_redacted": redact_db_url(cfg.db_url),
            "diagnostic_checks": diag_checks,
        }
        snap.update(extra)
        return snap

    async def export(self, output_dir: str | None = None) -> dict[str, Any]:
        """生成脱敏诊断包（zip），记录 DiagnosticRun。返回路径与摘要。"""
        snap = await self.snapshot()
        out_dir = Path(output_dir) if output_dir else cfg.data_dir / "diagnostics"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = utcnow().strftime("%Y%m%d_%H%M%S")
        zip_path = out_dir / f"diagnostics_{ts}.zip"

        import json

        run = DiagnosticRun(status="pending", summary_json={"version": __version__})
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)

        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(
                    "diagnostics.json",
                    json.dumps(snap, ensure_ascii=False, default=str, indent=2),
                )
                zf.writestr(
                    "health.json",
                    json.dumps(snap["health"], ensure_ascii=False, default=str, indent=2),
                )
                zf.writestr(
                    "settings.redacted.json",
                    json.dumps(
                        snap["settings_redacted"], ensure_ascii=False, indent=2
                    ),
                )
                zf.writestr(
                    "recent-errors.log",
                    "\n".join(snap["recent_errors"]),
                )
                zf.writestr("version.txt", f"{__version__}\n")
                zf.writestr("migration.txt", f"{snap['migration_head']}\n")
            run.status = "succeeded"
            run.output_path = str(zip_path)
            run.summary_json = {
                "version": __version__,
                "migration_head": snap["migration_head"],
                "failed_activities": len(snap["failed_activities"]),
                "provider_failures": len(snap["provider_failures"]),
            }
            run.finished_at = utcnow()
            await self.db.commit()
            return {
                "path": str(zip_path),
                "run_id": run.id,
                "size_bytes": zip_path.stat().st_size,
            }
        except Exception as e:  # noqa: BLE001
            run.status = "failed"
            run.error_message = str(e)[:1000]
            run.finished_at = utcnow()
            await self.db.commit()
            raise

    # ---- 子查询 ----

    async def _migration_head(self) -> str | None:
        try:
            result = await self.db.execute(text("SELECT version_num FROM alembic_version"))
            row = result.first()
            return row[0] if row else None
        except Exception:  # noqa: BLE001
            return None

    async def _import_queue(self) -> dict[str, int]:
        """导入队列：pending/processing/needs_ocr 文档计数。"""
        out: dict[str, int] = {}
        for st in ("pending", "processing", "needs_ocr", "failed"):
            result = await self.db.execute(
                select(func.count(Document.id)).where(Document.status == st)
            )
            out[st] = int(result.scalar() or 0)
        return out

    async def _reminder_tick_status(self) -> dict[str, Any]:
        try:
            settings_all = await SettingsService(self.db).get_all()
            enabled = settings_all.get("reminders_enabled", "true").lower() == "true"
            result = await self.db.execute(
                select(func.max(Reminder.last_fired_at)).where(Reminder.status == "active")
            )
            last_fired = result.scalar()
            return {
                "enabled": enabled,
                "last_fired_at": last_fired.isoformat() if last_fired else None,
            }
        except Exception:  # noqa: BLE001
            return {"enabled": True}

    async def _orphan_evidence_count(self) -> int:
        result = await self.db.execute(
            select(func.count(AgentEvidence.id)).where(AgentEvidence.step_id.is_(None))
        )
        return int(result.scalar() or 0)

    def _recent_log_errors(self) -> list[str]:
        """解析 rotating log 尾部的 ERROR/WARNING 行（脱敏：日志不含密钥原文）。"""
        log_file = cfg.log_dir / "personal_assistant.log"
        if not log_file.exists():
            return []
        try:
            with log_file.open("r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception:  # noqa: BLE001
            return []
        matched = [_scrub_log_line(ln.rstrip()) for ln in lines if _LOG_ERROR_RE.search(ln)]
        return matched[-_RECENT_ERROR_LINES:]


def _register_diagnostic_checks() -> None:
    """注册内置 diagnostic_check（元数据，数据由 snapshot 内联采集），幂等。

    内置诊断检查 configurable=False（始终出现在快照）；新增 diagnostic_check 附带
    runner 时，其返回 dict 会自动并入诊断快照与诊断包（diagnostics.json）。
    """
    checks = [
        ("diag.health", "依赖健康检查"),
        ("diag.migration", "迁移 head 检查"),
        ("diag.recent_errors", "最近错误日志"),
        ("diag.provider_failures", "Provider 失败"),
        ("diag.backup", "备份状态"),
        ("diag.integrity", "数据体检摘要"),
        ("diag.reminder_tick", "提醒 tick 状态"),
        ("diag.import_queue", "导入队列"),
    ]
    for cid, title in checks:
        if extension_registry.get(cid) is None:
            extension_registry.register(
                ExtensionDescriptor(
                    id=cid,
                    title=title,
                    kind=ExtensionKind.DIAGNOSTIC_CHECK,
                    description=title,
                    risk_level="safe",
                    permissions=["read:diagnostics"],
                    output_summary="贡献诊断快照字段",
                    configurable=False,
                )
            )


_register_diagnostic_checks()
