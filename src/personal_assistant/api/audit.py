"""全请求操作审计中间件与保留期清理。"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from time import perf_counter
from uuid import uuid4

from sqlalchemy import delete
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..config import settings
from ..core.auth import Principal
from ..core.models import AuditLog, AuthSession
from ..core.timeutil import utcnow
from ..logging_setup import get_logger

logger = get_logger(__name__)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if key.lower() == name:
            try:
                return value.decode("latin-1")
            except UnicodeDecodeError:
                return None
    return None


class RequestAuditMiddleware:
    """记录 HTTP 操作结果；审计写入失败不得改变业务响应。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        started = perf_counter()
        status_code = 500
        request_id = str(uuid4())

        async def capture_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            duration_ms = max(0, int((perf_counter() - started) * 1000))
            state = scope.get("state") or {}
            principal = state.get("principal")
            if not isinstance(principal, Principal):
                principal = None
            client = scope.get("client")
            client_ip = str(client[0])[:64] if client else None
            method = str(scope.get("method") or "UNKNOWN")[:10]
            path = str(scope.get("path") or "/")[:512]
            actor_type = principal.actor_type if principal else "anonymous"
            actor_user_id = principal.user_id if principal else None
            logger.info(
                "http operation",
                request_id=request_id,
                actor_type=actor_type,
                actor_user_id=actor_user_id,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
            )
            try:
                from ..core import db as db_module

                async with db_module.async_session_factory() as db:
                    db.add(
                        AuditLog(
                            request_id=request_id,
                            actor_user_id=actor_user_id,
                            actor_type=actor_type,
                            method=method,
                            path=path,
                            status_code=status_code,
                            duration_ms=duration_ms,
                            client_ip=client_ip,
                            user_agent=(_header(scope, b"user-agent") or "")[:512]
                            or None,
                        )
                    )
                    await db.commit()
            except Exception as exc:
                logger.error(
                    "audit persistence failed",
                    request_id=request_id,
                    error_type=type(exc).__name__,
                )


async def purge_expired_security_records() -> dict[str, int]:
    """清理超过保留期的审计记录和已经失效的登录会话。"""
    from ..core import db as db_module

    now = utcnow()
    audit_cutoff = now - timedelta(days=settings.audit_log_retention_days)
    session_cutoff = now - timedelta(days=7)
    async with db_module.async_session_factory() as db:
        audit_result = await db.execute(
            delete(AuditLog).where(AuditLog.created_at < audit_cutoff)
        )
        session_result = await db.execute(
            delete(AuthSession).where(
                (AuthSession.expires_at < session_cutoff)
                | (
                    AuthSession.revoked_at.is_not(None)
                    & (AuthSession.revoked_at < session_cutoff)
                )
            )
        )
        await db.commit()
    return {
        "audit_logs": int(audit_result.rowcount or 0),
        "auth_sessions": int(session_result.rowcount or 0),
    }


async def security_cleanup_loop() -> None:
    """按配置周期执行日志/会话保留策略。"""
    while True:
        try:
            removed = await purge_expired_security_records()
            logger.info("security retention cleanup", **removed)
        except Exception as exc:
            logger.error("security retention cleanup failed", error_type=type(exc).__name__)
        await asyncio.sleep(settings.security_cleanup_interval_seconds)
