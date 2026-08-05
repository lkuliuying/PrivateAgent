"""健康检查路由。"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import settings
from ..core.health import HealthService
from ..logging_setup import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


class RuntimeCapabilities(BaseModel):
    """Stable, non-secret feature gates needed by local clients."""

    chat_execution_mode: Literal["agent_runtime", "legacy"]
    legacy_tool_planner_enabled: bool
    agent_read_only_tools_enabled: bool
    rag_chat_runtime_enabled: bool


@router.get("/health")
async def health() -> dict:
    """返回 API、Ollama、MySQL、ChromaDB 四项状态。"""
    result = await HealthService().check_all()
    logger.info("health check", **{k: v.get("ok") for k, v in result.items()})
    return result


@router.get("/capabilities", response_model=RuntimeCapabilities)
async def capabilities() -> RuntimeCapabilities:
    """Return lightweight execution-mode gates without probing dependencies."""
    agent_runtime = settings.chat_agent_runtime_enabled
    return RuntimeCapabilities(
        chat_execution_mode="agent_runtime" if agent_runtime else "legacy",
        legacy_tool_planner_enabled=not agent_runtime,
        agent_read_only_tools_enabled=settings.agent_run_read_only_tools_enabled,
        rag_chat_runtime_enabled=(
            agent_runtime
            and settings.agent_rag_tools_enabled
            and settings.agent_output_verification_enabled
        ),
    )
