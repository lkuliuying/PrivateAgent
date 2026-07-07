"""补丁集与项目命令配置异步仓储层（第四阶段 M4）。

照 core/repo.py 模式：每仓储持 AsyncSession，方法内自带 commit。
PatchSet.files 用 selectinload 预取，避免 async 下 lazy-load 触发 MissingGreenlet。
project_command_profiles / patch_sets 的 project_id / task_id 为跨域软引用，不建外键。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import PatchFile, PatchSet, ProjectCommandProfile


class ProjectCommandProfileRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        project_id: int,
        name: str,
        command_json: dict,
        kind: str,
        timeout_seconds: int = 120,
        enabled: bool = True,
    ) -> ProjectCommandProfile:
        p = ProjectCommandProfile(
            project_id=project_id,
            name=name,
            command_json=command_json,
            kind=kind,
            timeout_seconds=timeout_seconds,
            enabled=enabled,
        )
        self.db.add(p)
        await self.db.commit()
        await self.db.refresh(p)
        return p

    async def get(self, profile_id: int) -> Optional[ProjectCommandProfile]:
        return await self.db.get(ProjectCommandProfile, profile_id)

    async def list_by_project(
        self, project_id: int, kind: str | None = None, enabled: bool | None = None
    ) -> list[ProjectCommandProfile]:
        stmt = select(ProjectCommandProfile).where(
            ProjectCommandProfile.project_id == project_id
        )
        if kind is not None:
            stmt = stmt.where(ProjectCommandProfile.kind == kind)
        if enabled is not None:
            stmt = stmt.where(ProjectCommandProfile.enabled == enabled)
        stmt = stmt.order_by(ProjectCommandProfile.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        profile_id: int,
        *,
        name: str | None = None,
        command_json: dict | None = None,
        kind: str | None = None,
        timeout_seconds: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        values: dict = {}
        if name is not None:
            values["name"] = name
        if command_json is not None:
            values["command_json"] = command_json
        if kind is not None:
            values["kind"] = kind
        if timeout_seconds is not None:
            values["timeout_seconds"] = timeout_seconds
        if enabled is not None:
            values["enabled"] = enabled
        if not values:
            return
        await self.db.execute(
            update(ProjectCommandProfile)
            .where(ProjectCommandProfile.id == profile_id)
            .values(**values)
        )
        await self.db.commit()

    async def delete(self, profile_id: int) -> None:
        p = await self.get(profile_id)
        if p is not None:
            await self.db.delete(p)
            await self.db.commit()


class PatchSetRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        project_id: int,
        title: str,
        files: list[dict],
        task_id: int | None = None,
    ) -> PatchSet:
        """创建补丁集及其文件。files 每项含 rel_path/old_sha256/new_sha256/
        diff_text/old_content/new_content（由服务层算好）。"""
        ps = PatchSet(project_id=project_id, title=title, task_id=task_id)
        ps.files = [
            PatchFile(
                rel_path=f["rel_path"],
                old_sha256=f.get("old_sha256"),
                new_sha256=f.get("new_sha256"),
                diff_text=f["diff_text"],
                old_content=f.get("old_content"),
                new_content=f["new_content"],
                status="draft",
            )
            for f in files
        ]
        self.db.add(ps)
        await self.db.commit()
        # 用 get（selectinload files）返回，避免响应序列化时 files lazy-load 触发 MissingGreenlet
        fresh = await self.get(ps.id)
        assert fresh is not None
        return fresh

    async def get(self, patch_set_id: int) -> Optional[PatchSet]:
        stmt = (
            select(PatchSet)
            .options(selectinload(PatchSet.files))
            .where(PatchSet.id == patch_set_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_project(self, project_id: int) -> list[PatchSet]:
        stmt = (
            select(PatchSet)
            .options(selectinload(PatchSet.files))
            .where(PatchSet.project_id == project_id)
            .order_by(PatchSet.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_status(self, patch_set_id: int, status: str) -> None:
        await self.db.execute(
            update(PatchSet).where(PatchSet.id == patch_set_id).values(status=status)
        )
        await self.db.commit()

    async def update_file_statuses(self, patch_set_id: int, status: str) -> None:
        await self.db.execute(
            update(PatchFile)
            .where(PatchFile.patch_set_id == patch_set_id)
            .values(status=status)
        )
        await self.db.commit()
