"""模型发现元数据归一化。

OpenAI 兼容的 ``/models`` 只统一了模型 ID，并未统一上下文窗口字段。本模块
把供应商明确返回的字段、Ollama 本地模型详情和少量官方模型目录归一到同一
契约；无法确认时返回 ``None``，绝不伪造一个通用默认窗口。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

MAX_TOKEN_LIMIT = 10_000_000
METADATA_SOURCES = frozenset(
    {"provider_api", "local_model", "official_catalog", "user_override", "unknown"}
)


@dataclass(frozen=True, slots=True)
class DiscoveredModelMetadata:
    model_id: str
    context_tokens: int | None = None
    max_output_tokens: int | None = None
    metadata_source: str = "unknown"

    def as_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "context_tokens": self.context_tokens,
            "max_output_tokens": self.max_output_tokens,
            "metadata_source": self.metadata_source,
        }


@dataclass(frozen=True, slots=True)
class _CatalogEntry:
    context_tokens: int
    max_output_tokens: int | None = None


# 只收录官方稳定事实；host 参与匹配，避免把第三方代理的实际限额误当成
# 官方端点限额。新模型可以独立更新此目录，不必改动发现协议。
_OFFICIAL_CATALOG: dict[str, dict[str, _CatalogEntry]] = {
    "api.deepseek.com": {
        "deepseek-v4-flash": _CatalogEntry(1_000_000, 384_000),
        "deepseek-v4-pro": _CatalogEntry(1_000_000, 384_000),
        # 官方兼容别名，均路由到 V4 Flash 的非思考/思考模式。
        "deepseek-chat": _CatalogEntry(1_000_000, 384_000),
        "deepseek-reasoner": _CatalogEntry(1_000_000, 384_000),
    },
    "api.openai.com": {
        "gpt-5.6": _CatalogEntry(1_050_000, 128_000),
        "gpt-5.6-sol": _CatalogEntry(1_050_000, 128_000),
        "gpt-5.6-terra": _CatalogEntry(1_050_000, 128_000),
        "gpt-5.6-luna": _CatalogEntry(1_050_000, 128_000),
    },
}


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float) and value.is_integer():
        parsed = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        return None
    return parsed if 1 <= parsed <= MAX_TOKEN_LIMIT else None


def _nested_value(item: Mapping[str, Any], path: Sequence[str]) -> object:
    current: object = item
    for part in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _first_int(item: Mapping[str, Any], paths: Sequence[Sequence[str]]) -> int | None:
    for path in paths:
        value = _positive_int(_nested_value(item, path))
        if value is not None:
            return value
    return None


def official_catalog_metadata(base_url: str, model_id: str) -> DiscoveredModelMetadata | None:
    host = (urlsplit(base_url).hostname or "").lower()
    entries = _OFFICIAL_CATALOG.get(host)
    if not entries:
        return None
    normalized_id = model_id.strip().lower()
    entry = entries.get(normalized_id)
    if entry is None and host == "api.openai.com":
        # 官方带日期快照沿用同系列上限；只对明确的 5.6 系列匹配。
        for prefix, candidate in entries.items():
            if normalized_id.startswith(f"{prefix}-20"):
                entry = candidate
                break
    if entry is None:
        return None
    return DiscoveredModelMetadata(
        model_id=model_id,
        context_tokens=entry.context_tokens,
        max_output_tokens=entry.max_output_tokens,
        metadata_source="official_catalog",
    )


_CONTEXT_PATHS: tuple[tuple[str, ...], ...] = (
    ("context_length",),
    ("context_window",),
    ("context_window_tokens",),
    ("max_context_length",),
    ("max_model_len",),
    ("max_sequence_length",),
    ("max_input_tokens",),
    ("inputTokenLimit",),
    ("input_token_limit",),
    ("top_provider", "context_length"),
)
_OUTPUT_PATHS: tuple[tuple[str, ...], ...] = (
    ("max_output_tokens",),
    ("max_completion_tokens",),
    ("outputTokenLimit",),
    ("output_token_limit",),
    ("top_provider", "max_completion_tokens"),
)


def _model_id(item: object) -> str:
    if isinstance(item, str):
        candidate = item
    elif isinstance(item, Mapping):
        candidate = item.get("id") or item.get("model") or item.get("name")
    else:
        return ""
    value = str(candidate or "").strip()
    return value if value and len(value) <= 200 else ""


def _raw_model_items(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload[:5_000]
    if not isinstance(payload, Mapping):
        return []
    items: object = payload.get("data")
    if isinstance(items, Mapping):
        items = items.get("items") or items.get("list")
    if not isinstance(items, list):
        items = payload.get("models")
    return items[:5_000] if isinstance(items, list) else []


def discover_model_metadata(
    payload: object, *, base_url: str, protocol: str
) -> list[DiscoveredModelMetadata]:
    """从常见模型列表响应中提取模型 ID 与可信上下文元数据。"""
    found: dict[str, DiscoveredModelMetadata] = {}
    for item in _raw_model_items(payload):
        model_id = _model_id(item)
        if not model_id:
            continue
        context_tokens: int | None = None
        max_output_tokens: int | None = None
        if isinstance(item, Mapping):
            context_tokens = _first_int(item, _CONTEXT_PATHS)
            max_output_tokens = _first_int(item, _OUTPUT_PATHS)
            # Anthropic Models API 在有 max_input_tokens 时用 max_tokens 表示
            # 最大输出；普通 OpenAI model object 的同名字段不作此推断。
            if (
                max_output_tokens is None
                and protocol == "claude"
                and context_tokens is not None
            ):
                max_output_tokens = _positive_int(item.get("max_tokens"))
        if context_tokens is not None:
            metadata = DiscoveredModelMetadata(
                model_id=model_id,
                context_tokens=context_tokens,
                max_output_tokens=max_output_tokens,
                metadata_source="provider_api",
            )
        else:
            metadata = official_catalog_metadata(base_url, model_id) or DiscoveredModelMetadata(
                model_id=model_id
            )
        found[model_id] = metadata
    return sorted(found.values(), key=lambda item: item.model_id.casefold())


def ollama_show_metadata(
    model_id: str, payload: object
) -> DiscoveredModelMetadata | None:
    """解析 ``/api/show`` 中架构相关的 ``*.context_length``。"""
    if not isinstance(payload, Mapping):
        return None
    model_info = payload.get("model_info")
    if not isinstance(model_info, Mapping):
        return None
    candidates = [
        value
        for key, raw in model_info.items()
        if str(key).endswith(".context_length")
        if (value := _positive_int(raw)) is not None
    ]
    if not candidates:
        return None
    return DiscoveredModelMetadata(
        model_id=model_id,
        context_tokens=max(candidates),
        metadata_source="local_model",
    )


def metadata_source(value: object) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate in METADATA_SOURCES else "unknown"


__all__ = [
    "DiscoveredModelMetadata",
    "MAX_TOKEN_LIMIT",
    "METADATA_SOURCES",
    "discover_model_metadata",
    "metadata_source",
    "official_catalog_metadata",
    "ollama_show_metadata",
]
