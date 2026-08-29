from __future__ import annotations

import json
from uuid import uuid4

import pytest

from personal_assistant.core.model_profiles import ModelProfileService
from personal_assistant.core.model_providers import (
    ModelProviderService,
    provider_for_profile,
)
from personal_assistant.core.settings import (
    SettingsService,
    clear_model_provider_runtime_secret,
    model_provider_secret_reference,
    resolve_model_provider_secret,
    set_model_provider_runtime_secret,
)


@pytest.mark.asyncio
async def test_unified_provider_replaces_stale_default_profile(db):
    provider_id = f"provider-{uuid4().hex[:12]}"
    configured_profile_id = f"provider:{provider_id}:deepseek-v4-flash"
    stale_profile_id = f"legacy-glm-{uuid4().hex[:12]}"
    settings = SettingsService(db)
    before = await settings.get("model_provider_configs")
    original_default = await ModelProfileService(db).get_default()
    service = ModelProviderService(db)
    try:
        await ModelProfileService(db).upsert(
            configured_profile_id,
            {
                "provider": "openai",
                "display_name": "deepseek-v4-flash",
                "model_name": "deepseek-v4-flash",
                "enabled": True,
            },
        )
        await ModelProfileService(db).upsert(
            stale_profile_id,
            {
                "provider": "openai",
                "display_name": "glm-5.3-flash",
                "model_name": "glm-5.3-flash",
                "enabled": True,
            },
        )
        await ModelProfileService(db).set_default(stale_profile_id)
        await settings.update(
            {
                "model_provider_configs": json.dumps(
                    [
                        {
                            "id": provider_id,
                            "name": "DeepSeek",
                            "protocol": "openai",
                            "base_url": "https://api.deepseek.com",
                            "api_format": "chat_completions",
                            "enabled": True,
                            "models": [
                                {
                                    "profile_id": configured_profile_id,
                                    "model_id": "deepseek-v4-flash",
                                    "context_tokens": 1_000_000,
                                }
                            ],
                        }
                    ],
                    ensure_ascii=False,
                )
            }
        )

        await service.list(ensure_legacy=False)
        default = await ModelProfileService(db).get_default()
        assert default is not None
        assert default.id == configured_profile_id

        await ModelProfileService(db).set_default(stale_profile_id)
        await service.upsert(
            provider_id,
            {
                "name": "DeepSeek",
                "protocol": "openai",
                "base_url": "https://api.deepseek.com",
                "api_format": "chat_completions",
                "enabled": True,
                "models": [
                    {"model_id": "deepseek-v4-flash", "context_tokens": 1_000_000}
                ],
            },
        )
        default = await ModelProfileService(db).get_default()
        assert default is not None
        assert default.id == configured_profile_id
    finally:
        for profile_id in (configured_profile_id, stale_profile_id):
            if await ModelProfileService(db).get(profile_id):
                await ModelProfileService(db).delete(profile_id)
        await settings.update({"model_provider_configs": before})
        if original_default and await ModelProfileService(db).get(original_default.id):
            await ModelProfileService(db).set_default(original_default.id)


@pytest.mark.asyncio
async def test_provider_save_syncs_enabled_models_and_runtime_route(db):
    provider_id = f"provider-{uuid4().hex[:12]}"
    reference = model_provider_secret_reference(provider_id)
    settings = SettingsService(db)
    before = await settings.get("model_provider_configs")
    service = ModelProviderService(db)
    profile_ids: list[str] = []
    try:
        set_model_provider_runtime_secret(provider_id, "latest-key")
        provider = await service.upsert(
            provider_id,
            {
                "name": "测试供应商",
                "protocol": "openai",
                "base_url": "https://example.com/v1",
                "api_format": "chat_completions",
                "credential_reference": reference,
                "enabled": True,
                "models": [
                    {"model_id": "model-a", "context_tokens": 131072},
                    {"model_id": "model-b", "context_tokens": 32768},
                ],
            },
        )
        profile_ids = [item["profile_id"] for item in provider["models"]]
        assert len(profile_ids) == 2
        profiles = await ModelProfileService(db).list(enabled_only=True)
        saved = [item for item in profiles if item.id in profile_ids]
        assert {item.model_name for item in saved} == {"model-a", "model-b"}

        values = await settings.get_all()
        route = provider_for_profile(values, profile_ids[0])
        assert route is not None and route["base_url"] == "https://example.com/v1"
        assert (
            resolve_model_provider_secret(
                provider_id, reference, legacy_settings=values
            )
            == "latest-key"
        )
    finally:
        clear_model_provider_runtime_secret(provider_id)
        if await service.get(provider_id):
            await service.delete(provider_id)
        await settings.update({"model_provider_configs": before})


@pytest.mark.asyncio
async def test_provider_list_migrates_legacy_deepseek_32k_to_catalog(db):
    provider_id = f"deepseek-{uuid4().hex[:12]}"
    settings = SettingsService(db)
    before = await settings.get("model_provider_configs")
    profile_id = f"provider:{provider_id}:deepseek-v4-flash"
    service = ModelProviderService(db)
    try:
        profile = await ModelProfileService(db).upsert(
            profile_id,
            {
                "provider": "openai",
                "display_name": "deepseek-v4-flash",
                "model_name": "deepseek-v4-flash",
                "context_tokens": 32_768,
            },
        )
        await settings.update(
            {
                "model_provider_configs": json.dumps([
                    {
                        "id": provider_id,
                        "name": "DeepSeek",
                        "protocol": "openai",
                        "base_url": "https://api.deepseek.com",
                        "api_format": "chat_completions",
                        "enabled": True,
                        "models": [
                            {
                                "profile_id": profile_id,
                                "model_id": "deepseek-v4-flash",
                                "context_tokens": 32_768,
                            }
                        ],
                    }
                ], ensure_ascii=False)
            }
        )

        providers = await service.list()
        model = providers[0]["models"][0]
        assert model["context_tokens"] == 1_000_000
        assert model["max_output_tokens"] == 384_000
        assert model["metadata_source"] == "official_catalog"
        await db.refresh(profile)
        assert profile.context_tokens == 1_000_000
    finally:
        await db.rollback()
        if await ModelProfileService(db).get(profile_id):
            await ModelProfileService(db).delete(profile_id)
        await settings.update({"model_provider_configs": before})


@pytest.mark.asyncio
async def test_provider_list_tolerates_missing_profile_reference(db):
    provider_id = f"stale-{uuid4().hex[:12]}"
    settings = SettingsService(db)
    before = await settings.get("model_provider_configs")
    try:
        await settings.update(
            {
                "model_provider_configs": json.dumps(
                    [
                        {
                            "id": provider_id,
                            "name": "旧配置",
                            "protocol": "openai",
                            "base_url": "https://api.example.com/v1",
                            "api_format": "chat_completions",
                            "enabled": True,
                            "models": [
                                {
                                    "profile_id": f"missing-{uuid4().hex}",
                                    "model_id": "missing-model",
                                    "context_tokens": 32768,
                                }
                            ],
                        }
                    ],
                    ensure_ascii=False,
                )
            }
        )

        providers = await ModelProviderService(db).list(ensure_legacy=False)
        assert providers[0]["id"] == provider_id
    finally:
        await settings.update({"model_provider_configs": before})
