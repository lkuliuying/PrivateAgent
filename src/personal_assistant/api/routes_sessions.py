"""会话与消息路由。

v0.9.0 H0 §5：所有时间字段统一序列化为带 ``Z`` 的 RFC 3339 UTC；
H1 §4.2：legacy/unbound 会话只通过显式 ``bind-project`` 迁移绑定，
不做批量/最近项目猜测。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from ..core.db import get_session
from ..core.history import MessageRepository, SessionRepository
from ..core.models import AgentRun
from ..core.timeutil import format_rfc3339_utc
from ..logging_setup import get_logger

router = APIRouter(tags=["sessions"])
logger = get_logger(__name__)


def _session_error(status: int, error_code: str, detail: str):
    # 平铺 error_code 响应（与 v0.6.0 契约错误码一致）
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status,
        content={"error_code": error_code, "detail": detail},
    )


def _coding_session_telemetry(outcome: str) -> None:
    """C0 §10：coding_session_create 只保存 outcome 计数，不记录绑定字段。"""
    from ..core.compatibility import compatibility_telemetry

    compatibility_telemetry.record(
        path="coding_session_create", mode="project_bound", outcome=outcome
    )


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    # v0.6.0 Coding Agent
    project_id: int | None = None
    workspace_id: int | None = None
    kind: str | None = None
    last_run_id: str | None = None
    pinned_at: datetime | None = None
    archived_at: datetime | None = None

    # v0.9.0 H0 §5：统一带 Z 的 RFC 3339 UTC（客户端按 Asia/Shanghai 转换显示）
    @field_serializer(
        "created_at", "updated_at", "pinned_at", "archived_at"
    )
    def _serialize_time(self, value: datetime | None) -> str | None:
        return format_rfc3339_utc(value)


class SessionCreateRequest(BaseModel):
    title: str = Field(default="新对话", max_length=255)
    project_id: int | None = None
    workspace_id: int | None = None
    kind: str | None = Field(default=None, max_length=32)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: int
    role: str
    content: str
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_time(self, value: datetime | None) -> str | None:
        return format_rfc3339_utc(value)


class LatestSessionRunOut(BaseModel):
    run_id: str | None


class SessionBindRequest(BaseModel):
    """H0 §4.2：legacy/unbound 会话显式绑定项目的唯一入口。"""

    project_id: int = Field(gt=0)
    workspace_id: int = Field(gt=0)


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    project_id: int | None = Query(default=None, gt=0),
    kind: str | None = Query(default=None, max_length=32),
    db: AsyncSession = Depends(get_session),
):
    """获取会话列表（按最近更新倒序）。可选按 project/kind 过滤。"""
    items = await SessionRepository(db).list(project_id=project_id, kind=kind)
    logger.info("sessions listed", count=len(items))
    return items


@router.get("/sessions/search", response_model=list[SessionOut])
async def search_sessions(
    q: str = Query(..., min_length=1, max_length=100),
    kind: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
):
    """按标题搜索会话（不返回已归档；含有界）。"""
    items = await SessionRepository(db).search(q, kind=kind, limit=limit)
    logger.info("sessions searched", keyword_len=len(q), count=len(items))
    return items


@router.get("/sessions/recent", response_model=list[SessionOut])
async def recent_sessions(
    kind: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
):
    """最近任务：置顶优先，其后按更新时间倒序（不含已归档）。"""
    items = await SessionRepository(db).list_recent(kind=kind, limit=limit)
    return items


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session_detail(
    session_id: int,
    db: AsyncSession = Depends(get_session),
):
    """获取会话详情（v0.6.0 返回 project/workspace 绑定）。"""
    sess = await SessionRepository(db).get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    return sess


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def create_session(
    request: SessionCreateRequest = SessionCreateRequest(),
    db: AsyncSession = Depends(get_session),
):
    """新建会话。v0.6.0 支持可选 project/workspace 绑定。

    C5：coding session 创建走校验链（flag 开启 + 绑定完整 + workspace
    归属一致），失败拒绝且不落库；legacy session（kind 省略）不受影响。
    """
    if request.kind is not None and request.kind != "coding":
        _coding_session_telemetry("rejected")
        return _session_error(
            422,
            "coding_context_incomplete",
            "kind must be 'coding' or omitted",
        )
    if request.kind == "coding":
        if not cfg.project_bound_runs_enabled:
            _coding_session_telemetry("rejected")
            return _session_error(
                409, "coding_mode_disabled", "Project-bound runs are disabled"
            )
        if request.project_id is None or request.workspace_id is None:
            _coding_session_telemetry("rejected")
            return _session_error(
                422,
                "coding_context_incomplete",
                "project_id/workspace_id are required for coding sessions",
            )
        from ..core.workspaces import ProjectWorkspaceService

        ws = await ProjectWorkspaceService(db).get(request.workspace_id)
        if ws is None:
            _coding_session_telemetry("rejected")
            return _session_error(404, "workspace_not_found", "Workspace not found")
        if ws.project_id != request.project_id:
            _coding_session_telemetry("rejected")
            return _session_error(
                403,
                "workspace_outside_trust",
                "Workspace does not belong to the requested project",
            )
    s = await SessionRepository(db).create(
        title=request.title,
        project_id=request.project_id,
        workspace_id=request.workspace_id,
        kind=request.kind,
    )
    if request.kind == "coding":
        _coding_session_telemetry("created")
    logger.info("session created", session_id=s.id)
    return s


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(session_id: int, db: AsyncSession = Depends(get_session)):
    """获取指定会话的消息历史。"""
    sess = await SessionRepository(db).get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    msgs = await MessageRepository(db).list_by_session(session_id)
    logger.info("messages listed", session_id=session_id, count=len(msgs))
    return msgs


@router.get(
    "/sessions/{session_id}/latest-agent-run",
    response_model=LatestSessionRunOut,
)
async def get_latest_session_agent_run(
    session_id: int,
    db: AsyncSession = Depends(get_session),
) -> LatestSessionRunOut:
    """返回会话最新 durable run。

    ``sessions.last_run_id`` 在旧安装版从未写入；这里以 ``agent_runs`` 事实表
    只读兜底，使升级后已有任务也能恢复活动流，而不是要求用户重建任务。
    """
    sess = await SessionRepository(db).get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    run_id = (
        await db.execute(
            select(AgentRun.id)
            .where(AgentRun.session_id == session_id)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return LatestSessionRunOut(run_id=run_id)


# ============ v0.9.0 H4：会话管理（重命名/归档/置顶） ============


class SessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


@router.patch("/sessions/{session_id}/title", response_model=SessionOut)
async def rename_session(
    session_id: int,
    request: SessionRenameRequest,
    db: AsyncSession = Depends(get_session),
):
    """重命名会话标题（有界）。"""
    sess = await SessionRepository(db).get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    await SessionRepository(db).rename(session_id, request.title.strip())
    await db.refresh(sess)
    logger.info("session renamed", session_id=session_id)
    return sess


@router.post("/sessions/{session_id}/archive", response_model=SessionOut)
async def archive_session(session_id: int, db: AsyncSession = Depends(get_session)):
    """归档会话（软删除；不物理删除消息与审计，仍可搜索/恢复）。"""
    sess = await SessionRepository(db).get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    await SessionRepository(db).set_archived(session_id, True)
    await db.refresh(sess)
    logger.info("session archived", session_id=session_id)
    return sess


@router.post("/sessions/{session_id}/unarchive", response_model=SessionOut)
async def unarchive_session(session_id: int, db: AsyncSession = Depends(get_session)):
    """恢复已归档会话。"""
    sess = await SessionRepository(db).get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    await SessionRepository(db).set_archived(session_id, False)
    await db.refresh(sess)
    logger.info("session unarchived", session_id=session_id)
    return sess


@router.post("/sessions/{session_id}/pin", response_model=SessionOut)
async def pin_session(session_id: int, db: AsyncSession = Depends(get_session)):
    """置顶会话（最近任务中优先呈现）。"""
    sess = await SessionRepository(db).get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    await SessionRepository(db).set_pinned(session_id, True)
    await db.refresh(sess)
    logger.info("session pinned", session_id=session_id)
    return sess


@router.post("/sessions/{session_id}/unpin", response_model=SessionOut)
async def unpin_session(session_id: int, db: AsyncSession = Depends(get_session)):
    """取消置顶。"""
    sess = await SessionRepository(db).get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    await SessionRepository(db).set_pinned(session_id, False)
    await db.refresh(sess)
    logger.info("session unpinned", session_id=session_id)
    return sess


@router.post(
    "/sessions/{session_id}/bind-project",
    response_model=SessionOut,
)
async def bind_session_to_project(
    session_id: int,
    request: SessionBindRequest,
    db: AsyncSession = Depends(get_session),
):
    """v0.9.0 H1：把 legacy/unbound 会话显式迁移绑定到项目。

    契约（H0 §4.2）：
    - 只处理未绑定会话（project_id 为空）；已绑定会话拒绝重复绑定，
      不静默改绑（更换归属 = 新建/选择另一会话）；
    - workspace 归属校验与 coding 会话创建链同语义；
    - 成功后 kind 升为 coding，并追加 session_project_bindings 审计行；
    - 无批量端点，不按最近项目/用户目录猜测。
    """
    from ..core.compatibility import compatibility_telemetry
    from ..core.models import SessionProjectBinding
    from ..core.workspaces import ProjectWorkspaceService

    def _reject(status: int, error_code: str, detail: str):
        compatibility_telemetry.record(
            path="legacy_session_bind", mode="explicit", outcome="rejected"
        )
        return _session_error(status, error_code, detail)

    if not cfg.project_bound_runs_enabled:
        return _reject(409, "coding_mode_disabled", "Project-bound runs are disabled")
    sess = await SessionRepository(db).get(session_id)
    if sess is None:
        return _reject(404, "workspace_not_found", "会话不存在")
    if sess.project_id is not None:
        return _reject(
            409,
            "session_bind_conflict",
            "Session is already bound to a project",
        )
    ws = await ProjectWorkspaceService(db).get(request.workspace_id)
    if ws is None:
        return _reject(404, "workspace_not_found", "Workspace not found")
    if ws.project_id != request.project_id:
        return _reject(
            403,
            "workspace_outside_trust",
            "Workspace does not belong to the requested project",
        )
    sess.project_id = request.project_id
    sess.workspace_id = request.workspace_id
    sess.kind = "coding"
    db.add(
        SessionProjectBinding(
            session_id=sess.id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
        )
    )
    await db.commit()
    await db.refresh(sess)
    compatibility_telemetry.record(
        path="legacy_session_bind", mode="explicit", outcome="bound"
    )
    logger.info(
        "session bound to project",
        session_id=sess.id,
        project_id=request.project_id,
    )
    return sess
