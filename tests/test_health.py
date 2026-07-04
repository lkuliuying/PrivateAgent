"""健康检查 API 测试。"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_returns_four_components(client):
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"api", "ollama", "mysql", "chroma"}
    for key in ("api", "ollama", "mysql", "chroma"):
        assert "ok" in data[key]
