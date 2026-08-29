"""应用设置：运行时可调参数，存 settings 表（KV）。

读取时 settings 表有值则用，否则用 config（.env）默认。
第一阶段 Provider 接口位（OpenAI/Claude）仅预留字段，UI 不承诺云端可用。
"""
from __future__ import annotations

import json
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from .models import Setting

PROVIDER_SECRET_REFS: dict[str, str] = {
    "openai_api_key": "secret://os-keyring/provider/openai",
    "claude_api_key": "secret://os-keyring/provider/claude",
}
PROVIDER_SECRET_ENVS: dict[str, str] = {
    "openai_api_key": "PA_OPENAI_API_KEY",
    "claude_api_key": "PA_CLAUDE_API_KEY",
}
PROVIDER_SECRET_KEYS: dict[str, str] = {
    "openai": "openai_api_key",
    "claude": "claude_api_key",
}

# 运行中由已认证的本地桌面 API 热更新。键存在但值为空表示显式清除，
# 不能再回落到 sidecar 启动时注入的旧环境变量。
_PROVIDER_RUNTIME_SECRETS: dict[str, str] = {}

# 自定义模型供应商的非秘密配置保存在 settings 表中；API Key 仍只存系统
# 凭据库引用。进程启动时桌面壳注入引用 -> 明文映射，保存新 Key 后则通过
# 已认证的 loopback API 热更新这一内存映射，因此无需重启 sidecar。
_MODEL_PROVIDER_RUNTIME_SECRETS: dict[str, str] = {}


def model_provider_secret_reference(provider_id: str) -> str:
    return f"secret://os-keyring/model-provider/{provider_id}"


def _startup_model_provider_secrets() -> dict[str, str]:
    raw = os.environ.get("PA_MODEL_PROVIDER_SECRETS_JSON", "")
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(reference): str(secret)
        for reference, secret in payload.items()
        if isinstance(reference, str) and isinstance(secret, str)
    }


_MODEL_PROVIDER_STARTUP_SECRETS = _startup_model_provider_secrets()


def resolve_model_provider_secret(
    provider_id: str,
    credential_reference: str | None,
    *,
    legacy_settings: dict[str, str] | None = None,
) -> str:
    """Resolve a provider-specific key without exposing or persisting plaintext."""
    reference = (credential_reference or "").strip()
    if not reference:
        return ""
    if reference in _MODEL_PROVIDER_RUNTIME_SECRETS:
        return _MODEL_PROVIDER_RUNTIME_SECRETS[reference]
    if reference in _MODEL_PROVIDER_STARTUP_SECRETS:
        return _MODEL_PROVIDER_STARTUP_SECRETS[reference]
    # 兼容升级前固定 OpenAI / Claude 凭据引用。
    values = legacy_settings or {}
    if reference == PROVIDER_SECRET_REFS["openai_api_key"]:
        return values.get("openai_api_key", "")
    if reference == PROVIDER_SECRET_REFS["claude_api_key"]:
        return values.get("claude_api_key", "")
    expected = model_provider_secret_reference(provider_id)
    if reference != expected:
        return ""
    return ""


def set_model_provider_runtime_secret(provider_id: str, secret: str) -> None:
    normalized = secret.strip()
    if not normalized:
        raise ValueError("provider secret must not be empty")
    if len(normalized) > 16_384:
        raise ValueError("provider secret is too long")
    _MODEL_PROVIDER_RUNTIME_SECRETS[
        model_provider_secret_reference(provider_id)
    ] = normalized


def clear_model_provider_runtime_secret(provider_id: str) -> None:
    _MODEL_PROVIDER_RUNTIME_SECRETS[
        model_provider_secret_reference(provider_id)
    ] = ""


def is_provider_secret_reference(key: str, value: str | None) -> bool:
    return bool(value) and value == PROVIDER_SECRET_REFS.get(key)


def resolve_provider_secret(key: str, stored_value: str | None) -> str:
    """Resolve a fixed OS-keyring reference from the latest process-local value."""
    if is_provider_secret_reference(key, stored_value):
        if key in _PROVIDER_RUNTIME_SECRETS:
            return _PROVIDER_RUNTIME_SECRETS[key]
        return os.environ.get(PROVIDER_SECRET_ENVS[key], "")
    # Read-only compatibility for legacy rows. Public APIs never expose this value
    # and all new writes are restricted to a fixed reference or deletion.
    return stored_value or ""


