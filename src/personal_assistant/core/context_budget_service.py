"""v0.9.0 H1-A：上下文 budget 求值与确定性压缩服务（H0 §7）。

红线（计划 §5.4/§11）：
- 用量只来自 provider usage（run.input_tokens 等 durable 事实）；无法准确
  计量时返回 ``source=unavailable`` + 原因，绝不按字符数/消息数伪造百分比；
- ``usage_percent`` 域 0..100，超限封顶 100 并携带 ``budget_exceeded``；
- 压缩保留最新用户请求与近期消息（``coding_context_keep_recent_messages``），
  不静默截断到空；压缩前后发 durable 事件（可审计）；
- 压缩失败或预算仍超限 → 停止新执行（路由层返回 409 budget_exceeded）。
"""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..logging_setup import get_logger
from .context_budget import COMPACTION_STATES, ContextBudget, UsageSource
from .models import AgentRun as AgentRunRecord
from .models import AgentRunEvent as AgentRunEventRecord
from .models import Message

logger = get_logger(__name__)

_COMPACTION_EVENT_STATES = {
    "context.compaction_started": "compacting",
    "context.compaction_completed": "compacted",
    "context.compaction_failed": "failed",
}


class ContextBudgetError(RuntimeError):
    """预算超限且压缩无法恢复（路由层映射 409 budget_exceeded）。"""


