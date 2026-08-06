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

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from ..core import approvals
from ..core.activities import ActivityService
from ..core.compatibility import compatibility_telemetry
from ..core.db import get_session
from ..core.provider import OllamaProvider
from ..core.repo_tools import ToolCallRepository
from ..core.settings import SettingsService
from ..core.tool_adapter import READ_ONLY_AGENT_TOOL_NAMES
from ..core.tools import (
    ToolError,
    ToolExecutor,
    ToolRegistry,
    default_registry,
    plan_tool_call,
)
from ..logging_setup import get_logger

router = APIRouter(tags=["tools"])
logger = get_logger(__name__)
_DEPRECATION_HEADERS = {"Deprecation": "true"}


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


def _runtime_tool_ownership_active() -> bool:
    return bool(
        cfg.chat_agent_runtime_enabled
        and cfg.agent_run_read_only_tools_enabled
    )


def _legacy_planner_registry() -> ToolRegistry:
    """Hide tools already owned by native Runtime from the text-JSON planner."""

    if not _runtime_tool_ownership_active():
        return default_registry
    registry = ToolRegistry()
    for tool in default_registry.list():
        if tool.name not in READ_ONLY_AGENT_TOOL_NAMES:
            registry.register(tool)
    return registry


def _record_legacy_tool_action(path: str, outcome: str) -> None:
    _record_compatibility(path, "legacy_tool_call", outcome)


def _record_compatibility(path: str, mode: str, outcome: str) -> None:
    compatibility_telemetry.record(
        path=path,
        mode=mode,
        outcome=outcome,
    )
    logger.info(
        "deprecated compatibility path invoked",
        compatibility_path=path,
        compatibility_mode=mode,
        compatibility_outcome=outcome,
    )


def _legacy_tool_http_error(status_code: int, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers=_DEPRECATION_HEADERS,
    )


# ---- Routes ----

@router.get("/tools", response_model=list[ToolDefinitionOut])
async def list_tools(response: Response) -> list[dict[str, Any]]:
    response.headers.update(_DEPRECATION_HEADERS)
    result = [
        {
            "name": t.name,
            "description": t.description,
            "risk_level": t.risk_level,
            "input_schema": t.input_schema,
            "output_schema": t.output_schema,
        }
        for t in default_registry.list()
    ]
    _record_compatibility("/tools", "legacy_registry", "returned")
    return result


@router.post("/tools/plan", response_model=ToolPlanResponse)
async def plan(
    req: ToolPlanRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
):
    response.headers["Deprecation"] = "true"
    mode = (
        "runtime_filtered" if _runtime_tool_ownership_active() else "legacy_full"
    )
    try:
        provider = await _provider(db)
        tc = await plan_tool_call(
            provider,
            db,
            req.session_id,
            req.message,
            registry=_legacy_planner_registry(),
        )
    except Exception as exc:
        compatibility_telemetry.record(
            path="/tools/plan", mode=mode, outcome="error"
        )
        if isinstance(exc, HTTPException):
            exc.headers = {**(exc.headers or {}), **_DEPRECATION_HEADERS}
        logger.warning(
            "deprecated compatibility path failed",
            compatibility_path="/tools/plan",
            compatibility_mode=mode,
            error_type=type(exc).__name__,
        )
        raise
    outcome = "planned" if tc is not None else "not_planned"
    compatibility_telemetry.record(
        path="/tools/plan", mode=mode, outcome=outcome
    )
    logger.info(
        "deprecated compatibility path invoked",
        compatibility_path="/tools/plan",
        compatibility_mode=mode,
        compatibility_outcome=outcome,
    )
    return ToolPlanResponse(tool_call=tc)


@router.post("/tool-calls/{tool_call_id}/approve", response_model=ToolCallOut)
async def approve(
    tool_call_id: int,
    response: Response,
    db: AsyncSession = Depends(get_session),
):
    path = "/tool-calls/:id/approve"
    response.headers.update(_DEPRECATION_HEADERS)
    repo = ToolCallRepository(db)
    tc = await repo.get(tool_call_id)
    if tc is None:
        _record_legacy_tool_action(path, "not_found")
        raise _legacy_tool_http_error(404, "工具调用不存在")
    try:
        approvals.assert_transition(tc.status, "approved")
    except approvals.ApprovalError as e:
        _record_legacy_tool_action(path, "conflict")
        raise _legacy_tool_http_error(409, str(e))
    try:
        result = await ToolExecutor(db).execute_tool_call(tool_call_id)
    except approvals.ApprovalError as e:
        # 原子 claim 失败：已被并发请求处理
        _record_legacy_tool_action(path, "conflict")
        raise _legacy_tool_http_error(409, str(e))
    except ToolError as e:
        # 执行失败已记录到 tool_calls（status=failed），这里返回 400 供前端提示
        _record_legacy_tool_action(path, "failed")
        raise _legacy_tool_http_error(400, str(e))
    _record_legacy_tool_action(path, "succeeded")
    return result


@router.post("/tool-calls/{tool_call_id}/reject", response_model=ToolCallOut)
async def reject(
    tool_call_id: int,
    response: Response,
    db: AsyncSession = Depends(get_session),
):
    path = "/tool-calls/:id/reject"
    response.headers.update(_DEPRECATION_HEADERS)
    repo = ToolCallRepository(db)
    tc = await repo.get(tool_call_id)
    if tc is None:
        _record_legacy_tool_action(path, "not_found")
        raise _legacy_tool_http_error(404, "工具调用不存在")
    try:
        approvals.assert_transition(tc.status, "rejected")
    except approvals.ApprovalError as e:
        _record_legacy_tool_action(path, "conflict")
        raise _legacy_tool_http_error(409, str(e))
    # 原子占用 pending_approval -> rejected，防与 approve 并发时 check-then-set 竞争。
    if not await repo.claim(
        tool_call_id, from_status="pending_approval", to_status="rejected"
    ):
        _record_legacy_tool_action(path, "conflict")
        raise _legacy_tool_http_error(409, "工具调用已被处理或状态已变更")
    tc = await repo.get_fresh(tool_call_id)
    assert tc is not None
    await ActivityService(db).sync_tool_call(tc)
    _record_legacy_tool_action(path, "rejected")
    return tc


@router.get("/tool-calls", response_model=list[ToolCallOut])
async def list_tool_calls(
    response: Response,
    session_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
):
    response.headers.update(_DEPRECATION_HEADERS)
    repo = ToolCallRepository(db)
    mode = "session_filtered" if session_id is not None else "all"
    if session_id is not None:
        result = await repo.list_by_session(session_id)
    else:
        result = await repo.list()
    _record_compatibility("/tool-calls", mode, "returned")
    return result


@router.get("/tool-calls/{tool_call_id}", response_model=ToolCallOut)
async def get_tool_call(
    tool_call_id: int,
    response: Response,
    db: AsyncSession = Depends(get_session),
):
    response.headers.update(_DEPRECATION_HEADERS)
    tc = await ToolCallRepository(db).get(tool_call_id)
    if tc is None:
        _record_legacy_tool_action("/tool-calls/:id", "not_found")
        raise _legacy_tool_http_error(404, "工具调用不存在")
    _record_legacy_tool_action("/tool-calls/:id", "found")
    return tc