def set_provider_runtime_secret(provider: str, secret: str) -> None:
    """Hot-update one provider secret in sidecar memory without persisting it."""
    key = PROVIDER_SECRET_KEYS.get(provider)
    if key is None:
        raise ValueError("unsupported provider")
    normalized = secret.strip()
    if not normalized:
        raise ValueError("provider secret must not be empty")
    if len(normalized) > 16_384:
        raise ValueError("provider secret is too long")
    _PROVIDER_RUNTIME_SECRETS[key] = normalized


def clear_provider_runtime_secret(provider: str) -> None:
    """Explicitly mask both the hot value and any stale startup injection."""
    key = PROVIDER_SECRET_KEYS.get(provider)
    if key is None:
        raise ValueError("unsupported provider")
    _PROVIDER_RUNTIME_SECRETS[key] = ""

# 可调参数 key -> 默认值（来自 .env/config）
DEFAULTS: dict[str, str] = {
    "llm_model": cfg.llm_model,
    "embed_model": cfg.embed_model,
    "llm_temperature": str(cfg.llm_temperature),
    "llm_context_length": str(cfg.llm_context_length),
    "kb_enabled_by_default": str(cfg.kb_enabled_by_default).lower(),
    # Provider / 模型路由（第四阶段 M6）
    "provider_type": "ollama",
    "remote_provider_enabled": "false",
    "openai_api_key": "",
    "openai_config_name": "OpenAI 兼容 API",
    "openai_base_url": "",
    "openai_model": "gpt-4o-mini",
    "claude_api_key": "",
    "claude_model": "claude-3-5-sonnet-latest",
    # 提醒与例行任务（第六阶段 M3）
    "reminders_enabled": "true",
    "reminder_tick_seconds": "60",
    "desktop_notifications_enabled": "false",
    # v0.9.0 H1-D（计划 §5.8）：旧配置 → Coding profile 导入状态（幂等升级）。
    # 词汇：pending（未评估）/ auto_imported（升级自动导入）/
    # imported（用户显式导入）/ dismissed（用户关闭一次性向导）/ not_needed。
    "coding_profile_import_state": "pending",
    # 统一模型供应商配置（仅非秘密元数据和 keyring 引用）。
    "model_provider_configs": "[]",
}


class SettingsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self) -> dict[str, str]:
        """返回全部设置（stored 优先，否则默认）。"""
        stmt = select(Setting)
        result = await self.db.execute(stmt)
        stored = {s.key: s.value for s in result.scalars().all()}
        values = {k: stored.get(k, v) or "" for k, v in DEFAULTS.items()}
        for key in PROVIDER_SECRET_REFS:
            values[key] = resolve_provider_secret(key, stored.get(key))
        return values

    async def get(self, key: str) -> str:
        return (await self.get_all()).get(key, DEFAULTS.get(key, ""))

    async def update(self, updates: dict[str, str]) -> dict[str, str]:
        """更新已知 key，忽略未知 key。"""
        for k, v in updates.items():
            if k not in DEFAULTS:
                continue
            if k in PROVIDER_SECRET_REFS and v not in ("", PROVIDER_SECRET_REFS[k]):
                raise ValueError("provider secrets must be stored by reference")
            existing = await self.db.get(Setting, k)
            if existing:
                existing.value = v
            else:
                self.db.add(Setting(key=k, value=v))
        await self.db.commit()
        return await self.get_all()

    async def set_provider_secret_reference(
        self, provider: str, *, configured: bool
    ) -> dict[str, object]:
        key = PROVIDER_SECRET_KEYS.get(provider)
        if key is None:
            raise ValueError("unsupported provider")
        if not configured:
            clear_provider_runtime_secret(provider)
        value = PROVIDER_SECRET_REFS[key] if configured else ""
        await self.update({key: value})
        return await self.get_provider_secret_status(provider)

    async def get_provider_secret_status(
        self, provider: str | None = None
    ) -> dict[str, dict[str, object]] | dict[str, object]:
        stmt = select(Setting).where(Setting.key.in_(tuple(PROVIDER_SECRET_REFS)))
        result = await self.db.execute(stmt)
        stored = {s.key: s.value or "" for s in result.scalars().all()}

        statuses: dict[str, dict[str, object]] = {}
        for provider_name, key in PROVIDER_SECRET_KEYS.items():
            raw = stored.get(key, "")
            if is_provider_secret_reference(key, raw):
                storage = "os_keyring"
            elif raw:
                storage = "legacy"
            else:
                storage = "none"
            statuses[provider_name] = {
                "configured": bool(raw),
                "available": bool(resolve_provider_secret(key, raw)),
                "storage": storage,
            }
        if provider is not None:
            if provider not in statuses:
                raise ValueError("unsupported provider")
            return statuses[provider]
        return statuses
