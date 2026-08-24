"""v0.9.0 H0 §6.3：full_access 独立 capability 的授予管理。

契约要点（与 ``workspace`` 互相独立，不是别名）：
- 授予绑定会话与项目，仅在有效期内有效（``coding_full_access_ttl_minutes``）；
- 到期 / 撤销 / 应用重启（启动时 reconcile）→ 自动失效；
- 每次授予必须由用户显式二次确认（路由层把关），不跨项目扩散；
- 查询只返回未撤销且未过期的授予；执行器在每次工具调用前重新校验。

本模块不触碰任何凭据/秘密；授予事实只含会话/项目引用与时间。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..logging_setup import get_logger
from .models import FullAccessGrant
from .timeutil import utcnow

logger = get_logger(__name__)

# 撤销原因低基数词汇（telemetry/审计同口径）
REVOKE_REASONS = frozenset(
    {"user_revoke", "expired", "app_exit", "project_switch"}
)


class FullAccessError(Exception):
    """full_access 授予相关失败（路由层映射到冻结错误码）。"""

    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class ActiveGrant:
    id: str
    session_id: int
    project_id: int
    granted_at: datetime
    expires_at: datetime


class FullAccessGrantService:
    """full_access 授予的创建/撤销/校验/到期回收。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def grant(self, *, session_id: int, project_id: int) -> FullAccessGrant:
        """创建新授予（调用方必须已完成用户显式二次确认）。

        同一会话已存在有效授予时直接复用（幂等），不叠加有效期。
        """
        existing = await self.get_active(session_id)
        if existing is not None and existing.project_id == project_id:
            return existing
        if existing is not None:
            # 切换项目：旧授予自动失效（H0 §6.3 自动失效规则）
            await self.revoke(existing.id, reason="project_switch")
        now = utcnow()
        grant = FullAccessGrant(
            session_id=session_id,
            project_id=project_id,
            granted_at=now,
            expires_at=now
            + timedelta(minutes=settings.coding_full_access_ttl_minutes),
        )
        self.db.add(grant)
        await self.db.flush()
        logger.info(
            "full_access granted",
            session_id=session_id,
            project_id=project_id,
            ttl_minutes=settings.coding_full_access_ttl_minutes,
        )
        return grant

    async def get_active(self, session_id: int) -> FullAccessGrant | None:
        """返回会话当前有效授予（未撤销且未过期），否则 None。"""
        now = utcnow()
        result = await self.db.execute(
            select(FullAccessGrant)
            .where(
                FullAccessGrant.session_id == session_id,
                FullAccessGrant.revoked_at.is_(None),
                FullAccessGrant.expires_at > now,
            )
            .order_by(FullAccessGrant.granted_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def require_active(self, session_id: int) -> FullAccessGrant:
        """校验有效授予；缺失/过期/撤销分别映射冻结错误码（fail-closed）。"""
        grant = await self.get_active(session_id)
        if grant is not None:
            return grant
        # 区分过期/撤销与从未授予：供路由层返回准确错误码
        result = await self.db.execute(
            select(FullAccessGrant)
            .where(FullAccessGrant.session_id == session_id)
            .order_by(FullAccessGrant.granted_at.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        if latest is not None and latest.revoked_at is not None:
            raise FullAccessError(
                "full_access_revoked", "full_access grant has been revoked"
            )
        if latest is not None:
            raise FullAccessError(
                "full_access_grant_expired", "full_access grant has expired"
            )
        raise FullAccessError(
            "full_access_unsupported", "no full_access grant for this session"
        )

    async def revoke(self, grant_id: str, *, reason: str = "user_revoke") -> bool:
        """撤销授予；已撤销/不存在返回 False（幂等）。"""
        if reason not in REVOKE_REASONS:
            raise ValueError(f"unknown revoke reason: {reason}")
        result = await self.db.execute(
            update(FullAccessGrant)
            .where(
                FullAccessGrant.id == grant_id,
                FullAccessGrant.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow(), revoke_reason=reason)
        )
        if result.rowcount:
            logger.info("full_access revoked", grant_id=grant_id, reason=reason)
            return True
        return False

    async def reconcile_expired(self) -> int:
        """启动/周期性回收：把已过期的未撤销授予标记为 expired。

        计划 §3.3/§6.3：退出应用（进程重启）后授予自动失效——启动时把
        上一个进程生命周期的授予全部回收，再叠加 expires_at 自然过期。
        """
        now = utcnow()
        result = await self.db.execute(
            update(FullAccessGrant)
            .where(
                FullAccessGrant.revoked_at.is_(None),
                FullAccessGrant.expires_at <= now,
            )
            .values(revoked_at=now, revoke_reason="expired")
        )
        return int(result.rowcount or 0)

    async def revoke_all_on_app_exit(self) -> int:
        """应用退出/重启时回收全部未撤销授予（自动失效规则）。"""
        result = await self.db.execute(
            update(FullAccessGrant)
            .where(FullAccessGrant.revoked_at.is_(None))
            .values(revoked_at=utcnow(), revoke_reason="app_exit")
        )
        return int(result.rowcount or 0)
