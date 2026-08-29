"""健康检查 API 测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from personal_assistant.api import routes_health
from personal_assistant.core import health as health_module
from personal_assistant.core.health import HealthService
from personal_assistant.main_api import register_managed_server


@pytest.mark.asyncio
async def test_mysql_health_uses_injected_session_without_global_engine(monkeypatch):
    class GuardEngine:
        def connect(self):
            raise AssertionError("global engine must not be used")

    db = AsyncMock()
    db.scalar.return_value = 1
    monkeypatch.setattr(health_module, "engine", GuardEngine())

    result = await HealthService(db)._check_mysql()

    assert result == {"ok": True}
    db.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_returns_only_core_components(client, monkeypatch):
    async def fail_if_ollama_is_probed(*_args, **_kwargs):
        raise AssertionError("Ollama must not participate in periodic health checks")

    from personal_assistant.core.provider import OllamaProvider

    monkeypatch.setattr(OllamaProvider, "health", fail_if_ollama_is_probed)
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"api", "mysql", "chroma"}
    for key in ("api", "mysql", "chroma"):
        assert "ok" in data[key]


@pytest.mark.asyncio
async def test_capabilities_expose_exclusive_chat_execution_mode(client, monkeypatch):
    monkeypatch.setattr(routes_health.settings, "chat_agent_runtime_enabled", True)
    monkeypatch.setattr(routes_health.settings, "agent_run_read_only_tools_enabled", True)
    monkeypatch.setattr(routes_health.settings, "agent_rag_tools_enabled", True)
    monkeypatch.setattr(routes_health.settings, "agent_output_verification_enabled", True)

    runtime = await client.get("/capabilities")

    assert runtime.status_code == 200
    assert runtime.json() == {
        "chat_execution_mode": "agent_runtime",
        "legacy_tool_planner_enabled": False,
        "agent_read_only_tools_enabled": True,
        "rag_chat_runtime_enabled": True,
        "patch_workflow_enabled": False,
        "command_workflow_enabled": False,
        "http_workflow_enabled": False,
        "sql_readonly_workflow_enabled": False,
        # v0.9.0 H0 §3 additive（默认 False；时区为常量声明）
        "agent_runs_api_enabled": False,
        "coding_agent_ui_enabled": False,
        "project_bound_runs_enabled": False,
        "coding_workspace_auto_approve": False,
        "coding_full_access_supported": False,
        "coding_context_budget_enabled": False,
        "coding_execution_detail_enabled": False,
        "coding_worktree_enabled": False,
        "product_timezone": "Asia/Shanghai",
        # v0.9.0 H1-C additive（§5.3/§5.7）
        "coding_full_access_audit": False,
        "coding_full_access_revoke": False,
        "coding_diagnostic_commands_enabled": False,
    }

    monkeypatch.setattr(routes_health.settings, "chat_agent_runtime_enabled", False)
    legacy = await client.get("/capabilities")
    assert legacy.status_code == 200
    assert legacy.json()["chat_execution_mode"] == "legacy"
    assert legacy.json()["legacy_tool_planner_enabled"] is True
    assert legacy.json()["rag_chat_runtime_enabled"] is False
    assert legacy.json()["patch_workflow_enabled"] is False


@pytest.mark.asyncio
async def test_capabilities_expose_complete_coding_run_creation_chain(client, monkeypatch):
    monkeypatch.setattr(routes_health.settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_health.settings, "coding_agent_ui_enabled", True)
    monkeypatch.setattr(routes_health.settings, "project_bound_runs_enabled", True)

    runtime = await client.get("/capabilities")

    assert runtime.status_code == 200
    assert runtime.json()["agent_runs_api_enabled"] is True
    assert runtime.json()["coding_agent_ui_enabled"] is True
    assert runtime.json()["project_bound_runs_enabled"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runtime", "rag_tools", "verification", "read_only", "expected"),
    [
        # 组合 1：Runtime 全开（含 RAG 与验证）→ agent_runtime + RAG 就绪
        (
            True,
            True,
            True,
            True,
            {
                "chat_execution_mode": "agent_runtime",
                "legacy_tool_planner_enabled": False,
                "agent_read_only_tools_enabled": True,
                "rag_chat_runtime_enabled": True,
            },
        ),
        # 组合 2：Runtime 开、RAG 工具关 → 普通聊天走 Runtime，RAG 不可用
        (
            True,
            False,
            True,
            False,
            {
                "chat_execution_mode": "agent_runtime",
                "legacy_tool_planner_enabled": False,
                "agent_read_only_tools_enabled": False,
                "rag_chat_runtime_enabled": False,
            },
        ),
        # 组合 3：Runtime 开、输出验证关 → RAG 聊天拒绝进入 Runtime（缺验证）
        (
            True,
            True,
            False,
            False,
            {
                "chat_execution_mode": "agent_runtime",
                "legacy_tool_planner_enabled": False,
                "agent_read_only_tools_enabled": False,
                "rag_chat_runtime_enabled": False,
            },
        ),
        # 组合 4：Runtime 关 → 全 legacy，planner 可用，RAG Runtime 关闭
        (
            False,
            True,
            True,
            True,
            {
                "chat_execution_mode": "legacy",
                "legacy_tool_planner_enabled": True,
                "agent_read_only_tools_enabled": True,
                "rag_chat_runtime_enabled": False,
            },
        ),
    ],
)
async def test_capabilities_four_key_combinations(
    client, monkeypatch, runtime, rag_tools, verification, read_only, expected
):
    """M1 §6.2：/capabilities 四种关键组合互斥且确定。"""
    monkeypatch.setattr(routes_health.settings, "chat_agent_runtime_enabled", runtime)
    monkeypatch.setattr(routes_health.settings, "agent_rag_tools_enabled", rag_tools)
    monkeypatch.setattr(
        routes_health.settings, "agent_output_verification_enabled", verification
    )
    monkeypatch.setattr(
        routes_health.settings, "agent_run_read_only_tools_enabled", read_only
    )

    r = await client.get("/capabilities")

    assert r.status_code == 200
    body = r.json()
    expected_body = dict(expected)
    expected_body.update(
        {
            "patch_workflow_enabled": False,
            "command_workflow_enabled": False,
            "http_workflow_enabled": False,
            "sql_readonly_workflow_enabled": False,
            # v0.9.0 H0 §3 additive
            "agent_runs_api_enabled": False,
            "coding_agent_ui_enabled": False,
            "project_bound_runs_enabled": False,
            "coding_workspace_auto_approve": False,
            "coding_full_access_supported": False,
            "coding_context_budget_enabled": False,
            "coding_execution_detail_enabled": False,
            "coding_worktree_enabled": False,
            "product_timezone": "Asia/Shanghai",
            # v0.9.0 H1-C additive（§5.3/§5.7）
            "coding_full_access_audit": False,
            "coding_full_access_revoke": False,
            "coding_diagnostic_commands_enabled": False,
        }
    )
    assert body == expected_body
    # 互斥约束：legacy_tool_planner 只由 chat_execution_mode 决定
    assert body["legacy_tool_planner_enabled"] == (
        body["chat_execution_mode"] == "legacy"
    )


@pytest.mark.asyncio
async def test_capabilities_expose_four_independent_workflow_flags(client, monkeypatch):
    """B0：四个可信工作流开关彼此独立，默认全部关闭。"""
    defaults = await client.get("/capabilities")
    assert defaults.status_code == 200
    for key in (
        "patch_workflow_enabled",
        "command_workflow_enabled",
        "http_workflow_enabled",
        "sql_readonly_workflow_enabled",
    ):
        assert defaults.json()[key] is False

    monkeypatch.setattr(routes_health.settings, "agent_patch_workflow_enabled", True)
    only_patch = await client.get("/capabilities")
    assert only_patch.status_code == 200
    assert only_patch.json() == {
        "chat_execution_mode": "legacy",
        "legacy_tool_planner_enabled": True,
        "agent_read_only_tools_enabled": False,
        "rag_chat_runtime_enabled": False,
        "patch_workflow_enabled": True,
        "command_workflow_enabled": False,
        "http_workflow_enabled": False,
        "sql_readonly_workflow_enabled": False,
        # v0.9.0 H0 §3 additive
        "agent_runs_api_enabled": False,
        "coding_agent_ui_enabled": False,
        "project_bound_runs_enabled": False,
        "coding_workspace_auto_approve": False,
        "coding_full_access_supported": False,
        "coding_context_budget_enabled": False,
        "coding_execution_detail_enabled": False,
        "coding_worktree_enabled": False,
        "product_timezone": "Asia/Shanghai",
        # v0.9.0 H1-C additive（§5.3/§5.7）
        "coding_full_access_audit": False,
        "coding_full_access_revoke": False,
        "coding_diagnostic_commands_enabled": False,
    }

    monkeypatch.setattr(routes_health.settings, "agent_command_workflow_enabled", True)
    monkeypatch.setattr(routes_health.settings, "agent_http_workflow_enabled", True)
    monkeypatch.setattr(
        routes_health.settings, "agent_sql_readonly_workflow_enabled", True
    )
    all_four = await client.get("/capabilities")
    assert all_four.status_code == 200
    body = all_four.json()
    assert body["patch_workflow_enabled"] is True
    assert body["command_workflow_enabled"] is True
    assert body["http_workflow_enabled"] is True
    assert body["sql_readonly_workflow_enabled"] is True


@pytest.mark.asyncio
async def test_internal_shutdown_requires_auth_and_accepts_registered_server(
    client, monkeypatch
):
    """M0：/internal/shutdown 需认证；注册 server 后触发 should_exit 优雅停机。"""
    import personal_assistant.main_api as main_api

    unauth = await client.get(
        "/internal/shutdown",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert unauth.status_code == 401

    monkeypatch.setattr(main_api, "_managed_server", None)
    not_managed = await client.post("/internal/shutdown")
    assert not_managed.status_code == 200
    assert not_managed.json() == {"accepted": False}

    class FakeServer:
        def __init__(self) -> None:
            self.should_exit = False

    fake = FakeServer()
    register_managed_server(fake)
    try:
        accepted = await client.post("/internal/shutdown")
        assert accepted.status_code == 200
        assert accepted.json() == {"accepted": True}
        assert fake.should_exit is True
    finally:
        monkeypatch.setattr(main_api, "_managed_server", None)
