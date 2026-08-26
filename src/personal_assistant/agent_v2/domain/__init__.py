"""agent_v2.domain：公共领域模型（Thread/Turn/Item，ADR-001）。

本层禁止导入 FastAPI、SQLAlchemy、Tauri、具体 Provider SDK 及任何实现层
（adapters/persistence/providers/execution），由
``scripts/check_agent_v2_imports.py`` 强制。

工具引擎领域契约（专项计划 §7 / ADR-007/008）：
- effects：Effect/Evidence 副作用事实；
- intents：ExecutionIntent 与 P0 意图 tag；
- completion：CompletionContract 与唯一完成求值引擎；
- tool_catalog：ToolSpec v2 元数据契约。
"""

from .completion import (
    KNOWN_POSTCONDITIONS,
    CompletionContract,
    CompletionContractError,
    CompletionEvaluation,
    evaluate_completion,
)
from .effects import DISK_MUTATING_EFFECTS, EffectClass, EffectRecord
from .intents import ExecutionIntent, IntentTag, required_effects_for_tags
from .tool_catalog import (
    ApprovalMode,
    ExecutorKind,
    ModelRequirements,
    NetworkPolicy,
    SideEffectClass,
    ToolExposure,
    ToolIdempotency,
    ToolMaturity,
    ToolRiskLevel,
    ToolSource,
    ToolSpecV2,
)

__all__ = [
    "DISK_MUTATING_EFFECTS",
    "KNOWN_POSTCONDITIONS",
    "ApprovalMode",
    "CompletionContract",
    "CompletionContractError",
    "CompletionEvaluation",
    "EffectClass",
    "EffectRecord",
    "ExecutionIntent",
    "ExecutorKind",
    "IntentTag",
    "ModelRequirements",
    "NetworkPolicy",
    "SideEffectClass",
    "ToolExposure",
    "ToolIdempotency",
    "ToolMaturity",
    "ToolRiskLevel",
    "ToolSource",
    "ToolSpecV2",
    "evaluate_completion",
    "required_effects_for_tags",
]
