"""本地集成源与导入记录异步仓储层（第八阶段 M8）。

照 core/repo_inbox.py 模式：每仓储持 AsyncSession，方法内自带 commit；
仓储层不抛 HTTPException，缺失返回 None。

集成源只存本地文件路径与选项，**不存凭据**（第八阶段仅本地文件型集成）；
导入记录保存解析摘要、目标对象引用与可撤销信息（reversal_info_json），支持按导入撤销。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import IntegrationImport, IntegrationSource


class IntegrationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ---- 集成源 ----

    async def create_source(
        self,
        *,
        kind: str,
        title: str,
        config_json: dict | None = None,
        enabled: bool = True,
    ) -> IntegrationSource:
        src = IntegrationSource(
            kind=kind, title=title, config_json=config_json, enabled=enabled
        )
        self.db.add(src)
        await self.db.commit()
        await self.db.refresh(src)
        return src

    async def get_source(self, source_id: int) -> Optional[IntegrationSource]:
        return await self.db.get(IntegrationSource, source_id)

    async def list_sources(self, *, kind: str | None = None) -> list[IntegrationSource]:
        stmt = select(IntegrationSource)
        if kind:
            stmt = stmt.where(IntegrationSource.kind == kind)
        stmt = stmt.order_by(IntegrationSource.created_at.desc())
        return list((await self.db.execute(stmt)).scalars().all())

    async def update_source_status(
        self,
        source_id: int,
        *,
        enabled: bool | None = None,
        last_status: str | None = None,
        last_run_at: datetime | None = None,
    ) -> None:
        values: dict = {}
        if enabled is not None:
            values["enabled"] = enabled
        if last_status is not None:
            values["last_status"] = last_status
        if last_run_at is not None:
            values["last_run_at"] = last_run_at
        if not values:
            return
        await self.db.execute(
            update(IntegrationSource)
            .where(IntegrationSource.id == source_id)
            .values(**values)
        )
        await self.db.commit()

    async def delete_source(self, source_id: int) -> None:
        src = await self.get_source(source_id)
        if src:
            await self.db.delete(src)
            await self.db.commit()

    # ---- 导入记录 ----

    async def create_import(
        self,
        *,
        source_id: int | None,
        source_kind: str,
        summary_json: dict | None = None,
        target_type: str | None = None,
        target_id: int | None = None,
        reversible: bool = True,
        reversal_info_json: dict | None = None,
        status: str = "previewed",
    ) -> IntegrationImport:
        imp = IntegrationImport(
            source_id=source_id,
            source_kind=source_kind,
            summary_json=summary_json,
            target_type=target_type,
            target_id=target_id,
            reversible=reversible,
            reversal_info_json=reversal_info_json,
            status=status,
        )
        self.db.add(imp)
        await self.db.commit()
        await self.db.refresh(imp)
        return imp

    async def get_import(self, import_id: int) -> Optional[IntegrationImport]:
        return await self.db.get(IntegrationImport, import_id)

    async def get_fresh(self, import_id: int) -> Optional[IntegrationImport]:
        """强制从 DB 重新加载（populate_existing），避免 update_import 后 db.get 返回缓存过期对象。"""
        stmt = (
            select(IntegrationImport)
            .where(IntegrationImport.id == import_id)
            .execution_options(populate_existing=True)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_imports(self, *, limit: int = 50) -> list[IntegrationImport]:
        stmt = (
            select(IntegrationImport)
            .order_by(IntegrationImport.created_at.desc())
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def update_import(self, import_id: int, **fields) -> None:
        if not fields:
            return
        await self.db.execute(
            update(IntegrationImport)
            .where(IntegrationImport.id == import_id)
            .values(**fields)
        )
        await self.db.commit()
