"""Preflight Gate：模型调用前的必需副作用预检（专项计划 §7.4/CT1-04/F-002）。

规则（ADR-007 §4）：明确的 file.mutate 意图在本轮没有任何可真正落盘的
工具入口时，run 创建即结构化失败——不调用模型、不产生任何磁盘变更，
并给出可诊断的公开原因（§14.3 话术模板）。

预检只做"能力是否存在"的判断：它不能授予任何权限，也不能用提示词
掩盖缺失工具。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ..domain.effects import EffectClass


class PreflightErrorCode(StrEnum):
    """公开错误码（专项计划 §7.7 冻结子集）。"""

    TOOL_CAPABILITY_UNAVAILABLE = "tool_capability_unavailable"
    TOOL_MODEL_UNSUPPORTED = "tool_model_unsupported"
    TOOL_HEALTH_FAILED = "tool_health_failed"
    EXECUTOR_UNAVAILABLE = "executor_unavailable"
    SANDBOX_POLICY_UNAVAILABLE = "sandbox_policy_unavailable"


class PreflightBlocker(BaseModel):
    """一个被阻断的必需 effect 及其低敏感原因。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    effect: EffectClass
    error_code: PreflightErrorCode
    reason: str = Field(min_length=1, max_length=500)


class PreflightDecision(BaseModel):
    """预检结论。``blocked=False`` 时其余字段为空。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    blocked: bool
    error_code: str | None = None
    public_message: str | None = Field(default=None, max_length=2_000)
    blockers: tuple[PreflightBlocker, ...] = ()


_OK = PreflightDecision(blocked=False)


def _public_message(blockers: tuple[PreflightBlocker, ...]) -> str:
    """§14.3 话术模板；只含公开原因，不含内部路径/堆栈。"""
    reasons = "；".join(blocker.reason for blocker in blockers[:4])
    return (
        "任务未执行：本轮没有可用的文件写入工具。"
        f"原因：{reasons}。未对磁盘进行任何更改。"
    )


def assess_required_effects(
    required_effects,
    *,
    providers: dict[str, list[str]] | None = None,
    unavailable_executors: frozenset[str] = frozenset(),
    unhealthy_executors: frozenset[str] = frozenset(),
    sandbox_ready: bool = True,
) -> PreflightDecision:
    """通用预检：每个 required effect 至少存在一个可用提供者。

    ``providers``：effect 值 → 提供该 effect 的 executor_kind 列表
    （按本轮 ToolPlan/exposure 结论投影）。无提供者 →
    tool_capability_unavailable；提供者全部健康失败 → tool_health_failed；
    提供者执行器离线 → executor_unavailable；需要 sandbox 而沙箱不可用 →
    sandbox_policy_unavailable。
    """
    effects = sorted(required_effects, key=lambda item: item.value)
    if not effects:
        return _OK
    provider_map = providers or {}
    blockers: list[PreflightBlocker] = []
    for effect in effects:
        kinds = provider_map.get(effect.value, [])
        if not kinds:
            blockers.append(
                PreflightBlocker(
                    effect=effect,
                    error_code=PreflightErrorCode.TOOL_CAPABILITY_UNAVAILABLE,
                    reason=f"本轮没有任何可提供 {effect.value} 的已暴露工具",
                )
            )
            continue
        if all(kind in unhealthy_executors for kind in kinds):
            blockers.append(
                PreflightBlocker(
                    effect=effect,
                    error_code=PreflightErrorCode.TOOL_HEALTH_FAILED,
                    reason=(
                        f"{effect.value} 的提供者健康检查/目录新鲜度失败"
                        f"（{', '.join(sorted(kinds))}）"
                    ),
                )
            )
            continue
        if all(kind in unavailable_executors for kind in kinds):
            blockers.append(
                PreflightBlocker(
                    effect=effect,
                    error_code=PreflightErrorCode.EXECUTOR_UNAVAILABLE,
                    reason=(
                        f"{effect.value} 的执行器离线"
                        f"（{', '.join(sorted(kinds))}）"
                    ),
                )
            )
            continue
        if not sandbox_ready and any(kind == "exec_host" for kind in kinds):
            blockers.append(
                PreflightBlocker(
                    effect=effect,
                    error_code=PreflightErrorCode.SANDBOX_POLICY_UNAVAILABLE,
                    reason=f"{effect.value} 需要的沙箱策略不可用",
                )
            )
    if not blockers:
        return _OK
    code = min(blocker.error_code.value for blocker in blockers)
    return PreflightDecision(
        blocked=True,
        error_code=code,
        public_message=_public_message(tuple(blockers)),
        blockers=tuple(blockers),
    )


def workspace_write_tool_names(
    *,
    patch_workflow_enabled: bool,
    patchset_enabled: bool,
    permission_mode: str | None,
) -> tuple[str, ...]:
    """当前配置/权限下真正会注册给模型的落盘工具名（v0.9 注册表口径）。

    与 get_agent_tool_bundle 的注册规则一致：readonly 权限不注册任何写工具；
    apply_patch_to_workspace 受 PA_AGENT_PATCH_WORKFLOW_ENABLED 控制，
    apply_patch_set 受项目 PatchSet 开关控制。
    """
    if permission_mode == "readonly":
        return ()
    names: list[str] = []
    if patch_workflow_enabled:
        names.append("apply_patch_to_workspace")
    if patchset_enabled:
        names.append("apply_patch_set")
    return tuple(names)


def assess_workspace_file_write(
    *,
    patch_workflow_enabled: bool,
    patchset_enabled: bool,
    permission_mode: str | None,
    model_supports_tools: bool,
) -> PreflightDecision:
    """file.mutate 意图的 v0.9 主链预检（F-002）。

    失败关闭顺序：模型不支持工具协议 > 写工作流未启用/权限只读。
    """
    if not model_supports_tools:
        blocker = PreflightBlocker(
            effect=EffectClass.FILESYSTEM_WRITE,
            error_code=PreflightErrorCode.TOOL_MODEL_UNSUPPORTED,
            reason="当前模型不支持本轮工具协议（native tool calls 未启用）",
        )
        return PreflightDecision(
            blocked=True,
            error_code=blocker.error_code.value,
            public_message=_public_message((blocker,)),
            blockers=(blocker,),
        )
    write_tools = workspace_write_tool_names(
        patch_workflow_enabled=patch_workflow_enabled,
        patchset_enabled=patchset_enabled,
        permission_mode=permission_mode,
    )
    if write_tools:
        return _OK
    reasons: list[str] = []
    if permission_mode == "readonly":
        reasons.append("当前 run 为只读权限模式，未授予文件写入能力")
    if not patch_workflow_enabled and not patchset_enabled:
        reasons.append(
            "文件写入工作流未启用"
            "（PA_AGENT_PATCH_WORKFLOW_ENABLED / 项目 PatchSet 开关均关闭）"
        )
    elif not patch_workflow_enabled:
        reasons.append("单文件写入工作流未启用（PA_AGENT_PATCH_WORKFLOW_ENABLED）")
    else:
        reasons.append("多文件 PatchSet 工作流未启用")
    blocker = PreflightBlocker(
        effect=EffectClass.FILESYSTEM_WRITE,
        error_code=PreflightErrorCode.TOOL_CAPABILITY_UNAVAILABLE,
        reason="；".join(reasons) or "没有已暴露的文件写入工具",
    )
    return PreflightDecision(
        blocked=True,
        error_code=blocker.error_code.value,
        public_message=_public_message((blocker,)),
        blockers=(blocker,),
    )
