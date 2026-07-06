"""FastAPI 应用入口。

开发启动：
    uvicorn personal_assistant.main_api:app --reload --port 8000
或（已安装本项目）：
    python -m personal_assistant.main_api
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes_activities import router as activities_router
from .api.routes_agent_tasks import router as agent_tasks_router
from .api.routes_chat import router as chat_router
from .api.routes_coding import router as coding_router
from .api.routes_documents import router as documents_router
from .api.routes_files import router as files_router
from .api.routes_health import router as health_router
from .api.routes_learning import router as learning_router
from .api.routes_projects import router as projects_router
from .api.routes_sessions import router as sessions_router
from .api.routes_settings import router as settings_router
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
    yield
    logger.info("后端关闭")


app = FastAPI(
    title="私人助手 Agent",
    version="0.1.0",
    description="本地优先、隐私可控的桌面私人助手后端",
    lifespan=lifespan,
)

# M0 阶段放开跨域，方便 Tauri（tauri://localhost / http://localhost:1420）调试。
# M3 打磨阶段按需收紧来源。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(sessions_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(settings_router)
app.include_router(tools_router)
app.include_router(files_router)
app.include_router(activities_router)
app.include_router(projects_router)
app.include_router(learning_router)
app.include_router(coding_router)
app.include_router(agent_tasks_router)


@app.get("/")
async def root() -> dict:
    return {"name": "personal-assistant", "version": "0.1.0", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "personal_assistant.main_api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
