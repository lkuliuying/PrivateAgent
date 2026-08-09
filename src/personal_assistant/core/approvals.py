"""工具调用审批状态机。

状态流转（docs/archive/phases/phase2-plan.md M1）::

    pending_approval → approved → running → succeeded | failed
    pending_approval → rejected
    pending_approval | approved | running → cancelled

rejected / succeeded / failed / cancelled 为终态。
非法转换抛 ApprovalError，避免审批被绕过。
"""
from __future__ import annotations


class ApprovalError(RuntimeError):
    """非法的审批状态转换。"""


# 各状态允许的后继状态
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending_approval": {"approved", "rejected", "cancelled"},
    "approved": {"running", "cancelled"},
    "running": {"succeeded", "failed", "cancelled"},
    "rejected": set(),
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}

TERMINAL_STATES = {"rejected", "succeeded", "failed", "cancelled"}


def can_transition(current: str, target: str) -> bool:
    return target in VALID_TRANSITIONS.get(current, set())


def assert_transition(current: str, target: str) -> None:
    """断言状态转换合法，否则抛 ApprovalError。"""
    if not can_transition(current, target):
        raise ApprovalError(f"非法状态转换: {current} -> {target}")
