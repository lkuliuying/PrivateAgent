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

from ..agents.contracts import AgentEventType
from ..logging_setup import get_logger
from .db import async_session_factory
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
        """创建初始计划（plan_version=1），随后写 plan.created durable 事件。"""
        self._validate_items(items)
        if await self.repo.get_latest_plan_version(run_id) > 0:
            raise PlanVersionConflict(
                "plan already exists; use expected_plan_version to update"
            )
        self._validate_single_in_progress(run_id, items)
        records = await self.repo.create_plan(
            run_id=run_id, items=items, plan_version=1
        )
        await self._emit_event(
            run_id,
            AgentEventType.PLAN_CREATED,
            {
                "plan_version": 1,
                "items": [
                    {"item_key": r.item_key, "title": r.title, "status": r.status}
                    for r in records
                ],
            },
        )
        return [self._to_dict(r) for r in records]

    async def update_plan(
        self,
        *,
        run_id: str,
        expected_plan_version: int,
        items: list[dict],
    ) -> list[dict]:
        """按 expected_plan_version（CAS）写入计划新版本，随后写 plan.updated/plan.item_changed。

        - expected_plan_version 是模型读取到的当前最新版本（快照 version）；
          仅当 == latest 时写入 latest+1；过期版本 → PlanVersionConflict，不做 last-write-wins。
        - 状态转换校验（相对最新版本的同一 item_key）先于版本校验：
          terminal 回退等非法转换直接 422，旧版本覆盖才 409。
        """
        self._validate_items(items)
        # 归一化：未提供 status 的 item 按默认 pending 参与转换检查与写入，
        # 避免后续 item["status"] 下标 KeyError（与 _validate_items 默认值一致）。
        items = [
            {**item, "status": item.get("status", "pending")} for item in items
        ]
        latest = await self.repo.get_latest_plan_version(run_id)
        if latest < 1:
            raise PlanVersionConflict(
                "plan does not exist; create it without expected_plan_version"
            )
        # 状态转换校验：同 item_key 状态未变则跳过（同状态不是转换）
        previous_items = await self.repo.get_plan(run_id)
        previous_by_key = {item.item_key: item.status for item in previous_items}
        for item in items:
            previous_status = previous_by_key.get(item["item_key"])
            if previous_status is not None and previous_status != item.get(
                "status"
            ):
                self._validate_transition(previous_status, item["status"])
        if expected_plan_version != latest:
            raise PlanVersionConflict(
                f"expected_plan_version={expected_plan_version} "
                f"but latest version is {latest}"
            )
        self._validate_single_in_progress(run_id, items)
        new_version = latest + 1
        records = await self.repo.replace_plan(
            run_id=run_id,
            items=items,
            plan_version=new_version,
        )
        await self._emit_event(
            run_id,
            AgentEventType.PLAN_UPDATED,
            {"previous_version": latest, "plan_version": new_version},
        )
        for item in items:
            previous_status = previous_by_key.get(item["item_key"])
            if previous_status is not None and previous_status != item.get(
                "status"
            ):
                await self._emit_event(
                    run_id,
                    AgentEventType.PLAN_ITEM_CHANGED,
                    {
                        "plan_version": new_version,
                        "item_key": item["item_key"],
                        "previous_status": previous_status,
                        "status": item["status"],
                    },
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
        """更新计划项状态（带状态机校验），随后写 plan.item_changed durable 事件。"""
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
        previous_status = item.status
        record = await self.repo.update_plan_item(
            item_id=item_id,
            status=new_status,
            evidence_json=evidence_json,
        )
        if record is None:
            return None
        await self._emit_event(
            record.run_id,
            AgentEventType.PLAN_ITEM_CHANGED,
            {
                "plan_version": await self.get_latest_plan_version(record.run_id),
                "item_key": record.item_key,
                "previous_status": previous_status,
                "status": record.status,
            },
        )
        return self._to_dict(record)

    async def get_plan(
        self, run_id: str, plan_version: int | None = None
    ) -> list[dict]:
        records = await self.repo.get_plan(run_id, plan_version)
        return [self._to_dict(r) for r in records]

    async def get_latest_plan_version(self, run_id: str) -> int:
        return await self.repo.get_latest_plan_version(run_id)

    async def _emit_event(
        self, run_id: str, event_type: AgentEventType, payload: dict
    ) -> None:
        """写 durable 计划事件（C0 §8）。

        使用独立 session：record_event 失败时的 rollback 只影响事件事务，
        不会使主 session 的 plan ORM 对象过期（避免懒加载 MissingGreenlet），
        也不会回滚计划本身的写入。计划表仍是事实（快照纠偏兜底），
        事件写入失败只记录日志；sequence 由 record_event 的行锁校验兜底。
        """
        try:
            from ..agents.contracts import AgentEvent
            from ..agents.repository import AgentRunRepository

            async with async_session_factory() as session:
                run_repo = AgentRunRepository(session)
                run = await run_repo.get_run(run_id)
                if run is None:
                    return
                await run_repo.record_event(
                    AgentEvent(
                        run_id=run_id,
                        sequence=run.last_event_sequence + 1,
                        type=event_type,
                        payload=payload,
                    )
                )
        except Exception:
            logger.warning(
                "plan durable event emit failed",
                run_id=run_id,
                event_type=event_type.value,
                exc_info=True,
            )

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
