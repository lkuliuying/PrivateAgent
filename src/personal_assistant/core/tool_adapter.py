"""Adapters from the legacy tool registry to versioned Agent ToolSpec objects."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.executions import ToolExecutionRepository
from ..agents.runtime import CancellationToken
from ..agents.tools import (
    ToolCapability,
    ToolCapabilityPolicy,
    ToolIdempotency,
    ToolRedactionPolicy,
    ToolRiskLevel,
    ToolSpec,
    ValidatedToolDispatcher,
    VersionedToolRegistry,
)
from .tools import ToolContext, ToolDefinition, ToolRegistry, default_registry


@dataclass(frozen=True, slots=True)
class _ReadOnlyToolDefaults:
    timeout_ms: int
    max_output_bytes: int
    supports_cancellation: bool
    capabilities: frozenset[ToolCapability]
    risk_level: ToolRiskLevel = ToolRiskLevel.SAFE


_READ_ONLY_TOOL_DEFAULTS: Mapping[str, _ReadOnlyToolDefaults] = {
    # Parsing PDF/DOCX and reading files use worker threads that cannot be
    # forcibly stopped once started. Access remains approval-gated because an
    # authorized path may still contain sensitive local data.
    "read_file": _ReadOnlyToolDefaults(
        30_000,
        256 * 1024,
        False,
        frozenset(
            {ToolCapability.FILESYSTEM_READ, ToolCapability.DATABASE_QUERY}
        ),
        ToolRiskLevel.CONFIRM,
    ),
    "search_files": _ReadOnlyToolDefaults(
        10_000,
        256 * 1024,
        True,
        frozenset({ToolCapability.DATABASE_QUERY}),
    ),
    # asyncio.to_thread work cannot stop the worker thread after cancellation.
    "grep_code": _ReadOnlyToolDefaults(
        20_000,
        256 * 1024,
        False,
        frozenset({ToolCapability.FILESYSTEM_READ, ToolCapability.DATABASE_QUERY}),
    ),
    "read_code_file": _ReadOnlyToolDefaults(
        20_000,
        256 * 1024,
        False,
        frozenset(
            {ToolCapability.FILESYSTEM_READ, ToolCapability.DATABASE_QUERY}
        ),
        ToolRiskLevel.CONFIRM,
    ),
    # The legacy git helper has timeout protection but no CancelledError process cleanup yet.
    "get_git_status": _ReadOnlyToolDefaults(
        20_000,
        128 * 1024,
        False,
        frozenset(
            {
                ToolCapability.FILESYSTEM_READ,
                ToolCapability.PROCESS_EXECUTE,
                ToolCapability.DATABASE_QUERY,
            }
        ),
    ),
    "get_git_diff": _ReadOnlyToolDefaults(
        30_000,
        256 * 1024,
        False,
        frozenset(
            {
                ToolCapability.FILESYSTEM_READ,
                ToolCapability.PROCESS_EXECUTE,
                ToolCapability.DATABASE_QUERY,
            }
        ),
    ),
    "propose_patch": _ReadOnlyToolDefaults(
        20_000,
        512 * 1024,
        False,
        frozenset({ToolCapability.FILESYSTEM_READ, ToolCapability.DATABASE_QUERY}),
    ),
}

READ_ONLY_AGENT_TOOL_NAMES = frozenset(_READ_ONLY_TOOL_DEFAULTS)


def build_read_only_tool_registry(
    db: AsyncSession,
    *,
    legacy_registry: ToolRegistry | None = None,
) -> VersionedToolRegistry:
    """Wrap audited read-only tools; sensitive reads remain approval-gated."""

    source = legacy_registry or default_registry
    registry = VersionedToolRegistry()
    for name, defaults in _READ_ONLY_TOOL_DEFAULTS.items():
        legacy = source.get(name)
        if legacy is None:
            raise RuntimeError(f"缺少内建工具：{name}")
        if legacy.risk_level != defaults.risk_level.value:
            raise RuntimeError(
                f"工具风险等级与审核后的 Agent 契约不一致，拒绝迁移：{name}"
            )
        registry.register(_wrap_legacy_tool(db, legacy, defaults))
    return registry


def build_read_only_tool_dispatcher(
    db: AsyncSession,
    run_id: str | None = None,
) -> ValidatedToolDispatcher:
    """Build a default-deny dispatcher for the audited read-only capabilities."""

    return ValidatedToolDispatcher(
        build_read_only_tool_registry(db),
        policy=ToolCapabilityPolicy(
            granted_capabilities=frozenset(
                {
                    ToolCapability.FILESYSTEM_READ,
                    ToolCapability.PROCESS_EXECUTE,
                    ToolCapability.DATABASE_QUERY,
                }
            )
        ),
        execution_store=(
            ToolExecutionRepository(db, run_id=run_id)
            if run_id is not None
            else None
        ),
    )


def _wrap_legacy_tool(
    db: AsyncSession,
    legacy: ToolDefinition,
    defaults: _ReadOnlyToolDefaults,
) -> ToolSpec:
    async def execute(arguments: dict[str, Any], cancellation: CancellationToken) -> Any:
        if cancellation.is_cancelled:
            raise RuntimeError("工具执行已取消")
        # R3：grep_code 的 to_thread 线程不可强杀。绑定取消事件让扫描循环提前
        # 退让（线程在文件/行之间检查事件）；即使迟到，结果也会被取消方丢弃
        # （supports_cancellation=False 明确声明）。finally 中无条件 set，
        # 保证取消/超时路径下线程不会继续全量扫描。
        stop_event: threading.Event | None = None
        watch_task: asyncio.Task | None = None
        if legacy.name == "grep_code":
            stop_event = threading.Event()

            async def _watch() -> None:
                with suppress(asyncio.CancelledError):
                    await cancellation.wait()
                stop_event.set()  # type: ignore[union-attr]

            watch_task = asyncio.create_task(_watch())
        try:
            return await legacy.execute(arguments, ToolContext(db, grep_stop_event=stop_event))
        finally:
            if stop_event is not None:
                stop_event.set()
            if watch_task is not None:
                watch_task.cancel()
                with suppress(asyncio.CancelledError):
                    await watch_task

    return ToolSpec(
        name=legacy.name,
        version="1.0.0",
        description=legacy.description,
        input_schema=legacy.input_schema,
        output_schema=legacy.output_schema,
        risk_level=defaults.risk_level,
        required_capabilities=defaults.capabilities,
        timeout_ms=defaults.timeout_ms,
        max_output_bytes=defaults.max_output_bytes,
        idempotency=ToolIdempotency.IDEMPOTENT,
        supports_cancellation=defaults.supports_cancellation,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        executor=execute,
    )
