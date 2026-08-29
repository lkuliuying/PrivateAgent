"""统一模型供应商 API：供应商配置、模型发现与运行时密钥热更新。"""
from __future__ import annotations

import asyncio
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.model_metadata import (
    DiscoveredModelMetadata,
    discover_model_metadata,
    metadata_source,
    ollama_show_metadata,
)
from ..core.model_providers import (
    ModelProviderError,
    ModelProviderNotFound,
    ModelProviderService,
)
from ..core.settings import (
    clear_model_provider_runtime_secret,
    model_provider_secret_reference,
    resolve_model_provider_secret,
    set_model_provider_runtime_secret,
)
from ..llm.url_policy import UnsafeModelEndpointError, validate_remote_base_url
from .routes_providers import _safe_upstream_detail

router = APIRouter(prefix="/model-providers", tags=["model-providers"])

ProviderProtocol = Literal["ollama", "openai", "claude"]
ApiFormat = Literal["ollama_chat", "chat_completions", "anthropic_messages"]


class ProviderModelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=200)
    context_tokens: int | None = Field(default=None, ge=1, le=10_000_000)
    max_output_tokens: int | None = Field(default=None, ge=1, le=10_000_000)
    metadata_source: Literal[
        "provider_api", "local_model", "official_catalog", "user_override", "unknown"
    ] = "unknown"


class ModelProviderUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    protocol: ProviderProtocol
    base_url: str = Field(min_length=1, max_length=500)
    api_format: ApiFormat
    credential_reference: str | None = Field(default=None, max_length=300)
    enabled: bool = True
    is_builtin: bool = False
    models: list[ProviderModelIn] = Field(min_length=1, max_length=256)


class ProviderModelOut(BaseModel):
    profile_id: str
    model_id: str
    context_tokens: int | None
    max_output_tokens: int | None = None
    metadata_source: str = "unknown"


class DiscoveredModelOut(BaseModel):
    model_id: str
    context_tokens: int | None = None
    max_output_tokens: int | None = None
    metadata_source: str = "unknown"


class ModelDiscoveryOut(BaseModel):
    models: list[DiscoveredModelOut]


class ModelProviderOut(BaseModel):
    id: str
    name: str
    protocol: ProviderProtocol
    base_url: str
    api_format: ApiFormat
    enabled: bool
    is_builtin: bool
    api_key_configured: bool
    models: list[ProviderModelOut]


class ModelProviderSecretUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: SecretStr = Field(min_length=1, max_length=16_384)


class ModelDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str | None = Field(default=None, max_length=64)
    protocol: ProviderProtocol
    base_url: str = Field(min_length=1, max_length=500)
    credential_reference: str | None = Field(default=None, max_length=300)
    api_key: SecretStr | None = Field(default=None, max_length=16_384)


async def _out(db: AsyncSession, provider: dict) -> ModelProviderOut:
    values = await ModelProviderService(db).settings.get_all()
    provider_id = str(provider.get("id") or "")
    reference = str(provider.get("credential_reference") or "") or None
    return ModelProviderOut(
        id=provider_id,
        name=str(provider.get("name") or provider_id),
        protocol=str(provider.get("protocol") or "ollama"),
        base_url=str(provider.get("base_url") or ""),
        api_format=str(provider.get("api_format") or "chat_completions"),
        enabled=bool(provider.get("enabled", True)),
        is_builtin=bool(provider.get("is_builtin", False)),
        api_key_configured=bool(
            resolve_model_provider_secret(
                provider_id, reference, legacy_settings=values
            )
        ),
        models=[
            ProviderModelOut(
                profile_id=str(item.get("profile_id") or ""),
                model_id=str(item.get("model_id") or ""),
                context_tokens=(
                    int(item["context_tokens"])
                    if item.get("context_tokens") is not None
                    else None
                ),
                max_output_tokens=(
                    int(item["max_output_tokens"])
                    if item.get("max_output_tokens") is not None
                    else None
                ),
                metadata_source=metadata_source(item.get("metadata_source")),
            )
            for item in provider.get("models", [])
            if isinstance(item, dict) and item.get("profile_id") and item.get("model_id")
        ],
    )


@router.get("", response_model=list[ModelProviderOut])
async def list_model_providers(
    db: AsyncSession = Depends(get_session),
) -> list[ModelProviderOut]:
    return [await _out(db, item) for item in await ModelProviderService(db).list()]


