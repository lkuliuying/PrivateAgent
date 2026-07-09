"""第四阶段 M6：模型 Provider 配置、健康检查与隐私范围。"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.provider import ClaudeProvider, OllamaProvider, OpenAICompatibleProvider, ProviderRouter
from ..core.settings import SettingsService

router = APIRouter(tags=["providers"])

# 密钥掩码占位（与 routes_settings 一致）；PATCH 收到此值时跳过，保留原值，
# 避免把掩码当真实密钥写入（第八阶段审查回归修复）。
_KEY_MASK = "********"


ProviderType = Literal["ollama", "openai", "claude"]


class ProviderUpdate(BaseModel):
    provider_type: ProviderType | None = None
    remote_provider_enabled: bool | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    claude_api_key: str | None = None
    claude_model: str | None = None


def _public_config(s: dict[str, str]) -> dict:
    return {
        "provider_type": s.get("provider_type", "ollama"),
        "remote_provider_enabled": s.get("remote_provider_enabled", "false").lower()
        == "true",
        "ollama": {
            "model": s.get("llm_model"),
            "embed_model": s.get("embed_model"),
        },
        "openai": {
            "base_url": s.get("openai_base_url"),
            "model": s.get("openai_model"),
            "configured": bool(s.get("openai_api_key")),
        },
        "claude": {
            "model": s.get("claude_model"),
            "configured": bool(s.get("claude_api_key")),
        },
    }


@router.get("/providers")
async def list_providers(db: AsyncSession = Depends(get_session)) -> dict:
    s = await SettingsService(db).get_all()
    router_ = ProviderRouter(s)
    return {
        "config": _public_config(s),
        "privacy": router_.privacy_scope(),
        "items": [
            {"type": "ollama", "enabled": True, "remote": False},
            {
                "type": "openai",
                "enabled": s.get("remote_provider_enabled", "false").lower() == "true",
                "remote": True,
                "configured": bool(s.get("openai_api_key")),
            },
            {
                "type": "claude",
                "enabled": s.get("remote_provider_enabled", "false").lower() == "true",
                "remote": True,
                "configured": bool(s.get("claude_api_key")),
            },
        ],
    }


@router.patch("/providers")
async def update_providers(
    req: ProviderUpdate, db: AsyncSession = Depends(get_session)
) -> dict:
    data = {k: str(v) for k, v in req.model_dump().items() if v is not None}
    # 密钥掩码占位 -> 跳过（保留原值），避免覆盖真实密钥
    data = {
        k: v
        for k, v in data.items()
        if not (k in ("openai_api_key", "claude_api_key") and v == _KEY_MASK)
    }
    if "remote_provider_enabled" in data:
        data["remote_provider_enabled"] = data["remote_provider_enabled"].lower()
    s = await SettingsService(db).update(data)
    return {
        "config": _public_config(s),
        "privacy": ProviderRouter(s).privacy_scope(),
    }


@router.post("/providers/test")
async def test_provider(db: AsyncSession = Depends(get_session)) -> dict:
    s = await SettingsService(db).get_all()
    provider_type = s.get("provider_type", "ollama")
    remote_enabled = s.get("remote_provider_enabled", "false").lower() == "true"
    if provider_type == "openai":
        if not remote_enabled:
            raise HTTPException(409, "远程 Provider 已关闭")
        health = await OpenAICompatibleProvider(
            base_url=s.get("openai_base_url") or "https://api.openai.com/v1",
            api_key=s.get("openai_api_key") or "",
            model=s.get("openai_model") or "gpt-4o-mini",
        ).health()
    elif provider_type == "claude":
        if not remote_enabled:
            raise HTTPException(409, "远程 Provider 已关闭")
        health = await ClaudeProvider(
            api_key=s.get("claude_api_key") or "",
            model=s.get("claude_model") or "claude-3-5-sonnet-latest",
        ).health()
    else:
        health = await OllamaProvider(llm_model=s.get("llm_model")).health()
    return {
        "provider_type": provider_type,
        "health": health,
        "privacy": ProviderRouter(s).privacy_scope(),
    }
