"""工具名 → EffectClass 冻结映射（专项计划 §7.6 / CT1-05）。

可信契约表：只登记 v0.9 工作流工具的声明副作用；未知/MCP 工具返回空集
——仍可充当"执行过工具"的证据，但不满足任何 required effect
（外部自报不作为落盘证据，ADR-007 §3）。
"""

from __future__ import annotations

from ..domain.effects import EffectClass

WORKFLOW_TOOL_EFFECTS: dict[str, tuple[EffectClass, ...]] = {
    # 只读预览：无落盘副作用（B0 契约：propose 只声明 filesystem.read）。
    "propose_patch": (EffectClass.FILESYSTEM_READ,),
    "propose_patch_set": (EffectClass.FILESYSTEM_READ,),
    # 审批写入：handler 原子替换 + 回读 SHA 核对（verified 标志）。
    "apply_patch_to_workspace": (
        EffectClass.FILESYSTEM_WRITE,
        EffectClass.FILESYSTEM_READ,
    ),
    "apply_patch_set": (
        EffectClass.FILESYSTEM_WRITE,
        EffectClass.FILESYSTEM_DELETE,
        EffectClass.FILESYSTEM_RENAME,
        EffectClass.FILESYSTEM_READ,
    ),
    # 白名单命令：进程事实由命令工作流持久化。
    "run_whitelisted_command": (
        EffectClass.PROCESS_SPAWN,
        EffectClass.PROCESS_EXIT,
    ),
    "call_allowlisted_api": (EffectClass.NETWORK_REQUEST,),
    "query_readonly_sql": (EffectClass.DATABASE_QUERY,),
}


def effects_for_tool(tool_name: str) -> tuple[EffectClass, ...]:
    """未知工具返回空集（诚实未知，失败关闭）。"""
    return WORKFLOW_TOOL_EFFECTS.get(tool_name or "", ())
