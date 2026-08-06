"""健康检查 API 测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from personal_assistant.api import routes_health
from personal_assistant.core import health as health_module
from personal_assistant.core.health import HealthService


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
async def test_health_returns_four_components(client):
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"api", "ollama", "mysql", "chroma"}
    for key in ("api", "ollama", "mysql", "chroma"):
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
    }

    monkeypatch.setattr(routes_health.settings, "chat_agent_runtime_enabled", False)
    legacy = await client.get("/capabilities")
    assert legacy.status_code == 200
    assert legacy.json()["chat_execution_mode"] == "legacy"
    assert legacy.json()["legacy_tool_planner_enabled"] is True
    assert legacy.json()["rag_chat_runtime_enabled"] is False
