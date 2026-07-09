"""统一通知中心服务（第七阶段 M4）。

包装 NotificationRepository，提供后端异步路径（导入/备份/提醒/任务/Provider）
记录操作结果的统一入口。通知只保存摘要，不保存敏感正文。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .repo_notifications import NotificationRepository


class NotificationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = NotificationRepository(db)

    async def notify(
        self,
        *,
        kind: str,
        title: str,
        level: str = "info",
        message: str | None = None,
        source_type: str | None = None,
        source_id: int | None = None,
        action_type: str | None = None,
        action_payload: dict | None = None,
    ):
        """记录一条通知（异步操作开始/成功/失败/可重试/跳转来源）。"""
        return await self.repo.create(
            kind=kind,
            title=title,
            level=level,
            message=message,
            source_type=source_type,
            source_id=source_id,
            action_type=action_type,
            action_payload_json=action_payload,
        )

    async def list(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ):
        return await self.repo.list(status=status, kind=kind, limit=limit)

    async def mark(self, notification_id: int, status: str) -> None:
        await self.repo.mark(notification_id, status)

    async def mark_all_read(self) -> int:
        return await self.repo.mark_all_read()
