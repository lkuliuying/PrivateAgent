"""设置服务测试。"""
from __future__ import annotations

import pytest

from personal_assistant.core.settings import SettingsService


@pytest.mark.asyncio
async def test_settings_has_defaults(db):
    svc = SettingsService(db)
    s = await svc.get_all()
    assert "llm_model" in s
    assert "llm_temperature" in s
    assert "kb_enabled_by_default" in s


@pytest.mark.asyncio
async def test_settings_update_and_persist(db):
    svc = SettingsService(db)
    original = (await svc.get_all())["llm_temperature"]
    try:
        await svc.update({"llm_temperature": "0.42"})
        s = await svc.get_all()
        assert s["llm_temperature"] == "0.42"
        # 未知 key 被忽略，不报错
        await svc.update({"unknown_key": "x"})
        s2 = await svc.get_all()
        assert "unknown_key" not in s2
    finally:
        await svc.update({"llm_temperature": original})
