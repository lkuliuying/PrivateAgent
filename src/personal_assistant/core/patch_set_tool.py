"""v0.7.0 E1：PatchSet 工具注册（propose_patch_set / apply_patch_set）。

契约见 ``agents/patchset_contracts.py``（E0 冻结），executor 委托
``core/patch_set_service``。两个工具绑定 run（构造时接收 db + run_id）：

- ``propose_patch_set``：safe + idempotent，只读零写入；
- ``apply_patch_set``：confirm + non_idempotent，消费 ToolApproval 后原子
  应用；崩溃/unknown 状态由 dispatcher 的 execution claim 与 repository
  状态检查双重阻止自动重放（T8/T12）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.runtime import CancellationToken
from ..agents.tools import (
    ToolCapability,
    ToolDispatchCancelled,
    ToolIdempotency,
    ToolRedactionPolicy,
    ToolRiskLevel,
    ToolSpec,
    VersionedToolRegistry,
)
from .patch_set_service import PatchSetService

# 契约层用下划线别名（E0 冻结的字符串），工具层映射到 ToolCapability 枚举
_CAPABILITY_ALIASES = {
    "filesystem_read": ToolCapability.FILESYSTEM_READ,
    "filesystem_write": ToolCapability.FILESYSTEM_WRITE,
    "process_execute": ToolCapability.PROCESS_EXECUTE,
    "network_fetch": ToolCapability.NETWORK_FETCH,
    "database_query": ToolCapability.DATABASE_QUERY,
}

_DESCRIPTIONS = {
    "propose_patch_set": (
        "为当前 coding run 的 workspace 生成多文件 PatchSet 预览；"
        "只读零写入。返回 patch_set_id / preview_version / parameters_hash "
        "供 apply_patch_set 强校验；truncated=true 时不能应用，必须拆分重试。"
    ),
    "apply_patch_set": (
        "原子应用已预览的多文件 PatchSet（需用户审批）。参数必须与预览一致"
        "（preview_version + expected_parameters_hash）；磁盘 SHA 或 Git HEAD "
        "漂移会失败关闭；冲突或回读不一致会完整回滚；无法完整回滚时标记 "
        "partial_unknown 并禁止自动续跑，只能人工处置。"
    ),
}


def build_patch_set_tool_registry(
    db: AsyncSession, run_id: str
) -> VersionedToolRegistry:
    """构造绑定到指定 run 的 PatchSet 工具注册表。"""
    from ..agents.patchset_contracts import PATCHSET_TOOL_CONTRACTS

    registry = VersionedToolRegistry()
    for contract in PATCHSET_TOOL_CONTRACTS:
        registry.register(_build_spec(db, run_id, contract))
    return registry


def _build_spec(db: AsyncSession, run_id: str, contract) -> ToolSpec:
    service = PatchSetService(db)

    async def execute(
        arguments: dict[str, Any], cancellation: CancellationToken
    ) -> dict[str, Any]:
        if cancellation.is_cancelled:
            raise ToolDispatchCancelled("工具执行已取消")
        if contract.name == "propose_patch_set":
            return await service.propose(run_id, arguments["operations"])
        return await service.apply(
            run_id,
            arguments["patch_set_id"],
            arguments["preview_version"],
            arguments["expected_parameters_hash"],
        )

    return ToolSpec(
        name=contract.name,
        version=contract.version,
        description=_DESCRIPTIONS[contract.name],
        input_schema=contract.input_schema,
        output_schema=contract.output_schema,
        risk_level=ToolRiskLevel(contract.risk_level),
        required_capabilities=frozenset(
            _CAPABILITY_ALIASES[name] for name in contract.required_capabilities
        ),
        timeout_ms=contract.timeout_ms,
        max_input_bytes=contract.max_input_bytes,
        max_output_bytes=contract.max_output_bytes,
        idempotency=ToolIdempotency(contract.idempotency),
        supports_cancellation=contract.supports_cancellation,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        executor=execute,
    )
