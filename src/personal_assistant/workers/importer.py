"""文档导入后台任务：状态机驱动的 解析 → 切分 → 向量化 → 入库。

状态流转：pending -> processing -> ready（失败进入 failed，记录 error_message 可重试）。

使用独立 db session（后台任务跨越请求生命周期，不能用 request 的 session）。
同步解析（pypdf/python-docx）用 asyncio.to_thread 隔离。
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from ..config import settings
from ..core.db import async_session_factory
from ..core.provider import OllamaProvider
from ..core.rag import parse_document, split_text
from ..core.repo import DocChunkRepository, DocumentRepository
from ..core.store_chroma import chroma_store
from ..logging_setup import get_logger

logger = get_logger(__name__)


async def import_document(doc_id: int, file_path: str) -> None:
    """后台导入一个文档。失败时记录 error_message，状态置 failed，可重试。"""
    async with async_session_factory() as db:
        docs = DocumentRepository(db)
        chunks_repo = DocChunkRepository(db)
        provider = OllamaProvider()

        await docs.update_status(doc_id, status="processing", error_message=None)
        logger.info("import start", doc_id=doc_id, file=file_path)

        try:
            # 1. 解析（同步，线程隔离）
            text = await asyncio.to_thread(parse_document, file_path)

            # 2. 切分
            pieces = split_text(text)
            if not pieces:
                raise ValueError("切分结果为空，文档可能无有效文本")

            # 3. 向量化
            embeddings = await provider.embed(pieces)
            if len(embeddings) != len(pieces):
                raise ValueError(
                    f"向量化数量({len(embeddings)})与切片数({len(pieces)})不一致"
                )

            # 4. 切片原文入 MySQL
            chunk_objs = await chunks_repo.add_many(
                doc_id, [(i + 1, p, None) for i, p in enumerate(pieces)]
            )
            chunk_ids = [c.id for c in chunk_objs]

            # 5. 向量入 ChromaDB
            await chroma_store.add(
                chunk_ids=chunk_ids,
                embeddings=embeddings,
                doc_ids=[doc_id] * len(chunk_ids),
            )

            # 6. ready
            await docs.update_status(
                doc_id,
                status="ready",
                chunk_count=len(chunk_ids),
                indexed_at=datetime.now(),
                embedding_model=settings.embed_model,
            )
            logger.info("import done", doc_id=doc_id, chunks=len(chunk_ids))

        except Exception as e:  # noqa: BLE001
            logger.exception("import failed", doc_id=doc_id)
            await docs.update_status(
                doc_id, status="failed", error_message=str(e)[:1000]
            )


async def retry_import(doc_id: int, file_path: str) -> None:
    """重试失败的导入（清理旧切片后重新导入）。"""
    async with async_session_factory() as db:
        chunks_repo = DocChunkRepository(db)
        # 清理可能残留的部分数据
        existing = await chunks_repo.list_by_doc(doc_id)
        if existing:
            await chroma_store.delete_by_doc(doc_id)
            for c in existing:
                await db.delete(c)
            await db.commit()
    await import_document(doc_id, file_path)
