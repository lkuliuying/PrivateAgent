"""多用户密码、登录会话和请求身份服务。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from .models import AuthSession, Base, User
from .timeutil import utcnow

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64


@dataclass(frozen=True, slots=True)
class Principal:
    """通过安全中间件认证后的最小身份。"""

    user_id: int | None
    role: str
    email: str | None
    actor_type: str
    session_id: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin" or self.actor_type == "service"


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def hash_password(password: str) -> str:
    """使用带随机盐的 scrypt 保存密码，不保存或记录明文。"""
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return "$".join(
        (
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(derived).decode("ascii"),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    """校验版本化 scrypt 哈希；畸形数据库值按失败处理。"""
    try:
        algorithm, n, r, p, salt_value, digest_value = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_value.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_value.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError, UnicodeError):
        return False
    return hmac.compare_digest(actual, expected)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue_auth_session(
    db: AsyncSession, user: User
) -> tuple[AuthSession, str]:
    """创建有期限会话；原始 token 仅在本次响应返回。"""
    raw_token = secrets.token_urlsafe(48)
    record = AuthSession(
        user_id=user.id,
        token_hash=token_digest(raw_token),
        expires_at=utcnow() + timedelta(hours=settings.auth_session_ttl_hours),
    )
    db.add(record)
    await db.flush()
    return record, raw_token


async def principal_for_token(db: AsyncSession, token: str) -> Principal | None:
    """解析用户会话 token；停用账号、撤销或过期会话全部拒绝。"""
    now = utcnow()
    record = (
        await db.execute(
            select(AuthSession)
            .options(selectinload(AuthSession.user))
            .where(
                AuthSession.token_hash == token_digest(token),
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if record is None or record.user.status != "active":
        return None
    return Principal(
        user_id=record.user.id,
        role=record.user.role,
        email=record.user.email,
        actor_type="user",
        session_id=record.id,
    )


async def claim_legacy_rows(db: AsyncSession, user_id: int) -> None:
    """显式迁移模式下，将尚未归属的旧本地业务数据交给首个管理员。"""
    for mapper in Base.registry.mappers:
        model = mapper.class_
        if not getattr(model, "__tenant_scoped__", True):
            continue
        await db.execute(
            update(model)
            .where(model.owner_user_id.is_(None))
            .values(owner_user_id=user_id)
        )
