"""v0.5.0 B4：只读 SQL connection profile 管理 API。

只管理非敏感连接元数据与 keyring 密码引用；明文密码通过
``PA_SQL_PROFILES_SECRETS_JSON`` 通道由桌面壳注入 sidecar 内存。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.db import get_session
from ..core.sql_profiles import (
    SqlProfileConflict,
    SqlProfileError,
    SqlProfileNotFound,
    SqlProfileService,
)

router = APIRouter(prefix="/sql-profiles", tags=["sql-profiles"])


class SqlProfilePayload(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    dialect: str = "mysql"
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    database: str = Field(min_length=1, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    connect_args: dict[str, Any] | None = None
    max_rows: int = Field(default=1000, ge=1, le=100_000)
    max_bytes: int = Field(default=1_048_576, ge=1_024, le=8 * 1_048_576)
    timeout_ms: int = Field(default=30_000, ge=1_000, le=60_000)
    enabled: bool = False

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name 不能为空")
        return value


class SqlProfileOut(BaseModel):
    id: int
    name: str
    dialect: str
    host: str
    port: int
    database: str
    username: str | None
    # keyring 引用（明文密码只经 OS keyring，Rust CredUI prompt）
    password_secret_ref: str
    max_rows: int
    max_bytes: int
    timeout_ms: int
    enabled: bool
    version: int
    created_at: str
    updated_at: str


def _to_out(profile) -> SqlProfileOut:
    return SqlProfileOut(
        id=profile.id,
        name=profile.name,
        dialect=profile.dialect,
        host=profile.host,
        port=profile.port,
        database=profile.database,
        username=profile.username,
        password_secret_ref=profile.password_secret_ref,
        max_rows=profile.max_rows,
        max_bytes=profile.max_bytes,
        timeout_ms=profile.timeout_ms,
        enabled=profile.enabled,
        version=profile.version,
        created_at=profile.created_at.isoformat(),
        updated_at=profile.updated_at.isoformat(),
    )


def require_sql_profiles_api() -> None:
    if not settings.agent_sql_readonly_workflow_enabled:
        raise HTTPException(status_code=404, detail="Not found")


def _password_ref(name: str) -> str:
    """后端为 profile 生成 keyring 密码引用（与 Rust 侧 sql_profile_reference 同构）。"""
    return f"secret://os-keyring/sql/{name}/password"


@router.get(
    "",
    response_model=list[SqlProfileOut],
    dependencies=[Depends(require_sql_profiles_api)],
)
async def list_sql_profiles(
    enabled_only: bool = False,
    db: AsyncSession = Depends(get_session),
) -> list[SqlProfileOut]:
    profiles = await SqlProfileService(db).repo.list(enabled_only=enabled_only)
    return [_to_out(profile) for profile in profiles]


@router.post(
    "",
    response_model=SqlProfileOut,
    status_code=201,
    dependencies=[Depends(require_sql_profiles_api)],
)
async def create_sql_profile(
    payload: SqlProfilePayload,
    db: AsyncSession = Depends(get_session),
) -> SqlProfileOut:
    try:
        profile = await SqlProfileService(db).create(
            {**payload.model_dump(), "password_secret_ref": _password_ref(payload.name)}
        )
    except SqlProfileConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SqlProfileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_out(profile)


@router.get(
    "/{profile_id}",
    response_model=SqlProfileOut,
    dependencies=[Depends(require_sql_profiles_api)],
)
async def get_sql_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_session),
) -> SqlProfileOut:
    profile = await SqlProfileService(db).repo.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="SQL profile not found")
    return _to_out(profile)


@router.put(
    "/{profile_id}",
    response_model=SqlProfileOut,
    dependencies=[Depends(require_sql_profiles_api)],
)
async def update_sql_profile(
    profile_id: int,
    payload: SqlProfilePayload,
    db: AsyncSession = Depends(get_session),
) -> SqlProfileOut:
    service = SqlProfileService(db)
    profile = await service.repo.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="SQL profile not found")
    try:
        values = payload.model_dump(exclude={"name"})
        updated = await service.repo.update(profile_id, **values)
    except SqlProfileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_out(updated)


class SqlProfileDeleteResponse(BaseModel):
    """删除结果；password_secret_ref 供桌面壳清理对应 OS keyring 条目。"""

    password_secret_ref: str | None


@router.delete(
    "/{profile_id}",
    response_model=SqlProfileDeleteResponse,
    dependencies=[Depends(require_sql_profiles_api)],
)
async def delete_sql_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_session),
) -> SqlProfileDeleteResponse:
    profile = await SqlProfileService(db).repo.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="SQL profile not found")
    reference = profile.password_secret_ref
    try:
        await SqlProfileService(db).repo.delete(profile_id)
    except SqlProfileNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SqlProfileDeleteResponse(password_secret_ref=reference)
