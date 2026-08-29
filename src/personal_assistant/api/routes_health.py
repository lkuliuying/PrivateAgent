"""健康检查路由。"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..config import settings
from ..core.auth import Principal
from ..core.health import HealthService
from ..logging_setup import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


class RuntimeCapabilities(BaseModel):
    """Stable, non-secret feature gates needed by local clients.

    v0.5.0 B0 additive extension：四个可信工作流开关（均默认 False），
    保持对既有字段的向后兼容。字段集合由 tests/test_public_contracts.py
    与 docs/releases/v0.3.0/v0.3.0-public-contracts.md 冻结。

    v0.9.0 H0 additive extension：coding 默认切换、三档权限能力位、
    上下文预算、执行详情与 worktree 声明（见 §3），全部默认 False；
    ``workspace`` 与 ``full_access`` 独立声明，不是别名。
    """

    chat_execution_mode: Literal["agent_runtime", "legacy"]
    legacy_tool_planner_enabled: bool
    agent_read_only_tools_enabled: bool
    rag_chat_runtime_enabled: bool
    patch_workflow_enabled: bool = False
    command_workflow_enabled: bool = False
    http_workflow_enabled: bool = False
    sql_readonly_workflow_enabled: bool = False
    # v0.9.0 H0 §3（additive，默认 False）
    agent_runs_api_enabled: bool = False
    coding_agent_ui_enabled: bool = False
    project_bound_runs_enabled: bool = False
    coding_workspace_auto_approve: bool = False
    coding_full_access_supported: bool = False
    coding_context_budget_enabled: bool = False
    coding_execution_detail_enabled: bool = False
    coding_worktree_enabled: bool = False
    product_timezone: str = "Asia/Shanghai"
    # v0.9.0 H1-C（计划 §5.3/§5.7，additive）：full_access 的审计与撤销是
    # 独立声明项（能力位开启但审计/撤销通道异常时前端应失败关闭）；
    # 内置只读诊断命令面（H1-B 动手主链证据来源）。
    coding_full_access_audit: bool = False
    coding_full_access_revoke: bool = False
    coding_diagnostic_commands_enabled: bool = False


@router.get("/health")
async def health() -> dict:
    """返回 API、MySQL、ChromaDB 状态；本地模型不参与周期探测。"""
    result = await HealthService().check_all()
    logger.info("health check", **{k: v.get("ok") for k, v in result.items()})
    return result


@router.get("/capabilities", response_model=RuntimeCapabilities)
async def capabilities(request: Request) -> RuntimeCapabilities:
    """Return lightweight execution-mode gates without probing dependencies."""
    from ..core.timeutil import PRODUCT_TIMEZONE

    agent_runtime = settings.chat_agent_runtime_enabled
    principal = getattr(request.state, "principal", None)
    privileged = isinstance(principal, Principal) and principal.is_admin
    return RuntimeCapabilities(
        chat_execution_mode="agent_runtime" if agent_runtime else "legacy",
        legacy_tool_planner_enabled=not agent_runtime,
        agent_read_only_tools_enabled=settings.agent_run_read_only_tools_enabled,
        rag_chat_runtime_enabled=(
            agent_runtime
            and settings.agent_rag_tools_enabled
            and settings.agent_output_verification_enabled
        ),
        patch_workflow_enabled=privileged and settings.agent_patch_workflow_enabled,
        command_workflow_enabled=privileged and settings.agent_command_workflow_enabled,
        http_workflow_enabled=privileged and settings.agent_http_workflow_enabled,
        sql_readonly_workflow_enabled=(
            privileged and settings.agent_sql_readonly_workflow_enabled
        ),
        # v0.9.0 H0 §3：能力位只反映 flag 事实；UI 据此启用选项，
        # workspace_auto_approve 额外要求命令 profile 子系统可用。
        agent_runs_api_enabled=privileged and settings.agent_runs_api_enabled,
        coding_agent_ui_enabled=privileged and settings.coding_agent_ui_enabled,
        project_bound_runs_enabled=privileged and settings.project_bound_runs_enabled,
        coding_workspace_auto_approve=(
            privileged
            and
            settings.coding_workspace_auto_approve_enabled
            and settings.coding_command_profiles_enabled
        ),
        coding_full_access_supported=privileged and settings.coding_full_access_enabled,
        coding_context_budget_enabled=(
            privileged and settings.coding_context_budget_enabled
        ),
        coding_execution_detail_enabled=(
            privileged and settings.coding_execution_detail_enabled
        ),
        coding_worktree_enabled=privileged and settings.coding_worktree_enabled,
        product_timezone=PRODUCT_TIMEZONE,
        # v0.9.0 H1-C（§5.3）：审计/撤销随 full_access 能力位声明（服务层内置）。
        coding_full_access_audit=privileged and settings.coding_full_access_enabled,
        coding_full_access_revoke=privileged and settings.coding_full_access_enabled,
        # v0.9.0 H1-B（§5.6）：内置只读诊断命令依赖命令工作流子系统。
        coding_diagnostic_commands_enabled=(
            privileged and settings.agent_command_workflow_enabled
        ),
    )
