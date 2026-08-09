"""FastAPI 应用入口。

开发启动：
    uvicorn personal_assistant.main_api:app --reload --port 8000
或（已安装本项目）：
    python -m personal_assistant.main_api
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api.routes_activities import router as activities_router
from .api.routes_agent_runs import agent_run_coordinator
from .api.routes_agent_runs import router as agent_runs_router
from .api.routes_agent_tasks import router as agent_tasks_router
from .api.routes_backup import router as backup_router
from .api.routes_briefings import router as briefings_router
from .api.routes_capture import router as capture_router
from .api.routes_chat import router as chat_router
from .api.routes_coding import router as coding_router
from .api.routes_commands import router as commands_router
from .api.routes_diagnostics import router as diagnostics_router
from .api.routes_document_collections import router as document_collections_router
from .api.routes_documents import router as documents_router
from .api.routes_extensions import router as extensions_router
from .api.routes_files import router as files_router
from .api.routes_goals import router as goals_router
from .api.routes_health import router as health_router
from .api.routes_http_profiles import router as http_profiles_router
from .api.routes_inbox import router as inbox_router
from .api.routes_integrations import router as integrations_router
from .api.routes_learning import router as learning_router
from .api.routes_learning_reviews import router as learning_reviews_router
from .api.routes_maintenance import router as maintenance_router
from .api.routes_mcp import router as mcp_router
from .api.routes_memories import router as memories_router
from .api.routes_notifications import router as notifications_router
from .api.routes_ocr import router as ocr_router
from .api.routes_patch_sets import router as patch_sets_router
from .api.routes_privacy import router as privacy_router
from .api.routes_projects import router as projects_router
from .api.routes_providers import router as providers_router
from .api.routes_reminders import router as reminders_router
from .api.routes_search import router as search_router
from .api.routes_sessions import router as sessions_router
from .api.routes_settings import router as settings_router
from .api.routes_testing import router as testing_router
from .api.routes_today import router as today_router
from .api.routes_tools import router as tools_router
from .api.security import (
    LocalApiSecurityMiddleware,
    parse_csv_setting,
    validate_local_api_security,
)
from .config import settings
from .logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


async def monitor_agent_runtime_owner(
    guard, coordinator, *, interval: float = 10.0
) -> None:
    """周期核验 Agent runtime 的 MySQL named lock 所有权（R3 故障门禁）。

    ``guard.verify()`` 失败（owner connection 丢失）时关闭 coordinator 并退出，
    防止失去锁后继续写入口。``interval`` 可注入便于测试。
    """
    while True:
        await asyncio.sleep(interval)
        if not await guard.verify():
            logger.error("Agent runtime process ownership lost")
            await coordinator.shutdown()
            return


@asynccontextmanager
async def lifespan(app: FastAPI):
    token = settings.api_token.get_secret_value() if settings.api_token else None
    validate_local_api_security(
        bind_host=settings.api_host,
        auth_enabled=settings.api_auth_enabled,
        token=token,
        allowed_hosts=parse_csv_setting(settings.api_allowed_hosts),
        allowed_origins=parse_csv_setting(settings.api_allowed_origins),
        allow_non_loopback_bind=settings.api_allow_non_loopback_bind,
    )
    logger.info(
        "后端启动",
        host=settings.api_host,
        port=settings.api_port,
        db=settings.db_url.split("@")[-1] if "@" in settings.db_url else "***",
        ollama=settings.ollama_base_url,
    )
    agent_guard_task: asyncio.Task | None = None
    if settings.agent_runs_api_enabled or settings.chat_agent_runtime_enabled:
        from .agents.recovery import agent_runtime_process_guard

        recovery = await agent_runtime_process_guard.acquire(settings.db_url)
        logger.info(
            "Agent runtime process ownership acquired",
            failed_runs=recovery.failed_runs,
            cancelled_runs=recovery.cancelled_runs,
            failed_executions=recovery.failed_executions,
            unknown_executions=recovery.unknown_executions,
        )

        agent_guard_task = asyncio.create_task(
            monitor_agent_runtime_owner(agent_runtime_process_guard, agent_run_coordinator)
        )
    # 提醒后台 tick：sidecar 生命周期内轻量轮询到期提醒（reminders_enabled 关闭则跳过）。
    # 测试用 POST /reminders/tick 手动触发，不依赖此循环（ASGITransport 不运行 lifespan）。
    from .core.reminders import reminder_tick_loop

    tick_task = asyncio.create_task(reminder_tick_loop())
    logger.info("提醒后台 tick 已启动")
    recovery_task: asyncio.Task | None = None
    if settings.versioned_rag_indexing_enabled:
        from .workers.importer import reconcile_versioned_indexes

        recovery_task = asyncio.create_task(reconcile_versioned_indexes())
        logger.info("版本化 RAG 恢复检查已启动")
    summary_task: asyncio.Task | None = None
    if settings.conversation_summary_worker_enabled:
        from .workers.conversation_summarizer import conversation_summary_tick_loop

        summary_task = asyncio.create_task(conversation_summary_tick_loop())
        logger.info("会话摘要后台 worker 已启动")
    telemetry_task: asyncio.Task | None = None
    if settings.compatibility_telemetry_persist_enabled:
        from .core.compatibility import (
            CompatibilityTelemetryPersister,
            compatibility_telemetry,
            telemetry_scope,
        )
        from .core.db import async_session_factory

        telemetry_persister = CompatibilityTelemetryPersister(
            compatibility_telemetry,
            async_session_factory,
            # 0.3.0 M1：scope 带 <origin>:<version>，观察脚本按版本/来源过滤，
            # 并区分真实用户窗口（process）与 QA 窗口（qa，PA_QA_STATIC_TOKEN）。
            scope=telemetry_scope(),
            flush_interval_seconds=settings.compatibility_telemetry_flush_seconds,
            # 启动时 reconcile 陈旧窗口（异常退出在下次启动被 reconcile）。
            reconcile_grace_seconds=(
                settings.compatibility_telemetry_reconcile_grace_seconds
            ),
        )
        telemetry_task = asyncio.create_task(telemetry_persister.run())
        logger.info(
            "兼容遥测持久化已启动",
            scope_key=telemetry_persister.scope_key,
            flush_interval_seconds=settings.compatibility_telemetry_flush_seconds,
        )
    try:
        yield
    finally:
        await agent_run_coordinator.shutdown()
        if telemetry_task is not None:
            # 先取消 run 循环再 flush，避免两个 flush 并发交错导致 ended_at 丢失
            # （0.3.0 M1 竞态修复；_write 内也有 rowcount 兜底）。
            telemetry_task.cancel()
            with suppress(asyncio.CancelledError):
                await telemetry_task
            await telemetry_persister.flush_now(ended=True)
        if agent_guard_task is not None:
            agent_guard_task.cancel()
            with suppress(asyncio.CancelledError):
                await agent_guard_task
            from .agents.recovery import agent_runtime_process_guard

            await agent_runtime_process_guard.release()
        if summary_task is not None:
            summary_task.cancel()
            with suppress(asyncio.CancelledError):
                await summary_task
        if recovery_task is not None:
            recovery_task.cancel()
            with suppress(asyncio.CancelledError):
                await recovery_task
        tick_task.cancel()
        with suppress(asyncio.CancelledError):
            await tick_task
        logger.info("后端关闭")


app = FastAPI(
    title="私人助手 Agent",
    version=__version__,
    description="本地优先、隐私可控的桌面私人助手后端",
    lifespan=lifespan,
)

_api_token = settings.api_token.get_secret_value() if settings.api_token else None
_allowed_hosts = parse_csv_setting(settings.api_allowed_hosts)
_allowed_origins = parse_csv_setting(settings.api_allowed_origins)

# Security is registered before CORS so CORS remains the outer middleware and
# adds the appropriate headers to 401/403 responses for trusted WebView origins.
app.add_middleware(
    LocalApiSecurityMiddleware,
    auth_enabled=settings.api_auth_enabled,
    token=_api_token,
    allowed_hosts=_allowed_hosts,
    allowed_origins=_allowed_origins,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Last-Event-ID"],
)

app.include_router(health_router)
app.include_router(http_profiles_router)
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
app.include_router(agent_runs_router)
app.include_router(backup_router)
app.include_router(capture_router)
app.include_router(document_collections_router)
app.include_router(diagnostics_router)
app.include_router(learning_reviews_router)
app.include_router(memories_router)
app.include_router(mcp_router)
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
    return {"name": "personal-assistant", "version": __version__, "docs": "/docs"}


# 优雅停机钩子：server_entry.py 用显式 uvicorn.Server 启动后注册句柄，
# 桌面退出前 POST /internal/shutdown 触发 lifespan finally
# （telemetry flush ended=True / coordinator shutdown），避免强杀丢窗口。
_managed_server: Any | None = None


def register_managed_server(server: Any) -> None:
    """由启动入口注册 uvicorn.Server 实例（不在入口则不注册）。"""
    global _managed_server
    _managed_server = server


@app.post("/internal/shutdown")
async def internal_shutdown() -> dict:
    """请求当前进程优雅停机。仅限 loopback + Bearer token（中间件校验）。

    返回 accepted=False 表示没有可管理的 server（如开发模式），调用方应
    继续走强杀兜底，不应依赖本端点。
    """
    server = _managed_server
    if server is None:
        logger.info("internal shutdown requested but no managed server is registered")
        return {"accepted": False}
    logger.info("internal shutdown requested; triggering graceful exit")
    server.should_exit = True
    return {"accepted": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "personal_assistant.main_api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