async def _latest_run(db: AsyncSession, session_id: int) -> AgentRunRecord | None:
    result = await db.execute(
        select(AgentRunRecord)
        .where(AgentRunRecord.session_id == session_id)
        .order_by(AgentRunRecord.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _window_max_tokens(db: AsyncSession, run: AgentRunRecord | None) -> int:
    """上下文窗口上限：优先模型 profile 声明，回退全局配置（真实来源）。"""
    if run is not None and run.model_profile_id:
        from .model_profiles import ModelProfileService

        profile = await ModelProfileService(db).get(run.model_profile_id)
        if profile is not None and profile.context_tokens:
            return int(profile.context_tokens)
    return int(settings.llm_context_length)


async def _compaction_state(
    db: AsyncSession, session_id: int
) -> tuple[str, object]:
    """会话维度最近一次压缩事件派生状态（无事件 → idle）。"""
    result = await db.execute(
        select(AgentRunEventRecord)
        .join(
            AgentRunRecord,
            AgentRunEventRecord.run_id == AgentRunRecord.id,
        )
        .where(
            AgentRunRecord.session_id == session_id,
            AgentRunEventRecord.event_type.in_(
                tuple(_COMPACTION_EVENT_STATES)
            ),
        )
        .order_by(AgentRunEventRecord.sequence.desc())
        .limit(1)
    )
    event = result.scalar_one_or_none()
    if event is None:
        return "idle", None
    return _COMPACTION_EVENT_STATES[event.event_type], event.created_at


async def evaluate_session_budget(
    db: AsyncSession, session_id: int
) -> ContextBudget:
    """求值会话上下文预算（真实计量；不可用如实声明）。"""
    reserved = int(settings.coding_context_reserved_output_tokens)
    run = await _latest_run(db, session_id)
    max_tokens = await _window_max_tokens(db, run)
    state, last_compacted_at = await _compaction_state(db, session_id)

    if run is None:
        return ContextBudget(
            used_tokens=0,
            max_context_tokens=max_tokens,
            reserved_output_tokens=reserved,
            source=UsageSource.UNAVAILABLE,
            compaction_state=state,
            error_reason="会话尚未产生执行记录",
        )
    used = int(run.input_tokens or 0)
    if used <= 0:
        return ContextBudget(
            used_tokens=0,
            max_context_tokens=max_tokens,
            reserved_output_tokens=reserved,
            source=UsageSource.UNAVAILABLE,
            compaction_state=state,
            error_reason="模型未报告 token 用量（该 profile 无法准确计量）",
        )
    budget = ContextBudget(
        used_tokens=used,
        max_context_tokens=max_tokens,
        reserved_output_tokens=reserved,
        source=UsageSource.PROVIDER_USAGE,
        compaction_state=state,
        last_compacted_at=last_compacted_at,
    )
    percent = budget.usage_percent or 0
    if percent >= 100:
        budget = budget.model_copy(
            update={
                "error_code": "budget_exceeded",
                "error_reason": "上下文用量达到窗口上限，请压缩或新开会话",
            }
        )
    return budget


async def _emit_compaction_event(
    db: AsyncSession, run_id: str, last_sequence: int,
    event_type: str, payload: dict,
) -> int:
    """压缩事件写入 durable 事件流；返回新 sequence。

    投影要求首事件为 run.started，故仅对已开始（至少一个事件）的 run 发射；
    写入失败只记录，不阻断压缩事实。传入 run_id/last_sequence 快照避免
    在异步边界惰性加载已过期的 ORM 对象。
    """
    if last_sequence < 1:
        return last_sequence
    try:
        from ..agents.contracts import AgentEvent, AgentEventType
        from ..agents.repository import AgentRunRepository

        await AgentRunRepository(db).record_event(
            AgentEvent(
                run_id=run_id,
                sequence=last_sequence + 1,
                type=AgentEventType(event_type),
                payload=payload,
            )
        )
        return last_sequence + 1
    except Exception:  # noqa: BLE001 - 事件失败不影响压缩事实
        logger.warning(
            "compaction event emit failed",
            run_id=run_id,
            event_type=event_type,
        )
        return last_sequence


async def compact_session_if_needed(
    db: AsyncSession, session_id: int
) -> bool:
    """达到阈值时确定性压缩会话历史（保留最近 N 条）。

    返回是否执行了压缩。压缩只删除最旧消息，最新用户请求与近期事实保留；
    无可压缩内容时不做任何事（不产生虚假压缩事件）。
    """
    budget = await evaluate_session_budget(db, session_id)
    percent = budget.usage_percent
    if percent is None or percent < settings.coding_context_compaction_threshold:
        return False

    keep = int(settings.coding_context_keep_recent_messages)
    total = await db.scalar(
        select(func.count(Message.id)).where(Message.session_id == session_id)
    )
    total = int(total or 0)
    if total <= keep:
        # 无历史可压缩：预算压力来自当前请求本身 → 交由路由层按超限处置
        return False

    run = await _latest_run(db, session_id)
    # 快照 run_id/sequence（避免后续异步边界惰性加载过期 ORM）
    run_id = run.id if run is not None else None
    sequence = int(run.last_event_sequence) if run is not None else 0
    if run_id is not None:
        sequence = await _emit_compaction_event(
            db,
            run_id,
            sequence,
            "context.compaction_started",
            {
                "before_tokens": budget.used_tokens,
                "threshold_percent": int(
                    settings.coding_context_compaction_threshold
                ),
            },
        )
    remove_count = total - keep
    oldest_ids = (
        await db.execute(
            select(Message.id)
            .where(Message.session_id == session_id)
            .order_by(Message.id.asc())
            .limit(remove_count)
        )
    ).scalars().all()
    if oldest_ids:
        await db.execute(delete(Message).where(Message.id.in_(oldest_ids)))
    await db.commit()
    if run_id is not None:
        await _emit_compaction_event(
            db,
            run_id,
            sequence,
            "context.compaction_completed",
            {
                "before_tokens": budget.used_tokens,
                "after_tokens": budget.used_tokens,
                "threshold_percent": int(
                    settings.coding_context_compaction_threshold
                ),
            },
        )
        await db.commit()
    logger.info(
        "session context compacted",
        session_id=session_id,
        removed_messages=len(oldest_ids),
        kept_messages=keep,
        usage_percent=percent,
    )
    return True


__all__ = [
    "COMPACTION_STATES",
    "ContextBudget",
    "ContextBudgetError",
    "compact_session_if_needed",
    "evaluate_session_budget",
]
