"""工具调用 / 授权路径 / 活动流的异步仓储层。

照 core/repo.py 模式：每个仓储持有一个 AsyncSession，方法内自带 commit。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Activity, ToolCall, TrustedPath


class ToolCallRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        session_id: int | None,
        tool_name: str,
        risk_level: str,
        status: str = "pending_approval",
        input_json: dict | None = None,
        task_id: int | None = None,
        step_id: int | None = None,
    ) -> ToolCall:
        tc = ToolCall(
            session_id=session_id,
            task_id=task_id,
            step_id=step_id,
            tool_name=tool_name,
            risk_level=risk_level,
            status=status,
            input_json=input_json,
        )
        self.db.add(tc)
        await self.db.commit()
        await self.db.refresh(tc)
        return tc

    async def get(self, tool_call_id: int) -> Optional[ToolCall]:
        return await self.db.get(ToolCall, tool_call_id)

    async def get_fresh(self, tool_call_id: int) -> Optional[ToolCall]:
        """强制从 DB 重新加载（populate_existing）。

        Core ``update()`` 后身份映射中的对象属性（尤其带 onupdate 的 updated_at）
        会被标记过期；用 db.get 会命中缓存返回过期对象，序列化时触发同步懒加载报错。
        """
        stmt = (
            select(ToolCall)
            .where(ToolCall.id == tool_call_id)
            .execution_options(populate_existing=True)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_session(self, session_id: int) -> list[ToolCall]:
        stmt = (
            select(ToolCall)
            .where(ToolCall.session_id == session_id)
            .order_by(ToolCall.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list(self, limit: int = 100) -> list[ToolCall]:
        stmt = select(ToolCall).order_by(ToolCall.created_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self,
        tool_call_id: int,
        *,
        status: str,
        output_json: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        values: dict = {"status": status}
        if output_json is not None:
            values["output_json"] = output_json
        if error_message is not None:
            values["error_message"] = error_message
        await self.db.execute(
            update(ToolCall).where(ToolCall.id == tool_call_id).values(**values)
        )
        await self.db.commit()

    async def claim(
        self,
        tool_call_id: int,
        *,
        from_status: str,
        to_status: str,
        output_json: dict | None = None,
        error_message: str | None = None,
    ) -> bool:
        """原子状态占用：仅当当前 status==from_status 时改为 to_status。

        用 ``WHERE status=from_status`` 的条件 UPDATE + rowcount 检查，保证并发
        approve 只有一个请求成功占用（解决 check-then-set 的 TOCTOU 双执行）。
        返回 True iff 命中恰好一行。
        """
        values: dict = {"status": to_status}
        if output_json is not None:
            values["output_json"] = output_json
        if error_message is not None:
            values["error_message"] = error_message
        result = await self.db.execute(
            update(ToolCall)
            .where(ToolCall.id == tool_call_id, ToolCall.status == from_status)
            .values(**values)
        )
        await self.db.commit()
        return result.rowcount == 1


class TrustedPathRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def authorize(self, path: str, kind: str) -> TrustedPath:
        """授权路径，已存在则返回原记录（去重，uk_trusted_path）。"""
        existing = await self.get_by_path(path)
        if existing:
            return existing
        tp = TrustedPath(path=path, kind=kind)
        self.db.add(tp)
        await self.db.commit()
        await self.db.refresh(tp)
        return tp

    async def get_by_path(self, path: str) -> Optional[TrustedPath]:
        stmt = select(TrustedPath).where(TrustedPath.path == path)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list(self) -> list[TrustedPath]:
        stmt = select(TrustedPath).order_by(TrustedPath.granted_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def all_paths(self) -> list[str]:
        return [tp.path for tp in await self.list()]


class ActivityRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        session_id: int | None,
        kind: str,
        title: str,
        status: str = "pending",
        ref_type: str | None = None,
        ref_id: int | None = None,
        detail_json: dict | None = None,
        started_at: datetime | None = None,
    ) -> Activity:
        act = Activity(
            session_id=session_id,
            kind=kind,
            title=title,
            status=status,
            ref_type=ref_type,
            ref_id=ref_id,
            detail_json=detail_json,
            started_at=started_at,
        )
        self.db.add(act)
        await self.db.commit()
        await self.db.refresh(act)
        return act

    async def get(self, activity_id: int) -> Optional[Activity]:
        return await self.db.get(Activity, activity_id)

    async def get_by_ref(self, ref_type: str, ref_id: int) -> Optional[Activity]:
        stmt = (
            select(Activity)
            .where(Activity.ref_type == ref_type, Activity.ref_id == ref_id)
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_session(self, session_id: int) -> list[Activity]:
        stmt = (
            select(Activity)
            .where(Activity.session_id == session_id)
            .order_by(Activity.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list(self, limit: int = 100) -> list[Activity]:
        stmt = select(Activity).order_by(Activity.created_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self,
        activity_id: int,
        *,
        status: str,
        error_message: str | None = None,
        detail_json: dict | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        values: dict = {"status": status}
        if error_message is not None:
            values["error_message"] = error_message
        if detail_json is not None:
            values["detail_json"] = detail_json
        if started_at is not None:
            values["started_at"] = started_at
        if finished_at is not None:
            values["finished_at"] = finished_at
        await self.db.execute(
            update(Activity).where(Activity.id == activity_id).values(**values)
        )
        await self.db.commit()
