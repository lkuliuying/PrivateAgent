"""文档与切片的异步仓储层。

文档元数据存 documents 表，切片原文存 doc_chunks 表；
切片通过 id（chunk_id）与 ChromaDB 中的向量关联。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import DocChunk, Document
from .timeutil import utcnow


class DocumentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        name: str,
        source_path: str | None = None,
        mime_type: str | None = None,
        size_bytes: int | None = None,
        content_hash: str | None = None,
        embedding_model: str | None = None,
        doc_type: str | None = None,
    ) -> Document:
        doc = Document(
            name=name,
            source_path=source_path,
            mime_type=mime_type,
            size_bytes=size_bytes,
            content_hash=content_hash,
            embedding_model=embedding_model,
            doc_type=doc_type,
            status="pending",
        )
        self.db.add(doc)
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def get(self, doc_id: int) -> Optional[Document]:
        return await self.db.get(Document, doc_id)

    async def list(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        enabled: bool | None = None,
        doc_type: str | None = None,
        topic: str | None = None,
        language: str | None = None,
        project_id: int | None = None,
    ) -> list[Document]:
        """文档列表，支持按名称搜索与多维度元数据筛选。"""
        stmt = select(Document)
        if search:
            stmt = stmt.where(Document.name.like(f"%{search}%"))
        if status:
            stmt = stmt.where(Document.status == status)
        if enabled is not None:
            stmt = stmt.where(Document.enabled == enabled)
        if doc_type:
            stmt = stmt.where(Document.doc_type == doc_type)
        if topic:
            stmt = stmt.where(Document.topic == topic)
        if language:
            stmt = stmt.where(Document.language == language)
        if project_id is not None:
            stmt = stmt.where(Document.project_id == project_id)
        stmt = stmt.order_by(Document.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_hash(self, content_hash: str) -> Optional[Document]:
        stmt = select(Document).where(Document.content_hash == content_hash)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        doc_id: int,
        *,
        status: str,
        error_message: str | None = None,
        chunk_count: int | None = None,
        indexed_at: datetime | None = None,
        embedding_model: str | None = None,
    ) -> None:
        values: dict = {"status": status}
        if error_message is not None:
            values["error_message"] = error_message
        if status == "failed":
            # 失败时记录最近失败时间，供知识库筛选与活动流展示
            values["last_error_at"] = utcnow()
        if chunk_count is not None:
            values["chunk_count"] = chunk_count
        if indexed_at is not None:
            values["indexed_at"] = indexed_at
        if embedding_model is not None:
            values["embedding_model"] = embedding_model
        await self.db.execute(
            update(Document).where(Document.id == doc_id).values(**values)
        )
        await self.db.commit()

    async def set_enabled(self, doc_id: int, enabled: bool) -> None:
        """启用/禁用文档。禁用后该文档切片不参与 RAG 检索。"""
        await self.db.execute(
            update(Document).where(Document.id == doc_id).values(enabled=enabled)
        )
        await self.db.commit()

    async def update_metadata(
        self,
        doc_id: int,
        *,
        doc_type: str | None = None,
        topic: str | None = None,
        tags: list[str] | None = None,
        language: str | None = None,
        project_id: int | None = None,
    ) -> None:
        """更新文档元数据（None 表示不改）。供 M2 知识库筛选与检索过滤用。"""
        values: dict = {}
        if doc_type is not None:
            values["doc_type"] = doc_type or None
        if topic is not None:
            values["topic"] = topic or None
        if tags is not None:
            values["tags_json"] = tags
        if language is not None:
            values["language"] = language or None
        if project_id is not None:
            values["project_id"] = project_id or None
        if not values:
            return
        await self.db.execute(
            update(Document).where(Document.id == doc_id).values(**values)
        )
        await self.db.commit()

    async def delete(self, doc_id: int) -> None:
        # doc_chunks 有 ON DELETE CASCADE，删 document 自动删 chunks
        doc = await self.get(doc_id)
        if doc:
            await self.db.delete(doc)
            await self.db.commit()


class DocChunkRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add_many(
        self, doc_id: int, chunks: list[dict]
    ) -> list[DocChunk]:
        """chunks: [{ordinal, content, token_count?, heading?, bm25_text?, keywords?}, ...]"""
        objs = [
            DocChunk(
                doc_id=doc_id,
                ordinal=c["ordinal"],
                content=c["content"],
                token_count=c.get("token_count"),
                heading=c.get("heading"),
                bm25_text=c.get("bm25_text"),
                keywords_json=c.get("keywords"),
            )
            for c in chunks
        ]
        self.db.add_all(objs)
        await self.db.commit()
        for o in objs:
            await self.db.refresh(o)
        return objs

    async def list_by_doc(self, doc_id: int) -> list[DocChunk]:
        stmt = (
            select(DocChunk)
            .where(DocChunk.doc_id == doc_id)
            .order_by(DocChunk.ordinal.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get(self, chunk_id: int) -> Optional[DocChunk]:
        """单个切片详情，供引用片段检查器展示原文。"""
        return await self.db.get(DocChunk, chunk_id)

    async def get_by_ids(self, chunk_ids: list[int]) -> dict[int, DocChunk]:
        """批量按 id 取切片，返回 {chunk_id: DocChunk}。检索后回查原文用。"""
        if not chunk_ids:
            return {}
        stmt = select(DocChunk).where(DocChunk.id.in_(chunk_ids))
        result = await self.db.execute(stmt)
        return {c.id: c for c in result.scalars().all()}
