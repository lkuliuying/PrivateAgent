"""文档管理与导入路由。

- GET    /documents            文档列表
- POST   /documents/import     上传文档（保存文件 + 创建 pending 记录 + 后台导入）
- DELETE /documents/{id}       删除文档（deleting -> 清 ChromaDB + MySQL）
- POST   /documents/{id}/retry 重试失败的导入
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.db import get_session
from ..core.repo import DocumentRepository
from ..core.store_chroma import chroma_store
from ..logging_setup import get_logger
from ..workers.importer import import_document, retry_import

router = APIRouter(tags=["documents"])
logger = get_logger(__name__)

ALLOWED_EXT = {".pdf", ".docx", ".md", ".markdown", ".txt"}


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
    error_message: str | None
    indexed_at: datetime | None
    created_at: datetime
    updated_at: datetime


def _upload_dir() -> Path:
    d = Path("./data/uploads")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _upload_path(doc_id: int, name: str) -> Path:
    """用 doc_id + 扩展名命名，避免文件名特殊字符问题。"""
    ext = Path(name).suffix
    return _upload_dir() / f"{doc_id}{ext}"


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(db: AsyncSession = Depends(get_session)):
    return await DocumentRepository(db).list()


@router.post("/documents/import", response_model=DocumentOut, status_code=201)
async def import_doc(
    file: UploadFile = File(...), db: AsyncSession = Depends(get_session)
):
    name = file.filename or "untitled"
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"不支持的文件类型: {ext}（支持 PDF/Word/MD/TXT）")

    data = await file.read()
    c_hash = hashlib.sha256(data).hexdigest()

    docs = DocumentRepository(db)
    # 重复导入检测
    existing = await docs.get_by_hash(c_hash)
    if existing:
        raise HTTPException(
            409, f"文档已导入过（{existing.name}，状态: {existing.status}）"
        )

    doc = await docs.create(
        name=name,
        mime_type=file.content_type,
        size_bytes=len(data),
        content_hash=c_hash,
        embedding_model=settings.embed_model,
    )

    upload_path = _upload_path(doc.id, name)
    await asyncio.to_thread(upload_path.write_bytes, data)
    logger.info("document uploaded", doc_id=doc.id, name=name, path=str(upload_path))

    # 后台导入（状态机驱动）
    asyncio.create_task(import_document(doc.id, str(upload_path)))
    return doc


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
        # 清理上传文件
        upload_path = _upload_path(doc_id, doc.name)
        await asyncio.to_thread(lambda p: p.unlink(missing_ok=True), upload_path)
        logger.info("document deleted", doc_id=doc_id)
    except Exception as e:  # noqa: BLE001
        await docs.update_status(
            doc_id, status="failed", error_message=f"删除失败: {e}"
        )
        raise HTTPException(500, f"删除失败: {e}")
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
