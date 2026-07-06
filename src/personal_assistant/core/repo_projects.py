"""项目与项目文件索引的异步仓储层。

照 core/repo.py 模式：每仓储持 AsyncSession，方法内自带 commit。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Project, ProjectFile


class ProjectRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        name: str,
        root_path: str,
        language: str | None = None,
        framework: str | None = None,
    ) -> Project:
        project = Project(
            name=name,
            root_path=root_path,
            language=language,
            framework=framework,
            status="active",
        )
        self.db.add(project)
        await self.db.commit()
        await self.db.refresh(project)
        return project

    async def get(self, project_id: int) -> Optional[Project]:
        return await self.db.get(Project, project_id)

    async def get_by_path(self, root_path: str) -> Optional[Project]:
        """按 root_path 去重查询（authorize 时用）。"""
        stmt = select(Project).where(Project.root_path == root_path)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list(self) -> list[Project]:
        """活跃项目优先，按创建时间倒序。"""
        stmt = select(Project).order_by(
            Project.status.asc(), Project.created_at.desc()
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_scan_time(self, project_id: int, last_scanned_at: datetime) -> None:
        await self.db.execute(
            update(Project)
            .where(Project.id == project_id)
            .values(last_scanned_at=last_scanned_at)
        )
        await self.db.commit()

    async def archive(self, project_id: int) -> None:
        await self.db.execute(
            update(Project).where(Project.id == project_id).values(status="archived")
        )
        await self.db.commit()


class ProjectFileRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def replace_all(self, project_id: int, files: list[dict]) -> int:
        """全量替换某项目的文件索引：先删旧后批量插。返回入库条数。

        files: [{rel_path, language, size_bytes, content_hash, mtime, is_binary}, ...]
        """
        await self.db.execute(
            delete(ProjectFile).where(ProjectFile.project_id == project_id)
        )
        objs = [
            ProjectFile(
                project_id=project_id,
                rel_path=f["rel_path"],
                language=f.get("language"),
                size_bytes=f.get("size_bytes"),
                content_hash=f.get("content_hash"),
                mtime=f.get("mtime"),
                is_binary=f.get("is_binary", False),
                indexed_at=f.get("indexed_at"),
            )
            for f in files
        ]
        self.db.add_all(objs)
        await self.db.commit()
        return len(objs)

    async def replace_all_and_mark(
        self, project_id: int, files: list[dict], scanned_at: datetime
    ) -> int:
        """原子地全量替换文件索引并更新 last_scanned_at（单事务）。

        避免分别提交时进程崩溃导致「新文件 + 旧扫描时间」不一致。
        """
        await self.db.execute(
            delete(ProjectFile).where(ProjectFile.project_id == project_id)
        )
        objs = [
            ProjectFile(
                project_id=project_id,
                rel_path=f["rel_path"],
                language=f.get("language"),
                size_bytes=f.get("size_bytes"),
                content_hash=f.get("content_hash"),
                mtime=f.get("mtime"),
                is_binary=f.get("is_binary", False),
                indexed_at=f.get("indexed_at"),
            )
            for f in files
        ]
        self.db.add_all(objs)
        await self.db.execute(
            update(Project)
            .where(Project.id == project_id)
            .values(last_scanned_at=scanned_at)
        )
        await self.db.commit()
        return len(objs)

    async def list_by_project(self, project_id: int) -> list[ProjectFile]:
        stmt = (
            select(ProjectFile)
            .where(ProjectFile.project_id == project_id)
            .order_by(ProjectFile.rel_path.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def search_by_name(
        self, project_id: int, query: str, limit: int = 50
    ) -> list[ProjectFile]:
        """按相对路径/文件名模糊匹配（转义 LIKE 元字符 % _ \\）。"""
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = (
            select(ProjectFile)
            .where(
                ProjectFile.project_id == project_id,
                ProjectFile.rel_path.like(f"%{escaped}%", escape="\\"),
            )
            .order_by(ProjectFile.rel_path.asc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_rel_path(
        self, project_id: int, rel_path: str
    ) -> Optional[ProjectFile]:
        stmt = select(ProjectFile).where(
            ProjectFile.project_id == project_id,
            ProjectFile.rel_path == rel_path,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def count(self, project_id: int) -> int:
        from sqlalchemy import func

        stmt = select(func.count()).select_from(ProjectFile).where(
            ProjectFile.project_id == project_id
        )
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)
