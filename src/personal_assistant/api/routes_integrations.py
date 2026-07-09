"""本地集成路由（第八阶段 M8）。

- GET    /integrations/sources           列出集成源
- POST   /integrations/sources           创建集成源（kind/title/file_path/target）
- POST   /integrations/preview           隐私预览（解析 ICS，不建对象）
- POST   /integrations/import            执行导入
- GET    /integrations/imports           列出导入记录
- DELETE /integrations/imports/{id}      撤销一次导入

对齐 docs/phase8-requirements.md §7。导入复用 trusted paths 与隐私预览，不默认外发。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.integrations import IntegrationService
from ..core.permissions import PermissionError_

router = APIRouter(tags=["integrations"])


class SourceCreate(BaseModel):
    kind: str = "ics_calendar"
    title: str
    file_path: str
    target: str = "reminder"  # reminder | inbox
    options: dict | None = None


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    title: str
    config_json: dict | None
    enabled: bool
    last_run_at: datetime | None = None
    last_status: str | None = None


class PreviewRequest(BaseModel):
    source_id: int | None = None
    file_path: str | None = None


class ImportRequest(BaseModel):
    source_id: int
    target: str | None = None


class ImportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int | None
    source_kind: str
    summary_json: dict | None
    target_type: str | None
    target_id: int | None
    reversible: bool
    reversal_info_json: dict | None
    status: str
    error_message: str | None = None
    created_at: datetime
    reverted_at: datetime | None = None


@router.get("/integrations/sources", response_model=list[SourceOut])
async def list_sources(db: AsyncSession = Depends(get_session)):
    return await IntegrationService(db).list_sources()


@router.post("/integrations/sources", response_model=SourceOut, status_code=201)
async def create_source(body: SourceCreate, db: AsyncSession = Depends(get_session)):
    return await IntegrationService(db).create_source(
        kind=body.kind,
        title=body.title,
        file_path=body.file_path,
        target=body.target,
        options=body.options,
    )


@router.post("/integrations/preview")
async def preview(body: PreviewRequest, db: AsyncSession = Depends(get_session)):
    try:
        return await IntegrationService(db).preview(
            source_id=body.source_id, file_path=body.file_path
        )
    except KeyError:
        raise HTTPException(404, "集成源不存在")
    except PermissionError_ as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/integrations/import", response_model=ImportOut)
async def run_import(body: ImportRequest, db: AsyncSession = Depends(get_session)):
    try:
        return await IntegrationService(db).run_import(
            source_id=body.source_id, target=body.target
        )
    except KeyError:
        raise HTTPException(404, "集成源不存在")
    except PermissionError_ as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/integrations/imports", response_model=list[ImportOut])
async def list_imports(db: AsyncSession = Depends(get_session)):
    return await IntegrationService(db).list_imports()


@router.delete("/integrations/imports/{import_id}", response_model=ImportOut)
async def revert_import(import_id: int, db: AsyncSession = Depends(get_session)):
    try:
        return await IntegrationService(db).revert(import_id)
    except KeyError:
        raise HTTPException(404, "导入记录不存在")
