"""健康检查服务：聚合 Ollama、MySQL、ChromaDB、本地 API 状态。

供 ``GET /health`` 与设置/状态页使用，帮助用户定位是模型、数据库、
向量库还是后端本身的问题。
"""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text

from ..config import settings
from ..logging_setup import get_logger
from .db import engine

logger = get_logger(__name__)


class HealthService:
    async def check_all(self) -> dict[str, Any]:
        ollama, mysql, chroma = await asyncio.gather(
            self._check_ollama(),
            self._check_mysql(),
            self._check_chroma(),
            return_exceptions=False,
        )
        return {
            "api": {"ok": True},
            "ollama": ollama,
            "mysql": mysql,
            "chroma": chroma,
        }

    async def _check_ollama(self) -> dict[str, Any]:
        from .provider import OllamaProvider

        return await OllamaProvider().health()

    async def _check_mysql(self) -> dict[str, Any]:
        result: dict[str, Any] = {"ok": False}
        try:
            async with engine.connect() as conn:
                val = await conn.scalar(text("SELECT 1"))
                result["ok"] = val == 1
        except Exception as e:  # noqa: BLE001
            result["error"] = f"MySQL 连接失败: {e}"
        return result

    async def _check_chroma(self) -> dict[str, Any]:
        result: dict[str, Any] = {"ok": False, "path": str(settings.chroma_dir)}

        def _probe() -> int:
            import chromadb

            settings.chroma_dir.mkdir(parents=True, exist_ok=True)
            # 嵌入式 ChromaDB 是同步 API，用线程隔离避免阻塞事件循环
            client = chromadb.PersistentClient(path=str(settings.chroma_dir))
            return len(client.list_collections())

        try:
            count = await asyncio.to_thread(_probe)
            result["ok"] = True
            result["collections"] = count
        except Exception as e:  # noqa: BLE001
            result["error"] = f"ChromaDB 初始化失败: {e}"
        return result
