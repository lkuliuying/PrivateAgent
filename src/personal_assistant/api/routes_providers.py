"""Provider configuration, health checks, and OS-keyring references."""
from __future__ import annotations

from typing import Any, Literal, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from ..core.db import get_session
from ..core.provider import (
    ClaudeProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    ProviderRouter,
)
from ..core.settings import (
    SettingsService,
    clear_provider_runtime_secret,
    set_provider_runtime_secret,
)
from ..llm.url_policy import UnsafeModelEndpointError, validate_remote_base_url

router = APIRouter(tags=["providers"])

ProviderType = Literal["ollama", "openai", "claude"]
RemoteProviderType = Literal["openai", "claude"]
SecretStatuses = dict[str, dict[str, object]]


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_type: ProviderType | None = None
    remote_provider_enabled: bool | None = None
    openai_config_name: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    claude_model: str | None = None


class ProviderSecretReferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool


class ProviderRuntimeSecretUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: SecretStr = Field(min_length=1, max_length=16_384)


class ProviderModelsRequest(BaseModel):
    """Explicit model discovery request; a draft secret is never persisted."""

    model_config = ConfigDict(extra="forbid")

    provider_type: ProviderType
    remote_provider_enabled: bool = False
    base_url: str | None = Field(default=None, max_length=2_048)
    api_key: SecretStr | None = Field(default=None, max_length=16_384)


def _safe_upstream_detail(response: httpx.Response) -> str:
    """Keep the provider's stable code/message without retaining response bodies."""
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return f"HTTP {response.status_code}"
    if not isinstance(payload, dict):
        return f"HTTP {response.status_code}"
    error = payload.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or "").strip()[:64]
        message = str(error.get("message") or "").strip()[:300]
    else:
        code = str(payload.get("code") or "").strip()[:64]
        message = str(
            payload.get("message") or payload.get("detail") or ""
        ).strip()[:300]
    detail = " · ".join(part for part in (code, message) if part)
    return detail or f"HTTP {response.status_code}"


def _model_ids(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("data")
    if isinstance(raw_items, dict):
        raw_items = raw_items.get("items") or raw_items.get("list")
    if not isinstance(raw_items, list):
        raw_items = payload.get("models")
    if not isinstance(raw_items, list):
        return []
    values: set[str] = set()
    for item in raw_items[:5_000]:
        if isinstance(item, str):
            candidate = item
        elif isinstance(item, dict):
            candidate = item.get("id") or item.get("name") or item.get("model")
        else:
            continue
        model_id = str(candidate or "").strip()
        if model_id and len(model_id) <= 200:
            values.add(model_id)
    return sorted(values, key=str.casefold)


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
            "name": s.get("openai_config_name") or "OpenAI 兼容 API",
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
        "restart_required": False,
    }


@router.put("/providers/{provider}/runtime-secret")
async def update_provider_runtime_secret(
    provider: RemoteProviderType,
    req: ProviderRuntimeSecretUpdate,
) -> dict:
    """Replace the process-local Provider secret without persisting or echoing it."""
    set_provider_runtime_secret(provider, req.secret.get_secret_value())
    return {"provider": provider, "available": True}


@router.delete("/providers/{provider}/runtime-secret")
async def delete_provider_runtime_secret(provider: RemoteProviderType) -> dict:
    """Mask the runtime secret immediately, including a stale startup value."""
    clear_provider_runtime_secret(provider)
    return {"provider": provider, "available": False}


@router.post("/providers/models")
async def list_provider_models(
    req: ProviderModelsRequest,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Fetch selectable model IDs from the configured upstream service."""
    values = await SettingsService(db).get_all()
    provider = req.provider_type
    headers: dict[str, str] = {"Accept": "application/json"}
    trust_env = True

    if provider == "ollama":
        base_url = cfg.ollama_base_url.rstrip("/")
        url = f"{base_url}/api/tags"
        trust_env = False
    else:
        if not req.remote_provider_enabled:
            raise HTTPException(409, "请先确认允许远程模型服务接收请求")
        if provider == "openai":
            raw_base_url = (
                req.base_url or values.get("openai_base_url") or ""
            ).strip()
            if not raw_base_url:
                raise HTTPException(422, "请先填写模型服务 Base URL")
            try:
                base_url = validate_remote_base_url(raw_base_url)
            except UnsafeModelEndpointError as exc:
                raise HTTPException(422, str(exc)) from exc
            secret = (
                req.api_key.get_secret_value().strip()
                if req.api_key is not None
                else (values.get("openai_api_key") or "").strip()
            )
            if not secret:
                raise HTTPException(409, "请先配置 API Key")
            headers["Authorization"] = f"Bearer {secret}"
            url = f"{base_url}/models"
        else:
            secret = (
                req.api_key.get_secret_value().strip()
                if req.api_key is not None
                else (values.get("claude_api_key") or "").strip()
            )
            if not secret:
                raise HTTPException(409, "请先配置 Claude API Key")
            headers.update(
                {
                    "x-api-key": secret,
                    "anthropic-version": "2023-06-01",
                }
            )
            url = "https://api.anthropic.com/v1/models"

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=False,
            trust_env=trust_env,
        ) as client:
            response = await client.get(url, headers=headers)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        detail = _safe_upstream_detail(exc.response)
        public_status = status if status in {400, 401, 403, 404, 409, 429} else 502
        raise HTTPException(public_status, f"模型列表获取失败：{detail}") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, "无法连接模型服务，请检查地址与网络") from exc

    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise HTTPException(502, "模型服务返回了无效的模型列表") from exc
    models = _model_ids(payload)
    if not models:
        raise HTTPException(502, "模型服务未返回可选择的模型 ID")
    return {"provider_type": provider, "models": models}


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
