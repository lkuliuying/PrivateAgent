"""模型 profile 能力 API（v0.7.0 E0 §5；最小设置入口）。

- GET    /agent-model-profiles            模型 profile 列表
- GET    /agent-model-profiles/{id}       模型 profile 详情
- PUT    /agent-model-profiles/{id}       创建/更新模型 profile（upsert）
- DELETE /agent-model-profiles/{id}       删除模型 profile

``PA_CODING_PERMISSION_MODELS_ENABLED`` 关闭时全部返回 409
``coding_mode_disabled``（关闭 flag 只隐藏 API，不需要 schema downgrade）。

Provider secret 保持在原生凭据边界：请求与响应 schema 均不含任何
secret/token/API key 字段。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from ..core.db import get_session
from ..core.model_profiles import (
    ModelProfileError,
    ModelProfileNotFound,
    ModelProfileService,
)

router = APIRouter(prefix="/agent-model-profiles", tags=["agent-model-profiles"])


def _error(status: int, error_code: str, detail: str) -> JSONResponse:
    """平铺 error_code 错误响应（C0 契约 §9，与 coding 主链一致）。

    错误响应不得包含本地绝对路径。
    """
    return JSONResponse(
        status_code=status,
        content={"error_code": error_code, "detail": detail},
    )


def _require_flag() -> JSONResponse | None:
    if not cfg.coding_permission_models_enabled:
        return _error(409, "coding_mode_disabled", "Model profiles are disabled")
    return None


class ModelProfileUpsertRequest(BaseModel):
    """模型 profile 设置请求（无任何 secret 字段）。"""

    provider: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    is_local: bool = False
    native_tool_calls: bool = True
    supports_streaming: bool = False
    supports_structured_output: bool = False
    supports_vision: bool = False
    context_tokens: int = Field(default=8192, ge=1)
    reasoning_efforts: list[str] | None = Field(default=None, max_length=16)
    usage_reporting: bool = False
    enabled: bool = True


class ModelProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    display_name: str
    is_local: bool
    native_tool_calls: bool
    supports_streaming: bool
    supports_structured_output: bool
    supports_vision: bool
    context_tokens: int
    reasoning_efforts: list | None = None
    usage_reporting: bool
    enabled: bool
    created_at: object
    updated_at: object


def _profile_out(profile) -> ModelProfileOut:
    out = ModelProfileOut.model_validate(profile)
    out.reasoning_efforts = profile.reasoning_efforts_json
    return out


@router.get("", response_model=None)
async def list_model_profiles(
    enabled_only: bool = False,
    db: AsyncSession = Depends(get_session),
) -> list[ModelProfileOut] | JSONResponse:
    blocked = _require_flag()
    if blocked is not None:
        return blocked
    profiles = await ModelProfileService(db).list(enabled_only=enabled_only)
    return [_profile_out(p) for p in profiles]


@router.get("/{profile_id}", response_model=None)
async def get_model_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_session),
) -> ModelProfileOut | JSONResponse:
    blocked = _require_flag()
    if blocked is not None:
        return blocked
    profile = await ModelProfileService(db).get(profile_id)
    if profile is None:
        return _error(
            404,
            "model_profile_not_found",
            f"Model profile not found: {profile_id}",
        )
    return _profile_out(profile)


@router.put("/{profile_id}", response_model=None)
async def upsert_model_profile(
    profile_id: str,
    request: ModelProfileUpsertRequest,
    db: AsyncSession = Depends(get_session),
) -> ModelProfileOut | JSONResponse:
    blocked = _require_flag()
    if blocked is not None:
        return blocked
    try:
        profile = await ModelProfileService(db).upsert(
            profile_id, request.model_dump()
        )
    except ModelProfileError as exc:
        return _error(422, "model_profile_invalid", str(exc))
    return _profile_out(profile)


@router.delete("/{profile_id}", status_code=204, response_model=None)
async def delete_model_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_session),
) -> JSONResponse | None:
    blocked = _require_flag()
    if blocked is not None:
        return blocked
    try:
        await ModelProfileService(db).delete(profile_id)
    except ModelProfileNotFound as exc:
        return _error(404, "model_profile_not_found", str(exc))
    return None
