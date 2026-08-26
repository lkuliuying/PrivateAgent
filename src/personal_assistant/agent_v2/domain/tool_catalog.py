"""ToolSpec v2 领域契约（专项计划 §7.1 / CT2-01 / ADR-008）。

现有 v0.9 ``ToolSpec``（agents/tools.py）保留执行器语义不动；本模块是
v2 Catalog/Planner 使用的**纯元数据契约**（不含 executor），按 §7.1 扩展
namespace/exposure/maturity/effects/approval/network/parallel 等字段。

红线（ADR-008）：
- 注册成功 ≠ 可暴露；暴露决策在 application/planner，且只决定可见性，
  不扩大 capability/approval/sandbox 权限；
- Provider 别名必须可逆；跨工具别名冲突由 Catalog 在模型调用前拒绝。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .effects import EffectClass


class ToolExposure(StrEnum):
    """暴露状态：direct=直接下发 Schema；deferred=可被 search_tools 检索；
    hidden=本轮不发给模型（不代表未注册、不代表自动批准）。"""

    DIRECT = "direct"
    DEFERRED = "deferred"
    HIDDEN = "hidden"


class ToolMaturity(StrEnum):
    STABLE = "stable"
    BETA = "beta"
    EXPERIMENTAL = "experimental"
    DISABLED = "disabled"


class SideEffectClass(StrEnum):
    NONE = "none"
    FILESYSTEM = "filesystem"
    PROCESS = "process"
    NETWORK = "network"
    DATABASE = "database"
    EXTERNAL = "external"


class ApprovalMode(StrEnum):
    """auto 仅允许只读无副作用工具（§12.2）；deny 不暴露不调用。"""

    AUTO = "auto"
    PROMPT = "prompt"
    WRITES = "writes"
    ALWAYS = "always"
    DENY = "deny"


class NetworkPolicy(StrEnum):
    NONE = "none"
    ALLOWLIST = "allowlist"
    APPROVED = "approved"
    UNRESTRICTED = "unrestricted"


class ExecutorKind(StrEnum):
    PYTHON = "python"
    EXEC_HOST = "exec_host"
    MCP = "mcp"
    PROVIDER_NATIVE = "provider_native"


class ToolIdempotency(StrEnum):
    IDEMPOTENT = "idempotent"
    NON_IDEMPOTENT = "non_idempotent"


class ToolRiskLevel(StrEnum):
    SAFE = "safe"
    CONFIRM = "confirm"
    RESTRICTED = "restricted"


# 副作用大类 → 允许声明的 effect 集合（external 为外部不透明调用，效果
# 由 MCP 自报+配置共同决定，不允许自声明落盘类 effect）。
_SIDE_EFFECT_ALLOWED_EFFECTS: dict[SideEffectClass, frozenset[EffectClass]] = {
    SideEffectClass.NONE: frozenset(),
    SideEffectClass.FILESYSTEM: frozenset(
        {
            EffectClass.FILESYSTEM_READ,
            EffectClass.FILESYSTEM_WRITE,
            EffectClass.FILESYSTEM_DELETE,
            EffectClass.FILESYSTEM_RENAME,
        }
    ),
    SideEffectClass.PROCESS: frozenset(
        {EffectClass.PROCESS_SPAWN, EffectClass.PROCESS_EXIT}
    ),
    SideEffectClass.NETWORK: frozenset({EffectClass.NETWORK_REQUEST}),
    SideEffectClass.DATABASE: frozenset({EffectClass.DATABASE_QUERY}),
    SideEffectClass.EXTERNAL: frozenset(),
}

_CANONICAL_NAME_PATTERN = r"^[a-z0-9][a-z0-9_.-]{0,127}$"
_VERSION_PATTERN = r"^\d+\.\d+\.\d+$"
_NAMESPACE_PATTERN = (
    r"^(builtin|project|mcp\.[a-z0-9][a-z0-9_-]{0,63}|"
    r"extension\.[a-z0-9][a-z0-9_-]{0,63})$"
)


class ModelRequirements(BaseModel):
    """模型能力条件（§7.1 model_requirements）。未知能力失败关闭：
    默认仅要求 function calling；freeform patch/vision/并行显式声明。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    function_calling: bool = True
    freeform_patch: bool = False
    vision: bool = False
    parallel_tool_calls: bool = False


