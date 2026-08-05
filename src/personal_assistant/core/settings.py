"""应用设置：运行时可调参数，存 settings 表（KV）。

读取时 settings 表有值则用，否则用 config（.env）默认。
第一阶段 Provider 接口位（OpenAI/Claude）仅预留字段，UI 不承诺云端可用。
"""
from __future__ import annotations

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


def is_provider_secret_reference(key: str, value: str | None) -> bool:
    return bool(value) and value == PROVIDER_SECRET_REFS.get(key)


def resolve_provider_secret(key: str, stored_value: str | None) -> str:
    """Resolve a fixed OS-keyring reference from process-only startup injection."""
    if is_provider_secret_reference(key, stored_value):
        return os.environ.get(PROVIDER_SECRET_ENVS[key], "")
    # Read-only compatibility for legacy rows. Public APIs never expose this value
    # and all new writes are restricted to a fixed reference or deletion.
    return stored_value or ""

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
    "openai_base_url": "",
    "openai_model": "gpt-4o-mini",
    "claude_api_key": "",
    "claude_model": "claude-3-5-sonnet-latest",
    # 提醒与例行任务（第六阶段 M3）
    "reminders_enabled": "true",
    "reminder_tick_seconds": "60",
    "desktop_notifications_enabled": "false",
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
