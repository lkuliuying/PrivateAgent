"""v0.9.0 H3：可选 Git worktree 路由（计划 §4）。

契约要点：
- 可选能力：``coding_worktree_enabled`` 关闭时整体 409 ``coding_mode_disabled``；
  默认仍使用项目根 workspace（不强制）。
- 创建前提供预览（原项目/基础分支/HEAD/新分支/路径/清理策略）。
- 固定 Git argv（``core/git_worktree``），不经 shell，模型无 worktree 工具。
- 创建失败不留半绑定 workspace；dirty worktree 永不自动删除；
  关闭能力后现有 worktree 只读（清理端点同样 409，不自动删除）。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from ..core.db import get_session
from ..core.projects import ProjectNotFound, ProjectService
from ..core.workspaces import ProjectWorkspaceService
from ..logging_setup import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/projects/{project_id}", tags=["worktrees"])

WORKTREE_BASE_DIR = ".pa-worktrees"
WORKTREE_CLEANUP_POLICY = (
    "清理前检查未提交变更与未追踪文件；dirty 状态永不自动删除；"
    "删除失败时保留现场并给出手工命令说明。"
)


def _error(status: int, error_code: str, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status,
        content={"error_code": error_code, "detail": detail},
    )


def _require_enabled():
    if not (cfg.coding_worktree_enabled and cfg.project_bound_runs_enabled):
        return _error(
            409, "coding_mode_disabled", "Worktree support is disabled"
        )
    return None


class WorktreeCreateRequest(BaseModel):
    """创建前由前端展示确认（计划 §4.2）；本请求即用户的显式确认动作。"""

    branch_name: str = Field(min_length=1, max_length=200)
    base_ref: str | None = Field(default=None, max_length=200)


class WorktreePreviewResponse(BaseModel):
    source_project: str
    base_branch: str | None
    base_head_sha: str | None
    new_branch: str
    worktree_path: str
    disk_note: str
    cleanup_policy: str


class WorktreeOut(BaseModel):
    workspace_id: int
    project_id: int
    kind: str
    root_path: str
    branch_name: str | None
    head_sha: str | None
    status: str


def _map_workspace(ws) -> WorktreeOut:
    return WorktreeOut(
        workspace_id=ws.id,
        project_id=ws.project_id,
        kind=ws.kind,
        root_path=ws.root_path,
        branch_name=ws.branch_name,
        head_sha=ws.head_sha,
        status=ws.status,
    )


async def _load_project_and_root(db: AsyncSession, project_id: int):
    try:
        project = await ProjectService(db).get(project_id)
    except ProjectNotFound:
        return None, None, _error(404, "workspace_not_found", "项目不存在")
    svc = ProjectWorkspaceService(db)
    root = await svc.repo.get_by_project_and_kind(project_id, kind="root")
    if root is None:
        return None, None, _error(
            409, "workspace_unavailable", "项目尚无根工作区，请先补建"
        )
    return project, root, None


@router.get("/worktrees/preview")
async def preview_worktree(
    project_id: int,
    branch_name: str,
    db: AsyncSession = Depends(get_session),
):
    """创建前预览（计划 §4.2）：原项目/基础分支/HEAD/新分支/路径/清理策略。"""
    disabled = _require_enabled()
    if disabled is not None:
        return disabled
    from ..core import git_worktree

    project, root, err = await _load_project_and_root(db, project_id)
    if err is not None:
        return err
    try:
        branch = git_worktree.validate_branch_name(branch_name)
    except git_worktree.WorktreeError as exc:
        return _error(422, exc.error_code, exc.detail)
    if not await git_worktree.is_git_repository(root.root_path):
        return _error(409, "worktree_not_git", "项目根目录不是 Git 仓库")
    infos = await git_worktree.list_worktrees(root.root_path)
    base = infos[0] if infos else None
    target = (
        Path(root.root_path)
        / WORKTREE_BASE_DIR
        / git_worktree.worktree_dir_name(branch)
    )
    return WorktreePreviewResponse(
        source_project=project.name,
        base_branch=base.branch if base else None,
        base_head_sha=base.head_sha if base else None,
        new_branch=branch,
        worktree_path=str(target),
        disk_note="worktree 共享原仓库对象库，额外占用约等于检出文件体积",
        cleanup_policy=WORKTREE_CLEANUP_POLICY,
    )


@router.post("/workspaces/worktree", status_code=201)
async def create_worktree_workspace(
    project_id: int,
    request: WorktreeCreateRequest,
    db: AsyncSession = Depends(get_session),
):
    """显式创建 worktree（固定 Git argv；失败不留半绑定记录）。"""
    disabled = _require_enabled()
    if disabled is not None:
        return disabled
    from ..core import git_worktree

    project, root, err = await _load_project_and_root(db, project_id)
    if err is not None:
        return err
    if not await git_worktree.is_git_repository(root.root_path):
        return _error(409, "worktree_not_git", "项目根目录不是 Git 仓库")
    target = (
        Path(root.root_path)
        / WORKTREE_BASE_DIR
        / git_worktree.worktree_dir_name(request.branch_name)
    )
    svc = ProjectWorkspaceService(db)
    try:
        info = await git_worktree.create_worktree(
            repo_root=root.root_path,
            branch_name=request.branch_name,
            target_path=str(target),
            base_ref=request.base_ref,
        )
    except git_worktree.WorktreeError as exc:
        return _error(
            422 if exc.error_code.endswith("invalid") else 409,
            exc.error_code,
            exc.detail,
        )
    try:
        ws = await svc.repo.create(
            project_id=project_id,
            root_path=info.path,
            kind="git_worktree",
            branch_name=info.branch,
            head_sha=info.head_sha,
            status="active",
        )
    except Exception:  # noqa: BLE001 - 唯一键冲突/落库失败 → 回收 worktree
        await db.rollback()
        try:
            await git_worktree.remove_worktree(
                repo_root=root.root_path, worktree_path=info.path
            )
        except git_worktree.WorktreeError:
            logger.warning(
                "worktree rollback remove failed", project_id=project_id
            )
        return _error(
            409, "worktree_create_failed", "worktree 登记失败，已回收现场"
        )
    logger.info(
        "worktree workspace created",
        project_id=project_id,
        workspace_id=ws.id,
        branch=info.branch,
    )
    return _map_workspace(ws)


@router.post("/workspaces/{workspace_id}/cleanup")
async def cleanup_worktree_workspace(
    project_id: int,
    workspace_id: int,
    db: AsyncSession = Depends(get_session),
):
    """显式清理 worktree（计划 §4.3）。

    - 任务归档不自动删除 dirty worktree；本端点同样拒绝 dirty（409）；
    - 删除前检查未提交变更/未追踪文件；路径缺失只归档记录；
    - 删除失败保留现场并返回手工处置提示。
    """
    disabled = _require_enabled()
    if disabled is not None:
        return disabled
    from ..core import git_worktree

    svc = ProjectWorkspaceService(db)
    ws = await svc.get(workspace_id)
    if ws is None or ws.project_id != project_id:
        return _error(404, "workspace_not_found", "Workspace not found")
    if ws.kind != "git_worktree":
        return _error(422, "worktree_path_invalid", "仅 worktree 工作区可清理")
    if ws.status == "archived":
        return {"removed": False, "reason": "archived"}

    root = await svc.repo.get_by_project_and_kind(project_id, kind="root")
    if root is None:
        return _error(409, "workspace_unavailable", "缺少根工作区")

    if not Path(ws.root_path).is_dir():
        await svc.update_status(ws.id, "archived")
        return {"removed": False, "reason": "missing"}

    if await git_worktree.is_worktree_dirty(ws.root_path):
        await svc.update_status(ws.id, "dirty")
        return _error(
            409,
            "worktree_dirty",
            "worktree 存在未提交变更或未追踪文件，不会自动删除；"
            "请先提交/暂存或手工处理（git -C <path> status 查看）",
        )
    try:
        await git_worktree.remove_worktree(
            repo_root=root.root_path, worktree_path=ws.root_path
        )
    except git_worktree.WorktreeError as exc:
        await svc.update_status(ws.id, "cleanup_pending")
        return _error(
            409,
            exc.error_code,
            f"{exc.detail}；手工处置：git -C <项目根> worktree remove <路径>",
        )
    await svc.update_status(ws.id, "archived")
    logger.info(
        "worktree workspace cleaned",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    return {"removed": True, "reason": "ok"}
