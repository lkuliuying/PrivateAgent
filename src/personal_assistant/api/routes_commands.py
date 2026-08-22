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
from ..core.permissions import PermissionError_
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
    # v0.7.0 E0 §6：版本化扩展字段（非法值由 service 校验，映射 422）
    cwd_rel: str | None = Field(default=None, max_length=2048)
    env_allowlist: list[str] | None = None
    allow_network: bool = False
    result_parser: str | None = None
    risk_level: str = "confirm"
    capability: str | None = Field(default=None, max_length=64)
    max_output_bytes: int | None = None
    description: str | None = Field(default=None, max_length=512)

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
    # v0.7.0 E0 §6：版本化扩展字段（None 不更新）
    cwd_rel: str | None = Field(default=None, max_length=2048)
    env_allowlist: list[str] | None = None
    allow_network: bool | None = None
    result_parser: str | None = None
    risk_level: str | None = None
    capability: str | None = Field(default=None, max_length=64)
    max_output_bytes: int | None = None
    description: str | None = Field(default=None, max_length=512)

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
    # v0.7.0 E0 §6：版本化扩展字段
    profile_version: int
    cwd_rel: str | None = None
    env_allowlist: list | None = None
    allow_network: bool = False
    result_parser: str | None = None
    risk_level: str = "confirm"
    capability: str | None = None
    max_output_bytes: int | None = None
    description: str | None = None
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
    # v0.7.0 E2：命令 profile 版本与结构化解析结果
    profile_version: int | None = None
    parsed: dict | None = None


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
    try:
        return await CommandProfileService(db).create(
            project_id=project_id,
            name=req.name,
            command_json=req.command_json,
            kind=req.kind,
            timeout_seconds=req.timeout_seconds,
            enabled=req.enabled,
            cwd_rel=req.cwd_rel,
            env_allowlist=req.env_allowlist,
            allow_network=req.allow_network,
            result_parser=req.result_parser,
            risk_level=req.risk_level,
            capability=req.capability,
            max_output_bytes=req.max_output_bytes,
            description=req.description,
        )
    except ValueError as e:
        # E0 §6：非法字段 → command_profile_invalid 422
        raise HTTPException(422, str(e))


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
            cwd_rel=req.cwd_rel,
            env_allowlist=req.env_allowlist,
            allow_network=req.allow_network,
            result_parser=req.result_parser,
            risk_level=req.risk_level,
            capability=req.capability,
            max_output_bytes=req.max_output_bytes,
            description=req.description,
        )
    except CommandProfileNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        # E0 §6：非法字段 → command_profile_invalid 422
        raise HTTPException(422, str(e))


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
    """运行项目命令配置（配置即预授权，不经全局白名单）。

    第六轮（P1-1）：校验路径 project_id 属于该 profile（跨项目引用拒绝），
    执行统一走受审计路径（CommandProfileService.run →
    run_whitelisted_command_trusted：argv/schema/网络校验 + Job Object
    进程树清理 + 流式有界输出）。
    """
    try:
        svc = CommandProfileService(db)
        profile = await svc.repo.get(command_id)
        if profile is None:
            raise CommandProfileNotFound(f"命令配置不存在: {command_id}")
        if profile.project_id != project_id:
            raise CommandProfileNotFound(
                f"命令配置 {command_id} 不属于项目 {project_id}"
            )
        return await svc.run(command_id)
    except CommandProfileNotFound as e:
        raise HTTPException(404, str(e))
    except ProjectNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        # E0 §6：禁用/非法配置 → command_profile_invalid 422
        raise HTTPException(422, str(e))
    except PermissionError_ as e:
        # 第七轮（O-1）：权限/白名单拒绝（restricted profile、argv 校验
        # 拒绝等）→ 403，不再落入 RuntimeError 的 500（命令零执行不变，
        # 仅 HTTP 语义修正；与 routes_projects/routes_integrations 惯例一致）。
        raise HTTPException(403, str(e))
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
