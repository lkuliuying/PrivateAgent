"""FastAPI 应用入口。

开发启动：
    uvicorn personal_assistant.main_api:app --reload --port 8000
或（已安装本项目）：
    python -m personal_assistant.main_api
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

    tick_task = asyncio.create_task(reminder_tick_loop())
    logger.info("提醒后台 tick 已启动")
    try:
        yield
    finally:
        tick_task.cancel()
        with suppress(asyncio.CancelledError):
            await tick_task
        logger.info("后端关闭")


app = FastAPI(
    title="私人助手 Agent",
    version="0.1.2",
    description="本地优先、隐私可控的桌面私人助手后端",
    lifespan=lifespan,
)

# CORS：本地优先应用（loopback），无 cookie。allow_credentials=False + 通配来源
# 可接受：GET /settings 已掩码密钥（不回显原文），诊断包脱敏，无 cookie 可窃。
# 之前收紧为固定来源导致 Tauri webview origin（https://tauri.localhost）被拦截，
# 前端 fetch 本地 API 全部 CORS 失败 -> 启动超时。故恢复通配 + 关闭 credentials。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
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
