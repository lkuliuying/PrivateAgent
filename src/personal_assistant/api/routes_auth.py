"""邮箱验证、注册、登录、当前账号与退出登录。"""
from __future__ import annotations

import asyncio
import hashlib
import re
import unicodedata
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import AliasChoices, BaseModel, Field, field_validator
from sqlalchemy import func, or_, select, text, update
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
from ..core.email_verification import (
    VERIFICATION_MAX_ATTEMPTS,
    VERIFICATION_RESEND_SECONDS,
    VERIFICATION_TTL_MINUTES,
    generate_verification_code,
    new_verification_digest,
    verification_code_matches,
)
from ..core.models import AuthSession, EmailVerificationCode, User
from ..core.smtp_email import (
    EmailDeliveryError,
    SmtpConfigurationError,
    send_registration_verification_email,
)
from ..core.timeutil import utcnow
from .auth_dependencies import current_principal

router = APIRouter(prefix="/auth", tags=["auth"])
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_VERIFICATION_CODE_PATTERN = re.compile(r"^[A-Za-z0-9]{6}$")


def _validated_email(value: str) -> str:
    normalized = normalize_email(value)
    if not _EMAIL_PATTERN.fullmatch(normalized):
        raise ValueError("请输入有效邮箱地址")
    return normalized


def _validated_username(value: str) -> str:
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


class LoginRequest(BaseModel):
    identifier: str = Field(
        min_length=2,
        max_length=320,
        validation_alias=AliasChoices("identifier", "email"),
    )
    password: str = Field(min_length=10, max_length=128)

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        return _validated_email(value) if "@" in value else _validated_username(value)


class EmailVerificationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validated_email(value)


class RegisterRequest(EmailVerificationRequest):
    username: str = Field(
        min_length=2,
        max_length=50,
        validation_alias=AliasChoices("username", "display_name"),
    )
    password: str = Field(min_length=10, max_length=128)
    verification_code: str = Field(min_length=6, max_length=6)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return _validated_username(value)

    @field_validator("verification_code")
    @classmethod
    def validate_verification_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not _VERIFICATION_CODE_PATTERN.fullmatch(normalized):
            raise ValueError("验证码应为 6 位字母或数字")
        return normalized


class EmailVerificationSent(BaseModel):
    expires_in_seconds: int = VERIFICATION_TTL_MINUTES * 60
    retry_after_seconds: int = VERIFICATION_RESEND_SECONDS


class UserOut(BaseModel):
    id: int
    email: str
    username: str
    # 保留旧客户端读取能力；新界面不再展示“显示名称”。
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
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        status=user.status,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def _email_lock_name(email: str) -> str:
    digest = hashlib.sha256(email.encode("utf-8")).hexdigest()[:40]
    return f"pa_email_verification_{digest}"


async def _acquire_lock(db: AsyncSession, name: str, busy_message: str) -> None:
    acquired = (
        await db.execute(text("SELECT GET_LOCK(:name, 10)"), {"name": name})
    ).scalar_one()
    if acquired != 1:
        raise HTTPException(status_code=503, detail=busy_message)


async def _release_lock(db: AsyncSession, name: str) -> None:
    await db.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})


