"""当前 workspace 配置 → v2 Tool Catalog 投影（CT-2 适配项 / CT-9 诊断）。

把 v0.9 已审计的工作流/只读工具按冻结元数据表投影为 ``ToolSpecV2``，
供 ToolPlan/ToolSnapshot 与诊断 API 使用。执行语义仍在 v0.9 handler；
本表只描述"模型看到什么、为什么"。

feature_flag 名与 ``get_agent_tool_bundle`` 的注册开关一一对应：
read_only_tools / patch_workflow / command_workflow / http_workflow /
sql_readonly / coding_patchset。
"""

from __future__ import annotations

from typing import Any, Mapping

from ..domain.effects import EffectClass
from ..domain.tool_catalog import (
    ApprovalMode,
    ExecutorKind,
    NetworkPolicy,
    SideEffectClass,
    ToolExposure,
    ToolIdempotency,
    ToolMaturity,
    ToolRiskLevel,
    ToolSpecV2,
)
from .catalog import ToolCatalog

_MIN_SCHEMA: Mapping[str, Any] = {"type": "object", "properties": {}}


def _entry(
    name: str,
    description: str,
    *,
    risk: str,
    caps: frozenset[str],
    side_effect_class: str,
    effects: frozenset[str],
    feature_flag: str,
    idempotent: bool = True,
    intent_tags: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "risk": risk,
        "caps": caps,
        "side_effect_class": side_effect_class,
        "effects": effects,
        "feature_flag": feature_flag,
        "idempotent": idempotent,
        "intent_tags": intent_tags,
    }


# 冻结的 workspace 工具元数据（与 agents/workflow_contracts.py、
# core/tool_adapter.py 的已审计契约一致；新增工具必须先改契约再改本表）。
WORKSPACE_TOOL_METADATA: tuple[dict[str, Any], ...] = (
    _entry(
        "search_files",
        "按关键词搜索项目内代码文件内容（只读索引查询）",
        risk="safe", caps=frozenset({"database.query"}),
        side_effect_class="none", effects=frozenset(),
        feature_flag="read_only_tools",
        intent_tags=("code.inspect",),
    ),
    _entry(
        "list_directory",
        "列出项目内目录条目",
        risk="safe", caps=frozenset({"filesystem.read", "database.query"}),
        side_effect_class="filesystem", effects=frozenset({"filesystem.read"}),
        feature_flag="read_only_tools",
        intent_tags=("code.inspect",),
    ),
    _entry(
        "grep_code",
        "在项目内做正则内容扫描",
        risk="safe", caps=frozenset({"filesystem.read", "database.query"}),
        side_effect_class="filesystem", effects=frozenset({"filesystem.read"}),
        feature_flag="read_only_tools",
        intent_tags=("code.inspect",),
    ),
    _entry(
        "read_code_file",
        "读取项目内单个源码文件的指定行区间",
        risk="confirm", caps=frozenset({"filesystem.read", "database.query"}),
        side_effect_class="filesystem", effects=frozenset({"filesystem.read"}),
        feature_flag="read_only_tools",
        intent_tags=("code.inspect",),
    ),
    _entry(
        "propose_patch",
        "生成单文件替换式 diff 预览；只读，不写盘",
        risk="safe", caps=frozenset({"filesystem.read"}),
        side_effect_class="filesystem", effects=frozenset({"filesystem.read"}),
        feature_flag="read_only_tools",
        intent_tags=("file.preview", "file.mutate"),
    ),
    _entry(
        "apply_patch_to_workspace",
        "审批后原子写入单个项目文件并回读核对 SHA",
        risk="confirm", caps=frozenset({"filesystem.read", "filesystem.write"}),
        side_effect_class="filesystem",
        effects=frozenset({"filesystem.read", "filesystem.write"}),
        feature_flag="patch_workflow", idempotent=False,
        intent_tags=("file.mutate",),
    ),
    _entry(
        "run_whitelisted_command",
        "运行白名单测试/构建/只读诊断命令（参数数组，不经 shell）",
        risk="confirm", caps=frozenset({"process.execute", "filesystem.read"}),
        side_effect_class="process",
        effects=frozenset({"process.spawn", "process.exit"}),
        feature_flag="command_workflow", idempotent=False,
        intent_tags=("command.run", "command.test"),
    ),
    _entry(
        "call_allowlisted_api",
        "按已启用 endpoint profile 调用固定 HTTPS 目标",
        risk="confirm", caps=frozenset({"network.fetch"}),
        side_effect_class="network", effects=frozenset({"network.request"}),
        feature_flag="http_workflow", idempotent=True,
        intent_tags=("network.read", "network.write"),
    ),
    _entry(
        "query_readonly_sql",
        "执行只读 SQL（SELECT/EXPLAIN/SHOW）",
        risk="confirm", caps=frozenset({"database.query"}),
        side_effect_class="database", effects=frozenset({"database.query"}),
        feature_flag="sql_readonly",
        intent_tags=("database.read",),
    ),
)

