"""不依赖存储或供应商的上下文预算、指令元数据与循环预算。"""
from __future__ import annotations

import hashlib
import json
import math

from pydantic import BaseModel, ConfigDict, Field

from .contracts import ModelRequest


class InstructionSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str
    scope: str
    sha256: str
    trusted: bool
    priority: int = Field(ge=0)
    content: str


class ContextLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_model_requests: int = Field(default=64, ge=1, le=256)
    max_tool_calls: int = Field(default=128, ge=0, le=512)
    max_active_seconds: int = Field(default=3600, ge=1, le=14400)
    max_cost_usd: float | None = Field(default=None, gt=0, le=1000, allow_inf_nan=False)
    max_total_tokens: int | None = Field(default=None, ge=1, le=10800000)
    reserved_output_tokens: int = Field(default=2048, ge=128, le=32768)
    auto_compact: bool = True
    auto_compact_token_limit: int | None = Field(default=None, ge=128, le=1_000_000_000)
    semantic_compaction: bool = True


def configuration_version(profile: dict) -> str:
    data = {key: profile.get(key) for key in ("id", "provider", "model_name", "context_tokens")}
    data.update({key: profile[key] for key in ("api_format", "endpoint") if key in profile})
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def request_budget(request: ModelRequest, capacity: int | None, reserve: int, *, calibration: float = 1.0,
                   previous_usage: tuple[int, int] | None = None, auto_compact_token_limit: int | None = None) -> dict:
    known = type(capacity) is int and 0 < capacity <= 1_000_000_000
    # UTF-8 字节数提供跨语言保守估计；协议展开和 tokenizer 差异另留 25% 与固定余量。
    size = len(request.model_dump_json().encode("utf-8"))
    estimated = math.ceil(size * max(1.0, calibration) * 1.25)
    source = "utf8_conservative"
    if previous_usage and size >= previous_usage[0]:
        # 已发送前缀采用供应商实测值，新增内容仍保守估算，避免把字节数当作真实 token。
        estimated = previous_usage[1] + math.ceil((size - previous_usage[0]) * max(1.0, calibration) * 1.25)
        source = "provider_usage_with_growth"
    effective_capacity = capacity if known else 8192
    # 大窗口请求不能被旧的小窗口字节限制提前截断，同时保留总内存与协议保护。
    max_request_bytes = min(64 * 1024 * 1024, max(1_500_000, effective_capacity * 8))
    margin = max(512, math.ceil(effective_capacity * 0.05))
    available = max(0, effective_capacity - reserve - margin)
    # 小窗口及大输出预留下，压缩必须先于硬上限；显式阈值也不能越过此边界。
    threshold = max(0, min(auto_compact_token_limit or math.ceil(effective_capacity * 0.8),
                           available - max(256, math.ceil(available * 0.1))))
    exceeded = estimated > available or size > max_request_bytes or len(request.messages) > 20000
    return {"estimated_input_tokens": estimated, "input_budget_tokens": available,
            "reserved_output_tokens": reserve, "safety_margin_tokens": margin,
            "max_context_tokens": capacity if known else 0, "measurement_source": source,
            "capacity_source": "configured" if known else "restricted_unknown",
            "estimate_ratio": max(1.0, calibration), "request_bytes": size,
            "max_request_bytes": max_request_bytes,
            "auto_compact_threshold_tokens": threshold,
            "should_compact": estimated >= threshold or exceeded,
            "exceeded": exceeded}
