"""Privacy preview, audit listing, and maintenance health for phase 6."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .activities import ActivityService
from .backup import BackupService
from .models import AgentEvidence
from .repo_memories import MemoryRepository
from .repo_privacy import ProviderCallAuditRepository
from .repo_tasks import AgentTaskRepository
from .settings import SettingsService
from .today import TodayService


class PrivacyService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.audits = ProviderCallAuditRepository(db)

    async def list_audits(
        self,
        *,
        remote: bool | None = None,
        limit: int = 100,
    ):
        return await self.audits.list(remote=remote, limit=limit)

    async def preview(
        self,
        *,
        purpose: str,
        provider_type: str | None = None,
        include_kb: bool = False,
        include_memories: bool = True,
        include_messages: bool = True,
        estimated_message_chars: int = 0,
    ) -> dict:
        settings = await SettingsService(self.db).get_all()
        provider = provider_type or settings.get("provider_type", "ollama")
        remote_enabled = settings.get("remote_provider_enabled") == "true"
        remote = provider in {"openai", "claude"} and remote_enabled
        context_types: list[str] = []
        estimated_chars = max(0, estimated_message_chars)
        if include_messages:
            context_types.append("chat_messages")
        if include_kb:
            context_types.append("kb_chunks")
        sensitive_excluded = 0
        usable_memories = 0
        if include_memories:
            memories = await MemoryRepository(self.db).list(
                status="confirmed", enabled=True
            )
            safe = [m for m in memories if not m.sensitive]
            sensitive_excluded = len(memories) - len(safe)
            usable_memories = len(safe)
            if safe:
                context_types.append("memories")
                estimated_chars += sum(
                    len((m.summary or m.title or "")[:300]) for m in safe[:8]
                )
        audit = await self.audits.create(
            provider_type=provider,
            purpose=purpose,
            remote=remote,
            context_types_json=context_types,
            estimated_input_chars=estimated_chars,
            status="planned",
        )
        return {
            "audit_id": audit.id,
            "provider_type": provider,
            "remote": remote,
            "remote_provider_enabled": remote_enabled,
            "context_types": context_types,
            "estimated_input_chars": estimated_chars,
            "safe_memory_count": usable_memories,
            "sensitive_memory_excluded": sensitive_excluded,
            "will_send_raw_sensitive_memory": False,
        }

    async def maintenance_health_report(self) -> dict:
        today = await TodayService(self.db).snapshot()
        backups = await BackupService(self.db).list()
        failed_activities = await ActivityService(self.db).list(
            status="failed", limit=200
        )
        draft_memories = await MemoryRepository(self.db).list(status="draft")
        tasks = await AgentTaskRepository(self.db).list()
        blocked_tasks = [
            t for t in tasks if t.status in {"failed", "paused", "plan_draft"}
        ]
        evidence = list(
            (
                await self.db.execute(select(AgentEvidence).limit(500))
            ).scalars().all()
        )
        orphan_evidence = [e for e in evidence if e.task_id is None]
        recommendations: list[str] = []
        if not backups.get("last_backup_at"):
            recommendations.append("Create a backup before the next larger change.")
        if failed_activities:
            recommendations.append("Review failed activities from the Today page.")
        if draft_memories:
            recommendations.append("Confirm or archive draft memories.")
        if blocked_tasks:
            recommendations.append("Review paused, failed, or draft agent tasks.")
        if orphan_evidence:
            recommendations.append("Clean up evidence records without a task.")
        return {
            "generated_at": today["generated_at"],
            "summary": {
                "last_backup_at": backups.get("last_backup_at"),
                "backup_count": len(backups.get("items") or []),
                "failed_activities": len(failed_activities),
                "draft_memories": len(draft_memories),
                "attention_tasks": len(blocked_tasks),
                "orphan_evidence": len(orphan_evidence),
                "open_inbox": today["summary"]["open_inbox"],
                "due_reminders": today["summary"]["due_reminders"],
            },
            "recommendations": recommendations,
        }
