"""远程 Provider 隐私审计异步仓储层（第六阶段 M1）。

照 core/repo_memories.py 模式：每仓储持 AsyncSession，方法内自带 commit；
仓储层不抛 HTTPException，缺失时返回 None。

审计只记录类别与估算大小，不保存完整 prompt（phase6 §6 隐私要求）：
- context_types_json：发送的上下文类别（如 chat_messages/kb_chunks/memories）。
- estimated_input_chars/output_chars：估算字符数（不存原文）。
- status：planned -> sent -> succeeded/failed/cancelled，finish 补 finished_at。

隐私预览（哪些类别将发送、是否含敏感记忆）与敏感记忆硬过滤属 M6 PrivacyService，
不在仓储层；本仓储只负责审计记录的读写。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ProviderCallAudit
from .timeutil import utcnow


class ProviderCallAuditRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        provider_type: str,
        purpose: str,
        model: str | None = None,
        remote: bool = False,
        context_types_json: list | None = None,
        estimated_input_chars: int | None = None,
        estimated_output_chars: int | None = None,
        status: str = "planned",
        error_message: str | None = None,
    ) -> ProviderCallAudit:
        audit = ProviderCallAudit(
            provider_type=provider_type,
            model=model,
            purpose=purpose,
            remote=remote,
            context_types_json=context_types_json,
            estimated_input_chars=estimated_input_chars,
            estimated_output_chars=estimated_output_chars,
            status=status,
            error_message=error_message,
        )
        self.db.add(audit)
        await self.db.commit()
        await self.db.refresh(audit)
        return audit

    async def get(self, audit_id: int) -> Optional[ProviderCallAudit]:
        return await self.db.get(ProviderCallAudit, audit_id)

    async def list(
        self,
        *,
        remote: bool | None = None,
        limit: int = 100,
    ) -> list[ProviderCallAudit]:
        """审计列表，默认按创建倒序。可按 remote 过滤（只看远程调用）。"""
        stmt = select(ProviderCallAudit)
        if remote is not None:
            stmt = stmt.where(ProviderCallAudit.remote == remote)
        stmt = stmt.order_by(ProviderCallAudit.created_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def finish(
        self,
        audit_id: int,
        *,
        status: str,
        error_message: str | None = None,
        estimated_output_chars: int | None = None,
    ) -> None:
        """标记调用终态并补 finished_at。"""
        values: dict = {"status": status, "finished_at": utcnow()}
        if error_message is not None:
            values["error_message"] = error_message
        if estimated_output_chars is not None:
            values["estimated_output_chars"] = estimated_output_chars
        await self.db.execute(
            update(ProviderCallAudit)
            .where(ProviderCallAudit.id == audit_id)
            .values(**values)
        )
        await self.db.commit()
