"""MCP server 目录 → v2 Tool Catalog 投影（专项计划 §12.1/§12.2、CT-7）。

把受信、已启用的 MCP server 的已发现工具投影为 ``ToolSpecV2``，供
ToolPlan/ToolSnapshot 与诊断 API 解释"模型看到什么、为什么"。执行语义
仍在 v0.9 ``mcp/manager.py``；本模块只描述可见性与审批模式，不扩大权限。

规则（§12.1/§12.2）：
- namespace = ``mcp.<server_id>``；canonical_name 是原始工具名的稳定
  规范化；Provider 可见别名复用 v0.9 的 ``mcp_<server>_<tool>_<slug>``
  命名（可逆）；
- discovery 过期（超 TTL 或连接身份变化）的工具携带 ``health_check_id``
  并入返回的失败集合——调用方把它放进 PolicySnapshot.health_failed，
  planner 给出稳定原因 ``hidden:health_failed``（失败关闭）；
- 审批模式为 ``deny`` 的工具以哨兵能力投影，由 capability policy 给出
  稳定原因 ``hidden:policy_denied``（不暴露、不调用）。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Sequence

from personal_assistant.core.models import McpServer
from personal_assistant.mcp.contracts import McpApprovalMode, McpTransport
from personal_assistant.mcp.manager import (
    DISCOVERY_CACHE_TTL_SECONDS,
    _provider_tool_name,
    _tool_version,
    discovery_is_fresh,
    resolve_tool_approval_mode,
)
from personal_assistant.mcp.repository import server_config

from ..domain.tool_catalog import (
    ApprovalMode,
    ExecutorKind,
    NetworkPolicy,
    SideEffectClass,
    ToolExposure,
    ToolIdempotency,
    ToolMaturity,
    ToolRiskLevel,
    ToolSource,
    ToolSpecV2,
)

_SLUG = re.compile(r"[^a-z0-9_.-]+")

#: deny 工具的哨兵能力：不在任何授权集合内 → planner 稳定原因
#: ``policy_denied``。诊断口径专用，不进入执行面。
_DENY_SENTINEL_CAPABILITY = "mcp.tool.denied"

_APPROVAL_BY_MODE = {
    McpApprovalMode.AUTO: ApprovalMode.AUTO,
    McpApprovalMode.PROMPT: ApprovalMode.PROMPT,
    McpApprovalMode.WRITES: ApprovalMode.WRITES,
    McpApprovalMode.ALWAYS: ApprovalMode.ALWAYS,
    McpApprovalMode.DENY: ApprovalMode.DENY,
}


def _canonical_tool_name(original_name: str, *, seen: set[str]) -> str:
    """原始工具名 → 稳定规范化（冲突时附 hash 后缀，保持可逆区分）。"""
    slug = _SLUG.sub("_", original_name.lower()).strip("_")[:100] or "tool"
    if not slug[0].isalnum():
        slug = f"t_{slug}"
    if slug in seen:
        digest = hashlib.sha256(original_name.encode("utf-8")).hexdigest()[:8]
        slug = f"{slug[:91]}_{digest}"
    seen.add(slug)
    return slug


def build_mcp_catalog_specs(
    records: Sequence[McpServer],
    *,
    discovery_ttl_seconds: int = DISCOVERY_CACHE_TTL_SECONDS,
    now: datetime | None = None,
) -> tuple[list[ToolSpecV2], frozenset[str]]:
    """投影全部受信/启用/已发现/允许清单内的工具。

    返回 ``(specs, health_failed_ids)``：``health_failed_ids`` 是 discovery
    过期（超 TTL 或连接身份变化）server 的 ``health_check_id`` 集合，
    调用方应放入 ``PolicySnapshot.health_failed``（失败关闭）。
    """
    specs: list[ToolSpecV2] = []
    health_failed: set[str] = set()
    for record in records:
        config = server_config(record)
        if not (config.trusted and config.enabled):
            continue
        if not record.discovery_tools_json:
            continue
        namespace = f"mcp.{config.id.lower()}"
        health_check_id = f"mcp.{config.id.lower()}"
        # 健康失败（§7.7 tool_health_failed）：status=error 的 server 与
        # 过期/身份变化的目录同口径失败关闭。
        healthy = record.status != "error"
        fresh = discovery_is_fresh(record, ttl_seconds=discovery_ttl_seconds, now=now)
        if not fresh or not healthy:
            health_failed.add(health_check_id)
        seen_names: set[str] = set()
        discovered = {
            str(tool.get("name")): tool
            for tool in (record.discovery_tools_json or [])
            if isinstance(tool, dict) and tool.get("name")
        }
        for original_name in sorted(config.allowed_tools):
            tool = discovered.get(original_name)
            if not isinstance(tool, dict):
                continue
            approval_mode = resolve_tool_approval_mode(config, original_name)
            denied = approval_mode == McpApprovalMode.DENY
            canonical = _canonical_tool_name(original_name, seen=seen_names)
            # §12.2：auto 仅限显式配置；投影为无副作用（契约要求），
            # 决策来源是受信配置而非 MCP 自报只读声明。
            side_effect = (
                SideEffectClass.NONE
                if approval_mode == McpApprovalMode.AUTO
                else SideEffectClass.EXTERNAL
            )
            input_schema = tool.get("input_schema")
            if not isinstance(input_schema, dict):
                input_schema = {"type": "object", "properties": {}}
            specs.append(
                ToolSpecV2(
                    namespace=namespace,
                    canonical_name=canonical,
                    version=_tool_version(tool),
                    description=(
                        "UNTRUSTED MCP TOOL METADATA. "
                        f"Server tool {original_name}（外部不可信数据）。"
                    )[:8_000],
                    input_schema=dict(input_schema),
                    output_schema={"type": "object", "properties": {}},
                    model_aliases={
                        "default": _provider_tool_name(config, original_name)
                    },
                    exposure=ToolExposure.HIDDEN if denied else ToolExposure.DIRECT,
                    maturity=ToolMaturity.STABLE,
                    risk_level=(
                        ToolRiskLevel.SAFE
                        if approval_mode == McpApprovalMode.AUTO
                        else ToolRiskLevel.CONFIRM
                    ),
                    side_effect_class=side_effect,
                    effects=frozenset(),
                    approval_mode=_APPROVAL_BY_MODE[approval_mode],
                    network_policy=(
                        NetworkPolicy.NONE
                        if config.transport == McpTransport.STDIO
                        else NetworkPolicy.ALLOWLIST
                    ),
                    idempotency=ToolIdempotency.NON_IDEMPOTENT,
                    supports_cancellation=True,
                    executor_kind=ExecutorKind.MCP,
                    required_capabilities=(
                        frozenset({_DENY_SENTINEL_CAPABILITY})
                        if denied
                        else frozenset({"external.mcp"})
                    ),
                    health_check_id=health_check_id,
                    intent_tags=frozenset({"external.mcp"}),
                    source=ToolSource(
                        component=f"mcp:{config.name[:96]}",
                        license_id=None,
                    ),
                )
            )
    return specs, frozenset(health_failed)
