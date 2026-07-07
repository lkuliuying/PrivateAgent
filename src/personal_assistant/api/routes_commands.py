"""项目命令配置路由（第四阶段 M4）。

- GET    /projects/{project_id}/commands               命令配置列表
- POST   /projects/{project_id}/commands               新建命令配置
- PATCH  /projects/{project_id}/commands/{command_id}  更新/启用/禁用
- DELETE /projects/{project_id}/commands/{command_id}  删除
- POST   /projects/{project_id}/commands/{command_id}/run  运行配置命令（预授权）
- POST   /projects/{project_id}/diagnose-command-output    命令失败诊断（LLM）
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.patch_sets import (
    CommandProfileNotFound,
    CommandProfileService,
    DiagnosticsService,
)
from ..core.projects import ProjectNotFound
from ..core.provider import ProviderError

router = APIRouter(tags=["project-commands"])

CommandKind = Literal["test", "build", "lint", "format", "typecheck", "custom"]


# ---- Schemas ----


class CommandProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    command_json: dict
    kind: CommandKind
    timeout_seconds: int = 120
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name 不能为空")
        return v[:128]


class CommandProfileUpdate(BaseModel):
    name: str | None = None
    command_json: dict | None = None
    kind: CommandKind | None = None
    timeout_seconds: int | None = None
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("name 不能为空")
        return v[:128]


class CommandProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    command_json: dict
    kind: str
    timeout_seconds: int
    enabled: bool
    created_at: datetime


class RunResult(BaseModel):
    project_id: int
    profile_id: int
    profile_name: str
    args: list[str]
    cwd: str
    returncode: int
    stdout: str
    stderr: str
    output: str
    truncated: bool
    succeeded: bool


class DiagnoseRequest(BaseModel):
    output: str
    returncode: int
    args: list[str] | None = None


class ErrorFileOut(BaseModel):
    file: str
    line: int
    message: str


class DiagnoseResult(BaseModel):
    summary: str
    error_files: list[ErrorFileOut]
    suggestion: str


# ---- Routes ----


@router.get(
    "/projects/{project_id}/commands", response_model=list[CommandProfileOut]
)
async def list_commands(
    project_id: int,
    kind: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
):
    return await CommandProfileService(db).list_by_project(project_id, kind=kind)


@router.post(
    "/projects/{project_id}/commands", response_model=CommandProfileOut, status_code=201
)
async def create_command(
    project_id: int, req: CommandProfileCreate, db: AsyncSession = Depends(get_session)
):
    return await CommandProfileService(db).create(
        project_id=project_id,
        name=req.name,
        command_json=req.command_json,
        kind=req.kind,
        timeout_seconds=req.timeout_seconds,
        enabled=req.enabled,
    )


@router.patch(
    "/projects/{project_id}/commands/{command_id}", response_model=CommandProfileOut
)
async def update_command(
    project_id: int,
    command_id: int,
    req: CommandProfileUpdate,
    db: AsyncSession = Depends(get_session),
):
    try:
        return await CommandProfileService(db).update(
            command_id,
            name=req.name,
            command_json=req.command_json,
            kind=req.kind,
            timeout_seconds=req.timeout_seconds,
            enabled=req.enabled,
        )
    except CommandProfileNotFound as e:
        raise HTTPException(404, str(e))


@router.delete(
    "/projects/{project_id}/commands/{command_id}", response_model=CommandProfileOut
)
async def delete_command(
    project_id: int, command_id: int, db: AsyncSession = Depends(get_session)
):
    """删除命令配置（返回被删对象便于前端移除）。"""
    svc = CommandProfileService(db)
    try:
        p = await svc.repo.get(command_id)
        if p is None:
            raise CommandProfileNotFound(f"命令配置不存在: {command_id}")
        out = CommandProfileOut.model_validate(p)
        await svc.delete(command_id)
        return out
    except CommandProfileNotFound as e:
        raise HTTPException(404, str(e))


@router.post(
    "/projects/{project_id}/commands/{command_id}/run", response_model=RunResult
)
async def run_command(
    project_id: int, command_id: int, db: AsyncSession = Depends(get_session)
):
    """运行项目命令配置（配置即预授权，不经全局白名单）。"""
    try:
        return await CommandProfileService(db).run(command_id)
    except CommandProfileNotFound as e:
        raise HTTPException(404, str(e))
    except ProjectNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except TimeoutError as e:
        raise HTTPException(504, str(e))


@router.post(
    "/projects/{project_id}/diagnose-command-output", response_model=DiagnoseResult
)
async def diagnose_command_output(
    project_id: int, req: DiagnoseRequest, db: AsyncSession = Depends(get_session)
):
    """命令失败诊断：LLM 抽错误摘要/文件行/下一步建议。"""
    try:
        return await DiagnosticsService(db).diagnose(
            output=req.output, returncode=req.returncode, args=req.args
        )
    except ProviderError as e:
        raise HTTPException(502, str(e))
