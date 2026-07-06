"""Coding helper routes for phase3 M5."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.activities import ActivityService
from ..core.code_tools import propose_patch
from ..core.db import get_session
from ..core.models import ToolCall
from ..core.permissions import PermissionError_
from ..core.repo_tools import ToolCallRepository
from ..core.tools import default_registry

router = APIRouter(tags=["coding"])


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


class CodingPlanRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    goal: str = Field(min_length=1)
    project_id: int | None = None


class CodingPlanResponse(BaseModel):
    title: str
    goal: str
    steps: list[dict]


class PatchPreviewRequest(BaseModel):
    project_id: int
    rel_path: str = Field(min_length=1)
    new_content: str
    create: bool = False


class PatchApplyRequest(PatchPreviewRequest):
    session_id: int | None = None
    expected_old_sha256: str | None = None


class PatchApplyResponse(BaseModel):
    preview: dict
    tool_call: ToolCallOut


class CommandRunRequest(BaseModel):
    project_id: int
    command: str | list[str]
    timeout: float = 120
    session_id: int | None = None


async def _create_tool_call(
    db: AsyncSession,
    *,
    session_id: int | None,
    tool_name: str,
    input_json: dict,
) -> ToolCall:
    tool = default_registry.get(tool_name)
    if tool is None:
        raise HTTPException(500, f"工具未注册: {tool_name}")
    tc = await ToolCallRepository(db).create(
        session_id=session_id,
        tool_name=tool.name,
        risk_level=tool.risk_level,
        input_json=input_json,
    )
    await ActivityService(db).sync_tool_call(tc)
    return tc


@router.post("/coding/plan", response_model=CodingPlanResponse)
async def plan_coding_task(req: CodingPlanRequest):
    """Generate a conservative editable coding plan.

    This is deterministic by design: the user can inspect or edit the plan before
    creating a real agent task.
    """
    base: dict = {"project_id": req.project_id} if req.project_id else {}
    steps = [
        {
            "title": "检查项目 git 状态",
            "tool_name": "get_git_status",
            "input_json": base,
        },
        {
            "title": "运行项目验证命令",
            "tool_name": "run_whitelisted_command",
            "input_json": {**base, "command": "pytest -q"},
        },
        {
            "title": "查看修改 diff",
            "tool_name": "get_git_diff",
            "input_json": base,
        },
    ]
    return CodingPlanResponse(title=req.title, goal=req.goal, steps=steps)


@router.post("/coding/patch/preview")
async def preview_patch(req: PatchPreviewRequest, db: AsyncSession = Depends(get_session)):
    try:
        return await propose_patch(
            db,
            req.project_id,
            req.rel_path,
            req.new_content,
            create=req.create,
        )
    except (PermissionError_, FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e))


@router.post("/coding/patch/apply", response_model=PatchApplyResponse)
async def request_patch_apply(
    req: PatchApplyRequest, db: AsyncSession = Depends(get_session)
):
    try:
        preview = await propose_patch(
            db,
            req.project_id,
            req.rel_path,
            req.new_content,
            create=req.create,
        )
    except (PermissionError_, FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e))
    expected = req.expected_old_sha256 or preview["old_sha256"]
    tc = await _create_tool_call(
        db,
        session_id=req.session_id,
        tool_name="apply_patch_to_workspace",
        input_json={
            "project_id": req.project_id,
            "rel_path": req.rel_path,
            "new_content": req.new_content,
            "expected_old_sha256": expected,
            "create": req.create,
        },
    )
    return PatchApplyResponse(preview=preview, tool_call=tc)


@router.post("/coding/commands/run", response_model=ToolCallOut)
async def request_command_run(
    req: CommandRunRequest, db: AsyncSession = Depends(get_session)
):
    return await _create_tool_call(
        db,
        session_id=req.session_id,
        tool_name="run_whitelisted_command",
        input_json={
            "project_id": req.project_id,
            "command": req.command,
            "timeout": req.timeout,
        },
    )
