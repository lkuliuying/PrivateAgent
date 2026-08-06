"""文档集合与结构化抽取异步仓储层（第四阶段 M3）。

照 core/repo.py 模式：每仓储持 AsyncSession，方法内自带 commit。
document_collection_items.doc_id 与 document_extractions.doc_id/collection_id 为
跨域软引用（documents 在另一域），不建外键；故删文档不会级联清 item/extraction，
查询时用 outerjoin 容忍悬空引用。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Document,
    DocumentCollection,
    DocumentCollectionItem,
    DocumentExtraction,
)


class DocumentCollectionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self, *, title: str, goal: str | None = None, tags: list[str] | None = None
    ) -> DocumentCollection:
        c = DocumentCollection(title=title, goal=goal, tags_json=tags)
        self.db.add(c)
        await self.db.commit()
        await self.db.refresh(c)
        return c

    async def get(self, collection_id: int) -> Optional[DocumentCollection]:
        return await self.db.get(DocumentCollection, collection_id)

    async def list(self) -> list[DocumentCollection]:
        stmt = select(DocumentCollection).order_by(DocumentCollection.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        collection_id: int,
        *,
        title: str | None = None,
        goal: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        from sqlalchemy import update

        values: dict = {}
        if title is not None:
            values["title"] = title
        if goal is not None:
            values["goal"] = goal
        if tags is not None:
            values["tags_json"] = tags
        if not values:
            return
        await self.db.execute(
            update(DocumentCollection)
            .where(DocumentCollection.id == collection_id)
            .values(**values)
        )
        await self.db.commit()

    async def delete(self, collection_id: int) -> None:
        c = await self.get(collection_id)
        if c is not None:
            await self.db.delete(c)  # cascade="all, delete-orphan" 清 items
            await self.db.commit()

    async def list_items(
        self, collection_id: int
    ) -> list[DocumentCollectionItem]:
        stmt = (
            select(DocumentCollectionItem)
            .where(DocumentCollectionItem.collection_id == collection_id)
            .order_by(DocumentCollectionItem.order_index.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_items_with_doc(
        self, collection_id: int
    ) -> list[tuple[DocumentCollectionItem, Optional[Document]]]:
        """集合成员 + 所属文档（outerjoin 容忍悬空 doc_id 软引用）。"""
        stmt = (
            select(DocumentCollectionItem, Document)
            .outerjoin(Document, DocumentCollectionItem.doc_id == Document.id)
            .where(DocumentCollectionItem.collection_id == collection_id)
            .order_by(DocumentCollectionItem.order_index.asc())
        )
        result = await self.db.execute(stmt)
        return [(item, doc) for item, doc in result.all()]

    async def get_item(
        self, collection_id: int, doc_id: int
    ) -> Optional[DocumentCollectionItem]:
        stmt = (
            select(DocumentCollectionItem)
            .where(DocumentCollectionItem.collection_id == collection_id)
            .where(DocumentCollectionItem.doc_id == doc_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def add_item(
        self, collection_id: int, doc_id: int
    ) -> DocumentCollectionItem:
        """添加文档到集合；已存在抛 ValueError（唯一约束 uk_collection_doc）。"""
        existing = await self.get_item(collection_id, doc_id)
        if existing is not None:
            raise ValueError(f"文档 {doc_id} 已在集合 {collection_id} 中")
        # order_index 取当前最大值 +1
        max_stmt = select(func.max(DocumentCollectionItem.order_index)).where(
            DocumentCollectionItem.collection_id == collection_id
        )
        cur = (await self.db.execute(max_stmt)).scalar()
        item = DocumentCollectionItem(
            collection_id=collection_id,
            doc_id=doc_id,
            order_index=(cur or 0) + 1,
        )
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def remove_item(self, collection_id: int, doc_id: int) -> bool:
        item = await self.get_item(collection_id, doc_id)
        if item is None:
            return False
        await self.db.delete(item)
        await self.db.commit()
        return True


class DocumentExtractionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        kind: str,
        doc_id: int | None = None,
        collection_id: int | None = None,
        content_json: dict | None = None,
        content_md: str | None = None,
        source_refs_json: list | None = None,
    ) -> DocumentExtraction:
        e = DocumentExtraction(
            doc_id=doc_id,
            collection_id=collection_id,
            kind=kind,
            content_json=content_json,
            content_md=content_md,
            source_refs_json=source_refs_json,
        )
        self.db.add(e)
        await self.db.commit()
        await self.db.refresh(e)
        return e

    async def get(self, extraction_id: int) -> Optional[DocumentExtraction]:
        return await self.db.get(DocumentExtraction, extraction_id)

    async def list_by_doc(
        self, doc_id: int, kind: str | None = None
    ) -> list[DocumentExtraction]:
        stmt = select(DocumentExtraction).where(DocumentExtraction.doc_id == doc_id)
        if kind is not None:
            stmt = stmt.where(DocumentExtraction.kind == kind)
        stmt = stmt.order_by(DocumentExtraction.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_by_collection(
        self, collection_id: int, kind: str | None = None
    ) -> list[DocumentExtraction]:
        stmt = select(DocumentExtraction).where(
            DocumentExtraction.collection_id == collection_id
        )
        if kind is not None:
            stmt = stmt.where(DocumentExtraction.kind == kind)
        stmt = stmt.order_by(DocumentExtraction.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
