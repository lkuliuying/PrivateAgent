"""v0.6.0 ProjectWorkspace 服务：幂等补建、状态管理、会话绑定。

C0 阶段只提供基础服务桩，后续 C1 阶段补全。
"""
from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .models import Project, ProjectWorkspace
from .repo_workspaces import ProjectWorkspaceRepository

logger = get_logger(__name__)


class ProjectWorkspaceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ProjectWorkspaceRepository(db)

    async def get(self, workspace_id: int) -> ProjectWorkspace | None:
        return await self.repo.get(workspace_id)

    async def ensure_root_workspace(
        self, project: Project
    ) -> ProjectWorkspace:
        """幂等为 project 建立 root workspace。

        旧项目在迁移或首次读取时调用此方法。
        """
        ws = await self.repo.ensure_root_workspace(
            project_id=project.id,
            root_path=project.root_path,
        )
        if ws is None:
            raise RuntimeError(
                f"Failed to ensure root workspace for project {project.id}"
            )
        return ws

    async def touch_last_used(
        self, workspace_id: int, at: datetime | None = None
    ) -> None:
        await self.repo.touch_last_used(workspace_id, at=at)

    async def update_status(
        self, workspace_id: int, status: str
    ) -> None:
        await self.repo.update_status(workspace_id, status)

    async def check_path(self, ws: ProjectWorkspace) -> bool:
        """校验 workspace 路径仍存在；缺失时标记 missing 并返回 False。

        C1 退出条件：项目路径丢失时失败关闭，不自动改绑。
        """
        if os.path.isdir(ws.root_path):
            return True
        if ws.status == "active":
            await self.update_status(ws.id, "missing")
        return False