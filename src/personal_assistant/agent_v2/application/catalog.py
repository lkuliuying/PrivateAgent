"""Tool Catalog 构建：唯一性、别名冲突与规范化 hash（专项计划 §9.1 / CT2-02）。

Catalog 合并顺序（内建 → 项目 → MCP → extension → provider-native）由调用方
按序传入 specs；本模块负责合并后的不变式：

1. 同一 ``namespace + canonical_name + version`` 必须唯一；
2. Provider 可见名规范化（casefold）后跨工具不得冲突，冲突在模型调用前拒绝
   （``tool_name_collision``）；
3. ``catalog_hash`` 是全集的规范化 SHA-256——同一全集任何顺序得到同一 hash。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..domain.tool_catalog import ToolSpecV2


class ToolCatalogError(ValueError):
    """Catalog 不变式被破坏；``code`` 是公开错误码。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _normalize_visible_name(name: str) -> str:
    return name.strip().casefold()


class ToolCatalog(BaseModel):
    """不可变工具全集。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    specs: tuple[ToolSpecV2, ...]

    @classmethod
    def build(cls, specs: list[ToolSpecV2] | tuple[ToolSpecV2, ...]) -> "ToolCatalog":
        keys: dict[tuple[str, str, str], str] = {}
        visible_owner: dict[str, tuple[str, str]] = {}
        for spec in specs:
            key = spec.catalog_key
            if key in keys:
                raise ToolCatalogError(
                    "tool_name_collision",
                    "工具重复注册："
                    f"namespace={key[0]} canonical_name={key[1]} version={key[2]}",
                )
            keys[key] = spec.canonical_name

            # 可见名冲突空间：canonical_name + 全部 provider 别名。
            candidates = [spec.canonical_name, *spec.model_aliases.values()]
            for name in candidates:
                normalized = _normalize_visible_name(name)
                owner = (spec.namespace, spec.canonical_name)
                existing = visible_owner.get(normalized)
                if existing is not None and existing != owner:
                    raise ToolCatalogError(
                        "tool_name_collision",
                        "Provider 可见名冲突（模型调用前拒绝）："
                        f"{normalized!r} 已归属 {existing[0]}/{existing[1]}",
                    )
                visible_owner[normalized] = owner
        ordered = tuple(sorted(specs, key=lambda item: item.catalog_key))
        return cls(specs=ordered)

    def find(
        self, *, namespace: str, canonical_name: str, version: str
    ) -> ToolSpecV2 | None:
        for spec in self.specs:
            if spec.catalog_key == (namespace, canonical_name, version):
                return spec
        return None

    def catalog_hash(self) -> str:
        """全集规范化哈希（§7.2 catalog_hash）。

        逐工具取元数据摘要（不含 secret/provenance 噪声字段），排序后整体
        SHA-256——与注册顺序无关。
        """
        digests = [_spec_digest(spec) for spec in self.specs]
        payload = json.dumps(
            {"tools": digests},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    )


# 内部历史别名。
_canonical_json = canonical_json


def _spec_digest(spec: ToolSpecV2) -> dict[str, Any]:
    return {
        "namespace": spec.namespace,
        "canonical_name": spec.canonical_name,
        "version": spec.version,
        "description_sha256": hashlib.sha256(
            spec.description.encode("utf-8")
        ).hexdigest(),
        "input_schema_sha256": hashlib.sha256(
            _canonical_json(dict(spec.input_schema)).encode("utf-8")
        ).hexdigest(),
        "output_schema_sha256": hashlib.sha256(
            _canonical_json(dict(spec.output_schema)).encode("utf-8")
        ).hexdigest(),
        "model_aliases": {
            provider: alias for provider, alias in sorted(spec.model_aliases.items())
        },
        "exposure": spec.exposure.value,
        "maturity": spec.maturity.value,
        "risk_level": spec.risk_level.value,
        "side_effect_class": spec.side_effect_class.value,
        "effects": sorted(effect.value for effect in spec.effects),
        "approval_mode": spec.approval_mode.value,
        "sandbox_profile": spec.sandbox_profile,
        "network_policy": spec.network_policy.value,
        "idempotency": spec.idempotency.value,
        "parallel_safe": spec.parallel_safe,
        "streaming_output": spec.streaming_output,
        "supports_cancellation": spec.supports_cancellation,
        "executor_kind": spec.executor_kind.value,
        "required_capabilities": sorted(spec.required_capabilities),
        "feature_flag": spec.feature_flag,
        "intent_tags": sorted(spec.intent_tags),
        "health_check_id": spec.health_check_id,
        "model_requirements": spec.model_requirements.model_dump(),
        "verifier_ids": list(spec.verifier_ids),
        "completion_evidence": sorted(
            effect.value for effect in spec.completion_evidence
        ),
    }
