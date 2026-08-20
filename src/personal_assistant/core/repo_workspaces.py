"""v0.6.0 ProjectWorkspace 异步仓储层。

每个仓储持 AsyncSession，方法内自带 commit。
路径规范化（C0 契约 §4.1）：

1. 先解析绝对路径并规范分隔符（``\\`` → ``/``）。
2. Windows 用大小写不敏感形式计算 ``root_path_sha256``，展示仍保留规范化原路径。
3. 禁止 ``..``、未解析环境变量和空路径进入数据库。
4. 创建 run 时重新验证路径存在、位于项目授权范围且 workspace/project 匹配。

``normalize_root_path_sha256`` 与迁移 0027 的回填哈希完全一致，保证
迁移中断后重跑（幂等补建）不会产生路径哈希漂移。
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ProjectWorkspace


def normalize_root_path(root_path: str) -> str:
    """规范化绝对路径：展开用户目录、禁止相对路径/``..``/环境变量残留。"""
    raw = os.path.expanduser(root_path).strip()
    if not raw:
        raise ValueError("root_path must not be empty")
    # Windows 绝对路径（盘符）与 POSIX 绝对路径（/ 开头）都接受；
    # 相对路径与 ~user 之外的未展开形式一律拒绝。
    if not (os.path.isabs(raw) or raw.startswith("/")):
        raise ValueError("root_path must be an absolute path")
    if any(part == ".." for part in raw.replace("\\", "/").split("/")):
        raise ValueError("root_path must not contain '..'")
    if "$" in raw or "%" in raw:
        raise ValueError("root_path must not contain unresolved environment variables")
    return raw.replace("\\", "/").rstrip("/") or "/"


def normalize_root_path_sha256(root_path: str) -> str:
    """规范化路径哈希：Windows 大小写不敏感（与迁移 0027 回填逻辑一致）。"""
    normalized = normalize_root_path(root_path)
    return hashlib.sha256(normalized.casefold().encode("utf-8")).hexdigest()


class ProjectWorkspaceRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        project_id: int,
        root_path: str,
        kind: str = "root",
        branch_name: str | None = None,
        head_sha: str | None = None,
        status: str = "active",
    ) -> ProjectWorkspace:
        normalized = normalize_root_path(root_path)
        ws = ProjectWorkspace(
            project_id=project_id,
            root_path=normalized,
            root_path_sha256=normalize_root_path_sha256(normalized),
            kind=kind,
            branch_name=branch_name,
            head_sha=head_sha,
            status=status,
        )
        self.db.add(ws)
        await self.db.commit()
        await self.db.refresh(ws)
        return ws

    async def get(self, workspace_id: int) -> Optional[ProjectWorkspace]:
        return await self.db.get(ProjectWorkspace, workspace_id)

    async def get_by_project_and_kind(
        self, project_id: int, kind: str = "root"
    ) -> Optional[ProjectWorkspace]:
        """按 project_id + kind 查询唯一 workspace（幂等补建用）。"""
        stmt = select(ProjectWorkspace).where(
            ProjectWorkspace.project_id == project_id,
            ProjectWorkspace.kind == kind,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_project(
        self, project_id: int
    ) -> list[ProjectWorkspace]:
        """列出项目的所有 workspace。"""
        stmt = (
            select(ProjectWorkspace)
            .where(ProjectWorkspace.project_id == project_id)
            .order_by(ProjectWorkspace.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_active(self) -> list[ProjectWorkspace]:
        """列出所有 active workspace。"""
        stmt = select(ProjectWorkspace).where(
            ProjectWorkspace.status == "active"
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self, workspace_id: int, status: str
    ) -> None:
        await self.db.execute(
            update(ProjectWorkspace)
            .where(ProjectWorkspace.id == workspace_id)
            .values(status=status)
        )
        await self.db.commit()

    async def touch_last_used(
        self, workspace_id: int, at: datetime | None = None
    ) -> None:
        await self.db.execute(
            update(ProjectWorkspace)
            .where(ProjectWorkspace.id == workspace_id)
            .values(last_used_at=at or datetime.now(timezone.utc).replace(tzinfo=None))
        )
        await self.db.commit()

    async def ensure_root_workspace(
        self, project_id: int, root_path: str
    ) -> ProjectWorkspace:
        """幂等确保 project 有 root workspace。

        并发安全：先查后插，``(project_id, root_path_sha256)`` 唯一键冲突时
        回滚并重新读取已有记录（迁移中断/并发重放均不会重复创建）。
        """
        existing = await self.get_by_project_and_kind(
            project_id, kind="root"
        )
        if existing is not None:
            return existing
        try:
            return await self.create(
                project_id=project_id,
                root_path=root_path,
                kind="root",
            )
        except IntegrityError:
            await self.db.rollback()
            existing = await self.get_by_project_and_kind(
                project_id, kind="root"
            )
            if existing is not None:
                return existing
            raise
