"""文档导入后台任务：状态机驱动的 解析 → 切分 → 向量化 → 入库。

状态流转：pending -> processing -> ready（失败进入 failed，记录 error_message 可重试）。

使用独立 db session（后台任务跨越请求生命周期，不能用 request 的 session）。
同步解析（pypdf/python-docx）用 asyncio.to_thread 隔离。

第二阶段 M4：导入与重建索引全程写入 activities 表。
"""
from __future__ import annotations

import asyncio

from ..config import settings
from ..core.activities import ActivityService
from ..core.db import async_session_factory
from ..core.provider import OllamaProvider
from ..core.rag import extract_heading, parse_document, split_text
from ..core.repo import DocChunkRepository, DocumentRepository
from ..core.store_chroma import chroma_store
from ..core.timeutil import utcnow
from ..logging_setup import get_logger

logger = get_logger(__name__)


async def _index_core(doc_id: int, file_path: str) -> int:
    """解析 → 切分 → 向量化 → 切片入 MySQL → 向量入 ChromaDB。返回切片数。

    不管理文档状态/活动，供 import_document / reindex_document 复用。
    """
    provider = OllamaProvider()
    text = await asyncio.to_thread(parse_document, file_path)
    pieces = split_text(text)
    if not pieces:
        raise ValueError("切分结果为空，文档可能无有效文本")

    embeddings = await provider.embed(pieces)
    if len(embeddings) != len(pieces):
        raise ValueError(
            f"向量化数量({len(embeddings)})与切片数({len(pieces)})不一致"
        )

    async with async_session_factory() as db:
        chunks_repo = DocChunkRepository(db)
        chunk_objs = await chunks_repo.add_many(
            doc_id,
            [
                {
                    "ordinal": i + 1,
                    "content": p,
                    "token_count": None,
                    "heading": extract_heading(p),
                    "bm25_text": p,  # 预留 FULLTEXT；M2 关键词召回走 content LIKE
                    "keywords": None,
                }
                for i, p in enumerate(pieces)
            ],
        )
        chunk_ids = [c.id for c in chunk_objs]

    await chroma_store.add(
        chunk_ids=chunk_ids,
        embeddings=embeddings,
        doc_ids=[doc_id] * len(chunk_ids),
    )
    return len(chunk_ids)


async def _sync_activity(
    activity_kind: str,
    doc_id: int,
    doc_name: str,
    doc_status: str,
    error_message: str | None = None,
) -> None:
    """按 activity_kind 写入对应活动流（document_import / reindex）。"""
    async with async_session_factory() as db:
        svc = ActivityService(db)
        if activity_kind == "reindex":
            await svc.sync_reindex(
                doc_id, doc_name=doc_name, doc_status=doc_status, error_message=error_message
            )
        else:
            await svc.sync_document_import(
                doc_id, doc_name=doc_name, doc_status=doc_status, error_message=error_message
            )


async def import_document(
    doc_id: int, file_path: str, *, activity_kind: str = "document_import"
) -> None:
    """后台导入一个文档。失败时记录 error_message，状态置 failed，可重试。

    activity_kind: "document_import"（普通导入）或 "reindex"（重建索引），决定活动流类型。
    """
    async with async_session_factory() as db:
        docs = DocumentRepository(db)
        doc = await docs.get(doc_id)
        doc_name = doc.name if doc else f"文档#{doc_id}"
        await docs.update_status(doc_id, status="processing", error_message=None)
    await _sync_activity(activity_kind, doc_id, doc_name, "processing")
    logger.info("import start", doc_id=doc_id, file=file_path, kind=activity_kind)

    try:
        chunk_count = await _index_core(doc_id, file_path)
        async with async_session_factory() as db:
            docs = DocumentRepository(db)
            await docs.update_status(
                doc_id,
                status="ready",
                chunk_count=chunk_count,
                indexed_at=utcnow(),
                embedding_model=settings.embed_model,
            )
        await _sync_activity(activity_kind, doc_id, doc_name, "ready")
        logger.info("import done", doc_id=doc_id, chunks=chunk_count, kind=activity_kind)
    except Exception as e:  # noqa: BLE001
        logger.exception("import failed", doc_id=doc_id, kind=activity_kind)
        async with async_session_factory() as db:
            docs = DocumentRepository(db)
            await docs.update_status(
                doc_id, status="failed", error_message=str(e)[:1000]
            )
        await _sync_activity(
            activity_kind, doc_id, doc_name, "failed", error_message=str(e)[:1000]
        )


async def retry_import(doc_id: int, file_path: str) -> None:
    """重试失败的导入（清理旧切片后重新导入）。"""
    async with async_session_factory() as db:
        chunks_repo = DocChunkRepository(db)
        existing = await chunks_repo.list_by_doc(doc_id)
        if existing:
            await chroma_store.delete_by_doc(doc_id)
            for c in existing:
                await db.delete(c)
            await db.commit()
    await import_document(doc_id, file_path)


async def reindex_document(doc_id: int, file_path: str) -> None:
    """重建单个文档索引：清理旧切片+向量后重新解析切分向量化（活动类型 reindex）。"""
    async with async_session_factory() as db:
        chunks_repo = DocChunkRepository(db)
        existing = await chunks_repo.list_by_doc(doc_id)
        if existing:
            await chroma_store.delete_by_doc(doc_id)
            for c in existing:
                await db.delete(c)
            await db.commit()
    await import_document(doc_id, file_path, activity_kind="reindex")
