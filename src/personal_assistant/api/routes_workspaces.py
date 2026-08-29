"""v0.6.0 ProjectWorkspace 路由（C0 契约 §6.1）。

- ``GET  /projects/{project_id}/workspaces``
- ``GET  /projects/{project_id}/workspaces/{workspace_id}``
- ``POST /projects/{project_id}/workspaces/root/ensure``

``ensure`` 只幂等登记项目现有 root，不创建目录、分支或 worktree。
flag ``PA_PROJECT_BOUND_RUNS_ENABLED`` 关闭时整体 404，legacy 主链不受影响。
"""
from __future__ import annotations

import asyncio
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from ..core.coding_errors import RUNNABLE_WORKSPACE_STATUSES
from ..core.db import get_session
from ..core.files import MAX_FILE_BYTES
from ..core.projects import language_for_ext
from ..core.timeutil import format_rfc3339_utc
from ..core.workspaces import ProjectWorkspaceService
from ..logging_setup import get_logger

router = APIRouter(prefix="/projects/{project_id}/workspaces", tags=["workspaces"])
logger = get_logger(__name__)


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    kind: str
    root_path: str
    branch_name: str | None = None
    head_sha: str | None = None
    status: str
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    # v0.9.0 H0 §5：统一带 Z 的 RFC 3339 UTC
    @field_serializer("last_used_at", "created_at", "updated_at")
    def _serialize_time(self, value: datetime | None) -> str | None:
        return format_rfc3339_utc(value)


class WorkspaceAttachmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str = Field(min_length=1, max_length=32_768)


class WorkspaceAttachmentOut(BaseModel):
    rel_path: str
    name: str
    language: str | None = None


def _require_project_bound() -> None:
    if not cfg.project_bound_runs_enabled:
        raise HTTPException(status_code=404, detail="Not found")


def _telemetry(outcome: str) -> None:
    """C0 §10：workspace_resolve 只保存 outcome 计数，不记录路径或 Git 快照。"""
    from ..core.compatibility import compatibility_telemetry

    compatibility_telemetry.record(
        path="workspace_resolve", mode="project_bound", outcome=outcome
    )


def _error(status: int, error_code: str, detail: str) -> JSONResponse:
    # 平铺 error_code 响应（契约测试按 resp.json()["error_code"] 断言）
    return JSONResponse(
        status_code=status,
        content={"error_code": error_code, "detail": detail},
    )


@router.get(
    "",
    response_model=list[WorkspaceOut],
    dependencies=[Depends(_require_project_bound)],
)
async def list_workspaces(
    project_id: int,
    db: AsyncSession = Depends(get_session),
):
    """列出项目的所有 workspace。"""
    svc = ProjectWorkspaceService(db)
    items = await svc.repo.list_by_project(project_id)
    _telemetry("resolved")
    return [WorkspaceOut.model_validate(ws) for ws in items]


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceOut,
    dependencies=[Depends(_require_project_bound)],
)
async def get_workspace(
    project_id: int,
    workspace_id: int,
    db: AsyncSession = Depends(get_session),
):
    svc = ProjectWorkspaceService(db)
    ws = await svc.get(workspace_id)
    if ws is None:
        _telemetry("missing")
        return _error(404, "workspace_not_found", "Workspace not found")
    if ws.project_id != project_id:
        _telemetry("mismatch")
        return _error(404, "workspace_not_found", "Workspace not found")
    _telemetry("resolved")
    return WorkspaceOut.model_validate(ws)


@router.post(
    "/{workspace_id}/attachments",
    response_model=WorkspaceAttachmentOut,
    dependencies=[Depends(_require_project_bound)],
)
async def attach_workspace_file(
    project_id: int,
    workspace_id: int,
    request: WorkspaceAttachmentRequest,
    db: AsyncSession = Depends(get_session),
) -> WorkspaceAttachmentOut | JSONResponse:
    """Copy a user-picked file into the current workspace and return a safe ref."""
    workspace = await ProjectWorkspaceService(db).get(workspace_id)
    if workspace is None or workspace.project_id != project_id:
        return _error(404, "workspace_not_found", "Workspace not found")
    if workspace.status not in RUNNABLE_WORKSPACE_STATUSES:
        return _error(
            409,
            "workspace_unavailable",
            f"Workspace is {workspace.status}",
        )

    source = Path(request.source_path).expanduser()
    if not source.is_absolute() or source.is_symlink():
        return _error(422, "attachment_invalid", "请选择一个本地普通文件")
    try:
        source = source.resolve(strict=True)
        workspace_root = Path(workspace.root_path).resolve(strict=True)
    except OSError:
        return _error(422, "attachment_invalid", "所选文件或工作区不存在")
    if not source.is_file():
        return _error(422, "attachment_invalid", "请选择一个本地普通文件")
    try:
        size = source.stat().st_size
    except OSError:
        return _error(422, "attachment_invalid", "无法读取所选文件")
    if size > MAX_FILE_BYTES:
        return _error(
            413,
            "attachment_too_large",
            f"文件超过 {MAX_FILE_BYTES // (1024 * 1024)} MB 上限",
        )

    try:
        relative = source.relative_to(workspace_root)
    except ValueError:
        attachment_dir = workspace_root / ".privateagent" / "attachments"
        try:
            await asyncio.to_thread(attachment_dir.mkdir, parents=True, exist_ok=True)
            resolved_attachment_dir = attachment_dir.resolve(strict=True)
            resolved_attachment_dir.relative_to(workspace_root)
        except (OSError, ValueError):
            return _error(409, "workspace_unavailable", "工作区附件目录不可用")
        destination = resolved_attachment_dir / f"{uuid4().hex[:8]}-{source.name}"
        try:
            await asyncio.to_thread(shutil.copy2, source, destination)
        except OSError:
            return _error(422, "attachment_copy_failed", "无法复制所选文件")
        relative = destination.relative_to(workspace_root)

    rel_path = relative.as_posix()
    return WorkspaceAttachmentOut(
        rel_path=rel_path,
        name=source.name,
        language=language_for_ext(source.suffix.lower()),
    )


@router.post(
    "/root/ensure",
    response_model=WorkspaceOut,
    status_code=201,
    dependencies=[Depends(_require_project_bound)],
)
async def ensure_root_workspace(
    project_id: int,
    db: AsyncSession = Depends(get_session),
):
    """幂等确保 project 有 root workspace。旧项目首次调用时补建。"""
    from ..core.projects import ProjectNotFound, ProjectService

    try:
        project = await ProjectService(db).get(project_id)
    except ProjectNotFound:
        _telemetry("missing")
        return _error(404, "workspace_not_found", "Project not found")
    svc = ProjectWorkspaceService(db)
    ws = await svc.ensure_root_workspace(project)
    await svc.touch_last_used(ws.id)
    await db.refresh(ws)
    _telemetry("resolved")
    return WorkspaceOut.model_validate(ws)
