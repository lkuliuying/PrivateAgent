"""管理员用户数据与系统状态监控 API。"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.health import HealthService
from ..core.models import AuditLog, ChatSession, Document, Project, User
from ..core.tenant import without_tenant_scope
from ..core.timeutil import utcnow
from .auth_dependencies import admin_principal

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminOverview(BaseModel):
    users_total: int
    users_active: int
    admins_total: int
    sessions_total: int
    operations_24h: int
    errors_24h: int
    health: dict
    generated_at: datetime


class AdminUserRow(BaseModel):
    id: int
    email: str
    display_name: str
    role: str
    status: str
    last_login_at: datetime | None
    created_at: datetime
    session_count: int
    project_count: int
    document_count: int
    operation_count: int


class AdminUserList(BaseModel):
    total: int
    results: list[AdminUserRow]


class AuditLogRow(BaseModel):
    id: int
    request_id: str
    actor_user_id: int | None
    actor_type: str
    method: str
    path: str
    status_code: int
    duration_ms: int
    client_ip: str | None
    created_at: datetime


class AuditLogList(BaseModel):
    total: int
    results: list[AuditLogRow]


@router.get("/overview", response_model=AdminOverview)
async def overview(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> AdminOverview:
    admin_principal(request)
    since = utcnow() - timedelta(hours=24)
    with without_tenant_scope():
        users_total = (await db.execute(select(func.count(User.id)))).scalar_one()
        users_active = (
            await db.execute(
                select(func.count(User.id)).where(User.status == "active")
            )
        ).scalar_one()
        admins_total = (
            await db.execute(select(func.count(User.id)).where(User.role == "admin"))
        ).scalar_one()
        sessions_total = (
            await db.execute(select(func.count(ChatSession.id)))
        ).scalar_one()
        operations_24h = (
            await db.execute(
                select(func.count(AuditLog.id)).where(AuditLog.created_at >= since)
            )
        ).scalar_one()
        errors_24h = (
            await db.execute(
                select(func.count(AuditLog.id)).where(
                    AuditLog.created_at >= since, AuditLog.status_code >= 400
                )
            )
        ).scalar_one()
    return AdminOverview(
        users_total=users_total,
        users_active=users_active,
        admins_total=admins_total,
        sessions_total=sessions_total,
        operations_24h=operations_24h,
        errors_24h=errors_24h,
        health=await HealthService().check_all(),
        generated_at=utcnow(),
    )


@router.get("/users", response_model=AdminUserList)
async def list_users(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    db: AsyncSession = Depends(get_session),
) -> AdminUserList:
    admin_principal(request)
    session_counts = (
        select(ChatSession.owner_user_id.label("user_id"), func.count().label("count"))
        .where(ChatSession.owner_user_id.is_not(None))
        .group_by(ChatSession.owner_user_id)
        .subquery()
    )
    project_counts = (
        select(Project.owner_user_id.label("user_id"), func.count().label("count"))
        .where(Project.owner_user_id.is_not(None))
        .group_by(Project.owner_user_id)
        .subquery()
    )
    document_counts = (
        select(Document.owner_user_id.label("user_id"), func.count().label("count"))
        .where(Document.owner_user_id.is_not(None))
        .group_by(Document.owner_user_id)
        .subquery()
    )
    operation_counts = (
        select(AuditLog.actor_user_id.label("user_id"), func.count().label("count"))
        .where(AuditLog.actor_user_id.is_not(None))
        .group_by(AuditLog.actor_user_id)
        .subquery()
    )
    filters = []
    if search:
        keyword = f"%{search.strip()}%"
        filters.append(or_(User.email.like(keyword), User.display_name.like(keyword)))
    total = (
        await db.execute(select(func.count(User.id)).where(*filters))
    ).scalar_one()
    query = (
        select(
            User,
            func.coalesce(session_counts.c.count, 0),
            func.coalesce(project_counts.c.count, 0),
            func.coalesce(document_counts.c.count, 0),
            func.coalesce(operation_counts.c.count, 0),
        )
        .outerjoin(session_counts, session_counts.c.user_id == User.id)
        .outerjoin(project_counts, project_counts.c.user_id == User.id)
        .outerjoin(document_counts, document_counts.c.user_id == User.id)
        .outerjoin(operation_counts, operation_counts.c.user_id == User.id)
        .where(*filters)
        .order_by(User.created_at.desc(), User.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    with without_tenant_scope():
        rows = (await db.execute(query)).all()
    return AdminUserList(
        total=total,
        results=[
            AdminUserRow(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                role=user.role,
                status=user.status,
                last_login_at=user.last_login_at,
                created_at=user.created_at,
                session_count=int(session_count),
                project_count=int(project_count),
                document_count=int(document_count),
                operation_count=int(operation_count),
            )
            for user, session_count, project_count, document_count, operation_count in rows
        ],
    )


@router.get("/audit-logs", response_model=AuditLogList)
async def list_audit_logs(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    actor_user_id: int | None = Query(default=None, gt=0),
    status_code: int | None = Query(default=None, ge=100, le=599),
    db: AsyncSession = Depends(get_session),
) -> AuditLogList:
    admin_principal(request)
    filters = []
    if actor_user_id is not None:
        filters.append(AuditLog.actor_user_id == actor_user_id)
    if status_code is not None:
        filters.append(AuditLog.status_code == status_code)
    total = (
        await db.execute(select(func.count(AuditLog.id)).where(*filters))
    ).scalar_one()
    rows = (
        await db.execute(
            select(AuditLog)
            .where(*filters)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).scalars().all()
    return AuditLogList(
        total=total,
        results=[
            AuditLogRow(
                id=item.id,
                request_id=item.request_id,
                actor_user_id=item.actor_user_id,
                actor_type=item.actor_type,
                method=item.method,
                path=item.path,
                status_code=item.status_code,
                duration_ms=item.duration_ms,
                client_ip=item.client_ip,
                created_at=item.created_at,
            )
            for item in rows
        ],
    )
