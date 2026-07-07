"""应用设置：运行时可调参数，存 settings 表（KV）。

读取时 settings 表有值则用，否则用 config（.env）默认。
第一阶段 Provider 接口位（OpenAI/Claude）仅预留字段，UI 不承诺云端可用。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from .models import Setting

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
}


class SettingsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self) -> dict[str, str]:
        """返回全部设置（stored 优先，否则默认）。"""
        stmt = select(Setting)
        result = await self.db.execute(stmt)
        stored = {s.key: s.value for s in result.scalars().all()}
        return {k: stored.get(k, v) for k, v in DEFAULTS.items()}

    async def get(self, key: str) -> str:
        return (await self.get_all()).get(key, DEFAULTS.get(key, ""))

    async def update(self, updates: dict[str, str]) -> dict[str, str]:
        """更新已知 key，忽略未知 key。"""
        for k, v in updates.items():
            if k not in DEFAULTS:
                continue
            existing = await self.db.get(Setting, k)
            if existing:
                existing.value = v
            else:
                self.db.add(Setting(key=k, value=v))
        await self.db.commit()
        return await self.get_all()