_RISK_BY_VALUE = {item.value: item for item in ToolRiskLevel}


def _approval_mode(risk: str, side_effect_class: str) -> ApprovalMode:
    if risk == "safe" and side_effect_class == "none":
        return ApprovalMode.AUTO
    return ApprovalMode.PROMPT


def build_workspace_catalog(*, enabled_flags: frozenset[str]) -> ToolCatalog:
    """按启用 flag 投影 catalog；flag 关闭的工具仍入册但标记
    feature_flag（由 planner 标记 hidden:feature_disabled），保证诊断视图
    能解释"为什么不可见"。maturity=disabled 的条目不进入。"""
    specs: list[ToolSpecV2] = []
    for entry in WORKSPACE_TOOL_METADATA:
        specs.append(
            ToolSpecV2(
                namespace="builtin",
                canonical_name=str(entry["name"]),
                version="1.0.0",
                description=str(entry["description"]),
                input_schema=dict(_MIN_SCHEMA),
                output_schema=dict(_MIN_SCHEMA),
                exposure=ToolExposure.DIRECT,
                maturity=ToolMaturity.STABLE,
                risk_level=_RISK_BY_VALUE[str(entry["risk"])],
                side_effect_class=SideEffectClass(str(entry["side_effect_class"])),
                effects=frozenset(EffectClass(e) for e in entry["effects"]),  # type: ignore[arg-type]
                approval_mode=_approval_mode(
                    str(entry["risk"]), str(entry["side_effect_class"])
                ),
                network_policy=NetworkPolicy.ALLOWLIST
                if str(entry["side_effect_class"]) == "network"
                else NetworkPolicy.NONE,
                idempotency=(
                    ToolIdempotency.IDEMPOTENT
                    if bool(entry["idempotent"])
                    else ToolIdempotency.NON_IDEMPOTENT
                ),
                executor_kind=ExecutorKind.PYTHON,
                required_capabilities=frozenset(entry["caps"]),  # type: ignore[arg-type]
                feature_flag=str(entry["feature_flag"]),
                intent_tags=frozenset(entry["intent_tags"]),
            )
        )
    return ToolCatalog.build(specs)


def workspace_enabled_flags(cfg_like) -> frozenset[str]:
    """从 settings 投影启用的 feature flag 名。"""
    enabled: set[str] = set()
    if getattr(cfg_like, "agent_run_read_only_tools_enabled", False):
        enabled.add("read_only_tools")
    if getattr(cfg_like, "agent_patch_workflow_enabled", False):
        enabled.add("patch_workflow")
    if getattr(cfg_like, "agent_command_workflow_enabled", False):
        enabled.add("command_workflow")
    if getattr(cfg_like, "agent_http_workflow_enabled", False):
        enabled.add("http_workflow")
    if getattr(cfg_like, "agent_sql_readonly_workflow_enabled", False):
        enabled.add("sql_readonly")
    if getattr(cfg_like, "coding_patchset_enabled", False):
        enabled.add("coding_patchset")
    return frozenset(enabled)
