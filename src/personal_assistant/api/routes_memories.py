"""长期记忆路由（第四阶段 M1）。

- GET    /memories                   记忆列表（kind/status/enabled/project/topic/search 过滤）
- POST   /memories                   手动创建记忆（status 默认 confirmed）
- GET    /memories/{id}              记忆详情
- PATCH  /memories/{id}              编辑/启用禁用/敏感标记/状态切换
- DELETE /memories/{id}              删除记忆
- POST   /memories/search            记忆检索（LIKE + 过滤）
- POST   /memories/candidates        从任务报告/聊天生成候选记忆（落库 draft）
- POST   /memories/{id}/use          记录记忆被使用的审计事件
- GET    /memories/{id}/revisions    查询不可变版本历史（含已软删除记忆）
- GET    /memory-conflicts           查询待处理事实冲突
- POST   /memory-conflicts           显式登记事实冲突
- POST   /memory-conflicts/{id}/resolve  显式解决事实冲突
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.memory import MemoryService
from ..core.memory_candidates import MemoryCandidateService
from ..core.provider import ProviderError

router = APIRouter(tags=["memories"])

MemoryKind = Literal["preference", "learning", "project", "document", "workflow", "note"]
MemoryStatus = Literal["draft", "confirmed", "archived"]
MemorySensitivity = Literal["normal", "sensitive", "restricted"]


# ---- Schemas ----


class MemoryCreate(BaseModel):
    kind: MemoryKind
    title: str
    content_md: str
    summary: str | None = None
    source_type: str | None = None
    source_id: int | None = None
    project_id: int | None = None
    topic_id: int | None = None
    tags: list[str] | None = None
    confidence: float | None = None
    sensitive: bool = False
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    expires_at: datetime | None = None
    sensitivity_level: MemorySensitivity | None = None

    @field_validator("title")
    @classmethod
    def _check_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title 不能为空")
        return v[:255]

    @field_validator("content_md")
    @classmethod
    def _check_content(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content_md 不能为空")
        return v


class MemoryUpdate(BaseModel):
    title: str | None = None
    content_md: str | None = None
    summary: str | None = None
    tags: list[str] | None = None
    confidence: float | None = None
    enabled: bool | None = None
    sensitive: bool | None = None
    status: MemoryStatus | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    expires_at: datetime | None = None
    sensitivity_level: MemorySensitivity | None = None


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    title: str
    content_md: str
    summary: str | None
    source_type: str | None
    source_id: int | None
    project_id: int | None
    topic_id: int | None
    tags_json: list | None
    confidence: float | None
    enabled: bool
    sensitive: bool
    status: str
    stable_key: str
    memory_version: int
    content_sha256: str
    importance: float
    expires_at: datetime | None
    sensitivity_level: str
    confirmed_at: datetime | None
    last_confirmed_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MemorySearchRequest(BaseModel):
    query: str | None = None
    kind: MemoryKind | None = None
    status: MemoryStatus | None = None
    enabled: bool | None = None
    project_id: int | None = None
    topic_id: int | None = None


class MemoryCandidateRequest(BaseModel):
    source_type: Literal["agent_task", "chat_session", "learning_review"]
    source_id: int


class MemoryUseRequest(BaseModel):
    ref_type: str | None = None
    ref_id: int | None = None


class MemoryEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    memory_id: int
    event_type: str
    ref_type: str | None
    ref_id: int | None
    detail_json: dict | None
    created_at: datetime


class MemoryRevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    memory_id: int
    stable_key: str
    memory_version: int
    kind: str
    title: str
    content_md: str
    content_sha256: str
    summary: str | None
    state_json: dict | None
    change_type: str
    created_at: datetime


class MemoryConflictCreate(BaseModel):
    left_memory_id: int
    right_memory_id: int
    reason: str = Field(min_length=1, max_length=4_000)


class MemoryConflictResolve(BaseModel):
    resolution: dict


class MemoryConflictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    left_memory_id: int
    right_memory_id: int
    reason: str
    status: str
    resolution_json: dict | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ---- Routes ----


@router.get("/memories", response_model=list[MemoryOut])
async def list_memories(
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    project_id: int | None = Query(default=None),
    topic_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
):
    """记忆列表，支持按类型/状态/启用/项目/主题过滤与关键词搜索。"""
    return await MemoryService(db).search(
        search,
        kind=kind,
        status=status,
        enabled=enabled,
        project_id=project_id,
        topic_id=topic_id,
    )


@router.post("/memories", response_model=MemoryOut, status_code=201)
async def create_memory(req: MemoryCreate, db: AsyncSession = Depends(get_session)):
    return await MemoryService(db).create(
        kind=req.kind,
        title=req.title,
        content_md=req.content_md,
        summary=req.summary,
        source_type=req.source_type,
        source_id=req.source_id,
        project_id=req.project_id,
        topic_id=req.topic_id,
        tags_json=req.tags,
        confidence=req.confidence,
        sensitive=req.sensitive,
        status="confirmed",
        importance=req.importance,
        expires_at=req.expires_at,
        sensitivity_level=req.sensitivity_level,
    )


@router.get("/memories/{memory_id}", response_model=MemoryOut)
async def get_memory(memory_id: int, db: AsyncSession = Depends(get_session)):
    item = await MemoryService(db).get(memory_id)
    if item is None:
        raise HTTPException(404, "记忆不存在")
    return item


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
async def update_memory(
    memory_id: int, req: MemoryUpdate, db: AsyncSession = Depends(get_session)
):
    item = await MemoryService(db).update(
        memory_id,
        title=req.title,
        content_md=req.content_md,
        summary=req.summary,
        tags_json=req.tags,
        confidence=req.confidence,
        enabled=req.enabled,
        sensitive=req.sensitive,
        status=req.status,
        importance=req.importance,
        expires_at=req.expires_at,
        sensitivity_level=req.sensitivity_level,
    )
    if item is None:
        raise HTTPException(404, "记忆不存在")
    return item


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: int, db: AsyncSession = Depends(get_session)):
    ok = await MemoryService(db).delete(memory_id)
    if not ok:
        raise HTTPException(404, "记忆不存在")
    return None


@router.post("/memories/search", response_model=list[MemoryOut])
async def search_memories(
    req: MemorySearchRequest, db: AsyncSession = Depends(get_session)
):
    """记忆检索（管理视图）：query 走 LIKE，叠加过滤。"""
    return await MemoryService(db).search(
        req.query,
        kind=req.kind,
        status=req.status,
        enabled=req.enabled,
        project_id=req.project_id,
        topic_id=req.topic_id,
    )


@router.post("/memories/candidates", response_model=list[MemoryOut], status_code=201)
async def create_candidates(
    req: MemoryCandidateRequest, db: AsyncSession = Depends(get_session)
):
    """从任务报告/聊天记录生成候选记忆（落库 status=draft，待用户确认）。"""
    svc = MemoryCandidateService(db)
    try:
        if req.source_type == "agent_task":
            items = await svc.generate_from_task(req.source_id)
        elif req.source_type == "chat_session":
            items = await svc.generate_from_chat(req.source_id)
        else:
            # learning_review 来源 defer 到 M2
            items = await svc.generate_from_learning_review(req.source_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ProviderError as e:
        raise HTTPException(502, str(e))
    return items


@router.post("/memories/{memory_id}/use")
async def mark_memory_used(
    memory_id: int, req: MemoryUseRequest, db: AsyncSession = Depends(get_session)
):
    """记录记忆被使用的审计事件（ref 标识使用场景，如 chat_session）。"""
    svc = MemoryService(db)
    if await svc.get(memory_id) is None:
        raise HTTPException(404, "记忆不存在")
    await svc.record_usage([memory_id], ref_type=req.ref_type, ref_id=req.ref_id)
    return {"ok": True, "memory_id": memory_id}


@router.get("/memories/{memory_id}/events", response_model=list[MemoryEventOut])
async def list_memory_events(
    memory_id: int, db: AsyncSession = Depends(get_session)
):
    """记忆事件流（创建/使用/编辑/禁用审计）。"""
    svc = MemoryService(db)
    if await svc.get(memory_id) is None:
        raise HTTPException(404, "记忆不存在")
    return await svc.list_events(memory_id)


@router.get("/memories/{memory_id}/revisions", response_model=list[MemoryRevisionOut])
async def list_memory_revisions(
    memory_id: int, db: AsyncSession = Depends(get_session)
):
    """返回完整版本链；软删除后仍可审计与恢复内容。"""
    svc = MemoryService(db)
    if await svc.get_including_deleted(memory_id) is None:
        raise HTTPException(404, "记忆不存在")
    return await svc.list_revisions(memory_id)


@router.get("/memory-conflicts", response_model=list[MemoryConflictOut])
async def list_memory_conflicts(db: AsyncSession = Depends(get_session)):
    return await MemoryService(db).list_open_conflicts()


@router.post("/memory-conflicts", response_model=MemoryConflictOut, status_code=201)
async def create_memory_conflict(
    req: MemoryConflictCreate, db: AsyncSession = Depends(get_session)
):
    try:
        return await MemoryService(db).create_conflict(
            req.left_memory_id,
            req.right_memory_id,
            reason=req.reason,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post(
    "/memory-conflicts/{conflict_id}/resolve",
    response_model=MemoryConflictOut,
)
async def resolve_memory_conflict(
    conflict_id: int,
    req: MemoryConflictResolve,
    db: AsyncSession = Depends(get_session),
):
    try:
        conflict = await MemoryService(db).resolve_conflict(
            conflict_id,
            resolution=req.resolution,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if conflict is None:
        raise HTTPException(404, "记忆冲突不存在")
    return conflict
