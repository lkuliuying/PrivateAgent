"""文档管理与导入路由。

- GET    /documents                 文档列表（支持 search/status/enabled 筛选）
- POST   /documents/import          上传单个文档
- POST   /documents/batch-import    批量导入（上限 200）
- PATCH  /documents/{id}            启用/禁用文档
- POST   /documents/{id}/reindex    重建单个文档索引
- POST   /documents/reindex-all     重建全部文档索引
- DELETE /documents/{id}            删除文档
- POST   /documents/{id}/retry      重试失败的导入
- GET    /chunks/{id}               引用片段详情
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.db import get_session
from ..core.exports import DocNotFound, ExportService
from ..core.permissions import PermissionError_
from ..core.repo import DocChunkRepository, DocumentRepository
from ..core.store_chroma import chroma_store
from ..logging_setup import get_logger
from ..workers.importer import import_document, reindex_document, retry_import

router = APIRouter(tags=["documents"])
logger = get_logger(__name__)

ALLOWED_EXT = {".pdf", ".docx", ".md", ".markdown", ".txt"}
BATCH_MAX_FILES = 200

# 扩展名 → doc_type（导入时自动推断，供知识库筛选）
_EXT_DOC_TYPE: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
}


def _doc_type_for(ext: str) -> str | None:
    return _EXT_DOC_TYPE.get(ext.lower())


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    mime_type: str | None
    size_bytes: int | None
    content_hash: str | None
    embedding_model: str | None
    chunk_count: int
    status: str
    enabled: bool
    error_message: str | None
    last_error_at: datetime | None
    indexed_at: datetime | None
    # 第三阶段 §4.5：元数据，供知识库筛选与检索过滤
    doc_type: str | None
    topic: str | None
    tags_json: list | None
    language: str | None
    project_id: int | None
    created_at: datetime
    updated_at: datetime


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    doc_id: int
    ordinal: int
    content: str
    token_count: int | None
    created_at: datetime


class DocumentPatch(BaseModel):
    enabled: bool | None = None
    # 第三阶段 M2：元数据可编辑（None=不改；空串/空列表=清空）
    doc_type: str | None = None
    topic: str | None = None
    tags: list[str] | None = None
    language: str | None = None
    project_id: int | None = None


class BatchImportItem(BaseModel):
    name: str
    status: str  # imported / duplicate / error
    doc_id: int | None = None
    error: str | None = None


def _upload_dir() -> Path:
    d = Path("./data/uploads")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _upload_path(doc_id: int, name: str) -> Path:
    """用 doc_id + 扩展名命名，避免文件名特殊字符问题。"""
    ext = Path(name).suffix
    return _upload_dir() / f"{doc_id}{ext}"


async def _ingest_one(file: UploadFile, db: AsyncSession) -> BatchImportItem:
    """单个文件入库（类型校验 + 去重 + 保存 + 后台导入）。供 import / batch-import 复用。"""
    name = file.filename or "untitled"
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        return BatchImportItem(name=name, status="error", error=f"不支持的类型: {ext}")
    data = await file.read()
    c_hash = hashlib.sha256(data).hexdigest()
    docs = DocumentRepository(db)
    existing = await docs.get_by_hash(c_hash)
    if existing:
        return BatchImportItem(name=name, status="duplicate", doc_id=existing.id)
    doc = await docs.create(
        name=name,
        mime_type=file.content_type,
        size_bytes=len(data),
        content_hash=c_hash,
        embedding_model=settings.embed_model,
        doc_type=_doc_type_for(ext),
    )
    upload_path = _upload_path(doc.id, name)
    await asyncio.to_thread(upload_path.write_bytes, data)
    logger.info("document uploaded", doc_id=doc.id, name=name, path=str(upload_path))
    asyncio.create_task(import_document(doc.id, str(upload_path)))
    return BatchImportItem(name=name, status="imported", doc_id=doc.id)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    topic: str | None = Query(default=None),
    language: str | None = Query(default=None),
    project_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
):
    return await DocumentRepository(db).list(
        search=search,
        status=status,
        enabled=enabled,
        doc_type=doc_type,
        topic=topic,
        language=language,
        project_id=project_id,
    )


@router.post("/documents/import", response_model=DocumentOut, status_code=201)
async def import_doc(
    file: UploadFile = File(...), db: AsyncSession = Depends(get_session)
):
    item = await _ingest_one(file, db)
    if item.status == "error":
        raise HTTPException(400, item.error)
    if item.status == "duplicate":
        raise HTTPException(409, f"文档已导入过（doc_id={item.doc_id}）")
    doc = await DocumentRepository(db).get(item.doc_id)
    assert doc is not None
    return doc


@router.post("/documents/batch-import", response_model=list[BatchImportItem])
async def batch_import(
    files: list[UploadFile] = File(...), db: AsyncSession = Depends(get_session)
):
    if len(files) > BATCH_MAX_FILES:
        raise HTTPException(400, f"批量导入上限 {BATCH_MAX_FILES} 个文件")
    if not files:
        raise HTTPException(400, "未提供文件")
    results: list[BatchImportItem] = []
    for file in files:
        try:
            results.append(await _ingest_one(file, db))
        except Exception as e:  # noqa: BLE001
            logger.warning("batch ingest file failed", name=file.filename, error=str(e))
            results.append(
                BatchImportItem(name=file.filename or "untitled", status="error", error=str(e)[:200])
            )
    return results


@router.patch("/documents/{doc_id}", response_model=DocumentOut)
async def patch_document(
    doc_id: int, patch: DocumentPatch, db: AsyncSession = Depends(get_session)
):
    docs = DocumentRepository(db)
    doc = await docs.get(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    if patch.enabled is not None:
        await docs.set_enabled(doc_id, patch.enabled)
    # 元数据字段：仅当请求显式包含（非 None）时更新
    meta_sent = any(
        getattr(patch, f) is not None
        for f in ("doc_type", "topic", "tags", "language", "project_id")
    )
    if meta_sent:
        await docs.update_metadata(
            doc_id,
            doc_type=patch.doc_type,
            topic=patch.topic,
            tags=patch.tags,
            language=patch.language,
            project_id=patch.project_id,
        )
    # update() 走后 identity map 里 doc 对象仍是旧值，需刷新
    await db.refresh(doc)
    return doc


@router.post("/documents/{doc_id}/reindex", response_model=DocumentOut)
async def reindex_doc(doc_id: int, db: AsyncSession = Depends(get_session)):
    docs = DocumentRepository(db)
    doc = await docs.get(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    upload_path = _upload_path(doc.id, doc.name)
    if not upload_path.exists():
        raise HTTPException(400, "原始文件不存在，无法重建索引，请重新导入")
    asyncio.create_task(reindex_document(doc.id, str(upload_path)))
    return doc


@router.post("/documents/reindex-all")
async def reindex_all(db: AsyncSession = Depends(get_session)):
    docs = DocumentRepository(db)
    all_docs = await docs.list()
    triggered = 0
    skipped = 0
    for doc in all_docs:
        upload_path = _upload_path(doc.id, doc.name)
        if upload_path.exists():
            asyncio.create_task(reindex_document(doc.id, str(upload_path)))
            triggered += 1
        else:
            skipped += 1
    return {"triggered": triggered, "skipped": skipped}


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: int, db: AsyncSession = Depends(get_session)):
    docs = DocumentRepository(db)
    doc = await docs.get(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")

    await docs.update_status(doc_id, status="deleting")
    try:
        await chroma_store.delete_by_doc(doc_id)
        await docs.delete(doc_id)  # cascade 删 doc_chunks
        upload_path = _upload_path(doc_id, doc.name)
        await asyncio.to_thread(lambda p: p.unlink(missing_ok=True), upload_path)
        logger.info("document deleted", doc_id=doc_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("document delete failed", doc_id=doc_id)
        await docs.update_status(
            doc_id, status="failed", error_message=f"删除失败: {e}"
        )
        raise HTTPException(500, "删除失败，请稍后重试")
    return {"ok": True, "id": doc_id}


@router.post("/documents/{doc_id}/retry", response_model=DocumentOut)
async def retry_document(doc_id: int, db: AsyncSession = Depends(get_session)):
    docs = DocumentRepository(db)
    doc = await docs.get(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    if doc.status not in ("failed", "pending"):
        raise HTTPException(400, f"仅 failed/pending 状态可重试，当前: {doc.status}")

    upload_path = _upload_path(doc.id, doc.name)
    if not upload_path.exists():
        raise HTTPException(400, "原始文件不存在，无法重试，请重新导入")

    asyncio.create_task(retry_import(doc.id, str(upload_path)))
    return doc


@router.get("/chunks/{chunk_id}", response_model=ChunkOut)
async def get_chunk(chunk_id: int, db: AsyncSession = Depends(get_session)):
    c = await DocChunkRepository(db).get(chunk_id)
    if c is None:
        raise HTTPException(404, "片段不存在")
    return c


# ============ 第三阶段 M4：文档工作台增强 ============


class CompareRequest(BaseModel):
    doc_ids: list[int]


class ExportRequest(BaseModel):
    content: str
    filename: str
    target_dir: str


class ImportNoteRequest(BaseModel):
    title: str
    content: str


@router.post("/documents/{doc_id}/sections/summary")
async def summarize_sections(doc_id: int, db: AsyncSession = Depends(get_session)):
    """生成单文档章节摘要（LLM）。"""
    try:
        return {"sections": await ExportService(db).summarize_sections(doc_id)}
    except DocNotFound:
        raise HTTPException(404, "文档不存在")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/documents/{doc_id}/glossary")
async def generate_glossary(doc_id: int, db: AsyncSession = Depends(get_session)):
    """生成单文档术语表（LLM）。"""
    try:
        return {"terms": await ExportService(db).generate_glossary(doc_id)}
    except DocNotFound:
        raise HTTPException(404, "文档不存在")


@router.post("/documents/compare")
async def compare_documents(req: CompareRequest, db: AsyncSession = Depends(get_session)):
    """多文档对比（共同点/差异/冲突/阅读顺序）。"""
    try:
        return await ExportService(db).compare_documents(req.doc_ids)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except DocNotFound as e:
        raise HTTPException(404, str(e))


@router.post("/documents/export")
async def export_markdown(req: ExportRequest, db: AsyncSession = Depends(get_session)):
    """把生成内容导出为 Markdown 到授权目录（写入需授权路径）。"""
    try:
        return await ExportService(db).export_markdown(
            content=req.content, filename=req.filename, target_dir=req.target_dir
        )
    except PermissionError_ as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/documents/import-note", response_model=BatchImportItem, status_code=201)
async def import_note(req: ImportNoteRequest, db: AsyncSession = Depends(get_session)):
    """把生成的 Markdown 笔记导入知识库（建 doc + 后台导入）。"""
    try:
        res = await ExportService(db).import_note_to_kb(
            title=req.title, content=req.content
        )
        return BatchImportItem(
            name=res["name"], status="imported", doc_id=res["doc_id"]
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
