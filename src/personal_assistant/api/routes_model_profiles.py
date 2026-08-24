"""模型 profile 能力 API（v0.7.0 E0 §5；v0.9.0 H1-D 配置闭环）。

- GET    /agent-model-profiles                  模型 profile 列表
- GET    /agent-model-profiles/import-status    旧配置导入状态（一次性向导依据）
- POST   /agent-model-profiles/import           幂等导入全局配置为默认 profile
- GET    /agent-model-profiles/{id}             模型 profile 详情
- PUT    /agent-model-profiles/{id}             创建/更新模型 profile（upsert）
- DELETE /agent-model-profiles/{id}             删除模型 profile
- POST   /agent-model-profiles/{id}/probe       受限探测（可达性/模型存在性）
- POST   /agent-model-profiles/{id}/set-default 设为默认 Coding profile

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
    # v0.9.0 H1-D：具体模型路由字段（可选：历史 profile 允许缺失，运行期失败关闭）
    model_name: str | None = Field(default=None, max_length=200)
    is_local: bool = False
    native_tool_calls: bool = True
    supports_streaming: bool = False
    supports_structured_output: bool = False
    supports_vision: bool = False
    context_tokens: int = Field(default=8192, ge=1)
    reasoning_efforts: list[str] | None = Field(default=None, max_length=16)
    usage_reporting: bool = False
    enabled: bool = True
    # 声明为默认 Coding profile（服务层排他维护唯一性）
    is_default: bool = False


class ModelProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    display_name: str
    model_name: str | None = None
    is_default: bool = False
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


@router.get("/import-status", response_model=None)
async def model_profile_import_status(
    db: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """v0.9.0 H1-D（§5.8）：旧配置导入状态（一次性向导依据，低基数）。"""
    blocked = _require_flag()
    if blocked is not None:
        return blocked
    from ..core.model_profile_import import IMPORT_STATE_KEY, evaluate_import_state
    from ..core.settings import SettingsService

    evaluation = await evaluate_import_state(db)
    stored_state = await SettingsService(db).get(IMPORT_STATE_KEY)
    # 已有显式终态（导入/关闭）时不因重复评估回退到 pending/wizard
    if stored_state in {"auto_imported", "imported", "dismissed", "not_needed"}:
        evaluation["import_state"] = stored_state
    return JSONResponse(status_code=200, content=evaluation)


@router.post("/import", response_model=None)
async def import_model_profile(
    db: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """v0.9.0 H1-D（§5.8）：把全局 Provider 配置幂等导入为默认 profile。

    用户显式发起（可含远程确认）；失败关闭并返回精确状态码：
    no_global_provider/feature_disabled/credentials_missing/
    provider_unreachable/model_missing/probe_failed。
    """
    blocked = _require_flag()
    if blocked is not None:
        return blocked
    from ..core.model_profile_import import (
        ModelProfileImportError,
        import_legacy_provider_profile,
    )

    try:
        result = await import_legacy_provider_profile(db, interactive=True)
    except ModelProfileImportError as exc:
        return _error(409, exc.error_code, exc.detail)
    return JSONResponse(status_code=200, content=result)


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


@router.post("/{profile_id}/probe", response_model=None)
async def probe_model_profile_route(
    profile_id: str,
    db: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """v0.9.0 H1-D（§5.8）：受限探测（可达性/模型存在性；不推断工具能力）。"""
    blocked = _require_flag()
    if blocked is not None:
        return blocked
    from ..core.model_profile_probe import probe_with_timeout

    result = await probe_with_timeout(db, profile_id)
    return JSONResponse(status_code=200, content=result.to_payload())


@router.post("/{profile_id}/set-default", response_model=None)
async def set_default_model_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_session),
) -> ModelProfileOut | JSONResponse:
    """v0.9.0 H1-D：设为默认 Coding profile（排他）。"""
    blocked = _require_flag()
    if blocked is not None:
        return blocked
    try:
        profile = await ModelProfileService(db).set_default(profile_id)
    except ModelProfileNotFound as exc:
        return _error(404, "model_profile_not_found", str(exc))
    return _profile_out(profile)
