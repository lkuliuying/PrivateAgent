"""FastAPI 应用入口。

开发启动：
    uvicorn personal_assistant.main_api:app --reload --port 8000
或（已安装本项目）：
    python -m personal_assistant.main_api
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from secrets import compare_digest
from time import perf_counter
from typing import Callable
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .api.routes_activities import router as activities_router
from .api.routes_agent_tasks import router as agent_tasks_router
from .api.routes_backup import router as backup_router
from .api.routes_briefings import router as briefings_router
from .api.routes_chat import router as chat_router
from .api.routes_coding import router as coding_router
from .api.routes_commands import router as commands_router
from .api.routes_capture import router as capture_router
from .api.routes_diagnostics import router as diagnostics_router
from .api.routes_document_collections import router as document_collections_router
from .api.routes_documents import router as documents_router
from .api.routes_extensions import router as extensions_router
from .api.routes_files import router as files_router
from .api.routes_integrations import router as integrations_router
from .api.routes_goals import router as goals_router
from .api.routes_health import router as health_router
from .api.routes_inbox import router as inbox_router
from .api.routes_learning import router as learning_router
from .api.routes_learning_reviews import router as learning_reviews_router
from .api.routes_maintenance import router as maintenance_router
from .api.routes_memories import router as memories_router
from .api.routes_notifications import router as notifications_router
from .api.routes_ocr import router as ocr_router
from .api.routes_patch_sets import router as patch_sets_router
from .api.routes_privacy import router as privacy_router
from .api.routes_projects import router as projects_router
from .api.routes_providers import router as providers_router
from .api.routes_reminders import router as reminders_router
from .api.routes_search import router as search_router
from .api.routes_testing import router as testing_router
from .api.routes_sessions import router as sessions_router
from .api.routes_settings import router as settings_router
from .api.routes_today import router as today_router
from .api.routes_tools import router as tools_router
from .config import settings
from .core.background import background_tasks
from .core.store_chroma import chroma_store
from .logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "后端启动",
        host=settings.api_host,
        port=settings.api_port,
        db=settings.db_url.split("@")[-1] if "@" in settings.db_url else "***",
        ollama=settings.ollama_base_url,
    )
    # 提醒后台 tick：sidecar 生命周期内轻量轮询到期提醒（reminders_enabled 关闭则跳过）。
    # 测试用 POST /reminders/tick 手动触发，不依赖此循环（ASGITransport 不运行 lifespan）。
    from .core.reminders import reminder_tick_loop

    tick_task = background_tasks.spawn(
        reminder_tick_loop,
        name="reminder-tick",
        key="service:reminder-tick",
        limited=False,
    )
    logger.info("提醒后台 tick 已启动")
    try:
        yield
    finally:
        tick_task.cancel()
        with suppress(asyncio.CancelledError):
            await tick_task
        await background_tasks.drain(timeout=5.0)
        await chroma_store.close()
        logger.info("后端关闭")


app = FastAPI(
    title="私人助手 Agent",
    version="0.1.2",
    description="本地优先、隐私可控的桌面私人助手后端",
    lifespan=lifespan,
)


# Tauri 生产 WebView 与浏览器开发服务的明确来源白名单。
TAURI_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
]
LOOPBACK_ORIGIN_REGEX = r"^https?://(?:localhost|127\.0\.0\.1)(?::\d{1,5})?$"


class ApiTokenAuthMiddleware:
    """校验桌面进程生成的 Bearer token；空 token 仅用于显式开发模式。"""

    def __init__(self, app: ASGIApp, token_provider: Callable[[], str]) -> None:
        self.app = app
        self._token_provider = token_provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        expected = self._token_provider()
        if not expected:
            await self.app(scope, receive, send)
            return

        raw_authorization = next(
            (
                value
                for name, value in scope.get("headers", [])
                if name.lower() == b"authorization"
            ),
            b"",
        )
        scheme, separator, credential = raw_authorization.partition(b" ")
        # 缺失或畸形 header 也执行比较；错误响应与日志均不包含令牌。
        credential_matches = compare_digest(credential, expected.encode("utf-8"))
        if separator != b" " or scheme.lower() != b"bearer" or not credential_matches:
            response = JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def _configured_api_token() -> str:
    return settings.api_token.get_secret_value()


# 先注册鉴权，再注册观测与 CORS，最终链路为 CORS(Observability(Auth(router)))。
app.add_middleware(ApiTokenAuthMiddleware, token_provider=_configured_api_token)


def _request_id(value: str | None) -> str:
    """只接受短且可安全写入日志/响应头的调用方 request id。"""
    if value and value.isascii() and 1 <= len(value) <= 64 and all(
        ch.isalnum() or ch in "-_" for ch in value
    ):
        return value
    return uuid4().hex


@app.middleware("http")
async def request_observability(request: Request, call_next) -> Response:
    """记录不含正文和查询参数的首字节耗时，并贯穿 request id。"""
    request_id = _request_id(request.headers.get("x-request-id"))
    started = perf_counter()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    status_code = 500
    try:
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            logger.exception(
                "API 请求异常",
                method=request.method,
                route=request.url.path,
                ttfb_ms=round((perf_counter() - started) * 1000, 2),
            )
            # Returning the generic response here (instead of re-raising to Starlette's
            # outer ServerErrorMiddleware) keeps correlation/timing and CORS headers on
            # otherwise-unhandled 500 responses without exposing exception details.
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal Server Error"},
            )
        elapsed_ms = (perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = f"ttfb;dur={elapsed_ms:.2f}"
        return response
    finally:
        elapsed_ms = (perf_counter() - started) * 1000
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        log = logger.debug if route_path == "/health" else logger.info
        log(
            "API 响应头已生成",
            method=request.method,
            route=route_path,
            status=status_code,
            ttfb_ms=round(elapsed_ms, 2),
        )
        structlog.contextvars.clear_contextvars()


# CORS 最外层包裹鉴权与观测中间件，使成功、401 与兜底 500 都携带一致响应头。
app.add_middleware(
    CORSMiddleware,
    allow_origins=TAURI_ORIGINS,
    allow_origin_regex=LOOPBACK_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Server-Timing"],
)

app.include_router(health_router)
app.include_router(today_router)
app.include_router(inbox_router)
app.include_router(goals_router)
app.include_router(briefings_router)
app.include_router(privacy_router)
app.include_router(sessions_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(settings_router)
app.include_router(extensions_router)
app.include_router(integrations_router)
app.include_router(tools_router)
app.include_router(files_router)
app.include_router(activities_router)
app.include_router(projects_router)
app.include_router(learning_router)
app.include_router(coding_router)
app.include_router(agent_tasks_router)
app.include_router(backup_router)
app.include_router(capture_router)
app.include_router(document_collections_router)
app.include_router(diagnostics_router)
app.include_router(learning_reviews_router)
app.include_router(memories_router)
app.include_router(maintenance_router)
app.include_router(notifications_router)
app.include_router(ocr_router)
app.include_router(patch_sets_router)
app.include_router(commands_router)
app.include_router(providers_router)
app.include_router(reminders_router)
app.include_router(search_router)
app.include_router(testing_router)


@app.get("/")
async def root() -> dict:
    return {"name": "personal-assistant", "version": "0.1.2", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "personal_assistant.main_api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
