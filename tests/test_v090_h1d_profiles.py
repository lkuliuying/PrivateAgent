"""v0.9.0 H1-D 契约测试：Provider/profile 配置闭环（计划 §5.8）。

覆盖：
- 迁移 0033：model_profiles 新增 model_name/is_default 列；
- 服务层：默认排他、get_default 只认启用项、model_name 幂等回填；
- typed API：upsert/get/delete 携带新字段，probe/set-default 端点；
- 受限探测状态码：profile_disabled/model_route_missing/
  provider_unreachable/tools_unsupported（不按名称推断工具能力）；
- 幂等导入：本地 Ollama 自动导入、远程需确认、失败回滚、重复调用幂等；
- Runtime 路由：实际 model 取 profile.model_name，缺失失败关闭；
- run 创建：未选 profile 时绑定默认项；无默认项保持兼容并计数。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, text
from test_v070_permissions import _create_coding_env, _post_coding_run

from personal_assistant.api import routes_agent_runs
from personal_assistant.config import settings as cfg
from personal_assistant.core import model_profile_import as import_mod
from personal_assistant.core.model_profile_probe import (
    ModelProfileProbeResult,
    _ollama_model_in_tags,
    probe_model_profile,
)
from personal_assistant.core.model_profiles import ModelProfileService

PROFILE_IDS = ("h1d-a", "h1d-b", "h1d-route", "ollama-default")


@pytest.fixture
async def cleanup_profiles(db):
    # 全量套件下其他用例会残留 profile（共享库无事务回滚）；导入/默认类
    # 用例对存量敏感，开始前清空、结束后再清（仅测试库）。
    from personal_assistant.core.models import ModelProfile

    await db.execute(delete(ModelProfile))
    await db.commit()
    yield
    for profile_id in PROFILE_IDS:
        await db.execute(delete(ModelProfile).where(ModelProfile.id == profile_id))
    await db.commit()


def _enable_flags(monkeypatch) -> None:
    monkeypatch.setattr(cfg, "coding_permission_models_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)


# ===========================================================================
# A. 迁移 0033：列存在
# ===========================================================================


async def test_migration_0033_columns_exist(db):
    rows = (
        await db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = DATABASE() "
                "AND table_name = 'model_profiles' "
                "AND column_name IN ('model_name', 'is_default')"
            )
        )
    ).fetchall()
    assert {row[0] for row in rows} == {"model_name", "is_default"}


# ===========================================================================
# B. 服务层：默认排他 / get_default / 回填
# ===========================================================================


async def test_set_default_is_exclusive_and_get_default_requires_enabled(
    db, cleanup_profiles
):
    svc = ModelProfileService(db)
    await svc.upsert(
        "h1d-a",
        {"provider": "ollama", "display_name": "A", "model_name": "m-a"},
    )
    await svc.upsert(
        "h1d-b",
        {"provider": "ollama", "display_name": "B", "model_name": "m-b"},
    )
    await svc.set_default("h1d-a")
    await svc.set_default("h1d-b")
    profiles = {p.id: p for p in await svc.list()}
    assert profiles["h1d-b"].is_default is True
    assert profiles["h1d-a"].is_default is False
    default = await svc.get_default()
    assert default is not None and default.id == "h1d-b"
    # 禁用默认项后 get_default 返回 None（不回落其他非默认项）
    await svc.upsert(
        "h1d-b",
        {
            "provider": "ollama",
            "display_name": "B",
            "model_name": "m-b",
            "enabled": False,
        },
    )
    assert await svc.get_default() is None


async def test_backfill_model_name_idempotent(db, cleanup_profiles):
    svc = ModelProfileService(db)
    await svc.upsert(
        "h1d-route", {"provider": "ollama", "display_name": "R"}
    )
    assert (await svc.get("h1d-route")).model_name is None
    assert await svc.backfill_model_name("ollama", "legacy-model") >= 1
    assert (await svc.get("h1d-route")).model_name == "legacy-model"
    # 幂等：再次回填不覆盖已有值、返回 0
    assert await svc.backfill_model_name("ollama", "other-model") == 0
    assert (await svc.get("h1d-route")).model_name == "legacy-model"


# ===========================================================================
# C. typed API：新字段 + probe / set-default / import-status
# ===========================================================================


async def test_api_upsert_and_output_carry_routing_fields(client, monkeypatch, cleanup_profiles):
    _enable_flags(monkeypatch)
    payload = {
        "provider": "ollama",
        "display_name": "路由字段",
        "model_name": "qwen3-coder",
        "is_local": True,
        "native_tool_calls": True,
        "is_default": True,
    }
    resp = await client.put("/agent-model-profiles/h1d-a", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model_name"] == "qwen3-coder"
    assert body["is_default"] is True
    resp = await client.get("/agent-model-profiles/h1d-a")
    assert resp.json()["model_name"] == "qwen3-coder"
    # 清理默认标记（避免污染共享库其他用例）
    await client.delete("/agent-model-profiles/h1d-a")


async def test_probe_endpoint_exact_status_codes(client, monkeypatch, cleanup_profiles):
    _enable_flags(monkeypatch)
    # 停用 → profile_disabled
    await client.put(
        "/agent-model-profiles/h1d-a",
        json={
            "provider": "ollama",
            "display_name": "p",
            "model_name": "m",
            "enabled": False,
        },
    )
    resp = await client.post("/agent-model-profiles/h1d-a/probe")
    assert resp.status_code == 200
    assert resp.json()["status"] == "profile_disabled"
    # 缺少具体模型路由字段 → model_route_missing
    await client.put(
        "/agent-model-profiles/h1d-a",
        json={"provider": "ollama", "display_name": "p", "enabled": True},
    )
    resp = await client.post("/agent-model-profiles/h1d-a/probe")
    assert resp.json()["status"] == "model_route_missing"
    # Provider 不可达（死端口）→ provider_unreachable
    await client.put(
        "/agent-model-profiles/h1d-a",
        json={
            "provider": "ollama",
            "display_name": "p",
            "model_name": "m",
            "enabled": True,
        },
    )
    monkeypatch.setattr(cfg, "ollama_base_url", "http://127.0.0.1:9")
    resp = await client.post("/agent-model-profiles/h1d-a/probe")
    assert resp.json()["status"] == "provider_unreachable"
    assert resp.json()["provider_reachable"] is False
    # flag 关闭 → 409
    monkeypatch.setattr(cfg, "coding_permission_models_enabled", False)
    resp = await client.post("/agent-model-profiles/h1d-a/probe")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "coding_mode_disabled"
    await client.delete("/agent-model-profiles/h1d-a")


async def test_probe_does_not_infer_tools_from_name(db, cleanup_profiles):
    """工具能力是显式声明事实：探测通过但 native_tool_calls=False →
    tools_unsupported（不按模型名称推断）。"""
    import personal_assistant.core.model_profile_probe as probe_mod

    async def fake_ollama(model_name):
        return ModelProfileProbeResult(
            status="ok", provider_reachable=True, model_exists=True
        )

    svc = ModelProfileService(db)
    await svc.upsert(
        "h1d-a",
        {
            "provider": "ollama",
            "display_name": "p",
            "model_name": "some-model",
            "native_tool_calls": False,
        },
    )
    monkey = pytest.MonkeyPatch()
    monkey.setattr(probe_mod, "_probe_ollama", fake_ollama)
    try:
        result = await probe_model_profile(db, "h1d-a")
    finally:
        monkey.undo()
    assert result.status == "tools_unsupported"
    assert result.native_tool_calls is False


def test_ollama_model_in_tags_latest_suffix():
    assert _ollama_model_in_tags("qwen3", ["qwen3:latest"]) is True
    assert _ollama_model_in_tags("qwen3", ["qwen3"]) is True
    assert _ollama_model_in_tags("qwen3", ["llama3"]) is False


# ===========================================================================
# D. 幂等导入（升级路径）
# ===========================================================================


def _patch_global_facts(monkeypatch, *, provider="ollama", model="qwen3-coder"):
    async def fake_facts(db):
        return {
            "provider": provider,
            "model_name": model,
            "remote_enabled": provider != "ollama",
            "credentials": True,
            "context_length": 32768,
        }

    monkeypatch.setattr(import_mod, "_global_provider_facts", fake_facts)


async def test_import_local_ollama_creates_stable_default_profile(
    db, monkeypatch, cleanup_profiles
):
    _patch_global_facts(monkeypatch)

    async def fake_probe(db, profile_id):
        return ModelProfileProbeResult(
            status="ok", provider_reachable=True, model_exists=True
        )

    monkeypatch.setattr(import_mod, "probe_model_profile", fake_probe)
    result = await import_mod.import_legacy_provider_profile(db, interactive=False)
    assert result["imported"] is True
    assert result["profile_id"] == "ollama-default"
    svc = ModelProfileService(db)
    profile = await svc.get("ollama-default")
    assert profile is not None
    assert profile.model_name == "qwen3-coder"
    assert profile.is_default is True
    # 幂等：重复调用不创建重复 profile
    again = await import_mod.import_legacy_provider_profile(db, interactive=False)
    assert again["imported"] is False
    assert again["already_exists"] is True
    assert len(await svc.list()) == 1


async def test_import_probe_failure_rolls_back_profile(
    db, monkeypatch, cleanup_profiles
):
    _patch_global_facts(monkeypatch)

    async def fake_probe(db, profile_id):
        return ModelProfileProbeResult(
            status="provider_unreachable",
            provider_reachable=False,
            detail="不可达",
        )

    monkeypatch.setattr(import_mod, "probe_model_profile", fake_probe)
    with pytest.raises(import_mod.ModelProfileImportError) as exc_info:
        await import_mod.import_legacy_provider_profile(db, interactive=False)
    assert exc_info.value.error_code == "provider_unreachable"
    # 回滚：不留下不可用的默认 profile
    assert await ModelProfileService(db).get("ollama-default") is None


async def test_import_remote_requires_user_confirmation(db, monkeypatch, cleanup_profiles):
    _patch_global_facts(monkeypatch, provider="openai", model="gpt-4o")
    with pytest.raises(import_mod.ModelProfileImportError) as exc_info:
        await import_mod.import_legacy_provider_profile(db, interactive=False)
    assert exc_info.value.error_code == "remote_requires_confirmation"


async def test_import_status_endpoint(client, monkeypatch, cleanup_profiles):
    _enable_flags(monkeypatch)
    resp = await client.get("/agent-model-profiles/import-status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["import_state"] in {
        "pending",
        "wizard",
        "not_needed",
        "auto_imported",
        "imported",
        "dismissed",
    }
    assert "reason_code" in body


async def test_import_endpoint_requires_global_provider(client, monkeypatch, cleanup_profiles):
    """全局未配置模型 → no_global_provider 失败关闭（不创建任何 profile）。"""
    _enable_flags(monkeypatch)
    from personal_assistant.core import settings as settings_mod

    monkeypatch.setitem(settings_mod.DEFAULTS, "llm_model", "")
    monkeypatch.setitem(settings_mod.DEFAULTS, "provider_type", "ollama")
    # 确保存储行不干扰（共享库可能残留其他用例的设置行）；结束后恢复。
    from personal_assistant.core.db import async_session_factory
    from personal_assistant.core.models import Setting
    from personal_assistant.core.settings import SettingsService

    async with async_session_factory() as sdb:
        await SettingsService(sdb).update({"llm_model": ""})
        await sdb.execute(
            delete(Setting).where(Setting.key == "provider_type")
        )
        await sdb.commit()
    try:
        resp = await client.post("/agent-model-profiles/import")
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "no_global_provider"
    finally:
        async with async_session_factory() as sdb:
            await sdb.execute(
                delete(Setting).where(
                    Setting.key.in_(("llm_model", "provider_type"))
                )
            )
            await sdb.commit()


# ===========================================================================
# E. Runtime 路由：实际 model = profile.model_name（不回落全局）
# ===========================================================================


async def test_runtime_routes_profile_model_name(db, cleanup_profiles):
    from personal_assistant.agents import AgentRunLimits, AgentRunRepository
    from personal_assistant.core.models import AgentRun as AgentRunRecord

    svc = ModelProfileService(db)
    await svc.upsert(
        "h1d-route",
        {
            "provider": "ollama",
            "display_name": "路由模型",
            "model_name": "specific-model-x",
            "is_local": True,
            "native_tool_calls": True,
            "context_tokens": 16384,
        },
    )
    run_id = str(uuid4())
    await AgentRunRepository(db).create_run(
        run_id=run_id, limits=AgentRunLimits(), model_profile_id="h1d-route"
    )
    try:
        run = await db.get(AgentRunRecord, run_id)
        gateway = await routes_agent_runs._model_gateway_for_run(db, run)
        # 实际适配器 model = profile 路由字段（零容忍：不得是全局旧模型）
        assert gateway.adapter.model_name == "specific-model-x"
        assert gateway.adapter.context_length == 16384
    finally:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
        await db.commit()


async def test_runtime_fails_closed_without_model_name(db, cleanup_profiles):
    from personal_assistant.agents import AgentRunLimits, AgentRunRepository
    from personal_assistant.core.model_profiles import ModelProfileUnsupported
    from personal_assistant.core.models import AgentRun as AgentRunRecord

    svc = ModelProfileService(db)
    await svc.upsert(
        "h1d-route",
        {
            "provider": "ollama",
            "display_name": "缺路由字段",
            "is_local": True,
            "native_tool_calls": True,
        },
    )
    run_id = str(uuid4())
    await AgentRunRepository(db).create_run(
        run_id=run_id, limits=AgentRunLimits(), model_profile_id="h1d-route"
    )
    try:
        run = await db.get(AgentRunRecord, run_id)
        with pytest.raises(ModelProfileUnsupported) as exc_info:
            await routes_agent_runs._model_gateway_for_run(db, run)
        assert "model_name" in str(exc_info.value)
    finally:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
        await db.commit()


# ===========================================================================
# F. run 创建：默认 profile 绑定
# ===========================================================================


async def test_run_creation_binds_default_profile(client, monkeypatch, tmp_path, cleanup_profiles):
    _enable_flags(monkeypatch)
    from test_v070_permissions import _enable_coding_flags

    _enable_coding_flags(monkeypatch)
    env = await _create_coding_env(client, tmp_path)
    # 创建默认 profile（稳定路由字段）
    resp = await client.put(
        "/agent-model-profiles/h1d-a",
        json={
            "provider": "ollama",
            "display_name": "默认",
            "model_name": "default-model",
            "is_local": True,
            "native_tool_calls": True,
            "is_default": True,
        },
    )
    assert resp.status_code == 200, resp.text
    # 未显式选择 → 绑定默认 profile 并持久化
    resp = await _post_coding_run(client, env)
    assert resp.status_code == 202, resp.text
    assert resp.json()["model_profile_id"] == "h1d-a"
    await client.delete("/agent-model-profiles/h1d-a")
