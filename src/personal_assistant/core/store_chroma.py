"""嵌入式 ChromaDB 封装。

只存向量 + 最小元数据（doc_id），不存原文。原文在 MySQL doc_chunks，
检索返回 chunk_id（即 doc_chunks.id）后回 MySQL 取原文与来源信息。

ChromaDB 是同步 API，所有调用经 asyncio.to_thread 隔离，避免阻塞事件循环。
持久化到 data/chroma/。
"""
from __future__ import annotations

import asyncio
from typing import Any

import chromadb

from ..config import settings
from ..logging_setup import get_logger

logger = get_logger(__name__)

COLLECTION_NAME = "doc_chunks"


class ChromaStore:
    """单 collection 存全部文档切片向量，metadata 含 doc_id 用于按文档删除。"""

    def __init__(self) -> None:
        self._client: Any = None
        self._collection: Any = None

    def _ensure(self) -> Any:
        if self._collection is None:
            def _init() -> Any:
                settings.chroma_dir.mkdir(parents=True, exist_ok=True)
                client = chromadb.PersistentClient(path=str(settings.chroma_dir))
                return client.get_or_create_collection(COLLECTION_NAME)

            # 首次初始化也走线程隔离（PersistentClient 可能慢）
            self._collection = _init()
        return self._collection

    async def add(
        self,
        chunk_ids: list[int],
        embeddings: list[list[float]],
        doc_ids: list[int],
    ) -> None:
        """批量写入切片向量。chunk_id 作为 chroma id（字符串）。"""
        ids = [str(i) for i in chunk_ids]
        metas = [{"doc_id": d} for d in doc_ids]

        def _add() -> None:
            self._ensure().add(ids=ids, embeddings=embeddings, metadatas=metas)

        await asyncio.to_thread(_add)

    async def query(self, embedding: list[float], top_k: int = 5) -> list[int]:
        """检索 top-k 相似切片，返回 chunk_id 列表（按相似度降序）。"""
        def _q() -> list[int]:
            res = self._ensure().query(
                query_embeddings=[embedding], n_results=top_k
            )
            ids = res.get("ids", [[]])[0]
            out = []
            for i in ids:
                try:
                    out.append(int(i))
                except (TypeError, ValueError):
                    continue
            return out

        return await asyncio.to_thread(_q)

    async def delete_by_doc(self, doc_id: int) -> None:
        """删除某文档的全部向量（按 metadata.doc_id 过滤）。"""
        def _del() -> None:
            self._ensure().delete(where={"doc_id": doc_id})

        await asyncio.to_thread(_del)

    async def count(self) -> int:
        def _c() -> int:
            return self._ensure().count()

        return await asyncio.to_thread(_c)


# 单例
chroma_store = ChromaStore()
