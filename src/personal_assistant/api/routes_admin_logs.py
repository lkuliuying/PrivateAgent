"""Administrator-only service log viewer, independent of database queries."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ..core.admin_logs import LogSource, LogUnavailable, read_log_tail, source_status


def require_log_admin(request: Request) -> None:
    from .auth_dependencies import admin_principal

    admin_principal(request)


router = APIRouter(
    prefix="/admin/logs", tags=["admin"], dependencies=[Depends(require_log_admin)]
)


def configured_log_sources() -> dict[str, LogSource]:
    from ..config import settings

    return {
        source.id: source
        for source in (
            LogSource("supervisor", "Supervisor · 应用输出", settings.admin_supervisor_log),
            LogSource("supervisord", "Supervisor · 进程管理", settings.admin_supervisord_log),
            LogSource("nginx-access", "Nginx · 访问日志", settings.admin_nginx_access_log),
            LogSource("nginx-error", "Nginx · 错误日志", settings.admin_nginx_error_log),
        )
    }


@router.get("")
async def list_log_sources(response: Response):
    response.headers["Cache-Control"] = "no-store"
    sources = configured_log_sources()
    return {"sources": await asyncio.to_thread(lambda: [source_status(s) for s in sources.values()])}


@router.get("/{source_id}")
async def get_log_tail(
    source_id: str,
    response: Response,
    lines: int = Query(default=200, ge=1, le=1000),
    search: str = Query(default="", max_length=100),
):
    source = configured_log_sources().get(source_id)
    if source is None:
        raise HTTPException(404, "未知日志类型")
    response.headers["Cache-Control"] = "no-store"
    try:
        return await asyncio.to_thread(read_log_tail, source, lines=lines, search=search)
    except LogUnavailable as error:
        raise HTTPException(503, str(error)) from None