class ToolSource(BaseModel):
    """来源登记（provenance）。不含 secret；上游复用记录 commit 与许可证
    （docs/third-party/codex-adoption-manifest.md）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    component: str = Field(min_length=1, max_length=128)
    version: str | None = Field(default=None, max_length=64)
    upstream_commit: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{40}$|^$"
    )
    license_id: str | None = Field(default=None, max_length=64)


class ToolSpecV2(BaseModel):
    """一个活跃工具版本的完整 v2 元数据（不可变）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: str = Field(pattern=_NAMESPACE_PATTERN)
    canonical_name: str = Field(pattern=_CANONICAL_NAME_PATTERN)
    version: str = Field(pattern=_VERSION_PATTERN)
    description: str = Field(min_length=1, max_length=8_000)
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]

    # Provider 可见别名：provider → 可见名；值在单工具内不得重复（可逆）。
    model_aliases: Mapping[str, str] = Field(default_factory=dict)

    exposure: ToolExposure = ToolExposure.DIRECT
    maturity: ToolMaturity = ToolMaturity.STABLE
    risk_level: ToolRiskLevel = ToolRiskLevel.SAFE

    side_effect_class: SideEffectClass = SideEffectClass.NONE
    effects: frozenset[EffectClass] = frozenset()
    approval_mode: ApprovalMode = ApprovalMode.AUTO
    sandbox_profile: str | None = Field(default=None, max_length=64)
    network_policy: NetworkPolicy = NetworkPolicy.NONE

    idempotency: ToolIdempotency = ToolIdempotency.IDEMPOTENT
    parallel_safe: bool = False
    streaming_output: bool = False
    supports_cancellation: bool = False

    executor_kind: ExecutorKind = ExecutorKind.PYTHON
    required_capabilities: frozenset[str] = frozenset()
    feature_flag: str | None = Field(default=None, max_length=64)
    intent_tags: frozenset[str] = frozenset()
    health_check_id: str | None = Field(default=None, max_length=64)

    model_requirements: ModelRequirements = Field(default_factory=ModelRequirements)
    verifier_ids: tuple[str, ...] = ()
    completion_evidence: tuple[EffectClass, ...] = ()
    source: ToolSource = Field(
        default_factory=lambda: ToolSource(component="personal_assistant/builtin")
    )

    @field_validator("model_aliases")
    @classmethod
    def _validate_aliases(cls, value: Mapping[str, str]) -> dict[str, str]:
        aliases = dict(value)
        seen_values: set[str] = set()
        for provider, alias in aliases.items():
            if not provider or len(provider) > 64:
                raise ValueError("model_aliases 的 provider 键长度必须是 1..64")
            if not 1 <= len(alias) <= 64:
                raise ValueError(f"Provider 别名长度必须是 1..64：{provider}")
            if alias.casefold() in seen_values:
                raise ValueError(
                    f"model_aliases 不是可逆映射：别名重复 {alias!r}"
                )
            seen_values.add(alias.casefold())
        return aliases

    @model_validator(mode="after")
    def _validate_effect_consistency(self) -> "ToolSpecV2":
        allowed = _SIDE_EFFECT_ALLOWED_EFFECTS[self.side_effect_class]
        illegal = self.effects - allowed
        if illegal:
            raise ValueError(
                f"effects {sorted(e.value for e in illegal)} 与副作用大类 "
                f"{self.side_effect_class.value} 不一致"
            )
        if self.approval_mode == ApprovalMode.AUTO and self.side_effect_class != (
            SideEffectClass.NONE
        ):
            raise ValueError(
                "approval_mode=auto 仅允许无副作用工具（§12.2）"
            )
        if self.maturity == ToolMaturity.DISABLED and self.exposure != (
            ToolExposure.HIDDEN
        ):
            raise ValueError("maturity=disabled 的工具只能处于 hidden 暴露")
        if ApprovalMode.DENY == self.approval_mode and self.exposure != (
            ToolExposure.HIDDEN
        ):
            raise ValueError("approval_mode=deny 的工具不能对模型暴露")
        return self

    def alias_for(self, provider: str) -> str:
        """Provider 可见名：显式别名优先，缺省用 canonical_name。"""
        return self.model_aliases.get(provider, self.canonical_name)

    @property
    def catalog_key(self) -> tuple[str, str, str]:
        return (self.namespace, self.canonical_name, self.version)

    def is_parallel_eligible(self) -> bool:
        """AD-T07 安全并发条件：全部满足才可与其它合格只读工具并发。"""
        return (
            self.parallel_safe
            and self.side_effect_class == SideEffectClass.NONE
            and self.idempotency == ToolIdempotency.IDEMPOTENT
            and self.approval_mode == ApprovalMode.AUTO
            and not self.streaming_output
        )
