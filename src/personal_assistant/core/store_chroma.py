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
VERSIONED_COLLECTION_NAME = "document_index_chunks_v2"


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

    async def delete_by_chunk_id(self, chunk_id: int) -> None:
        """删除单个切片的向量（按 chroma id，即 doc_chunks.id 字符串）。

        用于完整性修复「Chroma 孤立向量」发现：其 ref_id 是 chunk_id，不是 doc_id，
        必须按 id 删，不能用 delete_by_doc（按 doc_id 元数据删会误删别的文档的向量）。
        """
        def _del() -> None:
            self._ensure().delete(ids=[str(chunk_id)])

        await asyncio.to_thread(_del)

    async def count(self) -> int:
        def _c() -> int:
            return self._ensure().count()

        return await asyncio.to_thread(_c)

    async def list_ids(self) -> list[int]:
        """枚举 collection 中全部 chunk_id（M7 与 MySQL doc_chunks 一致性检查用）。"""
        return await asyncio.to_thread(self.list_ids_sync)

    def list_ids_sync(self) -> list[int]:
        """Synchronous bounded ID listing for offline audit/maintenance tools."""
        res = self._ensure().get(include=[], limit=1_000_000)
        out: list[int] = []
        for i in res.get("ids", []):
            try:
                out.append(int(i))
            except (TypeError, ValueError):
                continue
        return out


class VersionedChromaStore:
    """Version-isolated vector store used by side-by-side RAG builds."""

    def __init__(self) -> None:
        self._collection: Any = None

    def _ensure(self) -> Any:
        if self._collection is None:
            settings.chroma_dir.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(settings.chroma_dir))
            self._collection = client.get_or_create_collection(
                VERSIONED_COLLECTION_NAME
            )
        return self._collection

    @staticmethod
    def _vector_id(chunk_id: int) -> str:
        return f"v2:{chunk_id}"

    @staticmethod
    def _chunk_id(vector_id: object) -> int | None:
        value = str(vector_id)
        if not value.startswith("v2:"):
            return None
        try:
            return int(value[3:])
        except ValueError:
            return None

    async def upsert_version(
        self,
        *,
        index_version_id: str,
        chunk_ids: list[int],
        embeddings: list[list[float]],
        doc_id: int,
    ) -> None:
        if len(chunk_ids) != len(embeddings):
            raise ValueError("chunk/vector count mismatch")
        ids = [self._vector_id(chunk_id) for chunk_id in chunk_ids]
        metadata = [
            {
                "doc_id": doc_id,
                "index_version_id": index_version_id,
                "chunk_id": chunk_id,
            }
            for chunk_id in chunk_ids
        ]

        def _upsert() -> None:
            self._ensure().upsert(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadata,
            )

        await asyncio.to_thread(_upsert)

    async def list_chunk_ids(self, index_version_id: str) -> list[int]:
        def _list() -> list[int]:
            result = self._ensure().get(
                where={"index_version_id": index_version_id},
                include=[],
                limit=1_000_000,
            )
            chunk_ids: list[int] = []
            for vector_id in result.get("ids", []):
                chunk_id = self._chunk_id(vector_id)
                if chunk_id is not None:
                    chunk_ids.append(chunk_id)
            return chunk_ids

        return await asyncio.to_thread(_list)

    async def count_version(self, index_version_id: str) -> int:
        return len(await self.list_chunk_ids(index_version_id))

    async def delete_version(self, index_version_id: str) -> None:
        def _delete() -> None:
            self._ensure().delete(where={"index_version_id": index_version_id})

        await asyncio.to_thread(_delete)

    async def query_active(
        self,
        embedding: list[float],
        *,
        active_version_ids: list[str],
        top_k: int = 5,
    ) -> list[int]:
        if not active_version_ids or top_k <= 0:
            return []
        where: dict[str, object]
        if len(active_version_ids) == 1:
            where = {"index_version_id": active_version_ids[0]}
        else:
            where = {"index_version_id": {"$in": active_version_ids}}

        def _query() -> list[int]:
            result = self._ensure().query(
                query_embeddings=[embedding],
                n_results=top_k,
                where=where,
            )
            chunk_ids: list[int] = []
            for vector_id in result.get("ids", [[]])[0]:
                chunk_id = self._chunk_id(vector_id)
                if chunk_id is not None:
                    chunk_ids.append(chunk_id)
            return chunk_ids

        return await asyncio.to_thread(_query)


# 单例
chroma_store = ChromaStore()
versioned_chroma_store = VersionedChromaStore()
