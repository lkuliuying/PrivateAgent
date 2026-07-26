"""健康检查服务：聚合 Ollama、MySQL、ChromaDB、本地 API 状态。

供 ``GET /health`` 与设置/状态页使用，帮助用户定位是模型、数据库、
向量库还是后端本身的问题。
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from copy import deepcopy
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any

from sqlalchemy import text

from ..config import settings
from ..logging_setup import get_logger
from .db import engine

logger = get_logger(__name__)
_CHROMA_PROBE_GATE = Lock()


def _load_chroma_collections(path: Path) -> int:
    """Open Chroma and return its collection count (synchronous library boundary)."""
    import chromadb

    path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(path))
    try:
        return len(client.list_collections())
    finally:
        # Chroma explicitly requires close() for PersistentClient; relying on GC leaves
        # chroma.sqlite3 locked on Windows and breaks test/profile cleanup.
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _read_chroma_collections(path: Path) -> int:
    """Execute the synchronous Chroma operation behind the process-wide gate."""
    if not _CHROMA_PROBE_GATE.acquire(blocking=False):
        raise RuntimeError("previous ChromaDB health probe is still running")
    try:
        return _load_chroma_collections(path)
    finally:
        _CHROMA_PROBE_GATE.release()


class HealthService:
    def __init__(self, *, cache_ttl: float = 5.0, probe_timeout: float = 4.0) -> None:
        self.cache_ttl = cache_ttl
        self.probe_timeout = probe_timeout
        self._cache: dict[str, Any] | None = None
        self._cache_until = 0.0
        self._inflight: asyncio.Task[dict[str, Any]] | None = None

    def clear_cache(self) -> None:
        self._cache = None
        self._cache_until = 0.0

    async def check_all(self, *, force: bool = False) -> dict[str, Any]:
        """并行探测依赖，并短暂缓存结果以避免多个工作区重复施压。"""
        now = monotonic()
        if not force and self._cache is not None and now < self._cache_until:
            return deepcopy(self._cache)

        # Task creation is atomic until the first await, so all callers on this event
        # loop join the same probe round.  shield keeps one cancelled HTTP request from
        # cancelling the shared health check for every other caller.
        task = self._inflight
        if task is None:
            task = asyncio.create_task(self._run_probes(), name="health-probes")
            self._inflight = task
            task.add_done_callback(self._release_inflight)
        result = await asyncio.shield(task)
        return deepcopy(result)

    async def _run_probes(self) -> dict[str, Any]:
        ollama, mysql, chroma = await asyncio.gather(
            self._bounded_probe("Ollama", self._check_ollama()),
            self._bounded_probe("MySQL", self._check_mysql()),
            self._bounded_probe("ChromaDB", self._check_chroma()),
            return_exceptions=False,
        )
        result = {
            "api": {"ok": True},
            "ollama": ollama,
            "mysql": mysql,
            "chroma": chroma,
        }
        if self.cache_ttl > 0:
            self._cache = deepcopy(result)
            self._cache_until = monotonic() + self.cache_ttl
        else:
            self.clear_cache()
        return result

    def _release_inflight(self, task: asyncio.Task[dict[str, Any]]) -> None:
        if self._inflight is task:
            self._inflight = None
        # Retrieve an exception even when every waiter was cancelled.  Awaiters still
        # receive the same exception from the task, but asyncio will not report a leaked
        # "Task exception was never retrieved" warning during shutdown.
        if not task.cancelled():
            task.exception()

    async def _bounded_probe(
        self, name: str, probe: Awaitable[dict[str, Any]]
    ) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(probe, timeout=self.probe_timeout)
        except TimeoutError:
            return {"ok": False, "error": f"{name} 健康检查超时"}
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - health must degrade, not fail the API
            logger.warning("健康检查探针异常", probe=name, error_type=type(exc).__name__)
            return {"ok": False, "error": f"{name} 健康检查失败"}

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

        try:
            # 嵌入式 ChromaDB 是同步 API，用线程隔离避免阻塞事件循环。模块级 gate
            # 防止 /health 与诊断快照的不同 HealthService 实例在超时后叠加线程。
            count = await asyncio.to_thread(_read_chroma_collections, settings.chroma_dir)
            result["ok"] = True
            result["collections"] = count
        except Exception as e:  # noqa: BLE001
            result["error"] = f"ChromaDB 初始化失败: {e}"
        return result
