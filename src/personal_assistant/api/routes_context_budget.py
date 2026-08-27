"""v0.9.0 H1-A：上下文 budget 公开端点（H0 §7.1）。

flag ``coding_context_budget_enabled`` 关闭时整体 409 ``coding_mode_disabled``；
遥测 ``context_budget_poll`` 只记 available/unavailable/error 低基数计数。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from ..core.compatibility import compatibility_telemetry
from ..core.context_budget_service import evaluate_session_budget
from ..core.db import get_session
from ..core.history import SessionRepository

router = APIRouter(tags=["context-budget"])


def _telemetry(outcome: str) -> None:
    compatibility_telemetry.record(
        path="context_budget_poll", mode="coding", outcome=outcome
    )


@router.get("/sessions/{session_id}/context-budget")
async def get_context_budget(
    session_id: int, db: AsyncSession = Depends(get_session)
):
    """typed context budget（字段契约见 H0 §7.1）。"""
    from fastapi.responses import JSONResponse

    if not cfg.coding_context_budget_enabled:
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "coding_mode_disabled",
                "detail": "Context budget is disabled",
            },
        )
    sess = await SessionRepository(db).get(session_id)
    if sess is None:
        _telemetry("error")
        return JSONResponse(
            status_code=404,
            content={
                "error_code": "workspace_not_found",
                "detail": "会话不存在",
            },
        )
    budget = await evaluate_session_budget(db, session_id)
    _telemetry(
        "available" if budget.source.value != "unavailable" else "unavailable"
    )
    return budget.to_response()
