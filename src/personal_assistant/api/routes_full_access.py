"""v0.9.0 H1-A：full_access 独立 capability 的授予管理路由（H0 §6.3）。

- 授予必须来自用户显式动作（前端二次确认后才调用本端点）；
- 会话必须是已绑定项目的 coding 会话；授予绑定该会话与项目，不跨项目扩散；
- 到期/撤销/应用退出自动失效（服务层语义）；
- ``workspace`` 与 ``full_access`` 不是别名：本路由不触碰任何
  workspace 自动批准配置。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from ..core.db import get_session
from ..core.full_access import FullAccessError, FullAccessGrantService
from ..core.timeutil import format_rfc3339_utc
from ..logging_setup import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["full-access"])


def _error(status: int, error_code: str, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status,
        content={"error_code": error_code, "detail": detail},
    )


class FullAccessGrantOut(BaseModel):
    active: bool
    grant_id: str | None = None
    session_id: int | None = None
    project_id: int | None = None
    granted_at: str | None = None
    expires_at: str | None = None


def _telemetry(outcome: str) -> None:
    from ..core.compatibility import compatibility_telemetry

    compatibility_telemetry.record(
        path="full_access_grant", mode="session", outcome=outcome
    )


def _map_grant(grant) -> FullAccessGrantOut:
    return FullAccessGrantOut(
        active=True,
        grant_id=grant.id,
        session_id=grant.session_id,
        project_id=grant.project_id,
        granted_at=format_rfc3339_utc(grant.granted_at),
        expires_at=format_rfc3339_utc(grant.expires_at),
    )


@router.get(
    "/sessions/{session_id}/full-access-grant",
    response_model=FullAccessGrantOut,
)
async def get_active_grant(
    session_id: int, db: AsyncSession = Depends(get_session)
):
    """查询会话当前有效授予（无则 active=false；能力位关闭同样视为无）。"""
    if not cfg.coding_full_access_enabled:
        return FullAccessGrantOut(active=False)
    grant = await FullAccessGrantService(db).get_active(session_id)
    if grant is None:
        return FullAccessGrantOut(active=False)
    return _map_grant(grant)


@router.post(
    "/sessions/{session_id}/full-access-grant",
    response_model=FullAccessGrantOut,
    status_code=201,
)
async def create_grant(
    session_id: int, db: AsyncSession = Depends(get_session)
):
    """显式授予（前端二次确认后调用）。失败关闭：能力位/会话绑定不满足即拒绝。"""
    from ..core.history import SessionRepository

    if not cfg.coding_full_access_enabled:
        _telemetry("denied")
        return _error(
            409, "full_access_unsupported", "full_access capability is not enabled"
        )
    sess = await SessionRepository(db).get(session_id)
    if sess is None or sess.project_id is None:
        _telemetry("denied")
        return _error(
            409,
            "full_access_unsupported",
            "full_access requires a project-bound session",
        )
    try:
        grant = await FullAccessGrantService(db).grant(
            session_id=session_id, project_id=sess.project_id
        )
        await db.commit()
    except FullAccessError as exc:
        _telemetry("denied")
        return _error(409, exc.error_code, exc.detail)
    _telemetry("granted")
    logger.info(
        "full_access grant created",
        session_id=session_id,
        project_id=sess.project_id,
    )
    return _map_grant(grant)


@router.delete("/full-access-grants/{grant_id}")
async def revoke_grant(grant_id: str, db: AsyncSession = Depends(get_session)):
    """即时撤销（支持立即撤销；幂等）。"""
    revoked = await FullAccessGrantService(db).revoke(
        grant_id, reason="user_revoke"
    )
    await db.commit()
    if revoked:
        _telemetry("revoked")
    return {"revoked": revoked}
