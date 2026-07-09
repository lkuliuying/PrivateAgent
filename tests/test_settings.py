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


# ============ API key 掩码（第八阶段审查修复）============


@pytest.mark.asyncio
async def test_settings_get_masks_api_keys(client, db):
    """GET /settings 不回显 API key 原文，返回掩码占位。"""
    svc = SettingsService(db)
    await svc.update({"openai_api_key": "sk-secret-12345"})
    try:
        r = await client.get("/settings")
        assert r.status_code == 200
        assert r.json()["openai_api_key"] == "********"
        assert "sk-secret-12345" not in r.text
    finally:
        await svc.update({"openai_api_key": ""})


@pytest.mark.asyncio
async def test_settings_put_mask_preserves_new_clears(client, db):
    """PUT：回传掩码保留原值；新值更新；空串清空。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from personal_assistant.config import settings as cfg

    svc = SettingsService(db)
    await svc.update({"openai_api_key": "sk-real-999"})

    async def raw_key() -> str:
        # 用 fresh session 读，避免 db fixture 旧事务快照看不到 client 写入
        eng = create_async_engine(cfg.db_url)
        try:
            f = async_sessionmaker(eng, expire_on_commit=False)
            async with f() as s:
                return (await SettingsService(s).get_all())["openai_api_key"]
        finally:
            await eng.dispose()

    try:
        # 回传掩码 -> 保留原值（不被掩码覆盖）
        await client.put("/settings", json={"openai_api_key": "********"})
        assert await raw_key() == "sk-real-999"
        # 回传新值 -> 更新
        await client.put("/settings", json={"openai_api_key": "sk-new-value"})
        assert await raw_key() == "sk-new-value"
        # 回传空 -> 清空
        await client.put("/settings", json={"openai_api_key": ""})
        assert await raw_key() == ""
    finally:
        await svc.update({"openai_api_key": ""})
