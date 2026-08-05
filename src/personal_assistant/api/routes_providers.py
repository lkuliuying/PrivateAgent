"""Provider configuration, health checks, and OS-keyring references."""
from __future__ import annotations

from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.provider import (
    ClaudeProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    ProviderRouter,
)
from ..core.settings import SettingsService

router = APIRouter(tags=["providers"])

ProviderType = Literal["ollama", "openai", "claude"]
RemoteProviderType = Literal["openai", "claude"]
SecretStatuses = dict[str, dict[str, object]]


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_type: ProviderType | None = None
    remote_provider_enabled: bool | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    claude_model: str | None = None


class ProviderSecretReferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool


def _public_config(s: dict[str, str], secret_statuses: SecretStatuses) -> dict:
    return {
        "provider_type": s.get("provider_type", "ollama"),
        "remote_provider_enabled": s.get(
            "remote_provider_enabled", "false"
        ).lower()
        == "true",
        "ollama": {
            "model": s.get("llm_model"),
            "embed_model": s.get("embed_model"),
        },
        "openai": {
            "base_url": s.get("openai_base_url"),
            "model": s.get("openai_model"),
            **secret_statuses["openai"],
        },
        "claude": {
            "model": s.get("claude_model"),
            **secret_statuses["claude"],
        },
    }


async def _provider_state(
    service: SettingsService,
) -> tuple[dict[str, str], SecretStatuses]:
    values = await service.get_all()
    statuses = cast(SecretStatuses, await service.get_provider_secret_status())
    return values, statuses


@router.get("/providers")
async def list_providers(db: AsyncSession = Depends(get_session)) -> dict:
    service = SettingsService(db)
    values, statuses = await _provider_state(service)
    router_ = ProviderRouter(values)
    remote_enabled = values.get("remote_provider_enabled", "false").lower() == "true"
    return {
        "config": _public_config(values, statuses),
        "privacy": router_.privacy_scope(),
        "items": [
            {"type": "ollama", "enabled": True, "remote": False},
            {
                "type": "openai",
                "enabled": remote_enabled,
                "remote": True,
                **statuses["openai"],
            },
            {
                "type": "claude",
                "enabled": remote_enabled,
                "remote": True,
                **statuses["claude"],
            },
        ],
    }


@router.patch("/providers")
async def update_providers(
    req: ProviderUpdate, db: AsyncSession = Depends(get_session)
) -> dict:
    data = {k: str(v) for k, v in req.model_dump().items() if v is not None}
    if "remote_provider_enabled" in data:
        data["remote_provider_enabled"] = data["remote_provider_enabled"].lower()
    service = SettingsService(db)
    values = await service.update(data)
    statuses = cast(SecretStatuses, await service.get_provider_secret_status())
    return {
        "config": _public_config(values, statuses),
        "privacy": ProviderRouter(values).privacy_scope(),
    }


@router.put("/providers/{provider}/secret-reference")
async def update_provider_secret_reference(
    provider: RemoteProviderType,
    req: ProviderSecretReferenceUpdate,
    db: AsyncSession = Depends(get_session),
) -> dict:
    status = await SettingsService(db).set_provider_secret_reference(
        provider, configured=req.configured
    )
    return {
        "provider": provider,
        "secret": status,
        "restart_required": True,
    }


@router.post("/providers/test")
async def test_provider(db: AsyncSession = Depends(get_session)) -> dict:
    values = await SettingsService(db).get_all()
    provider_type = values.get("provider_type", "ollama")
    remote_enabled = (
        values.get("remote_provider_enabled", "false").lower() == "true"
    )
    if provider_type == "openai":
        if not remote_enabled:
            raise HTTPException(409, "远程 Provider 已关闭")
        health = await OpenAICompatibleProvider(
            base_url=values.get("openai_base_url") or "https://api.openai.com/v1",
            api_key=values.get("openai_api_key") or "",
            model=values.get("openai_model") or "gpt-4o-mini",
        ).health()
    elif provider_type == "claude":
        if not remote_enabled:
            raise HTTPException(409, "远程 Provider 已关闭")
        health = await ClaudeProvider(
            api_key=values.get("claude_api_key") or "",
            model=values.get("claude_model") or "claude-3-5-sonnet-latest",
        ).health()
    else:
        health = await OllamaProvider(llm_model=values.get("llm_model")).health()
    return {
        "provider_type": provider_type,
        "health": health,
        "privacy": ProviderRouter(values).privacy_scope(),
    }
