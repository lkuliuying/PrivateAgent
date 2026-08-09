"""v0.5.0 B3：HTTP endpoint profile 管理 API。

只管理非敏感元数据与 keyring secret 引用；明文 key 通过
``PA_HTTP_PROFILES_SECRETS_JSON`` 通道由桌面壳注入 sidecar 内存。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.db import get_session
from ..core.http_profiles import (
    HttpProfileConflict,
    HttpProfileError,
    HttpProfileNotFound,
    HttpProfileService,
)

router = APIRouter(prefix="/http-profiles", tags=["http-profiles"])


class HttpProfilePayload(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    scheme: str = Field(default="https", pattern="^(https|http)$")
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    path_prefix: str = Field(default="/", max_length=1024)
    allowed_methods: list[str] = Field(min_length=1, max_length=3)
    request_schema: dict[str, Any] | None = None
    response_schema: dict[str, Any] | None = None
    max_request_bytes: int = Field(default=65_536, ge=1_024, le=1_048_576)
    max_response_bytes: int = Field(default=1_048_576, ge=1_024, le=8 * 1_048_576)
    timeout_ms: int = Field(default=30_000, ge=1_000, le=60_000)
    headers: dict[str, str] = Field(default_factory=dict, max_length=16)
    # v0.5.0 rc.2：只声明需要密钥的请求头名；keyring 引用由后端生成，
    # 明文只经 OS keyring（Rust CredUI prompt），不进入 Vue/API/DB。
    secret_slots: list[str] = Field(default_factory=list, max_length=8)
    retry_policy: dict[str, Any] | None = None
    allow_insecure_local: bool = False
    allow_private_network: bool = False
    enabled: bool = False

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name 不能为空")
        return value


class HttpProfileOut(BaseModel):
    id: int
    name: str
    scheme: str
    host: str
    port: int
    path_prefix: str
    allowed_methods: list[str]
    max_request_bytes: int
    max_response_bytes: int
    timeout_ms: int
    headers: dict[str, str]
    secret_slots: list[str]
    secret_refs: dict[str, str]
    allow_insecure_local: bool
    allow_private_network: bool
    enabled: bool
    version: int
    created_at: str
    updated_at: str


def _to_out(profile) -> HttpProfileOut:
    return HttpProfileOut(
        id=profile.id,
        name=profile.name,
        scheme=profile.scheme,
        host=profile.host,
        port=profile.port,
        path_prefix=profile.path_prefix,
        allowed_methods=list(profile.allowed_methods_json or []),
        max_request_bytes=profile.max_request_bytes,
        max_response_bytes=profile.max_response_bytes,
        timeout_ms=profile.timeout_ms,
        headers=dict(profile.headers_json or {}),
        secret_slots=[header for header in (profile.secret_refs_json or {})],
        secret_refs=dict(profile.secret_refs_json or {}),
        allow_insecure_local=profile.allow_insecure_local,
        allow_private_network=profile.allow_private_network,
        enabled=profile.enabled,
        version=profile.version,
        created_at=profile.created_at.isoformat(),
        updated_at=profile.updated_at.isoformat(),
    )


def require_http_profiles_api() -> None:
    if not settings.agent_http_workflow_enabled:
        raise HTTPException(status_code=404, detail="Not found")


@router.get(
    "",
    response_model=list[HttpProfileOut],
    dependencies=[Depends(require_http_profiles_api)],
)
async def list_http_profiles(
    enabled_only: bool = False,
    db: AsyncSession = Depends(get_session),
) -> list[HttpProfileOut]:
    profiles = await HttpProfileService(db).repo.list(enabled_only=enabled_only)
    return [_to_out(profile) for profile in profiles]


@router.post(
    "",
    response_model=HttpProfileOut,
    status_code=201,
    dependencies=[Depends(require_http_profiles_api)],
)
async def create_http_profile(
    payload: HttpProfilePayload,
    db: AsyncSession = Depends(get_session),
) -> HttpProfileOut:
    try:
        profile = await HttpProfileService(db).create(payload.model_dump())
    except HttpProfileConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HttpProfileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_out(profile)


@router.get(
    "/{profile_id}",
    response_model=HttpProfileOut,
    dependencies=[Depends(require_http_profiles_api)],
)
async def get_http_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_session),
) -> HttpProfileOut:
    profile = await HttpProfileService(db).repo.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="endpoint profile not found")
    return _to_out(profile)


@router.put(
    "/{profile_id}",
    response_model=HttpProfileOut,
    dependencies=[Depends(require_http_profiles_api)],
)
async def update_http_profile(
    profile_id: int,
    payload: HttpProfilePayload,
    db: AsyncSession = Depends(get_session),
) -> HttpProfileOut:
    service = HttpProfileService(db)
    try:
        updated = await service.update(profile_id, payload.model_dump(exclude={"name"}))
    except HttpProfileNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HttpProfileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_out(updated)


class HttpProfileDeleteResponse(BaseModel):
    """删除结果；secret_refs 供桌面壳清理对应 OS keyring 条目。"""

    secret_refs: dict[str, str]


@router.delete(
    "/{profile_id}",
    response_model=HttpProfileDeleteResponse,
    dependencies=[Depends(require_http_profiles_api)],
)
async def delete_http_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_session),
) -> HttpProfileDeleteResponse:
    profile = await HttpProfileService(db).repo.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="endpoint profile not found")
    secret_refs = dict(profile.secret_refs_json or {})
    try:
        await HttpProfileService(db).repo.delete(profile_id)
    except HttpProfileNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return HttpProfileDeleteResponse(secret_refs=secret_refs)
