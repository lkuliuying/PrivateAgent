"""v0.6.0 ProjectWorkspace 路由（C0 契约 §6.1）。

- ``GET  /projects/{project_id}/workspaces``
- ``GET  /projects/{project_id}/workspaces/{workspace_id}``
- ``POST /projects/{project_id}/workspaces/root/ensure``

``ensure`` 只幂等登记项目现有 root，不创建目录、分支或 worktree。
flag ``PA_PROJECT_BOUND_RUNS_ENABLED`` 关闭时整体 404，legacy 主链不受影响。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_serializer
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from ..core.db import get_session
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


def _require_project_bound() -> None:
    if not cfg.project_bound_runs_enabled:
        raise HTTPException(status_code=404, detail="Not found")


def _telemetry(outcome: str) -> None:
    """C0 §10：workspace_resolve 只保存 outcome 计数，不记录路径或 Git 快照。"""
    from ..core.compatibility import compatibility_telemetry

    compatibility_telemetry.record(
        path="workspace_resolve", mode="project_bound", outcome=outcome
    )


def _error(status: int, error_code: str, detail: str) -> HTTPException:
    # 平铺 error_code 响应（契约测试按 resp.json()["error_code"] 断言）
    from fastapi.responses import JSONResponse

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
