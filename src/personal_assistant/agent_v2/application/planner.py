"""ToolPlan 与 ToolSnapshot：暴露决策与诊断视图（专项计划 §7.2/§7.3/§9.2、CT2-03、ADR-008）。

Exposure 决策顺序（§9.2 冻结）：

    feature maturity → model requirements → workspace/environment applicability
      → capability policy → feature flag → health → intent relevance
        → context/schema budget → direct / deferred / hidden

规则：
- 每个被排除的工具都带稳定、可测试的隐藏原因（HiddenReason 枚举，
  禁止自由文本原因进入公开协议）；
- Exposure 只决定可见性，不消费审批 token、不扩大任何权限；
- ToolPlan 不可变；Turn 运行中设置变化不得静默换工具。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ..domain.effects import EffectClass
from ..domain.intents import IntentTag, required_effects_for_tags
from ..domain.tool_catalog import ToolExposure, ToolMaturity, ToolSpecV2
from .catalog import ToolCatalog, canonical_json


class HiddenReason(StrEnum):
    """稳定隐藏原因（§7.3 诊断视图口径，可测试）。"""

    MATURITY_DISABLED = "maturity_disabled"
    MODEL_UNSUPPORTED = "model_unsupported"
    NOT_APPLICABLE = "not_applicable"
    POLICY_DENIED = "policy_denied"
    FEATURE_DISABLED = "feature_disabled"
    HEALTH_FAILED = "health_failed"
    NOT_RELEVANT = "not_relevant"
    CONTEXT_BUDGET = "context_budget"


DEFAULT_MAX_DIRECT_TOOLS = 12
DEFAULT_MAX_SCHEMA_BYTES = 96 * 1024


class ModelCapabilitySnapshot(BaseModel):
    """Provider/模型能力快照输入（无有效快照时调用方应给最小集）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_hash: str = Field(min_length=8, max_length=128)
    function_calling: bool = True
    freeform_patch: bool = False
    vision: bool = False
    parallel_tool_calls: bool = False
    max_direct_tools: int = Field(default=DEFAULT_MAX_DIRECT_TOOLS, ge=1, le=256)
    max_schema_bytes: int = Field(
        default=DEFAULT_MAX_SCHEMA_BYTES, ge=1024, le=4 * 1024 * 1024
    )


class PolicySnapshot(BaseModel):
    """权限/feature/健康快照输入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_hash: str = Field(min_length=8, max_length=128)
    granted_capabilities: frozenset[str] = frozenset()
    enabled_features: frozenset[str] = frozenset()
    # 健康检查失败集合（health_check_id）；未列入即视为可用。
    health_failed: frozenset[str] = frozenset()


class PlannedTool(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: str
    canonical_name: str
    version: str


class HiddenTool(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: str
    canonical_name: str
    reason: HiddenReason


def _plan_id(
    *,
    catalog_hash: str,
    visible_hash: str,
    model_profile_hash: str,
    policy_hash: str,
    tags: frozenset[IntentTag],
) -> str:
    payload = json.dumps(
        {
            "catalog": catalog_hash,
            "visible": visible_hash,
            "model": model_profile_hash,
            "policy": policy_hash,
            "tags": sorted(tag.value for tag in tags),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"tp-{hashlib.sha256(payload).hexdigest()[:32]}"


class ToolPlan(BaseModel):
    """一轮 Turn 的不可变工具计划（§7.2）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_plan_id: str = Field(pattern=r"^tp-[0-9a-f]{32}$")
    turn_tags: frozenset[IntentTag]
    required_effects: frozenset[EffectClass]
    direct_tools: tuple[PlannedTool, ...]
    deferred_tools: tuple[PlannedTool, ...]
    hidden_tools: tuple[HiddenTool, ...]
    catalog_hash: str
    visible_hash: str
    model_profile_hash: str
    policy_hash: str
    created_at: datetime | None = None

    @property
    def visible_names(self) -> tuple[str, ...]:
        return tuple(item.canonical_name for item in self.direct_tools)


