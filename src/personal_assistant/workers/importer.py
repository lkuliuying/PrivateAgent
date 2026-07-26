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
from ..core.notifications import NotificationService
from ..core.provider import OllamaProvider
from ..core.rag import NeedsOcrError, extract_heading, parse_document, split_text
from ..core.repo import DocChunkRepository, DocumentRepository
from ..core.store_chroma import chroma_store
from ..core.timeutil import utcnow
from ..logging_setup import get_logger

logger = get_logger(__name__)
CANCELLED_RETRY_ERROR = "任务因应用关闭而中断，可重试"
EMBED_BATCH_SIZE = 32


async def _purge_partial_index(doc_id: int) -> None:
    """Best-effort is not enough here: both indexes must agree after failure."""

    failures: list[str] = []
    try:
        await chroma_store.delete_by_doc(doc_id)
    except Exception as exc:  # noqa: BLE001 - aggregate both cleanup targets
        failures.append(f"chroma:{type(exc).__name__}")
    try:
        async with async_session_factory() as db:
            await DocChunkRepository(db).delete_by_doc(doc_id)
    except Exception as exc:  # noqa: BLE001 - aggregate both cleanup targets
        failures.append(f"mysql:{type(exc).__name__}")
    if failures:
        raise RuntimeError(
            "partial document index cleanup failed (" + ", ".join(failures) + ")"
        )


async def _notify(
    level: str,
    kind: str,
    title: str,
    message: str | None = None,
    *,
    source_id: int | None = None,
) -> None:
    """后台导入结果写入统一通知中心（独立 session）。"""
    try:
        async with async_session_factory() as db:
            await NotificationService(db).notify(
                level=level,
                kind=kind,
                title=title,
                message=message,
                source_type="document",
                source_id=source_id,
            )
    except Exception:  # noqa: BLE001
        logger.warning("notify failed", exc_info=True)


async def _index_core(doc_id: int, file_path: str) -> int:
    """解析 → 切分 → 向量化 → 切片入 MySQL → 向量入 ChromaDB。返回切片数。

    不管理文档状态/活动，供 import_document / reindex_document 复用。
    """
    provider = OllamaProvider()
    text = await asyncio.to_thread(parse_document, file_path)
    pieces = split_text(text)
    if not pieces:
        raise ValueError("切分结果为空，文档可能无有效文本")

    indexed = 0
    try:
        # Ollama processes every input in an embedding request. Sending all
        # chunks from a multi-megabyte document in one call exceeds the client
        # timeout and creates an unbounded response. Keep each request and each
        # MySQL/Chroma write bounded instead.
        async with provider:
            for start in range(0, len(pieces), EMBED_BATCH_SIZE):
                batch = pieces[start : start + EMBED_BATCH_SIZE]
                embeddings = await provider.embed(batch)
                if len(embeddings) != len(batch):
                    raise ValueError(
                        f"向量化数量({len(embeddings)})与切片数({len(batch)})不一致"
                    )

                async with async_session_factory() as db:
                    chunk_objs = await DocChunkRepository(db).add_many(
                        doc_id,
                        [
                            {
                                "ordinal": start + offset + 1,
                                "content": piece,
                                "token_count": None,
                                "heading": extract_heading(piece),
                                "bm25_text": piece,
                                "keywords": None,
                            }
                            for offset, piece in enumerate(batch)
                        ],
                    )
                    chunk_ids = [chunk.id for chunk in chunk_objs]

                await chroma_store.add(
                    chunk_ids=chunk_ids,
                    embeddings=embeddings,
                    doc_ids=[doc_id] * len(chunk_ids),
                )
                indexed += len(chunk_ids)
    except BaseException:
        # Includes cancellation: a stopped import must not leave a document
        # half-present in MySQL or Chroma.
        await _purge_partial_index(doc_id)
        raise
    return indexed


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


