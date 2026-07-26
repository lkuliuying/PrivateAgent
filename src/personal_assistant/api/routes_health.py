"""健康检查路由。"""
from __future__ import annotations

from fastapi import APIRouter

from ..core.health import HealthService
from ..logging_setup import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])
_health_service = HealthService()


@router.get("/health")
async def health() -> dict:
    """返回 API、Ollama、MySQL、ChromaDB 四项状态。"""
    result = await _health_service.check_all()
    logger.info("health check", **{k: v.get("ok") for k, v in result.items()})
    return result
