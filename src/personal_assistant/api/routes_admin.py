"""管理员用户数据与系统状态监控 API。"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from typing import Literal, Self

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth import hash_password, normalize_email
from ..core.db import get_session
from ..core.health import HealthService
from ..core.models import AuditLog, AuthSession, ChatSession, Document, Project, User
from ..core.tenant import without_tenant_scope
from ..core.timeutil import format_rfc3339_utc, utcnow
from .auth_dependencies import admin_principal

router = APIRouter(prefix="/admin", tags=["admin"])
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AdminOverview(BaseModel):
    users_total: int
    users_active: int
    admins_total: int
    sessions_total: int
    projects_total: int
    operations_24h: int
    errors_24h: int
    health: dict
    generated_at: datetime

    @field_serializer("generated_at")
    def _serialize_time(self, value: datetime) -> str | None:
        return format_rfc3339_utc(value)


class AdminUserRow(BaseModel):
    id: int
    email: str
    username: str
    # 旧客户端兼容字段；新界面统一使用 username。
    display_name: str
    role: str
    status: str
    last_login_at: datetime | None
    created_at: datetime
    session_count: int
    project_count: int
    document_count: int
    operation_count: int

    @field_serializer("last_login_at", "created_at")
    def _serialize_time(self, value: datetime | None) -> str | None:
        return format_rfc3339_utc(value)


class AdminUserList(BaseModel):
    total: int
    results: list[AdminUserRow]


class AdminUserAccount(BaseModel):
    id: int
    email: str
    username: str
    display_name: str
    role: str
    status: str
    last_login_at: datetime | None
    created_at: datetime

    @field_serializer("last_login_at", "created_at")
    def _serialize_time(self, value: datetime | None) -> str | None:
        return format_rfc3339_utc(value)


class AdminUserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=10, max_length=128)
    role: Literal["admin", "user"] = "user"

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if not _EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("请输入有效邮箱地址")
        return normalized

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized = value.strip()
        if not 2 <= len(normalized) <= 50:
            raise ValueError("用户名长度需为 2–50 个字符")
        if "@" in normalized or any(
            character.isspace()
            or unicodedata.category(character).startswith("C")
            for character in normalized
        ):
            raise ValueError("用户名不能包含 @、空白或控制字符")
        return normalized


class AdminUserUpdate(BaseModel):
    role: Literal["admin", "user"] | None = None
    status: Literal["active", "disabled"] | None = None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if self.role is None and self.status is None:
            raise ValueError("至少提供一项用户变更")
        return self


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

    @field_serializer("created_at")
    def _serialize_time(self, value: datetime) -> str | None:
        return format_rfc3339_utc(value)


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
        projects_total = (
            await db.execute(select(func.count(Project.id)))
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
        projects_total=projects_total,
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
    role: Literal["admin", "user"] | None = Query(default=None),
    status_filter: Literal["active", "disabled"] | None = Query(
        default=None, alias="status"
    ),
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
        filters.append(or_(User.email.like(keyword), User.username.like(keyword)))
    if role is not None:
        filters.append(User.role == role)
    if status_filter is not None:
        filters.append(User.status == status_filter)
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
                username=user.username,
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


def _admin_user_account(user: User) -> AdminUserAccount:
    return AdminUserAccount(
        id=user.id,
        email=user.email,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        status=user.status,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


@router.post(
    "/users",
    response_model=AdminUserAccount,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    payload: AdminUserCreate,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> AdminUserAccount:
    """由管理员创建已激活账号；不走公开注册和邮箱验证码流程。"""
    admin_principal(request)
    with without_tenant_scope():
        existing = (
            await db.execute(
                select(User.id).where(
                    or_(
                        User.email == payload.email,
                        User.username == payload.username,
                    )
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="邮箱或用户名已存在")
        user = User(
            email=payload.email,
            username=payload.username,
            display_name=payload.username,
            password_hash=hash_password(payload.password),
            role=payload.role,
            status="active",
        )
        db.add(user)
        try:
            await db.commit()
            await db.refresh(user)
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(status_code=409, detail="邮箱或用户名已存在") from exc
    return _admin_user_account(user)


@router.patch("/users/{user_id}", response_model=AdminUserAccount)
async def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> AdminUserAccount:
    """修改用户角色或状态；停用账号时立即撤销其全部有效会话。"""
    principal = admin_principal(request)
    with without_tenant_scope():
        user = (
            await db.execute(
                select(User).where(User.id == user_id).with_for_update()
            )
        ).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")

        next_role = payload.role or user.role
        next_status = payload.status or user.status
        removes_admin_access = next_role != "admin" or next_status != "active"
        if principal.user_id == user.id and removes_admin_access:
            raise HTTPException(status_code=409, detail="不能停用或降级当前管理员账号")

        if user.role == "admin" and user.status == "active" and removes_admin_access:
            active_admins = (
                await db.execute(
                    select(func.count(User.id)).where(
                        User.role == "admin", User.status == "active"
                    )
                )
            ).scalar_one()
            if active_admins <= 1:
                raise HTTPException(status_code=409, detail="系统必须保留一个可用管理员")

        user.role = next_role
        user.status = next_status
        if next_status == "disabled":
            now = utcnow()
            await db.execute(
                update(AuthSession)
                .where(
                    AuthSession.user_id == user.id,
                    AuthSession.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
        await db.commit()
        await db.refresh(user)
    return _admin_user_account(user)


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
