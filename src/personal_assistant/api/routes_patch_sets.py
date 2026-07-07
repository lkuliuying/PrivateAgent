"""补丁集路由（第四阶段 M4）。

- POST   /projects/{project_id}/patch-sets  创建补丁集（多文件快照）
- GET    /projects/{project_id}/patch-sets  项目补丁集列表
- GET    /patch-sets/{id}                    补丁集详情（含文件 diff）
- POST   /patch-sets/{id}/submit             提交审批（draft→waiting_approval）
- POST   /patch-sets/{id}/apply              审批后应用（sha256 校验，写入多文件）
- POST   /patch-sets/{id}/reject             拒绝
- POST   /patch-sets/{id}/rollback           审批后回滚（恢复 old_content，校验 new sha）
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.patch_sets import PatchSetNotFound, PatchSetService
from ..core.projects import ProjectNotFound

router = APIRouter(tags=["patch-sets"])

PatchSetStatus = Literal["draft", "waiting_approval", "applied", "rejected", "rolled_back"]
PatchFileStatus = Literal["draft", "applied", "rejected", "rolled_back"]


# ---- Schemas ----


class PatchFileCreate(BaseModel):
    rel_path: str = Field(min_length=1)
    new_content: str
    create: bool = False


class PatchSetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    files: list[PatchFileCreate] = Field(min_length=1)
    task_id: int | None = None


class PatchFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patch_set_id: int
    rel_path: str
    old_sha256: str | None
    new_sha256: str | None
    diff_text: str
    status: PatchFileStatus


class PatchSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    task_id: int | None
    title: str
    status: PatchSetStatus
    created_at: datetime
    updated_at: datetime
    files: list[PatchFileOut]


class ApplyResult(BaseModel):
    patch_set_id: int
    status: str
    written: list[dict] = []
    restored: list[dict] = []


# ---- Routes ----


@router.post(
    "/projects/{project_id}/patch-sets", response_model=PatchSetOut, status_code=201
)
async def create_patch_set(
    project_id: int, req: PatchSetCreate, db: AsyncSession = Depends(get_session)
):
    try:
        return await PatchSetService(db).create(
            project_id=project_id,
            title=req.title,
            task_id=req.task_id,
            files=[f.model_dump() for f in req.files],
        )
    except ProjectNotFound as e:
        raise HTTPException(404, str(e))
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/projects/{project_id}/patch-sets", response_model=list[PatchSetOut])
async def list_patch_sets(project_id: int, db: AsyncSession = Depends(get_session)):
    return await PatchSetService(db).list_by_project(project_id)


@router.get("/patch-sets/{patch_set_id}", response_model=PatchSetOut)
async def get_patch_set(patch_set_id: int, db: AsyncSession = Depends(get_session)):
    try:
        return await PatchSetService(db).get(patch_set_id)
    except PatchSetNotFound as e:
        raise HTTPException(404, str(e))


@router.post("/patch-sets/{patch_set_id}/submit", response_model=PatchSetOut)
async def submit_patch_set(patch_set_id: int, db: AsyncSession = Depends(get_session)):
    try:
        return await PatchSetService(db).submit_for_approval(patch_set_id)
    except PatchSetNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/patch-sets/{patch_set_id}/apply", response_model=ApplyResult)
async def apply_patch_set(patch_set_id: int, db: AsyncSession = Depends(get_session)):
    """审批后应用：校验各文件 sha256 未变，写入多文件。"""
    try:
        return await PatchSetService(db).apply(patch_set_id)
    except PatchSetNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        # sha256 不一致 → 文件已变，409 冲突
        raise HTTPException(409, str(e))


@router.post("/patch-sets/{patch_set_id}/reject", response_model=PatchSetOut)
async def reject_patch_set(patch_set_id: int, db: AsyncSession = Depends(get_session)):
    try:
        return await PatchSetService(db).reject(patch_set_id)
    except PatchSetNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/patch-sets/{patch_set_id}/rollback", response_model=ApplyResult)
async def rollback_patch_set(patch_set_id: int, db: AsyncSession = Depends(get_session)):
    """审批后回滚：恢复 old_content（created 文件删除），校验 new sha 未变。"""
    try:
        return await PatchSetService(db).rollback(patch_set_id)
    except PatchSetNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
