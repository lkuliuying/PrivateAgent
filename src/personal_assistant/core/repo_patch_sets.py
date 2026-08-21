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
        profile_version: int = 1,
        cwd_rel: str | None = None,
        env_allowlist: list | None = None,
        allow_network: bool = False,
        result_parser: str | None = None,
        risk_level: str = "confirm",
        capability: str | None = None,
        max_output_bytes: int | None = None,
        description: str | None = None,
    ) -> ProjectCommandProfile:
        p = ProjectCommandProfile(
            project_id=project_id,
            name=name,
            command_json=command_json,
            kind=kind,
            timeout_seconds=timeout_seconds,
            enabled=enabled,
            # v0.7.0 E0 §6：版本化扩展字段（全部 additive，旧数据回填默认值）
            profile_version=profile_version,
            cwd_rel=cwd_rel,
            env_allowlist=env_allowlist,
            allow_network=allow_network,
            result_parser=result_parser,
            risk_level=risk_level,
            capability=capability,
            max_output_bytes=max_output_bytes,
            description=description,
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
        # E0 §6：版本化扩展字段（None 不更新；profile_version 由 service 递增）
        profile_version: int | None = None,
        cwd_rel: str | None = None,
        env_allowlist: list | None = None,
        allow_network: bool | None = None,
        result_parser: str | None = None,
        risk_level: str | None = None,
        capability: str | None = None,
        max_output_bytes: int | None = None,
        description: str | None = None,
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
        if profile_version is not None:
            values["profile_version"] = profile_version
        if cwd_rel is not None:
            values["cwd_rel"] = cwd_rel
        if env_allowlist is not None:
            values["env_allowlist"] = env_allowlist
        if allow_network is not None:
            values["allow_network"] = allow_network
        if result_parser is not None:
            values["result_parser"] = result_parser
        if risk_level is not None:
            values["risk_level"] = risk_level
        if capability is not None:
            values["capability"] = capability
        if max_output_bytes is not None:
            values["max_output_bytes"] = max_output_bytes
        if description is not None:
            values["description"] = description
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
