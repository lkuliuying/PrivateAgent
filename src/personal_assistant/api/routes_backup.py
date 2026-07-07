"""第四阶段 M6：备份、恢复预览、导出与清理路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.backup import BackupService
from ..core.db import get_session
from ..core.learning import LearningNotFound, LearningService
from ..core.models import Activity, AgentEvidence
from ..core.tasks import AgentTaskService, TaskNotFound

router = APIRouter(tags=["backup"])


class RestoreRequest(BaseModel):
    path: str


@router.get("/backup")
async def list_backups(db: AsyncSession = Depends(get_session)) -> dict:
    return await BackupService(db).list()


@router.post("/backup/export")
async def export_backup(db: AsyncSession = Depends(get_session)) -> dict:
    return await BackupService(db).export()


@router.post("/backup/restore/preview")
async def restore_preview(
    req: RestoreRequest, db: AsyncSession = Depends(get_session)
) -> dict:
    try:
        return await BackupService(db).restore_preview(req.path)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@router.post("/backup/restore")
async def restore_backup(
    req: RestoreRequest, db: AsyncSession = Depends(get_session)
) -> dict:
    try:
        return await BackupService(db).restore(req.path)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@router.post("/exports/learning-topic/{topic_id}")
async def export_learning_topic(
    topic_id: int, db: AsyncSession = Depends(get_session)
) -> dict:
    svc = LearningService(db)
    try:
        topic = await svc.get_topic(topic_id)
        dashboard = await svc.topic_dashboard(topic_id)
        weak = await svc.weak_points(topic_id)
        wrong = await svc.wrong_answers(topic_id)
        report = await svc.weekly_report(topic_id)
    except LearningNotFound as e:
        raise HTTPException(404, str(e))
    md = [
        f"# {topic.title}",
        "",
        topic.description or "",
        "",
        "## 学习概览",
        f"- 到期复习：{dashboard['due_today']}",
        f"- 总卡片：{dashboard['total_cards']}",
        f"- 近 7 天复习：{dashboard['reviews_7d']}",
        "",
        "## 薄弱点",
        *(f"- {w['title']}" for w in weak[:20]),
        "",
        "## 错题",
        *(f"- {w['question']}" for w in wrong[:20]),
        "",
        "## 周报",
        report["report_md"],
    ]
    return {"topic_id": topic_id, "markdown": "\n".join(md)}


@router.post("/exports/task/{task_id}")
async def export_task(task_id: int, db: AsyncSession = Depends(get_session)) -> dict:
    try:
        task = await AgentTaskService(db).get(task_id)
    except TaskNotFound as e:
        raise HTTPException(404, str(e))
    if task.final_report_md:
        markdown = task.final_report_md
    else:
        evidence = await AgentTaskService(db).list_evidence(task_id)
        lines = [f"# {task.title}", "", task.goal or "", ""]
        for ev in evidence:
            lines += [f"## {ev.title}", ev.content_md, ""]
        markdown = "\n".join(lines).strip() + "\n"
    return {"task_id": task_id, "markdown": markdown}


@router.post("/maintenance/cleanup")
async def cleanup(db: AsyncSession = Depends(get_session)) -> dict:
    """轻量清理：删除孤立任务证据和过期活动之外的危险数据不自动处理。"""
    # 当前阶段只提供可审计的轻量清理入口，避免误删用户知识库/任务历史。
    result = await db.execute(
        delete(AgentEvidence).where(AgentEvidence.task_id.is_(None))
    )
    await db.execute(delete(Activity).where(Activity.status == "cancelled"))
    await db.commit()
    return {"deleted_orphan_evidence": result.rowcount or 0}
