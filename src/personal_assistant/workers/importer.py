"""文档导入后台任务：状态机驱动的 解析 → 切分 → 向量化 → 入库。

状态流转：pending -> processing -> ready（失败进入 failed，记录 error_message 可重试）。

使用独立 db session（后台任务跨越请求生命周期，不能用 request 的 session）。
同步解析（pypdf/python-docx）用 asyncio.to_thread 隔离。

第二阶段 M4：导入与重建索引全程写入 activities 表。
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta
from pathlib import Path

from sqlalchemy import text

from ..config import settings
from ..core.activities import ActivityService
from ..core.db import async_session_factory
from ..core.index_versions import (
    DocumentIndexRepository,
    IndexBuildInput,
    VersionedDocumentIndexer,
)
from ..core.notifications import NotificationService
from ..core.provider import OllamaProvider
from ..core.rag import (
    NeedsOcrError,
    estimate_token_count,
    extract_heading,
    parse_document,
    parse_document_blocks,
    split_document_blocks,
    split_text,
)
from ..core.repo import DocChunkRepository, DocumentRepository
from ..core.store_chroma import chroma_store, versioned_chroma_store
from ..core.timeutil import utcnow
from ..logging_setup import get_logger

logger = get_logger(__name__)

_MINIMUM_STRUCTURED_RAG_SCHEMA_REVISION = 20


def schema_supports_structured_versioned_rag(revision: str | None) -> bool:
    """Return whether the schema can persist one provenance row per chunk."""

    if revision is None or len(revision) != 4 or not revision.isdigit():
        return False
    return int(revision) >= _MINIMUM_STRUCTURED_RAG_SCHEMA_REVISION


async def _require_structured_versioned_rag_schema() -> None:
    async with async_session_factory() as db:
        revision = await db.scalar(
            text("SELECT version_num FROM alembic_version LIMIT 1")
        )
    observed = str(revision) if revision is not None else None
    if not schema_supports_structured_versioned_rag(observed):
        raise RuntimeError(
            "versioned RAG indexing requires database schema revision 0020 or later"
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
                    "token_count": estimate_token_count(p),
                    "heading": extract_heading(p),
                    "bm25_text": p,  # MySQL FULLTEXT ngram / BM25 召回正文
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


async def _index_core_versioned(doc_id: int, file_path: str) -> int:
    """Build and validate a new version without mutating the online index."""

    await _require_structured_versioned_rag_schema()
    provider = OllamaProvider()
    source_bytes = await asyncio.to_thread(Path(file_path).read_bytes)
    blocks = await asyncio.to_thread(parse_document_blocks, file_path)
    structured_chunks = split_document_blocks(blocks)
    if not structured_chunks:
        raise ValueError("切分结果为空，文档可能无有效文本")
    pieces = [chunk.content for chunk in structured_chunks]
    embeddings = await provider.embed(pieces)
    if len(embeddings) != len(pieces):
        raise ValueError(
            f"向量化数量({len(embeddings)})与切片数({len(pieces)})不一致"
        )
    async with async_session_factory() as db:
        version = await VersionedDocumentIndexer(
            db, versioned_chroma_store
        ).build_and_activate(
            doc_id=doc_id,
            source_sha256=hashlib.sha256(source_bytes).hexdigest(),
            chunker_version="structured-blocks:v1",
            embedding_model=settings.embed_model,
            chunks=[
                IndexBuildInput(
                    ordinal=index + 1,
                    content=chunk.content,
                    token_count=estimate_token_count(chunk.content),
                    heading=chunk.heading,
                    bm25_text=chunk.content,
                    source_kind=chunk.source_kind,
                    parser_version=chunk.parser_version,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    line_start=chunk.line_start,
                    line_end=chunk.line_end,
                    heading_path=chunk.heading_path,
                )
                for index, chunk in enumerate(structured_chunks)
            ],
            embeddings=embeddings,
        )
    return version.chunk_count


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
    doc_id: int,
    file_path: str,
    *,
    activity_kind: str = "document_import",
    use_versioned: bool | None = None,
) -> None:
    """后台导入一个文档。失败时记录 error_message，状态置 failed，可重试。

    activity_kind: "document_import"（普通导入）或 "reindex"（重建索引），决定活动流类型。
    """
    if use_versioned is None:
        use_versioned = (
            settings.versioned_rag_indexing_enabled
            and settings.versioned_rag_retrieval_enabled
        )
    preserve_online_status = False
    async with async_session_factory() as db:
        docs = DocumentRepository(db)
        doc = await docs.get(doc_id)
        doc_name = doc.name if doc else f"文档#{doc_id}"
        preserve_online_status = bool(
            use_versioned
            and activity_kind == "reindex"
            and doc is not None
            and doc.status == "ready"
        )
        if not preserve_online_status:
            await docs.update_status(doc_id, status="processing", error_message=None)
    await _sync_activity(activity_kind, doc_id, doc_name, "processing")
    logger.info("import start", doc_id=doc_id, file=file_path, kind=activity_kind)

    try:
        chunk_count = (
            await _index_core_versioned(doc_id, file_path)
            if use_versioned
            else await _index_core(doc_id, file_path)
        )
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
    except NeedsOcrError:
        # 扫描件 PDF：创建 OCR job 并置 needs_ocr，而非 hard fail（第七阶段 M3）。
        logger.info("import needs ocr", doc_id=doc_id, kind=activity_kind)
        async with async_session_factory() as db:
            docs = DocumentRepository(db)
            if not preserve_online_status:
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
        if not preserve_online_status:
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
    if (
        settings.versioned_rag_indexing_enabled
        and settings.versioned_rag_retrieval_enabled
    ):
        await import_document(doc_id, file_path, use_versioned=True)
        return
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
    if settings.versioned_rag_indexing_enabled:
        await import_document(
            doc_id,
            file_path,
            activity_kind="reindex",
            use_versioned=True,
        )
        return
    async with async_session_factory() as db:
        chunks_repo = DocChunkRepository(db)
        existing = await chunks_repo.list_by_doc(doc_id)
        if existing:
            await chroma_store.delete_by_doc(doc_id)
            for c in existing:
                await db.delete(c)
            await db.commit()
    await import_document(doc_id, file_path, activity_kind="reindex")


async def recover_versioned_index(
    version_id: str, *, retry_failed: bool = False
) -> None:
    """Resume a crash-interrupted version from persisted chunks."""

    provider = OllamaProvider()
    async with async_session_factory() as db:
        repository = DocumentIndexRepository(db)
        version = await repository.get_version(version_id)
        if version is None:
            raise LookupError(f"index version does not exist: {version_id}")
        status = version.status
        chunks = await repository.list_chunks(version_id)
        embeddings = None
        if status in {"building", "failed"}:
            if not chunks:
                await repository.mark_failed(
                    version_id,
                    failure_code="recovery_missing_chunks",
                    error_message="recoverable index has no persisted chunks",
                )
                return
            try:
                embeddings = await provider.embed([chunk.content for chunk in chunks])
            except Exception as exc:
                if status == "building":
                    await repository.mark_failed(
                        version_id,
                        failure_code="recovery_embedding_failed",
                        error_message=str(exc) or exc.__class__.__name__,
                    )
                raise
        await VersionedDocumentIndexer(db, versioned_chroma_store).resume_and_activate(
            version_id,
            embeddings=embeddings,
            retry_failed=retry_failed,
        )


async def reconcile_versioned_indexes() -> None:
    """Recover crash-interrupted builds once per sidecar startup."""

    if not settings.versioned_rag_indexing_enabled:
        return
    try:
        async with async_session_factory() as db:
            recoverable_ids = [
                version.id
                for version in await DocumentIndexRepository(
                    db
                ).list_recoverable_versions()
            ]
    except Exception:  # noqa: BLE001
        logger.exception("versioned index recovery scan failed")
        return
    for version_id in recoverable_ids:
        try:
            await recover_versioned_index(version_id)
        except Exception:  # noqa: BLE001
            logger.exception("versioned index recovery failed", version_id=version_id)
    try:
        async with async_session_factory() as db:
            indexer = VersionedDocumentIndexer(db, versioned_chroma_store)
            resumed = await indexer.resume_pending_deletions()
            retired = await indexer.cleanup_retired_versions(
                retired_before=utcnow()
                - timedelta(days=settings.versioned_rag_retention_days),
                keep_retired_per_doc=settings.versioned_rag_min_retired_versions,
            )
        if resumed or retired:
            logger.info(
                "versioned index retention cleanup",
                resumed_deletions=len(resumed),
                retired_deleted=len(retired),
            )
    except Exception:  # noqa: BLE001
        logger.exception("versioned index retention cleanup failed")