def _schema_bytes(spec: ToolSpecV2) -> int:
    return len(canonical_json(dict(spec.input_schema)).encode("utf-8")) + len(
        spec.description.encode("utf-8")
    )


def compute_visible_hash(direct_tools) -> str:
    """direct 集合的规范化可见哈希（§7.2 visible_hash；激活后重算）。"""
    payload = json.dumps(
        [
            [item.namespace, item.canonical_name, item.version]
            for item in sorted(direct_tools, key=lambda i: i.canonical_name)
        ],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_plan_id(
    *,
    catalog_hash: str,
    visible_hash: str,
    model_profile_hash: str,
    policy_hash: str,
    tags,
) -> str:
    return _plan_id(
        catalog_hash=catalog_hash,
        visible_hash=visible_hash,
        model_profile_hash=model_profile_hash,
        policy_hash=policy_hash,
        tags=frozenset(tags),
    )


def build_tool_plan(
    catalog: ToolCatalog,
    intent_tags: frozenset[IntentTag],
    *,
    model: ModelCapabilitySnapshot,
    policy: PolicySnapshot,
    applicable: dict[str, bool] | None = None,
    created_at: datetime | None = None,
) -> ToolPlan:
    """按 §9.2 决策顺序产出本轮 ToolPlan。

    ``applicable``：workspace/environment 适用性覆盖表
    （键为 canonical_name，缺省视为适用）。
    """
    applicable_map = applicable or {}
    direct: list[PlannedTool] = []
    deferred: list[PlannedTool] = []
    hidden: list[HiddenTool] = []

    survivors: list[ToolSpecV2] = []
    for spec in catalog.specs:
        # 1. maturity
        if spec.maturity == ToolMaturity.DISABLED:
            hidden.append(HiddenTool(namespace=spec.namespace, canonical_name=spec.canonical_name, reason=HiddenReason.MATURITY_DISABLED))
            continue
        # 2. model requirements
        req = spec.model_requirements
        if (req.function_calling and not model.function_calling) or (
            req.freeform_patch and not model.freeform_patch
        ) or (req.vision and not model.vision) or (
            req.parallel_tool_calls and not model.parallel_tool_calls
        ):
            hidden.append(HiddenTool(namespace=spec.namespace, canonical_name=spec.canonical_name, reason=HiddenReason.MODEL_UNSUPPORTED))
            continue
        # 3. workspace/environment applicability
        if applicable_map.get(spec.canonical_name, True) is False:
            hidden.append(HiddenTool(namespace=spec.namespace, canonical_name=spec.canonical_name, reason=HiddenReason.NOT_APPLICABLE))
            continue
        # 4. capability policy
        if not spec.required_capabilities <= policy.granted_capabilities:
            hidden.append(HiddenTool(namespace=spec.namespace, canonical_name=spec.canonical_name, reason=HiddenReason.POLICY_DENIED))
            continue
        # 5. feature flag
        if spec.feature_flag is not None and (
            spec.feature_flag not in policy.enabled_features
        ):
            hidden.append(HiddenTool(namespace=spec.namespace, canonical_name=spec.canonical_name, reason=HiddenReason.FEATURE_DISABLED))
            continue
        # 6. health
        if spec.health_check_id is not None and (
            spec.health_check_id in policy.health_failed
        ):
            hidden.append(HiddenTool(namespace=spec.namespace, canonical_name=spec.canonical_name, reason=HiddenReason.HEALTH_FAILED))
            continue
        # 7. intent relevance（空 intent_tags 的工具恒相关）
        if spec.intent_tags and not (spec.intent_tags & {t.value for t in intent_tags}):
            hidden.append(HiddenTool(namespace=spec.namespace, canonical_name=spec.canonical_name, reason=HiddenReason.NOT_RELEVANT))
            continue
        survivors.append(spec)

    # 8. context/schema budget（确定性顺序：canonical_name）
    used_bytes = 0
    for spec in sorted(survivors, key=lambda item: item.canonical_name):
        planned = PlannedTool(
            namespace=spec.namespace,
            canonical_name=spec.canonical_name,
            version=spec.version,
        )
        if spec.exposure == ToolExposure.DEFERRED:
            # Deferred 不下发 Schema，不占用上下文预算（激活走 S6 上限）。
            deferred.append(planned)
            continue
        cost = _schema_bytes(spec)
        if (
            len(direct) < model.max_direct_tools
            and used_bytes + cost <= model.max_schema_bytes
        ):
            direct.append(planned)
            used_bytes += cost
        else:
            hidden.append(HiddenTool(namespace=spec.namespace, canonical_name=spec.canonical_name, reason=HiddenReason.CONTEXT_BUDGET))

    catalog_hash = catalog.catalog_hash()
    visible_hash = compute_visible_hash(direct)
    return ToolPlan(
        tool_plan_id=_plan_id(
            catalog_hash=catalog_hash,
            visible_hash=visible_hash,
            model_profile_hash=model.profile_hash,
            policy_hash=policy.policy_hash,
            tags=intent_tags,
        ),
        turn_tags=frozenset(intent_tags),
        required_effects=required_effects_for_tags(frozenset(intent_tags)),
        direct_tools=tuple(sorted(direct, key=lambda i: i.canonical_name)),
        deferred_tools=tuple(sorted(deferred, key=lambda i: i.canonical_name)),
        hidden_tools=tuple(hidden),
        catalog_hash=catalog_hash,
        visible_hash=visible_hash,
        model_profile_hash=model.profile_hash,
        policy_hash=policy.policy_hash,
        created_at=created_at,
    )


class SnapshotEntry(BaseModel):
    """脱敏诊断条目：不含 schema/description 全文/参数/secret。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: str
    canonical_name: str
    version: str
    exposure: str  # direct | deferred | hidden:<reason>
    risk_level: str
    approval_mode: str
    executor_kind: str
    side_effect_class: str
    health_check_id: str | None = None


class ToolSnapshot(BaseModel):
    """回答"模型究竟看到了什么工具以及原因"的脱敏诊断视图（§7.3）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_plan_id: str
    direct_total: int
    deferred_total: int
    hidden_total: int
    entries: tuple[SnapshotEntry, ...]
    catalog_hash: str
    visible_hash: str
    model_profile_hash: str
    policy_hash: str


def build_tool_snapshot(plan: ToolPlan, catalog: ToolCatalog) -> ToolSnapshot:
    hidden_reason = {
        item.canonical_name: item.reason for item in plan.hidden_tools
    }
    deferred_names = {item.canonical_name for item in plan.deferred_tools}
    direct_names = {item.canonical_name for item in plan.direct_tools}
    entries: list[SnapshotEntry] = []
    for spec in sorted(catalog.specs, key=lambda item: item.canonical_name):
        name = spec.canonical_name
        if name in direct_names:
            exposure = ToolExposure.DIRECT.value
        elif name in deferred_names:
            exposure = ToolExposure.DEFERRED.value
        else:
            exposure = f"hidden:{hidden_reason.get(name, HiddenReason.CONTEXT_BUDGET).value}"
        entries.append(
            SnapshotEntry(
                namespace=spec.namespace,
                canonical_name=name,
                version=spec.version,
                exposure=exposure,
                risk_level=str(spec.risk_level),
                approval_mode=str(spec.approval_mode),
                executor_kind=str(spec.executor_kind),
                side_effect_class=str(spec.side_effect_class),
                health_check_id=spec.health_check_id,
            )
        )
    return ToolSnapshot(
        tool_plan_id=plan.tool_plan_id,
        direct_total=len(plan.direct_tools),
        deferred_total=len(plan.deferred_tools),
        hidden_total=len(plan.hidden_tools),
        entries=tuple(entries),
        catalog_hash=plan.catalog_hash,
        visible_hash=plan.visible_hash,
        model_profile_hash=plan.model_profile_hash,
        policy_hash=plan.policy_hash,
    )