@router.post(
    "/email-verification/send",
    response_model=EmailVerificationSent,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_email_verification(
    payload: EmailVerificationRequest,
    db: AsyncSession = Depends(get_session),
) -> EmailVerificationSent:
    if not settings.allow_public_registration:
        raise HTTPException(status_code=403, detail="当前部署未开放注册")

    lock_name = _email_lock_name(payload.email)
    await _acquire_lock(db, lock_name, "验证码请求繁忙，请稍后重试")
    try:
        existing = (
            await db.execute(select(User.id).where(User.email == payload.email))
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="该邮箱已注册")

        now = utcnow()
        latest = (
            await db.execute(
                select(EmailVerificationCode)
                .where(
                    EmailVerificationCode.email == payload.email,
                    EmailVerificationCode.purpose == "registration",
                )
                .order_by(
                    EmailVerificationCode.created_at.desc(),
                    EmailVerificationCode.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest is not None:
            elapsed = (now - latest.created_at).total_seconds()
            if elapsed < VERIFICATION_RESEND_SECONDS:
                retry_after = max(1, int(VERIFICATION_RESEND_SECONDS - elapsed))
                raise HTTPException(
                    status_code=429,
                    detail=f"请在 {retry_after} 秒后重新获取验证码",
                    headers={"Retry-After": str(retry_after)},
                )

        code = generate_verification_code()
        salt, digest = new_verification_digest(code)
        record = EmailVerificationCode(
            email=payload.email,
            purpose="registration",
            code_hash=digest,
            code_salt=salt,
            attempts=0,
            expires_at=now + timedelta(minutes=VERIFICATION_TTL_MINUTES),
            created_at=now,
        )
        db.add(record)
        await db.flush()
        try:
            await asyncio.to_thread(
                send_registration_verification_email,
                payload.email,
                code,
                valid_minutes=VERIFICATION_TTL_MINUTES,
            )
        except SmtpConfigurationError as exc:
            await db.rollback()
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except EmailDeliveryError as exc:
            await db.rollback()
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        await db.execute(
            update(EmailVerificationCode)
            .where(
                EmailVerificationCode.email == payload.email,
                EmailVerificationCode.purpose == "registration",
                EmailVerificationCode.id != record.id,
                EmailVerificationCode.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        await db.commit()
        return EmailVerificationSent()
    finally:
        await _release_lock(db, lock_name)


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_session),
) -> AuthResponse:
    if not settings.allow_public_registration:
        raise HTTPException(status_code=403, detail="当前部署未开放注册")
    lock_name = "pa_user_registration"
    await _acquire_lock(db, lock_name, "注册请求繁忙，请稍后重试")
    try:
        existing_email = (
            await db.execute(select(User.id).where(User.email == payload.email))
        ).scalar_one_or_none()
        if existing_email is not None:
            raise HTTPException(status_code=409, detail="该邮箱已注册")
        existing_username = (
            await db.execute(select(User.id).where(User.username == payload.username))
        ).scalar_one_or_none()
        if existing_username is not None:
            raise HTTPException(status_code=409, detail="该用户名已被使用")

        now = utcnow()
        verification = (
            await db.execute(
                select(EmailVerificationCode)
                .where(
                    EmailVerificationCode.email == payload.email,
                    EmailVerificationCode.purpose == "registration",
                    EmailVerificationCode.consumed_at.is_(None),
                    EmailVerificationCode.expires_at > now,
                )
                .order_by(
                    EmailVerificationCode.created_at.desc(),
                    EmailVerificationCode.id.desc(),
                )
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if verification is None:
            raise HTTPException(status_code=400, detail="请先获取有效的邮箱验证码")
        if not verification_code_matches(
            payload.verification_code,
            verification.code_salt,
            verification.code_hash,
        ):
            verification.attempts += 1
            if verification.attempts >= VERIFICATION_MAX_ATTEMPTS:
                verification.consumed_at = now
            await db.commit()
            raise HTTPException(status_code=400, detail="邮箱验证码错误或已失效")

        user_count = (await db.execute(select(func.count(User.id)))).scalar_one()
        verification.consumed_at = now
        user = User(
            email=payload.email,
            username=payload.username,
            display_name=payload.username,
            password_hash=hash_password(payload.password),
            role="admin" if user_count == 0 else "user",
            status="active",
            last_login_at=now,
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
            raise HTTPException(
                status_code=409,
                detail="邮箱或用户名已存在",
            ) from exc
    finally:
        await _release_lock(db, lock_name)
    return AuthResponse(
        access_token=raw_token,
        expires_at=session.expires_at,
        user=_user_out(user),
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_session),
) -> AuthResponse:
    user = (
        await db.execute(
            select(User).where(
                or_(
                    User.email == payload.identifier,
                    User.username == payload.identifier,
                )
            )
        )
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱/用户名或密码错误")
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