async def _mark_import_cancelled(
    activity_kind: str,
    doc_id: int,
    doc_name: str,
) -> None:
    """Best-effort recovery so shutdown never leaves a document processing forever."""
    try:
        async with async_session_factory() as db:
            await DocumentRepository(db).update_status(
                doc_id,
                status="failed",
                error_message=CANCELLED_RETRY_ERROR,
            )
    except Exception:  # noqa: BLE001 - preserve the original cancellation
        logger.exception("import cancellation status update failed", doc_id=doc_id)
    try:
        await _sync_activity(
            activity_kind,
            doc_id,
            doc_name,
            "failed",
            error_message=CANCELLED_RETRY_ERROR,
        )
    except Exception:  # noqa: BLE001 - preserve the original cancellation
        logger.exception("import cancellation activity update failed", doc_id=doc_id)


async def import_document(
    doc_id: int, file_path: str, *, activity_kind: str = "document_import"
) -> None:
    """后台导入一个文档。失败时记录 error_message，状态置 failed，可重试。

    activity_kind: "document_import"（普通导入）或 "reindex"（重建索引），决定活动流类型。
    """
    doc_name = f"文档#{doc_id}"
    try:
        async with async_session_factory() as db:
            docs = DocumentRepository(db)
            doc = await docs.get(doc_id)
            doc_name = doc.name if doc else doc_name
            await docs.update_status(doc_id, status="processing", error_message=None)
        await _sync_activity(activity_kind, doc_id, doc_name, "processing")
        logger.info("import start", doc_id=doc_id, file=file_path, kind=activity_kind)

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
        action_label = "重建索引" if activity_kind == "reindex" else "导入"
        await _notify(
            "success",
            "import",
            f"文档{action_label}完成：{doc_name}",
            f"{chunk_count} 个切片已入库",
            source_id=doc_id,
        )
        logger.info("import done", doc_id=doc_id, chunks=chunk_count, kind=activity_kind)
    except asyncio.CancelledError:
        logger.warning("import cancelled during shutdown", doc_id=doc_id, kind=activity_kind)
        await _mark_import_cancelled(activity_kind, doc_id, doc_name)
        raise
    except NeedsOcrError:
        # 扫描件 PDF：创建 OCR job 并置 needs_ocr，而非 hard fail（第七阶段 M3）。
        logger.info("import needs ocr", doc_id=doc_id, kind=activity_kind)
        async with async_session_factory() as db:
            docs = DocumentRepository(db)
            await docs.update_status(
                doc_id, status="needs_ocr", error_message="扫描件 PDF 需 OCR 处理"
            )
            from ..core.repo_ocr_jobs import OcrJobRepository

            await OcrJobRepository(db).create(
                doc_id=doc_id,
                file_path=file_path,
                source="document_import",
                source_type="document",
                source_id=doc_id,
            )
        await _sync_activity(
            activity_kind, doc_id, doc_name, "needs_ocr", error_message="需 OCR"
        )
        action_label = "重建索引" if activity_kind == "reindex" else "导入"
        await _notify(
            "warning",
            "import",
            f"文档需 OCR：{doc_name}",
            "扫描件 PDF 已加入 OCR 队列，请在 OCR 队列查看",
            source_id=doc_id,
        )
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
        action_label = "重建索引" if activity_kind == "reindex" else "导入"
        await _notify(
            "error",
            "import",
            f"文档{action_label}失败：{doc_name}",
            str(e)[:200],
            source_id=doc_id,
        )


async def retry_import(doc_id: int, file_path: str) -> None:
    """重试失败的导入（清理旧切片后重新导入）。"""
    async with async_session_factory() as db:
        chunks_repo = DocChunkRepository(db)
        existing = await chunks_repo.list_by_doc(doc_id)
        if existing:
            await chroma_store.delete_by_doc(doc_id)
            await chunks_repo.delete_by_doc(doc_id)
    await import_document(doc_id, file_path)


async def reindex_document(doc_id: int, file_path: str) -> None:
    """重建单个文档索引：清理旧切片+向量后重新解析切分向量化（活动类型 reindex）。"""
    async with async_session_factory() as db:
        chunks_repo = DocChunkRepository(db)
        existing = await chunks_repo.list_by_doc(doc_id)
        if existing:
            await chroma_store.delete_by_doc(doc_id)
            await chunks_repo.delete_by_doc(doc_id)
    await import_document(doc_id, file_path, activity_kind="reindex")
