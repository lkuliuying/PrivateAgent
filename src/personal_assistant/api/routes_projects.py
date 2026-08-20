"""项目工作区路由（第三阶段 M1）。

- POST   /projects                 授权并创建项目（同步授权 root_path 到 trusted_paths）
- GET    /projects                 项目列表
- GET    /projects/{id}            项目详情
- GET    /projects/{id}/stats      文件统计（总数/语言分布/二进制数）
- POST   /projects/{id}/scan       触发后台扫描（全量重建文件索引）
- GET    /projects/{id}/tree       目录树
- GET    /projects/{id}/files      文件列表（可按 ext/language 过滤）
- GET    /projects/{id}/search     文件名(name)/内容(content)搜索
- GET    /projects/{id}/git/status git 状态（只读）
- GET    /projects/{id}/git/diff   git diff（只读）
- DELETE /projects/{id}            归档项目（status=archived，不删数据）
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.code_tools import (
    get_git_diff,
    get_git_status,
    grep_code,
    read_code_file,
    search_files,
)
from ..core.db import get_session
from ..core.permissions import PermissionError_
from ..core.projects import ProjectNotFound, ProjectService
from ..workers.project_scanner import scan_project

router = APIRouter(tags=["projects"])


# ---- Schemas ----

class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    root_path: str
    language: str | None
    framework: str | None
    status: str
    last_scanned_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    name: str
    root_path: str

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name 不能为空")
        return v[:255]

    @field_validator("root_path")
    @classmethod
    def _check_path(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("root_path 不能为空")
        p = Path(v).expanduser()
        if not p.is_absolute():
            raise ValueError("root_path 必须为绝对路径")
        return str(p)


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rel_path: str
    language: str | None
    size_bytes: int | None
    is_binary: bool


class ReadFileQuery(BaseModel):
    rel_path: str
    start_line: int = 1
    max_lines: int = 2000


# ---- Routes ----

def _map_project(p) -> ProjectOut:
    return ProjectOut.model_validate(p)


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_session)):
    return [_map_project(p) for p in await ProjectService(db).list()]


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(req: ProjectCreate, db: AsyncSession = Depends(get_session)):
    try:
        project = await ProjectService(db).authorize(
            name=req.name, root_path=req.root_path
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _map_project(project)


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: int, db: AsyncSession = Depends(get_session)):
    try:
        return _map_project(await ProjectService(db).get(project_id))
    except ProjectNotFound:
        raise HTTPException(404, "项目不存在")


@router.delete("/projects/{project_id}", response_model=ProjectOut)
async def archive_project(project_id: int, db: AsyncSession = Depends(get_session)):
    from ..core.repo_projects import ProjectRepository

    try:
        await ProjectService(db).get(project_id)
    except ProjectNotFound:
        raise HTTPException(404, "项目不存在")
    await ProjectRepository(db).archive(project_id)
    # C0 契约 §4.1：项目归档只把 workspace 标记 archived，不物理删除运行审计关系。
    from ..core.repo_workspaces import ProjectWorkspaceRepository

    await ProjectWorkspaceRepository(db).archive_by_project(project_id)
    project = await ProjectRepository(db).get(project_id)
    assert project is not None
    return _map_project(project)


@router.get("/projects/{project_id}/stats")
async def project_stats(project_id: int, db: AsyncSession = Depends(get_session)):
    try:
        return await ProjectService(db).file_stats(project_id)
    except ProjectNotFound:
        raise HTTPException(404, "项目不存在")


@router.post("/projects/{project_id}/scan", response_model=ProjectOut)
async def scan_project_route(project_id: int, db: AsyncSession = Depends(get_session)):
    """触发后台扫描（不阻塞请求）。返回项目对象，前端可轮询 /tree 或 /stats。"""
    try:
        project = await ProjectService(db).get(project_id)
    except ProjectNotFound:
        raise HTTPException(404, "项目不存在")
    asyncio.create_task(scan_project(project_id))
    return _map_project(project)


@router.get("/projects/{project_id}/tree")
async def project_tree(project_id: int, db: AsyncSession = Depends(get_session)):
    try:
        return await ProjectService(db).tree(project_id)
    except ProjectNotFound:
        raise HTTPException(404, "项目不存在")


@router.get("/projects/{project_id}/files", response_model=list[FileOut])
async def project_files(
    project_id: int,
    ext: str | None = Query(default=None),
    language: str | None = Query(default=None),
    limit: int = Query(default=500, le=5000),
    db: AsyncSession = Depends(get_session),
):
    try:
        files = await ProjectService(db).files(
            project_id, ext=ext, language=language, limit=limit
        )
    except ProjectNotFound:
        raise HTTPException(404, "项目不存在")
    return [FileOut.model_validate(f) for f in files]


@router.get("/projects/{project_id}/search")
async def project_search(
    project_id: int,
    query: str = Query(..., description="搜索词（文件名或正则内容）"),
    kind: str = Query(default="name", pattern="^(name|content)$"),
    db: AsyncSession = Depends(get_session),
):
    """按文件名(name)或内容(content, 正则)搜索项目。"""
    try:
        if kind == "content":
            return await grep_code(db, project_id, query)
        return await search_files(db, project_id, query)
    except ProjectNotFound:
        raise HTTPException(404, "项目不存在")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/projects/{project_id}/read")
async def project_read_file(
    project_id: int,
    rel_path: str = Query(..., description="项目内相对路径"),
    start_line: int = Query(default=1, ge=1),
    max_lines: int = Query(default=2000, ge=1, le=10000),
    db: AsyncSession = Depends(get_session),
):
    """读取项目内文件片段（按行分页）。rel_path 必须在项目根下。"""
    try:
        return await read_code_file(
            db, project_id, rel_path, start_line=start_line, max_lines=max_lines
        )
    except ProjectNotFound:
        raise HTTPException(404, "项目不存在")
    except PermissionError_ as e:
        raise HTTPException(403, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/projects/{project_id}/git/status")
async def project_git_status(project_id: int, db: AsyncSession = Depends(get_session)):
    try:
        return await get_git_status(db, project_id)
    except ProjectNotFound:
        raise HTTPException(404, "项目不存在")
    except (RuntimeError, TimeoutError) as e:
        _raise_git_error(e)


@router.get("/projects/{project_id}/git/diff")
async def project_git_diff(
    project_id: int,
    cached: bool = Query(default=False),
    db: AsyncSession = Depends(get_session),
):
    try:
        return await get_git_diff(db, project_id, cached=cached)
    except ProjectNotFound:
        raise HTTPException(404, "项目不存在")
    except (RuntimeError, TimeoutError) as e:
        _raise_git_error(e)


def _raise_git_error(e: Exception) -> None:
    """git 错误脱敏：非 git 仓库 → 400；超时 → 504；其他 → 500。原始错误仅日志。"""
    msg = str(e)
    if "not a git repository" in msg.lower():
        raise HTTPException(400, "该项目不是 git 仓库")
    if isinstance(e, TimeoutError):
        raise HTTPException(504, "git 命令超时")
    raise HTTPException(500, "git 操作失败")
