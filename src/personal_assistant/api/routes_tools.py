"""工具调用路由。

- GET  /tools                  可用工具列表
- POST /tools/plan             LLM 规划：判断是否需工具，建 pending_approval 记录
- POST /tool-calls/{id}/approve 批准并执行
- POST /tool-calls/{id}/reject  拒绝（不执行）
- GET  /tool-calls             工具调用记录（可按 session 过滤）
- GET  /tool-calls/{id}        单条记录
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import approvals
from ..core.activities import ActivityService
from ..core.db import get_session
from ..core.provider import OllamaProvider
from ..core.repo_tools import ToolCallRepository
from ..core.settings import SettingsService
from ..core.tools import ToolError, ToolExecutor, default_registry, plan_tool_call

router = APIRouter(tags=["tools"])


# ---- Schemas ----

class ToolDefinitionOut(BaseModel):
    name: str
    description: str
    risk_level: str
    input_schema: dict
    output_schema: dict


class ToolCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: int | None
    task_id: int | None
    step_id: int | None
    tool_name: str
    risk_level: str
    status: str
    input_json: dict | None
    output_json: dict | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ToolPlanRequest(BaseModel):
    session_id: int
    message: str


class ToolPlanResponse(BaseModel):
    tool_call: ToolCallOut | None


# ---- Helpers ----

async def _provider(db: AsyncSession) -> OllamaProvider:
    """从 settings 构造 Provider（与 ChatService 一致，支持运行时调整）。"""
    s = await SettingsService(db).get_all()
    return OllamaProvider(
        llm_model=s["llm_model"],
        temperature=float(s["llm_temperature"]),
        context_length=int(s["llm_context_length"]),
    )


# ---- Routes ----

@router.get("/tools", response_model=list[ToolDefinitionOut])
async def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "risk_level": t.risk_level,
            "input_schema": t.input_schema,
            "output_schema": t.output_schema,
        }
        for t in default_registry.list()
    ]


@router.post("/tools/plan", response_model=ToolPlanResponse)
async def plan(req: ToolPlanRequest, db: AsyncSession = Depends(get_session)):
    provider = await _provider(db)
    tc = await plan_tool_call(provider, db, req.session_id, req.message)
    return ToolPlanResponse(tool_call=tc)


@router.post("/tool-calls/{tool_call_id}/approve", response_model=ToolCallOut)
async def approve(tool_call_id: int, db: AsyncSession = Depends(get_session)):
    repo = ToolCallRepository(db)
    tc = await repo.get(tool_call_id)
    if tc is None:
        raise HTTPException(404, "工具调用不存在")
    try:
        approvals.assert_transition(tc.status, "approved")
    except approvals.ApprovalError as e:
        raise HTTPException(409, str(e))
    try:
        return await ToolExecutor(db).execute_tool_call(tool_call_id)
    except approvals.ApprovalError as e:
        # 原子 claim 失败：已被并发请求处理
        raise HTTPException(409, str(e))
    except ToolError as e:
        # 执行失败已记录到 tool_calls（status=failed），这里返回 400 供前端提示
        raise HTTPException(400, str(e))


@router.post("/tool-calls/{tool_call_id}/reject", response_model=ToolCallOut)
async def reject(tool_call_id: int, db: AsyncSession = Depends(get_session)):
    repo = ToolCallRepository(db)
    tc = await repo.get(tool_call_id)
    if tc is None:
        raise HTTPException(404, "工具调用不存在")
    try:
        approvals.assert_transition(tc.status, "rejected")
    except approvals.ApprovalError as e:
        raise HTTPException(409, str(e))
    # 原子占用 pending_approval -> rejected，防与 approve 并发时 check-then-set 竞争。
    if not await repo.claim(
        tool_call_id, from_status="pending_approval", to_status="rejected"
    ):
        raise HTTPException(409, "工具调用已被处理或状态已变更")
    tc = await repo.get_fresh(tool_call_id)
    assert tc is not None
    await ActivityService(db).sync_tool_call(tc)
    return tc


@router.get("/tool-calls", response_model=list[ToolCallOut])
async def list_tool_calls(
    session_id: int | None = Query(default=None), db: AsyncSession = Depends(get_session)
):
    repo = ToolCallRepository(db)
    if session_id is not None:
        return await repo.list_by_session(session_id)
    return await repo.list()


@router.get("/tool-calls/{tool_call_id}", response_model=ToolCallOut)
async def get_tool_call(tool_call_id: int, db: AsyncSession = Depends(get_session)):
    tc = await ToolCallRepository(db).get(tool_call_id)
    if tc is None:
        raise HTTPException(404, "工具调用不存在")
    return tc
