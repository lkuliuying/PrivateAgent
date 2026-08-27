"""CompletionContract 与完成求值引擎（专项计划 §7.5 / ADR-007 / CT1-03）。

单一事实源：副作用任务的完成判定只有本模块的 ``evaluate_completion`` 一个
实现。v0.9 H1-B 的 ``min_tool_executions``/``require_successful_file_write``
分支自 CT-1 起委托到这里（ADR-007 §2），不得再出现第二套并行判断。

公开错误码（冻结）：
- ``required_effect_missing``：零执行证据却宣称完成（F-003）；
- ``side_effect_unverified``：必需副作用已执行但回读证据不成立（F-007）；
- ``completion_not_met``（或契约自定义 ``failure_message_code``）：其余未满足。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .effects import DISK_MUTATING_EFFECTS, EffectClass, EffectRecord

# P0 可信后置谓词注册表（§7.5）。语义映射（P0 实现）：谓词由写入类 effect
# 的 verified=True 回读确认统一兑现——target_path_exists 与
# target_sha_matches_committed_effect 即回读核对的结论，不允许模型自证。
KNOWN_POSTCONDITIONS: frozenset[str] = frozenset(
    {
        "target_path_exists",
        "target_sha_matches_committed_effect",
        "python_source_contains_expected_behavior",
        "command_exit_code_zero",
        "database_row_present",
    }
)

_ALLOWED_TERMINAL_STATES = ("completed", "failed", "waiting_approval")

# 少于最低证据时的公开话术（与 v0.9 H1-B 保持一致，UI 无感迁移）。
_MIN_EVIDENCE_REASON = (
    "工具/命令执行证据 {evidence} 条，少于要求的 {required} 条；"
    "可执行请求必须调用工具收集证据，不得只回复文字教程"
)
# 文件写入缺失时的公开话术（同上）。
_FILE_WRITE_UNMET_REASON = (
    "文件变更任务没有 succeeded 的 Patch 写入执行；失败命令和只读预览不算完成"
)


class CompletionContractError(ValueError):
    """契约构造非法（未知谓词/字段越界），失败关闭。"""


class CompletionContract(BaseModel):
    """Turn/run 开始时由可信代码生成并冻结的完成契约。

    契约不能由模型修改；持久化条件确定性重建时 ``contract_id`` 保持稳定
    （create 与 resume 得到同一契约，ADR-007 §1-3）。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_id: str = Field(pattern=r"^cc-[0-9a-f]{32}$")
    required_effects: frozenset[EffectClass] = frozenset()
    # 按 effect 的最低成功次数（键为 EffectClass 值）。
    minimum_execution_counts: dict[str, int] = Field(default_factory=dict)
    # 任意终态工具执行的最低证据数（失败命令也是证据，H1-B 语义）。
    minimum_evidence_count: int = 0
    postconditions: tuple[str, ...] = ()
    allowed_terminal_states: tuple[str, ...] = ("completed", "failed")
    failure_message_code: str = Field(default="completion_not_met", pattern=r"^[a-z0-9_]{1,64}$")

    @field_validator("minimum_execution_counts")
    @classmethod
    def _validate_counts(cls, value: dict[str, int]) -> dict[str, int]:
        for key, count in value.items():
            EffectClass(key)  # 非法 effect 键直接抛错（失败关闭）
            if not 1 <= int(count) <= 64:
                raise ValueError(
                    f"minimum_execution_counts[{key}] 必须是 1..64 的整数"
                )
        return dict(value)

    @field_validator("postconditions")
    @classmethod
    def _validate_postconditions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = [name for name in value if name not in KNOWN_POSTCONDITIONS]
        if unknown:
            raise ValueError(f"未知完成谓词：{unknown}（必须在 KNOWN_POSTCONDITIONS 内）")
        return tuple(value)

    @field_validator("allowed_terminal_states")
    @classmethod
    def _validate_terminal_states(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        if not value:
            raise ValueError("allowed_terminal_states 不能为空")
        invalid = [state for state in value if state not in _ALLOWED_TERMINAL_STATES]
        if invalid:
            raise ValueError(f"非法终态：{invalid}")
        return tuple(value)

    @classmethod
    def build(cls, *, payload: dict[str, Any]) -> "CompletionContract":
        """从规范化 payload 构建契约并派生稳定 contract_id。

        同一 payload（持久化完成条件）在任何时间重建都得到同一 contract_id，
        满足"契约随 Turn 恢复、不按新设置重算"（专项计划 §13.3）。
        """
        digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return cls(contract_id=f"cc-{digest[:32]}", **payload)


class CompletionEvaluation(BaseModel):
    """一次完成求值的结构化结论（公开、低敏感）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    satisfied: bool
    failure_code: str | None = None
    unmet_reasons: tuple[str, ...] = ()
    missing_effects: tuple[EffectClass, ...] = ()
    evidence_count: int = 0


def _effect_success_count(records: list[EffectRecord], effect: EffectClass) -> int:
    return sum(1 for record in records if record.satisfies_effect(effect))


def _has_succeeded_but_unverified(
    records: list[EffectRecord], effect: EffectClass
) -> bool:
    return any(
        record.status == "succeeded"
        and effect in record.effects
        and not record.satisfies_effect(effect)
        for record in records
    )


def evaluate_completion(
    contract: CompletionContract,
    records: list[EffectRecord],
) -> CompletionEvaluation:
    """在 durable effect 证据上求值契约（唯一完成判定实现）。

    失败关闭顺序：
    1. 终态执行证据为 0 且存在任何门槛 → ``required_effect_missing``；
    2. 必需 effect 出现过 succeeded 但回读验证不成立 → ``side_effect_unverified``；
    3. 其余未满足 → ``contract.failure_message_code``。
    """
    terminal_records = [record for record in records if record.is_terminal()]
    evidence_count = len(terminal_records)
    unmet: list[str] = []
    missing: list[EffectClass] = []
    gates_active = bool(
        contract.required_effects or contract.minimum_evidence_count > 0
    )

    if contract.minimum_evidence_count > evidence_count:
        unmet.append(
            _MIN_EVIDENCE_REASON.format(
                evidence=evidence_count,
                required=contract.minimum_evidence_count,
            )
        )

    for effect in sorted(contract.required_effects, key=lambda item: item.value):
        floor = max(1, int(contract.minimum_execution_counts.get(effect.value, 1)))
        if _effect_success_count(terminal_records, effect) >= floor:
            continue
        missing.append(effect)
        if effect in DISK_MUTATING_EFFECTS:
            unmet.append(_FILE_WRITE_UNMET_REASON)
            if _has_succeeded_but_unverified(terminal_records, effect):
                # 写入声称成功但磁盘回读不一致/缺失——证据不可信。
                unmet.append(
                    "文件写入执行未通过回读验证：磁盘事实与执行声明不一致，"
                    "不能采信为已完成"
                )
        else:
            unmet.append(f"缺少必需的成功副作用：{effect.value}")

    postcondition_effects = [
        effect
        for effect in contract.required_effects
        if effect in DISK_MUTATING_EFFECTS
    ]
    if contract.postconditions and postcondition_effects:
        # P0 谓词语义：由落盘类 effect 的回读确认兑现（见模块 docstring）。
        all_verified = all(
            _effect_success_count(terminal_records, effect) >= 1
            for effect in postcondition_effects
        )
        if not all_verified and not missing:
            unmet.append("完成后置条件未取得可信证据")

    if not unmet:
        return CompletionEvaluation(
            satisfied=True,
            failure_code=None,
            evidence_count=evidence_count,
        )

    if gates_active and evidence_count == 0:
        failure_code = "required_effect_missing"
    elif any("回读验证" in reason for reason in unmet):
        failure_code = "side_effect_unverified"
    else:
        failure_code = contract.failure_message_code
    return CompletionEvaluation(
        satisfied=False,
        failure_code=failure_code,
        unmet_reasons=tuple(unmet)[:16],
        missing_effects=tuple(missing),
        evidence_count=evidence_count,
    )
