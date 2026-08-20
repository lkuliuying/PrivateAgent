"""v0.6.0 RunPlan 服务：计划更新、版本控制、状态约束（C0 契约 §7）。

规则（§7.1）：

- 1–32 个 item；title 最长 512，detail 最长 4000。
- item_key 只允许 ``[a-z0-9][a-z0-9_-]{0,127}``。
- 同时最多一个 in_progress。
- completed/failed/cancelled 不能回到 pending 或 in_progress。
- expected version 不匹配时失败，不做 last-write-wins。
"""
from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .models import RunPlanItem
from .repo_plan import PLAN_ITEM_STATUSES, RunPlanRepository

logger = get_logger(__name__)

ITEM_KEY_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}")
MAX_ITEMS = 32
MAX_TITLE = 512
MAX_DETAIL = 4000

# 合法状态转换（§7.1）：终态不可回退
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"in_progress", "cancelled"},
    "in_progress": {"completed", "blocked", "failed", "cancelled"},
    "completed": set(),
    "blocked": {"in_progress", "cancelled", "failed"},
    "failed": set(),
    "cancelled": set(),
}


class PlanTransitionInvalid(Exception):
    """item 状态转换非法（422 plan_transition_invalid）。"""


class PlanVersionConflict(Exception):
    """expected plan version 已过期（409 plan_version_conflict）。"""


class RunPlanService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = RunPlanRepository(db)

    def _validate_items(self, items: list[dict]) -> None:
        if not 1 <= len(items) <= MAX_ITEMS:
            raise PlanTransitionInvalid(
                f"plan must contain 1..{MAX_ITEMS} items"
            )
        keys: set[str] = set()
        for item in items:
            item_key = item.get("item_key")
            title = item.get("title")
            if not isinstance(item_key, str) or not ITEM_KEY_PATTERN.fullmatch(
                item_key
            ):
                raise PlanTransitionInvalid(
                    "item_key must match [a-z0-9][a-z0-9_-]{0,127}"
                )
            if item_key in keys:
                raise PlanTransitionInvalid(
                    f"duplicate item_key: {item_key}"
                )
            keys.add(item_key)
            if not isinstance(title, str) or not 1 <= len(title) <= MAX_TITLE:
                raise PlanTransitionInvalid(
                    "title must be 1..512 characters"
                )
            detail = item.get("detail")
            if detail is not None and (
                not isinstance(detail, str) or len(detail) > MAX_DETAIL
            ):
                raise PlanTransitionInvalid(
                    "detail must be at most 4000 characters"
                )
            status = item.get("status", "pending")
            if status not in PLAN_ITEM_STATUSES:
                raise PlanTransitionInvalid(f"invalid status: {status}")

    @staticmethod
    def _validate_transition(current: str, new: str) -> None:
        if new not in _VALID_TRANSITIONS.get(current, set()):
            raise PlanTransitionInvalid(
                f"invalid plan item transition: {current} -> {new}"
            )

    async def create_plan(self, *, run_id: str, items: list[dict]) -> list[dict]:
        """创建初始计划（plan_version=1）。"""
        self._validate_items(items)
        if await self.repo.get_latest_plan_version(run_id) > 0:
            raise PlanVersionConflict(
                "plan already exists; use expected_plan_version to update"
            )
        self._validate_single_in_progress(run_id, items)
        records = await self.repo.create_plan(
            run_id=run_id, items=items, plan_version=1
        )
        return [self._to_dict(r) for r in records]

    async def update_plan(
        self,
        *,
        run_id: str,
        expected_plan_version: int,
        items: list[dict],
    ) -> list[dict]:
        """按 expected_plan_version 写入计划新版本。

        版本不匹配 → PlanVersionConflict（拒绝旧模型回合覆盖新计划）。
        """
        self._validate_items(items)
        latest = await self.repo.get_latest_plan_version(run_id)
        if latest != expected_plan_version:
            raise PlanVersionConflict(
                f"expected_plan_version={expected_plan_version} "
                f"but latest is {latest}"
            )
        self._validate_single_in_progress(run_id, items)
        records = await self.repo.replace_plan(
            run_id=run_id,
            items=items,
            plan_version=latest + 1,
        )
        return [self._to_dict(r) for r in records]

    def _validate_single_in_progress(
        self, run_id: str, items: list[dict]
    ) -> None:
        """新版本 items 中同时最多一个 in_progress。"""
        in_progress = sum(
            1 for item in items if item.get("status") == "in_progress"
        )
        if in_progress > 1:
            raise PlanTransitionInvalid(
                "at most one plan item may be in_progress"
            )

    async def update_item_status(
        self,
        *,
        item_id: str,
        new_status: str,
        evidence_json: dict | None = None,
    ) -> dict | None:
        """更新计划项状态（带状态机校验）。"""
        if new_status not in PLAN_ITEM_STATUSES:
            raise PlanTransitionInvalid(f"invalid status: {new_status}")
        item = await self.db.get(RunPlanItem, item_id)
        if item is None:
            return None
        self._validate_transition(item.status, new_status)
        if new_status == "in_progress":
            # 同一 run 同时最多一个 in_progress
            count = await self.repo.count_in_progress(item.run_id)
            if count >= 1:
                raise PlanTransitionInvalid(
                    "at most one plan item may be in_progress"
                )
        record = await self.repo.update_plan_item(
            item_id=item_id,
            status=new_status,
            evidence_json=evidence_json,
        )
        if record is None:
            return None
        return self._to_dict(record)

    async def get_plan(
        self, run_id: str, plan_version: int | None = None
    ) -> list[dict]:
        records = await self.repo.get_plan(run_id, plan_version)
        return [self._to_dict(r) for r in records]

    async def get_latest_plan_version(self, run_id: str) -> int:
        return await self.repo.get_latest_plan_version(run_id)

    @staticmethod
    def _to_dict(item: RunPlanItem) -> dict:
        return {
            "id": item.id,
            "run_id": item.run_id,
            "plan_version": item.plan_version,
            "item_key": item.item_key,
            "ordinal": item.ordinal,
            "title": item.title,
            "detail": item.detail,
            "status": item.status,
            "evidence_json": item.evidence_json,
            "created_at": item.created_at.isoformat()
            if item.created_at is not None
            else None,
            "updated_at": item.updated_at.isoformat()
            if item.updated_at is not None
            else None,
        }