@router.put("/{provider_id}", response_model=ModelProviderOut)
async def upsert_model_provider(
    provider_id: str,
    request: ModelProviderUpsert,
    db: AsyncSession = Depends(get_session),
) -> ModelProviderOut:
    payload = request.model_dump()
    if payload.get("credential_reference") is None:
        current = await ModelProviderService(db).get(provider_id)
        if current is not None:
            payload["credential_reference"] = current.get("credential_reference")
    try:
        provider = await ModelProviderService(db).upsert(
            provider_id, payload
        )
    except ModelProviderError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await _out(db, provider)


@router.delete("/{provider_id}", status_code=204)
async def delete_model_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    try:
        await ModelProviderService(db).delete(provider_id)
    except ModelProviderNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/{provider_id}/runtime-secret")
async def update_model_provider_runtime_secret(
    provider_id: str, request: ModelProviderSecretUpdate
) -> dict[str, object]:
    set_model_provider_runtime_secret(provider_id, request.secret.get_secret_value())
    return {
        "provider_id": provider_id,
        "credential_reference": model_provider_secret_reference(provider_id),
        "available": True,
    }


@router.delete("/{provider_id}/runtime-secret")
async def delete_model_provider_runtime_secret(provider_id: str) -> dict[str, object]:
    clear_model_provider_runtime_secret(provider_id)
    return {"provider_id": provider_id, "available": False}


@router.post("/discover/models", response_model=ModelDiscoveryOut)
async def discover_model_provider_models(
    request: ModelDiscoveryRequest,
    db: AsyncSession = Depends(get_session),
) -> ModelDiscoveryOut:
    protocol = request.protocol
    base_url = request.base_url.strip().rstrip("/")
    trust_env = protocol != "ollama"
    headers: dict[str, str] = {"Accept": "application/json"}
    values = await ModelProviderService(db).settings.get_all()
    provider_id = request.provider_id or "draft"
    reference = request.credential_reference
    if request.provider_id and not reference:
        saved_provider = await ModelProviderService(db).get(request.provider_id)
        if saved_provider is not None:
            reference = str(saved_provider.get("credential_reference") or "") or None
    secret = (
        request.api_key.get_secret_value().strip()
        if request.api_key is not None
        else resolve_model_provider_secret(
            provider_id,
            reference,
            legacy_settings=values,
        ).strip()
    )

    if protocol == "ollama":
        from urllib.parse import urlsplit

        if (urlsplit(base_url).hostname or "").lower() not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "0.0.0.0",
        }:
            raise HTTPException(422, "Ollama 模型列表只允许从本机地址获取")
        url = f"{base_url}/api/tags"
    else:
        try:
            base_url = validate_remote_base_url(base_url)
        except UnsafeModelEndpointError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not secret:
            raise HTTPException(409, "请先输入 API Key")
        if protocol == "claude":
            headers.update(
                {"x-api-key": secret, "anthropic-version": "2023-06-01"}
            )
        else:
            headers["Authorization"] = f"Bearer {secret}"
        url = f"{base_url}/models"

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=False,
            trust_env=trust_env,
        ) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            models = discover_model_metadata(
                payload,
                base_url=base_url,
                protocol=protocol,
            )
            if protocol == "ollama" and models:
                semaphore = asyncio.Semaphore(6)

                async def enrich_ollama(
                    model: DiscoveredModelMetadata,
                ) -> DiscoveredModelMetadata:
                    async with semaphore:
                        try:
                            detail = await client.post(
                                f"{base_url}/api/show",
                                json={"model": model.model_id, "verbose": False},
                            )
                            detail.raise_for_status()
                            return ollama_show_metadata(
                                model.model_id, detail.json()
                            ) or model
                        except (httpx.HTTPError, TypeError, ValueError):
                            # 单个本地模型详情不可用不应让整个列表失败；该模型
                            # 保持“未知”，用户仍可选择并自行覆盖。
                            return model

                enriched = await asyncio.gather(
                    *(enrich_ollama(model) for model in models[:256])
                )
                if len(models) > 256:
                    enriched.extend(models[256:])
                models = enriched
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        detail = _safe_upstream_detail(exc.response)
        public_status = status if status in {400, 401, 403, 404, 409, 429} else 502
        raise HTTPException(public_status, f"模型列表获取失败：{detail}") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, "无法连接模型服务，请检查地址与网络") from exc

    except (TypeError, ValueError) as exc:
        raise HTTPException(502, "模型服务返回了无效的模型列表") from exc
    if not models:
        raise HTTPException(502, "模型服务未返回可选择的模型 ID")
    return ModelDiscoveryOut(
        models=[DiscoveredModelOut(**model.as_dict()) for model in models]
    )
