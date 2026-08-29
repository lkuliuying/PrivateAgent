"""统一模型供应商配置与 ModelProfile 同步。

供应商元数据保存在 settings 表 JSON 中，避免再维护一套项目级模型实体；每个
启用模型仍落为 ModelProfile，供对话/Coding 选择与运行时路由复用。API Key
只保存系统凭据库引用，绝不进入 JSON。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from .model_metadata import metadata_source, official_catalog_metadata
from .model_profiles import ModelProfileService
from .models import ModelProfile, ModelToolProfileSnapshotRecord
from .settings import PROVIDER_SECRET_REFS, SettingsService

PROVIDERS_SETTING_KEY = "model_provider_configs"
PROTOCOLS = frozenset({"ollama", "openai", "claude"})
API_FORMATS = frozenset({"chat_completions", "anthropic_messages", "ollama_chat"})
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


class ModelProviderError(ValueError):
    pass


class ModelProviderNotFound(LookupError):
    pass


def _profile_id(provider_id: str, model_id: str) -> str:
    safe_model = re.sub(r"[^A-Za-z0-9._-]+", "-", model_id).strip("-.")
    digest = hashlib.sha256(model_id.encode("utf-8")).hexdigest()[:10]
    prefix = f"{provider_id}--{safe_model or 'model'}"
    if len(prefix) <= 116:
        return f"{prefix}--{digest}"
    return f"{prefix[:116]}--{digest}"


def _loads(raw: str | None) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _validate_provider(fields: Mapping[str, Any]) -> dict[str, Any]:
    provider_id = str(fields.get("id") or "").strip()
    name = str(fields.get("name") or "").strip()
    protocol = str(fields.get("protocol") or "").strip().lower()
    base_url = str(fields.get("base_url") or "").strip().rstrip("/")
    api_format = str(fields.get("api_format") or "").strip().lower()
    reference = str(fields.get("credential_reference") or "").strip() or None
    if not _ID_RE.fullmatch(provider_id):
        raise ModelProviderError("供应商 ID 只能包含字母、数字、点、下划线和连字符")
    if not name or len(name) > 200:
        raise ModelProviderError("供应商名称不能为空且不能超过 200 个字符")
    if protocol not in PROTOCOLS:
        raise ModelProviderError("不支持的模型服务协议")
    if api_format not in API_FORMATS:
        raise ModelProviderError("不支持的 API 格式")
    if protocol == "ollama":
        parsed = urlsplit(base_url or cfg.ollama_base_url)
        if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in _LOOPBACK_HOSTS:
            raise ModelProviderError("Ollama 必须使用本机 HTTP(S) 地址")
        base_url = base_url or cfg.ollama_base_url.rstrip("/")
        reference = None
    else:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ModelProviderError("Base URL 必须是完整的 HTTP(S) 地址")
    models = fields.get("models")
    if not isinstance(models, list) or not models:
        raise ModelProviderError("请至少选择一个模型")
    normalized_models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in models:
        if isinstance(item, str):
            model_id = item.strip()
            context_tokens = None
            max_output_tokens = None
            source = "unknown"
        elif isinstance(item, Mapping):
            model_id = str(item.get("model_id") or item.get("id") or "").strip()
            raw_context = item.get("context_tokens")
            context_tokens = (
                int(raw_context) if isinstance(raw_context, (int, str)) else None
            )
            raw_output = item.get("max_output_tokens")
            max_output_tokens = (
                int(raw_output) if isinstance(raw_output, (int, str)) else None
            )
            source = metadata_source(item.get("metadata_source"))
        else:
            continue
        if not model_id or len(model_id) > 200 or model_id in seen:
            continue
        if context_tokens is not None and not 1 <= context_tokens <= 10_000_000:
            raise ModelProviderError("模型上下文窗口必须在 1 到 10,000,000 tokens 之间")
        if max_output_tokens is not None and not 1 <= max_output_tokens <= 10_000_000:
            raise ModelProviderError("模型最大输出必须在 1 到 10,000,000 tokens 之间")
        seen.add(model_id)
        normalized_models.append(
            {
                "model_id": model_id,
                "context_tokens": context_tokens,
                "max_output_tokens": max_output_tokens,
                "metadata_source": source,
            }
        )
    if not normalized_models:
        raise ModelProviderError("模型列表中没有有效的模型 ID")
    return {
        "id": provider_id,
        "name": name,
        "protocol": protocol,
        "base_url": base_url,
        "api_format": api_format,
        "credential_reference": reference,
        "enabled": bool(fields.get("enabled", True)),
        "is_builtin": bool(fields.get("is_builtin", False)),
        "models": normalized_models,
    }


def provider_for_profile(
    provider_settings: Mapping[str, str], profile_id: str
) -> dict[str, Any] | None:
    for provider in _loads(provider_settings.get(PROVIDERS_SETTING_KEY)):
        for model in provider.get("models") or []:
            if isinstance(model, dict) and model.get("profile_id") == profile_id:
                return provider
    return None


class ModelProviderService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = SettingsService(db)

    async def list(self, *, ensure_legacy: bool = True) -> list[dict[str, Any]]:
        values = await self.settings.get_all()
        providers = _loads(values.get(PROVIDERS_SETTING_KEY))
        if not providers and ensure_legacy:
            providers = await self._bootstrap_legacy(values)
        if providers:
            migrated = await self._reconcile_catalog_metadata(providers)
            if migrated:
                await self._write(providers)
            await self._reconcile_default_profile(providers)
            return providers
        return []

    async def _reconcile_default_profile(
        self, providers: list[dict[str, Any]]
    ) -> None:
        """确保默认 Profile 属于当前启用的统一供应商模型。

        旧版 Agent/Coding 模型页可能留下仍为启用状态的默认 Profile。统一
        供应商配置启用后，这类游离 Profile 不应继续接管未显式选模的请求。
        """
        enabled_profile_ids = [
            str(model.get("profile_id"))
            for provider in providers
            if provider.get("enabled")
            for model in provider.get("models", [])
            if isinstance(model, dict) and model.get("profile_id")
        ]
        if not enabled_profile_ids:
            return
        existing_profile_ids = {
            profile.id
            for profile in await ModelProfileService(self.db).list(enabled_only=True)
        }
        enabled_profile_ids = [
            profile_id
            for profile_id in enabled_profile_ids
            if profile_id in existing_profile_ids
        ]
        # 配置恢复、旧备份或测试库可能留下已不存在的 profile 引用。供应商
        # 列表仍应可读，让“当前模型”回落到基础设置，而不是整个接口返回 500。
        if not enabled_profile_ids:
            return
        default = await ModelProfileService(self.db).get_default()
        if default is None or default.id not in enabled_profile_ids:
            await ModelProfileService(self.db).set_default(enabled_profile_ids[0])

    async def get(self, provider_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in await self.list() if item.get("id") == provider_id),
            None,
        )

    async def _bootstrap_legacy(self, values: dict[str, str]) -> list[dict[str, Any]]:
        profiles = list((await self.db.execute(select(ModelProfile))).scalars())
        grouped: dict[str, list[ModelProfile]] = {key: [] for key in PROTOCOLS}
        for profile in profiles:
            protocol = (profile.provider or "").strip().lower()
            if protocol in grouped:
                grouped[protocol].append(profile)

        specs: list[dict[str, Any]] = []
        ollama_models = grouped["ollama"]
        if not ollama_models and values.get("llm_model"):
            profile = await ModelProfileService(self.db).upsert(
                "ollama-local--default",
                {
                    "provider": "ollama",
                    "display_name": values["llm_model"],
                    "model_name": values["llm_model"],
                    "is_local": True,
                    "supports_streaming": True,
                    "context_tokens": int(values.get("llm_context_length") or 32768),
                    "reasoning_efforts": ["low", "medium", "high", "max"],
                    "enabled": True,
                    "is_default": values.get("provider_type") == "ollama",
                },
            )
            ollama_models = [profile]
        specs.append(
            self._legacy_provider(
                "ollama-local",
                "Ollama（本地）",
                "ollama",
                cfg.ollama_base_url,
                "ollama_chat",
                None,
                True,
                ollama_models,
            )
        )
        if grouped["openai"] or values.get("openai_base_url"):
            specs.append(
                self._legacy_provider(
                    "openai-default",
                    values.get("openai_config_name") or "OpenAI 兼容 API",
                    "openai",
                    values.get("openai_base_url") or "https://api.openai.com/v1",
                    "chat_completions",
                    PROVIDER_SECRET_REFS["openai_api_key"] if values.get("openai_api_key") else None,
                    values.get("remote_provider_enabled", "false").lower() == "true",
                    grouped["openai"],
                )
            )
        if grouped["claude"]:
            specs.append(
                self._legacy_provider(
                    "claude-default",
                    "Claude",
                    "claude",
                    "https://api.anthropic.com/v1",
                    "anthropic_messages",
                    PROVIDER_SECRET_REFS["claude_api_key"] if values.get("claude_api_key") else None,
                    values.get("remote_provider_enabled", "false").lower() == "true",
                    grouped["claude"],
                )
            )
        await self._write(specs)
        return specs

    @staticmethod
    def _legacy_provider(
        provider_id: str,
        name: str,
        protocol: str,
        base_url: str,
        api_format: str,
        reference: str | None,
        enabled: bool,
        profiles: list[ModelProfile],
    ) -> dict[str, Any]:
        return {
            "id": provider_id,
            "name": name,
            "protocol": protocol,
            "base_url": base_url.rstrip("/"),
            "api_format": api_format,
            "credential_reference": reference,
            "enabled": enabled,
            "is_builtin": protocol == "ollama",
            "models": [
                {
                    "profile_id": profile.id,
                    "model_id": profile.model_name or profile.id,
                    "context_tokens": profile.context_tokens,
                    "max_output_tokens": None,
                    "metadata_source": "unknown",
                }
                for profile in profiles
                if profile.model_name
            ],
        }

    async def upsert(self, provider_id: str, fields: Mapping[str, Any]) -> dict[str, Any]:
        normalized = _validate_provider({**fields, "id": provider_id})
        providers = await self.list()
        current = next((item for item in providers if item.get("id") == provider_id), None)
        current_models = {
            str(item.get("model_id")): item
            for item in (current or {}).get("models", [])
            if isinstance(item, dict)
        }
        next_models: list[dict[str, Any]] = []
        selected_profile_ids: set[str] = set()
        for model in normalized["models"]:
            model_id = model["model_id"]
            previous = current_models.get(model_id, {})
            profile_id = str(previous.get("profile_id") or _profile_id(provider_id, model_id))
            selected_profile_ids.add(profile_id)
            existing = await self.db.get(ModelProfile, profile_id)
            is_default = bool(existing and existing.is_default)
            profile_fields = {
                "provider": normalized["protocol"],
                "display_name": model_id,
                "model_name": model_id,
                "is_local": normalized["protocol"] == "ollama",
                "native_tool_calls": True,
                "supports_streaming": True,
                "supports_structured_output": False,
                "supports_vision": False,
                "context_tokens": model["context_tokens"],
                "reasoning_efforts": ["low", "medium", "high", "max"],
                "usage_reporting": normalized["protocol"] != "ollama",
                "enabled": normalized["enabled"],
                "is_default": is_default,
            }
            await ModelProfileService(self.db).upsert(profile_id, profile_fields)
            next_models.append({**model, "profile_id": profile_id})

        removed_ids = {
            str(item.get("profile_id"))
            for item in current_models.values()
            if item.get("profile_id") and item.get("profile_id") not in selected_profile_ids
        }
        if removed_ids:
            await self.db.execute(
                delete(ModelToolProfileSnapshotRecord).where(
                    ModelToolProfileSnapshotRecord.profile_id.in_(removed_ids)
                )
            )
            await self.db.execute(delete(ModelProfile).where(ModelProfile.id.in_(removed_ids)))
            await self.db.commit()

        normalized["models"] = next_models
        next_providers = [item for item in providers if item.get("id") != provider_id]
        next_providers.append(normalized)
        next_providers.sort(key=lambda item: (not bool(item.get("is_builtin")), str(item.get("name", "")).lower()))
        await self._write(next_providers)

        await self._reconcile_default_profile(next_providers)
        return normalized

    async def _reconcile_catalog_metadata(
        self, providers: list[dict[str, Any]]
    ) -> int:
        """修复旧版本写入的通用 32K，并补全可确认的官方模型元数据。

        只改动官方 host、目录精确匹配且来源不是用户覆盖的记录；其他已有
        数值保持原样，避免覆盖私有网关或管理员设置的实际限额。
        """
        changed = 0
        for provider in providers:
            base_url = str(provider.get("base_url") or "")
            for model in provider.get("models") or []:
                if not isinstance(model, dict):
                    continue
                model_id = str(model.get("model_id") or "")
                catalog = official_catalog_metadata(base_url, model_id)
                if catalog is None:
                    if "metadata_source" not in model:
                        model["metadata_source"] = "unknown"
                        changed += 1
                    continue
                source = metadata_source(model.get("metadata_source"))
                raw_context = model.get("context_tokens")
                try:
                    current_context = (
                        int(raw_context) if raw_context is not None else None
                    )
                except (TypeError, ValueError):
                    current_context = None
                should_replace = source != "user_override" and current_context in {
                    None,
                    32768,
                    catalog.context_tokens,
                }
                if not should_replace:
                    continue
                updates = {
                    "context_tokens": catalog.context_tokens,
                    "max_output_tokens": catalog.max_output_tokens,
                    "metadata_source": catalog.metadata_source,
                }
                if any(model.get(key) != value for key, value in updates.items()):
                    model.update(updates)
                    changed += 1
                profile_id = str(model.get("profile_id") or "")
                if profile_id:
                    profile = await self.db.get(ModelProfile, profile_id)
                    if profile is not None and profile.context_tokens != catalog.context_tokens:
                        profile.context_tokens = catalog.context_tokens
                        changed += 1
        return changed

    async def delete(self, provider_id: str) -> None:
        providers = await self.list()
        target = next((item for item in providers if item.get("id") == provider_id), None)
        if target is None:
            raise ModelProviderNotFound("模型供应商不存在")
        profile_ids = [
            str(item.get("profile_id"))
            for item in target.get("models", [])
            if isinstance(item, dict) and item.get("profile_id")
        ]
        if profile_ids:
            await self.db.execute(delete(ModelToolProfileSnapshotRecord).where(ModelToolProfileSnapshotRecord.profile_id.in_(profile_ids)))
            await self.db.execute(delete(ModelProfile).where(ModelProfile.id.in_(profile_ids)))
            await self.db.commit()
        remaining = [item for item in providers if item.get("id") != provider_id]
        await self._write(remaining)
        await self._reconcile_default_profile(remaining)

    async def _write(self, providers: list[dict[str, Any]]) -> None:
        await self.settings.update(
            {PROVIDERS_SETTING_KEY: json.dumps(providers, ensure_ascii=False, separators=(",", ":"))}
        )
