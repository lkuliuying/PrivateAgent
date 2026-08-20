"""v0.6.0 update_run_plan 内部 safe 工具（C0 契约 §7.1）。

工具不授予文件、进程、网络或数据库 capability；模型只能通过
expected_plan_version + items 更新计划，版本不匹配时失败（不做
last-write-wins）。计划表是事实，durable 事件由 RunPlanService 写入。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.runtime import CancellationToken
from ..agents.tools import (
    ToolDispatchCancelled,
    ToolIdempotency,
    ToolRedactionPolicy,
    ToolRiskLevel,
    ToolSpec,
)
from .repo_plan import PLAN_ITEM_STATUSES
from .run_plan import PlanTransitionInvalid, PlanVersionConflict, RunPlanService

_TOOL_NAME = "update_run_plan"
_TOOL_VERSION = "1.0.0"

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "expected_plan_version": {"type": "integer", "minimum": 1},
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 32,
            "items": {
                "type": "object",
                "required": ["item_key", "title"],
                "properties": {
                    "item_key": {
                        "type": "string",
                        "pattern": "^[a-z0-9][a-z0-9_-]{0,127}$",
                    },
                    "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 512,
                    },
                    "detail": {"type": "string", "maxLength": 4000},
                    "status": {
                        "enum": sorted(PLAN_ITEM_STATUSES),
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    "required": ["expected_plan_version", "items"],
    "additionalProperties": False,
}

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "plan_version": {"type": "integer", "minimum": 1},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["item_key", "title", "status"],
                "properties": {
                    "item_key": {"type": "string"},
                    "title": {"type": "string"},
                    "status": {"enum": sorted(PLAN_ITEM_STATUSES)},
                },
                "additionalProperties": False,
            },
        },
    },
    "required": ["plan_version", "items"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "更新当前 coding run 的真实计划。"
    "expected_plan_version 必须是当前最新版本 + 1（首次创建计划时传 1）；"
    "版本过期会被拒绝，请从计划快照或最新错误中读取最新版本后重试。"
    "item_key 只允许小写字母/数字/下划线/连字符；同时最多一个 item 处于 in_progress；"
    "completed/failed/cancelled 的 item 不能回退到 pending 或 in_progress。"
)


def build_run_plan_tool_spec(db: AsyncSession, run_id: str) -> ToolSpec:
    """构造绑定到指定 run 的 update_run_plan 工具。"""

    async def execute(
        arguments: dict[str, Any], cancellation: CancellationToken
    ) -> dict[str, Any]:
        if cancellation.is_cancelled:
            raise ToolDispatchCancelled("工具执行已取消")
        service = RunPlanService(db)
        expected = arguments["expected_plan_version"]
        items = arguments["items"]
        try:
            latest = await service.get_latest_plan_version(run_id)
            if latest == 0 and expected == 1:
                records = await service.create_plan(run_id=run_id, items=items)
            else:
                records = await service.update_plan(
                    run_id=run_id,
                    expected_plan_version=expected,
                    items=items,
                )
        except (PlanVersionConflict, PlanTransitionInvalid) as exc:
            raise RuntimeError(str(exc)) from exc
        return {
            "plan_version": records[0]["plan_version"],
            "items": [
                {
                    "item_key": item["item_key"],
                    "title": item["title"],
                    "status": item["status"],
                }
                for item in records
            ],
        }

    return ToolSpec(
        name=_TOOL_NAME,
        version=_TOOL_VERSION,
        description=_DESCRIPTION,
        input_schema=_INPUT_SCHEMA,
        output_schema=_OUTPUT_SCHEMA,
        risk_level=ToolRiskLevel.SAFE,
        required_capabilities=frozenset(),
        timeout_ms=30_000,
        max_input_bytes=128 * 1024,
        max_output_bytes=64 * 1024,
        idempotency=ToolIdempotency.IDEMPOTENT,
        supports_cancellation=True,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        executor=execute,
    )
