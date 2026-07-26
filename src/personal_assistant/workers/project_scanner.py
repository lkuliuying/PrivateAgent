"""项目扫描后台任务：遍历目录 → 全量替换 project_files → 更新扫描时间 → 写活动流。

照 workers/importer.py 模式：用独立 db session（后台任务跨越请求生命周期），
同步遍历用 asyncio.to_thread 隔离，全程经 ActivityService.sync_system 写活动流。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from ..core.activities import ActivityService
from ..core.db import async_session_factory
from ..core.projects import walk_project_files
from ..core.repo_projects import ProjectFileRepository, ProjectRepository
from ..core.timeutil import utcnow
from ..logging_setup import get_logger

logger = get_logger(__name__)
CANCELLED_RETRY_ERROR = "任务因应用关闭而中断，可重试"


async def _walk_files(root: str) -> list[dict]:
    """Keep the blocking filesystem boundary explicit and independently testable."""
    return await asyncio.to_thread(walk_project_files, Path(root))


async def scan_project(project_id: int) -> int:
    """扫描项目并全量重建文件索引。返回入库文件数。

    失败时记录活动（failed），不抛出（后台任务）。
    """
    async with async_session_factory() as db:
        project = await ProjectRepository(db).get(project_id)
        project_name = project.name if project else f"项目#{project_id}"
        root = project.root_path if project else None

    if project is None or root is None:
        logger.warning("scan: project not found", project_id=project_id)
        return 0

    try:
        await _sync(project_id, project_name, "running", {"root": root})
        logger.info("project scan start", project_id=project_id, root=root)
        files = await _walk_files(root)
        async with async_session_factory() as db:
            file_repo = ProjectFileRepository(db)
            count = await file_repo.replace_all_and_mark(
                project_id, files, utcnow()
            )
        await _sync(project_id, project_name, "succeeded", {"root": root, "files": count})
        logger.info("project scan done", project_id=project_id, files=count)
        return count
    except asyncio.CancelledError:
        logger.warning("project scan cancelled during shutdown", project_id=project_id)
        try:
            await _sync(
                project_id,
                project_name,
                "failed",
                {"root": root},
                error_message=CANCELLED_RETRY_ERROR,
            )
        except Exception:  # noqa: BLE001 - preserve the original cancellation
            logger.exception(
                "project scan cancellation activity update failed",
                project_id=project_id,
            )
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("project scan failed", project_id=project_id)
        await _sync(
            project_id,
            project_name,
            "failed",
            {"root": root},
            error_message=str(e)[:1000],
        )
        return 0


async def _sync(
    project_id: int,
    project_name: str,
    status: str,
    detail: dict,
    *,
    error_message: str | None = None,
) -> None:
    """把扫描状态写入活动流（ref_type='project_scan'+ref_id=project_id upsert）。"""
    async with async_session_factory() as db:
        await ActivityService(db).sync_system(
            ref_type="project_scan",
            ref_id=project_id,
            title=f"扫描项目：{project_name}",
            act_status=status,
            detail=detail,
            error_message=error_message,
        )
