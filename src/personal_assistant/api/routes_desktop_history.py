"""仅导出当前登录用户的历史；不读取配置、密钥、授权令牌或生产日志。"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from private_agent_core.history import (
    FIELDS,
    FORMAT,
    MAX_RECORDS,
    encode_archive,
    validate_archive,
)

from ..core import models
from ..core.db import get_session
from .auth_dependencies import current_principal

router = APIRouter(prefix="/desktop/history", tags=["desktop-history"])
ENTITIES = {
    "projects": models.Project, "workspaces": models.ProjectWorkspace,
    "sessions": models.ChatSession, "messages": models.Message, "runs": models.AgentRun,
    "events": models.AgentRunEvent, "approvals": models.ToolApproval,
    "executions": models.AgentToolExecution, "run_steps": models.RunStep,
    "agent_tasks": models.AgentTask, "agent_task_steps": models.AgentTaskStep, "agent_evidence": models.AgentEvidence,
}


async def export_history(db: AsyncSession, owner_id: int, authority: str) -> bytes:
    records = {}
    remaining = MAX_RECORDS
    for kind, entity in ENTITIES.items():
        # 显式列白名单：即使以后模型新增凭据字段，也不会自动进入导出结果。
        columns = [getattr(entity, field) for field in FIELDS[kind] if hasattr(entity, field)]
        query = select(*columns).where(entity.owner_user_id == owner_id).order_by(entity.id).limit(remaining + 1)
        rows = [dict(row) for row in (await db.execute(query)).mappings().all()]
        remaining -= len(rows)
        if remaining < 0:
            raise ValueError("历史记录超过 50000 条，请分批迁移")
        records[kind] = rows
    archive = {"format": FORMAT, "source": {"authority": authority, "owner_id": owner_id}, "records": records}
    # 日期和数值先转为交换格式，再检查所有父子关系；未归属账号的旧记录不猜测所有者。
    import json
    encoded = encode_archive(archive)
    validate_archive(json.loads(encoded), authority=authority, owner_id=owner_id)
    return encoded


@router.get("/export")
async def download_history(request: Request, db: AsyncSession = Depends(get_session)):
    principal = current_principal(request)
    try:
        content = await export_history(db, principal.user_id, str(request.base_url).rstrip("/"))
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    return Response(content, media_type="application/json", headers={"Cache-Control": "no-store",
                    "Content-Disposition": 'attachment; filename="privateagent-history.json"'})
