"""活动流服务。

把工具调用 / 文档导入 / 索引重建同步到 activities 表，作为活动流的 derived view。
M4：扩展读取（list/get）与文档导入/索引任务的活动接入。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Activity, ToolCall
from .repo_tools import ActivityRepository
from .timeutil import utcnow as _now

# tool_call.status -> activity.status 映射
_TOOL_STATUS_MAP: dict[str, str] = {
    "pending_approval": "waiting_approval",
    "approved": "running",
    "running": "running",
    "succeeded": "succeeded",
    "failed": "failed",
    "rejected": "cancelled",
    "cancelled": "cancelled",
}

# document.status -> activity.status 映射
_DOC_STATUS_MAP: dict[str, str] = {
    "pending": "pending",
    "processing": "running",
    "ready": "succeeded",
    "failed": "failed",
    "deleting": "cancelled",
}

# 终态：补 finished_at
_TERMINAL = {"succeeded", "failed", "cancelled"}


class ActivityService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ActivityRepository(db)

    # ---------------- 读取 ----------------
    async def list(
        self,
        *,
        session_id: int | None = None,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Activity]:
        stmt = select(Activity)
        if session_id is not None:
            stmt = stmt.where(Activity.session_id == session_id)
        if kind:
            stmt = stmt.where(Activity.kind == kind)
        if status:
            stmt = stmt.where(Activity.status == status)
        stmt = stmt.order_by(Activity.created_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get(self, activity_id: int) -> Activity | None:
        return await self.repo.get(activity_id)

    # ---------------- 工具调用同步 ----------------
    async def sync_tool_call(self, tool_call: ToolCall) -> None:
        """同步工具调用状态到活动流（按 ref_type='tool_call'+ref_id upsert）。"""
        act_status = _TOOL_STATUS_MAP.get(tool_call.status, "running")
        detail = {
            "tool_name": tool_call.tool_name,
            "risk_level": tool_call.risk_level,
            "input": tool_call.input_json,
            "output": tool_call.output_json,
        }
        await self._upsert(
            ref_type="tool_call",
            ref_id=tool_call.id,
            session_id=tool_call.session_id,
            kind="tool",
            title=f"工具调用：{tool_call.tool_name}",
            act_status=act_status,
            detail=detail,
            error_message=tool_call.error_message,
        )

    # ---------------- 文档导入同步 ----------------
    async def sync_document_import(
        self,
        doc_id: int,
        *,
        doc_name: str,
        doc_status: str,
        error_message: str | None = None,
    ) -> None:
        await self._sync_doc_activity(
            doc_id=doc_id,
            doc_name=doc_name,
            doc_status=doc_status,
            kind="document_import",
            ref_type="document_import",
            title=f"导入文档：{doc_name}",
            error_message=error_message,
        )

    # ---------------- 索引重建同步 ----------------
    async def sync_reindex(
        self,
        doc_id: int,
        *,
        doc_name: str,
        doc_status: str,
        error_message: str | None = None,
    ) -> None:
        await self._sync_doc_activity(
            doc_id=doc_id,
            doc_name=doc_name,
            doc_status=doc_status,
            kind="reindex",
            ref_type="document_reindex",
            title=f"重建索引：{doc_name}",
            error_message=error_message,
        )

    # ---------------- 系统活动同步（第三阶段：项目扫描等）----------------
    async def sync_system(
        self,
        *,
        ref_type: str,
        ref_id: int,
        title: str,
        act_status: str,
        detail: dict,
        error_message: str | None = None,
    ) -> None:
        """通用系统活动 upsert（按 ref_type+ref_id 去重更新）。

        act_status 直接用 activities.status 枚举值（running/succeeded/failed/cancelled/...）。
        供项目扫描等非工具、非文档活动复用。
        """
        await self._upsert(
            ref_type=ref_type,
            ref_id=ref_id,
            session_id=None,
            kind="system",
            title=title,
            act_status=act_status,
            detail=detail,
            error_message=error_message,
        )

    # ---------------- 内部 ----------------
    async def _sync_doc_activity(
        self,
        *,
        doc_id: int,
        doc_name: str,
        doc_status: str,
        kind: str,
        ref_type: str,
        title: str,
        error_message: str | None = None,
    ) -> None:
        act_status = _DOC_STATUS_MAP.get(doc_status, "running")
        detail = {"doc_id": doc_id, "doc_name": doc_name}
        await self._upsert(
            ref_type=ref_type,
            ref_id=doc_id,
            session_id=None,
            kind=kind,
            title=title,
            act_status=act_status,
            detail=detail,
            error_message=error_message,
        )

    async def _upsert(
        self,
        *,
        ref_type: str,
        ref_id: int,
        session_id: int | None,
        kind: str,
        title: str,
        act_status: str,
        detail: dict,
        error_message: str | None = None,
    ) -> None:
        """按 ref_type+ref_id upsert 活动记录。"""
        existing = await self.repo.get_by_ref(ref_type, ref_id)
        if existing:
            finished = _now() if act_status in _TERMINAL else None
            # running 转换时补 started_at（仅在尚未设置时，避免覆盖）
            started = (
                _now() if act_status == "running" and existing.started_at is None else None
            )
            await self.repo.update_status(
                existing.id,
                status=act_status,
                error_message=error_message,
                detail_json=detail,
                started_at=started,
                finished_at=finished,
            )
            return
        # 新建：running 起补 started_at
        started = _now() if act_status == "running" else None
        finished = _now() if act_status in _TERMINAL else None
        await self.repo.create(
            session_id=session_id,
            kind=kind,
            title=title,
            status=act_status,
            ref_type=ref_type,
            ref_id=ref_id,
            detail_json=detail,
            started_at=started,
        )
        # 若直接进入终态（非 running 起步），补 finished
        if finished is not None:
            created = await self.repo.get_by_ref(ref_type, ref_id)
            if created:
                await self.repo.update_status(
                    created.id, status=act_status, finished_at=finished
                )
