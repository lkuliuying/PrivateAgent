"""文档集合路由（第四阶段 M3）。

- POST   /document-collections              创建集合
- GET    /document-collections              集合列表
- GET    /document-collections/{id}         集合详情（含成员文档）
- PATCH  /document-collections/{id}         更新集合（title/goal/tags）
- DELETE /document-collections/{id}         删除集合（CASCADE 删成员）
- POST   /document-collections/{id}/items   添加文档到集合
- DELETE /document-collections/{id}/items/{doc_id}  移除文档
- POST   /document-collections/{id}/extract 集合级结构化抽取
- GET    /document-collections/{id}/extractions  集合抽取结果（可按 kind 过滤）
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.document_extraction import (
    ExtractionNotFound,
    DocumentExtractionService,
)
from ..core.repo import DocumentRepository
from ..core.repo_documents import DocumentCollectionRepository

router = APIRouter(tags=["document-collections"])

ExtractionKind = Literal["terms", "table_summary", "actions", "claims", "code"]


# ---- Schemas ----


class CollectionCreate(BaseModel):
    title: str
    goal: str | None = None
    tags: list[str] | None = None

    @field_validator("title")
    @classmethod
    def _check_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title 不能为空")
        return v[:255]


class CollectionUpdate(BaseModel):
    title: str | None = None
    goal: str | None = None
    tags: list[str] | None = None

    @field_validator("title")
    @classmethod
    def _check_title(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("title 不能为空")
        return v[:255]


class CollectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    goal: str | None
    tags_json: list | None
    created_at: datetime
    updated_at: datetime


class CollectionItemOut(BaseModel):
    id: int
    collection_id: int
    doc_id: int
    doc_name: str | None
    doc_status: str | None
    order_index: int


class CollectionDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    goal: str | None
    tags_json: list | None
    created_at: datetime
    updated_at: datetime
    items: list[CollectionItemOut]


class ItemAddRequest(BaseModel):
    doc_id: int


class ExtractRequest(BaseModel):
    kind: ExtractionKind


class ExtractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doc_id: int | None
    collection_id: int | None
    kind: str
    content_json: dict | None
    content_md: str | None
    source_refs_json: list | None
    created_at: datetime


# ---- Routes ----


@router.post("/document-collections", response_model=CollectionOut, status_code=201)
async def create_collection(
    req: CollectionCreate, db: AsyncSession = Depends(get_session)
):
    return await DocumentCollectionRepository(db).create(
        title=req.title, goal=req.goal, tags=req.tags
    )


@router.get("/document-collections", response_model=list[CollectionOut])
async def list_collections(db: AsyncSession = Depends(get_session)):
    return await DocumentCollectionRepository(db).list()


@router.get("/document-collections/{collection_id}", response_model=CollectionDetailOut)
async def get_collection(collection_id: int, db: AsyncSession = Depends(get_session)):
    repo = DocumentCollectionRepository(db)
    coll = await repo.get(collection_id)
    if coll is None:
        raise HTTPException(404, "文档集合不存在")
    rows = await repo.list_items_with_doc(collection_id)
    items = [
        CollectionItemOut(
            id=item.id,
            collection_id=item.collection_id,
            doc_id=item.doc_id,
            doc_name=doc.name if doc else None,
            doc_status=doc.status if doc else None,
            order_index=item.order_index,
        )
        for item, doc in rows
    ]
    return CollectionDetailOut(
        id=coll.id,
        title=coll.title,
        goal=coll.goal,
        tags_json=coll.tags_json,
        created_at=coll.created_at,
        updated_at=coll.updated_at,
        items=items,
    )


@router.patch("/document-collections/{collection_id}", response_model=CollectionOut)
async def update_collection(
    collection_id: int, req: CollectionUpdate, db: AsyncSession = Depends(get_session)
):
    repo = DocumentCollectionRepository(db)
    coll = await repo.get(collection_id)
    if coll is None:
        raise HTTPException(404, "文档集合不存在")
    await repo.update(
        collection_id, title=req.title, goal=req.goal, tags=req.tags
    )
    # repo.update 走 Core UPDATE + commit，coll 对象已过期；async refresh 重读最新值，
    # 避免 Pydantic 序列化时同步 lazy load 触发 MissingGreenlet。
    await db.refresh(coll)
    return coll


@router.delete("/document-collections/{collection_id}", status_code=204)
async def delete_collection(collection_id: int, db: AsyncSession = Depends(get_session)):
    repo = DocumentCollectionRepository(db)
    coll = await repo.get(collection_id)
    if coll is None:
        raise HTTPException(404, "文档集合不存在")
    await repo.delete(collection_id)
    return None


@router.post(
    "/document-collections/{collection_id}/items",
    response_model=CollectionItemOut,
    status_code=201,
)
async def add_item(
    collection_id: int, req: ItemAddRequest, db: AsyncSession = Depends(get_session)
):
    repo = DocumentCollectionRepository(db)
    coll = await repo.get(collection_id)
    if coll is None:
        raise HTTPException(404, "文档集合不存在")
    doc = await DocumentRepository(db).get(req.doc_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")
    try:
        item = await repo.add_item(collection_id, req.doc_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except IntegrityError:
        # 并发重复添加（check-then-insert 竞态）也归 409
        raise HTTPException(409, f"文档 {req.doc_id} 已在集合 {collection_id} 中")
    return CollectionItemOut(
        id=item.id,
        collection_id=item.collection_id,
        doc_id=item.doc_id,
        doc_name=doc.name,
        doc_status=doc.status,
        order_index=item.order_index,
    )


@router.delete(
    "/document-collections/{collection_id}/items/{doc_id}", status_code=204
)
async def remove_item(
    collection_id: int, doc_id: int, db: AsyncSession = Depends(get_session)
):
    repo = DocumentCollectionRepository(db)
    ok = await repo.remove_item(collection_id, doc_id)
    if not ok:
        raise HTTPException(404, "该文档不在此集合中")
    return None


@router.post(
    "/document-collections/{collection_id}/extract", response_model=ExtractionOut
)
async def extract_collection(
    collection_id: int, req: ExtractRequest, db: AsyncSession = Depends(get_session)
):
    """对集合内全部文档执行结构化抽取。"""
    try:
        return await DocumentExtractionService(db).extract(
            req.kind, collection_id=collection_id
        )
    except ExtractionNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get(
    "/document-collections/{collection_id}/extractions",
    response_model=list[ExtractionOut],
)
async def list_collection_extractions(
    collection_id: int,
    kind: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
):
    from ..core.repo_documents import DocumentExtractionRepository

    repo = DocumentExtractionRepository(db)
    coll = await DocumentCollectionRepository(db).get(collection_id)
    if coll is None:
        raise HTTPException(404, "文档集合不存在")
    return await repo.list_by_collection(collection_id, kind=kind)


@router.get("/document-extractions/{extraction_id}", response_model=ExtractionOut)
async def get_extraction(
    extraction_id: int, db: AsyncSession = Depends(get_session)
):
    """按 id 取单个抽取结果（含 doc_ids 路径生成的模板报告，便于检索回看）。"""
    from ..core.repo_documents import DocumentExtractionRepository

    e = await DocumentExtractionRepository(db).get(extraction_id)
    if e is None:
        raise HTTPException(404, "抽取结果不存在")
    return e
