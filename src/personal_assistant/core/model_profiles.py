"""模型 profile 服务（v0.7.0 E0 §5）。

能力全部是 profile 显式声明的事实（``native_tool_calls`` 等），**不通过
模型名称猜测**；不支持原生工具调用的模型只能用于只读问答，不进入 Coding
执行循环（run 创建时校验，``model_profile_unsupported`` 422）。

Provider secret 保持在原生凭据边界：本模块不接收、不持久化任何 secret /
token / API key；``permission_snapshot_json`` 只存非秘密策略摘要。
"""
from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.models import ModelProfile


class ModelProfileError(ValueError):
    """模型 profile 字段非法。"""


class ModelProfileNotFound(LookupError):
    """模型 profile 不存在。"""


class ModelProfileUnsupported(LookupError):
    """模型 profile 不支持 Coding 执行循环（禁用或缺少原生工具调用）。"""


# 必填字段（upsert 时校验；字段集与 model_profiles 表一一对应）
_REQUIRED_FIELDS = frozenset({"provider", "display_name"})
_BOOL_FIELDS = frozenset(
    {
        "is_local",
        "native_tool_calls",
        "supports_streaming",
        "supports_structured_output",
        "supports_vision",
        "usage_reporting",
        "enabled",
    }
)


def _validate_fields(fields: Mapping[str, Any]) -> None:
    """字段校验（非法抛 ModelProfileError，路由层映射 422）。"""
    for name in _REQUIRED_FIELDS:
        value = fields.get(name)
        if value is None:
            raise ModelProfileError(f"model profile 缺少必填字段: {name}")
        if not isinstance(value, str) or not value.strip():
            raise ModelProfileError(f"{name} 必须是非空字符串")
        limit = 100 if name == "provider" else 200
        if len(value) > limit:
            raise ModelProfileError(f"{name} 过长（上限 {limit} 字符）")
    for name in _BOOL_FIELDS:
        if name in fields and not isinstance(fields[name], bool):
            raise ModelProfileError(f"{name} 必须是布尔值")
    if "context_tokens" in fields:
        value = fields["context_tokens"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ModelProfileError("context_tokens 必须是 ≥1 的整数")
    if "reasoning_efforts" in fields and fields["reasoning_efforts"] is not None:
        value = fields["reasoning_efforts"]
        if not isinstance(value, list) or not all(
            isinstance(x, str) and x.strip() for x in value
        ):
            raise ModelProfileError("reasoning_efforts 必须是字符串数组")
        if len(value) > 16:
            raise ModelProfileError("reasoning_efforts 项数超限（上限 16）")


class ModelProfileService:
    """模型 profile 能力 API（``PA_CODING_PERMISSION_MODELS_ENABLED`` 门控由路由层负责）。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, profile_id: str) -> ModelProfile | None:
        return await self.db.get(ModelProfile, profile_id)

    async def list(self, *, enabled_only: bool = False) -> list[ModelProfile]:
        stmt = select(ModelProfile).order_by(ModelProfile.provider, ModelProfile.id)
        if enabled_only:
            stmt = stmt.where(ModelProfile.enabled.is_(True))
        return list((await self.db.execute(stmt)).scalars())

    async def upsert(self, profile_id: str, fields: Mapping[str, Any]) -> ModelProfile:
        """创建或整体更新 profile（最小设置入口，幂等）。"""
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise ModelProfileError("profile id 必须是非空字符串")
        if len(profile_id) > 128:
            raise ModelProfileError("profile id 过长（上限 128 字符）")
        _validate_fields(fields)
        existing = await self.db.get(ModelProfile, profile_id)
        if existing is None:
            profile = ModelProfile(
                id=profile_id,
                provider=fields["provider"].strip(),
                display_name=fields["display_name"].strip(),
                is_local=bool(fields.get("is_local", False)),
                native_tool_calls=bool(fields.get("native_tool_calls", True)),
                supports_streaming=bool(fields.get("supports_streaming", False)),
                supports_structured_output=bool(
                    fields.get("supports_structured_output", False)
                ),
                supports_vision=bool(fields.get("supports_vision", False)),
                context_tokens=int(fields.get("context_tokens", 8192)),
                reasoning_efforts_json=fields.get("reasoning_efforts"),
                usage_reporting=bool(fields.get("usage_reporting", False)),
                enabled=bool(fields.get("enabled", True)),
            )
            self.db.add(profile)
            await self.db.commit()
            await self.db.refresh(profile)
            return profile
        for name in ("provider", "display_name"):
            setattr(existing, name, fields[name].strip())
        for name in _BOOL_FIELDS:
            if name in fields:
                setattr(existing, name, bool(fields[name]))
        if "context_tokens" in fields:
            existing.context_tokens = int(fields["context_tokens"])
        if "reasoning_efforts" in fields:
            existing.reasoning_efforts_json = fields["reasoning_efforts"]
        await self.db.commit()
        await self.db.refresh(existing)
        return existing

    async def delete(self, profile_id: str) -> None:
        existing = await self.db.get(ModelProfile, profile_id)
        if existing is None:
            raise ModelProfileNotFound(f"模型 profile 不存在: {profile_id}")
        await self.db.delete(existing)
        await self.db.commit()

    async def validate_for_coding(self, profile_id: str) -> ModelProfile:
        """run 创建时校验（E0 §5）：不存在 → 404；禁用/无原生工具调用 → 422。

        不支持原生工具调用的模型只能用于只读问答，不进入 Coding 执行循环。
        """
        profile = await self.get(profile_id)
        if profile is None:
            raise ModelProfileNotFound(f"模型 profile 不存在: {profile_id}")
        if not profile.enabled or not profile.native_tool_calls:
            raise ModelProfileUnsupported(
                f"模型 profile {profile_id} 不支持 Coding 执行循环"
                "（需 enabled 且 native_tool_calls=true）"
            )
        return profile
