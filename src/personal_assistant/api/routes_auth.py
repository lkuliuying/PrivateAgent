"""注册、登录、当前账号与退出登录。"""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.auth import (
    claim_legacy_rows,
    hash_password,
    issue_auth_session,
    normalize_email,
    token_digest,
    verify_password,
)
from ..core.db import get_session
from ..core.models import AuthSession, User
from ..core.timeutil import utcnow
from .auth_dependencies import current_principal

router = APIRouter(prefix="/auth", tags=["auth"])
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if not _EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("请输入有效邮箱地址")
        return normalized


class RegisterRequest(Credentials):
    display_name: str = Field(min_length=1, max_length=100)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("显示名称不能为空")
        return normalized


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    role: str
    status: str
    last_login_at: datetime | None
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        status=user.status,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_session),
) -> AuthResponse:
    if not settings.allow_public_registration:
        raise HTTPException(status_code=403, detail="当前部署未开放注册")
    lock_acquired = (
        await db.execute(text("SELECT GET_LOCK('pa_user_registration', 10)"))
    ).scalar_one()
    if lock_acquired != 1:
        raise HTTPException(status_code=503, detail="注册请求繁忙，请稍后重试")
    try:
        existing = (
            await db.execute(select(User.id).where(User.email == payload.email))
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="该邮箱已注册")

        user_count = (await db.execute(select(func.count(User.id)))).scalar_one()
        user = User(
            email=payload.email,
            display_name=payload.display_name,
            password_hash=hash_password(payload.password),
            role="admin" if user_count == 0 else "user",
            status="active",
            last_login_at=utcnow(),
        )
        db.add(user)
        try:
            await db.flush()
            if user_count == 0 and settings.claim_legacy_data_on_first_user:
                await claim_legacy_rows(db, user.id)
            session, raw_token = await issue_auth_session(db, user)
            await db.commit()
            await db.refresh(user)
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(status_code=409, detail="该邮箱已注册") from exc
    finally:
        await db.execute(text("SELECT RELEASE_LOCK('pa_user_registration')"))
    return AuthResponse(
        access_token=raw_token,
        expires_at=session.expires_at,
        user=_user_out(user),
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: Credentials,
    db: AsyncSession = Depends(get_session),
) -> AuthResponse:
    user = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已停用")
    user.last_login_at = utcnow()
    session, raw_token = await issue_auth_session(db, user)
    await db.commit()
    await db.refresh(user)
    return AuthResponse(
        access_token=raw_token,
        expires_at=session.expires_at,
        user=_user_out(user),
    )


@router.get("/me", response_model=UserOut)
async def me(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> UserOut:
    principal = current_principal(request)
    user = await db.get(User, principal.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    return _user_out(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> None:
    principal = current_principal(request)
    authorization = request.headers.get("Authorization", "")
    _, _, raw_token = authorization.partition(" ")
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == principal.user_id,
            AuthSession.token_hash == token_digest(raw_token),
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    await db.commit()
