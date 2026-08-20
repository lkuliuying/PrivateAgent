"""v0.6.0 RunPlan API 路由（C0 契约 §6/§7）。

``POST /agent-runs/{run_id}/plan`` 接受 safe 工具 ``update_run_plan`` 的输入格式：
``expected_plan_version`` + ``items``（1..32 项）。错误响应携带冻结错误码
（§9）：``plan_version_conflict``(409) / ``plan_transition_invalid``(422)。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from ..core.db import get_session
from ..core.run_plan import (
    PlanTransitionInvalid,
    PlanVersionConflict,
    RunPlanService,
)

router = APIRouter(prefix="/agent-runs", tags=["run-plan"])


class PlanItemIn(BaseModel):
    item_key: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    detail: str | None = Field(default=None, max_length=4000)
    status: str = Field(default="pending", max_length=32)


class PlanItemOut(BaseModel):
    id: str
    run_id: str
    plan_version: int
    item_key: str
    ordinal: int
    title: str
    detail: str | None = None
    status: str
    evidence_json: dict | None = None
    created_at: str | None = None
    updated_at: str | None = None


class PlanUpsertRequest(BaseModel):
    expected_plan_version: int | None = Field(default=None, ge=1)
    items: list[PlanItemIn] = Field(min_length=1, max_length=32)

    @field_validator("items")
    @classmethod
    def _validate_items(cls, items: list[PlanItemIn]) -> list[PlanItemIn]:
        from ..core.run_plan import ITEM_KEY_PATTERN

        keys: set[str] = set()
        for item in items:
            if not ITEM_KEY_PATTERN.fullmatch(item.item_key):
                raise ValueError(
                    "item_key must match [a-z0-9][a-z0-9_-]{0,127}"
                )
            if item.item_key in keys:
                raise ValueError(f"duplicate item_key: {item.item_key}")
            keys.add(item.item_key)
        return items


class PlanItemUpdateRequest(BaseModel):
    status: str = Field(min_length=1, max_length=32)
    evidence_json: dict | None = None


def _require_plan_enabled() -> None:
    if not cfg.agent_run_plan_enabled:
        raise HTTPException(status_code=404, detail="Not found")


def _error(status: int, error_code: str, detail: str) -> HTTPException:
    # 平铺 error_code 响应（契约测试按 resp.json()["error_code"] 断言）
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status,
        content={"error_code": error_code, "detail": detail},
    )


@router.get(
    "/{run_id}/plan",
    response_model=dict,
    dependencies=[Depends(_require_plan_enabled)],
)
async def get_run_plan(
    run_id: str,
    plan_version: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_session),
):
    """run 计划快照（重连纠偏事实）。"""
    svc = RunPlanService(db)
    items = await svc.get_plan(run_id, plan_version)
    version = plan_version or await svc.get_latest_plan_version(run_id)
    return {"version": version, "items": items}


@router.post(
    "/{run_id}/plan",
    response_model=dict,
    status_code=201,
    dependencies=[Depends(_require_plan_enabled)],
)
async def upsert_run_plan(
    run_id: str,
    request: PlanUpsertRequest,
    db: AsyncSession = Depends(get_session),
):
    """创建或更新 run 计划。

    - 首次提交（无 existing plan）→ 创建 plan_version=1。
    - 后续提交必须携带 ``expected_plan_version`` = 当前最新版本；否则 409。
    """
    from ..agents.repository import AgentRunRepository

    run = await AgentRunRepository(db).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    items = [item.model_dump() for item in request.items]
    svc = RunPlanService(db)
    try:
        if request.expected_plan_version is None:
            records = await svc.create_plan(run_id=run_id, items=items)
        elif (
            request.expected_plan_version == 1
            and await svc.get_latest_plan_version(run_id) == 0
        ):
            # 首版创建允许携带 expected_plan_version=1（等价无 expected 的创建）。
            # 创建路径仍由 create_plan 的版本检查兜底并发竞态。
            records = await svc.create_plan(run_id=run_id, items=items)
        else:
            records = await svc.update_plan(
                run_id=run_id,
                expected_plan_version=request.expected_plan_version,
                items=items,
            )
    except PlanVersionConflict as exc:
        return _error(409, "plan_version_conflict", str(exc))
    except PlanTransitionInvalid as exc:
        return _error(422, "plan_transition_invalid", str(exc))
    version = records[0]["plan_version"] if records else 0
    return {"version": version, "items": records}


@router.patch(
    "/{run_id}/plan/{item_id}",
    response_model=PlanItemOut,
    dependencies=[Depends(_require_plan_enabled)],
)
async def update_plan_item_status(
    run_id: str,
    item_id: str,
    request: PlanItemUpdateRequest,
    db: AsyncSession = Depends(get_session),
):
    svc = RunPlanService(db)
    try:
        result = await svc.update_item_status(
            item_id=item_id,
            new_status=request.status,
            evidence_json=request.evidence_json,
        )
    except PlanTransitionInvalid as exc:
        return _error(422, "plan_transition_invalid", str(exc))
    if result is None:
        return _error(404, "workspace_not_found", "Plan item not found")
    return result
