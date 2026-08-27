"""CompletionContract 工厂：从持久化完成条件确定性重建（CT1-05/ADR-007）。

create 注入的完成条件（``completion_conditions_json``）是唯一输入——resume
读取同一持久化 JSON 重建出**同一 contract_id** 的契约，满足"契约随 Turn
恢复、不按新设置重算"（专项计划 §13.3）。返回 ``None`` 表示本轮没有
v2 收口门槛（其余旧条件继续走 v0.9 兼容 verifier）。
"""

from __future__ import annotations

from typing import Any, Mapping

from ..domain.completion import CompletionContract
from ..domain.effects import EffectClass


def build_completion_contract_from_conditions(
    conditions: Mapping[str, Any] | None,
) -> CompletionContract | None:
    """由完成条件派生契约；无门槛条件时返回 None。

    v2 收口的条件族（ADR-007 §2，单一判断）：
    - ``min_tool_executions`` → minimum_evidence_count；
    - ``require_successful_file_write`` → required_effects={filesystem.write}
      + 磁盘回读后置谓词。
    """
    if not isinstance(conditions, Mapping):
        return None
    min_evidence_raw = conditions.get("min_tool_executions") or 0
    try:
        min_evidence = max(0, int(min_evidence_raw))
    except (TypeError, ValueError):
        min_evidence = 0
    require_write = bool(conditions.get("require_successful_file_write"))
    if min_evidence <= 0 and not require_write:
        return None

    payload: dict[str, Any] = {
        "required_effects": (
            [EffectClass.FILESYSTEM_WRITE.value] if require_write else []
        ),
        "minimum_execution_counts": (
            {EffectClass.FILESYSTEM_WRITE.value: 1} if require_write else {}
        ),
        "minimum_evidence_count": min_evidence,
        "postconditions": (
            [
                "target_path_exists",
                "target_sha_matches_committed_effect",
            ]
            if require_write
            else []
        ),
        "allowed_terminal_states": ["completed", "failed"],
        "failure_message_code": "completion_not_met",
    }
    return CompletionContract.build(payload=payload)
