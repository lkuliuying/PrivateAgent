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


# 分项计量只保留分类、字节与估算，不复制提示词、工具正文或供应商不透明状态。
BREAKDOWN_LABELS = {
    "system_prompt": "系统提示",
    "project_rules": "项目规则",
    "task_state": "任务状态",
    "user_messages": "用户消息",
    "assistant_messages": "助手消息",
    "tool_results": "工具结果",
    "history_summary": "历史摘要",
    "tool_definitions": "工具定义",
    "long_term_memory": "长期记忆",
    "images": "图片",
    "provider_state": "不透明供应商状态",
    "protocol": "协议与结构",
}
# 固定顺序；预算响应和界面按同一顺序展示，便于对照同一请求。
BREAKDOWN_ORDER = ("system_prompt", "project_rules", "task_state", "tool_definitions", "user_messages",
                   "assistant_messages", "tool_results", "history_summary", "long_term_memory",
                   "images", "provider_state", "protocol")


def configuration_version(profile: dict) -> str:
    data = {key: profile.get(key) for key in ("id", "provider", "model_name", "context_tokens")}
    data.update({key: profile[key] for key in ("api_format", "endpoint") if key in profile})
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def request_budget(request: ModelRequest, capacity: int | None, reserve: int, *, calibration: float = 1.0,
                   previous_usage: tuple[int, int] | None = None, auto_compact_token_limit: int | None = None) -> dict:
    known = type(capacity) is int and 0 < capacity <= 1_000_000_000
    # UTF-8 字节数提供跨语言保守估计；协议展开和 tokenizer 差异另留 25% 与固定余量。
    size = len(request.model_dump_json().encode("utf-8"))
    images = [image for message in request.messages for image in message.images]
    text_size = size - sum(len(image.data) for image in images)
    # 图片采用独立保守预算，不能把 Base64 长度当作文本 token；实际用量仍以服务回执为准。
    estimated = math.ceil((text_size * 1.25 + 8192 * len(images)) * max(1.0, calibration))
    source = "utf8_conservative"
    if previous_usage and not images and size >= previous_usage[0]:
        # 已发送前缀采用供应商实测值，新增内容仍保守估算，避免把字节数当作真实 token。
        estimated = previous_usage[1] + math.ceil((size - previous_usage[0]) * max(1.0, calibration) * 1.25)
        source = "provider_usage_with_growth"
    effective_capacity = capacity if known else 8192
    # 大窗口请求不能被旧的小窗口字节限制提前截断，同时保留总内存与协议保护。
    max_request_bytes = min(64 * 1024 * 1024, max(1_500_000, effective_capacity * 8))
    if images:
        max_request_bytes = 32 * 1024 * 1024
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


def request_breakdown(request: ModelRequest, labels, *, calibration: float = 1.0,
                      provider_usage_tokens: int | None = None) -> dict:
    """按组装位置分摊同一次请求的估算，不改变预算决策，也不保存任何正文。

    labels 与 request.messages 一一对应；图片与不透明供应商状态单独计量。
    各项字节之和等于请求字节，剩余结构开销归入“协议与结构”，因此分项可以解释总量。
    """
    if len(labels) != len(request.messages):
        raise ValueError("分项标签数量与请求消息不一致")
    ratio = max(1.0, calibration)
    totals: dict[str, dict] = {}

    def add(category: str, *, text_bytes: int = 0, display_bytes: int | None = None,
            image_count: int = 0, messages: int = 0):
        # bytes 用于展示（各项之和等于请求字节）；text_bytes 只用于文本 token 估算。
        entry = totals.setdefault(category, {"bytes": 0, "text_bytes": 0, "images": 0, "messages": 0})
        entry["bytes"] += max(0, text_bytes if display_bytes is None else display_bytes)
        entry["text_bytes"] += max(0, text_bytes)
        entry["images"] += image_count
        entry["messages"] += messages

    for message, category in zip(request.messages, labels, strict=True):
        payload = message.model_dump(mode="json")
        size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        image_bytes = sum(len(image.data) for image in message.images)
        state_bytes = 0
        if message.provider_state is not None:
            state_bytes = len(json.dumps(message.provider_state.model_dump(mode="json"), ensure_ascii=False,
                                         separators=(",", ":")).encode("utf-8"))
        add(category, text_bytes=size - image_bytes - state_bytes, messages=1)
        if image_bytes:
            # 图片单独计量：Base64 长度不计入文本估算，按每张 8192 tokens 保守预留。
            add("images", text_bytes=0, display_bytes=image_bytes, image_count=len(message.images))
        if state_bytes:
            add("provider_state", text_bytes=state_bytes)
    tools = [tool.model_dump(mode="json") for tool in request.tools]
    if tools:
        add("tool_definitions", text_bytes=len(json.dumps(tools, ensure_ascii=False, separators=(",", ":")).encode("utf-8")))
    total_bytes = len(request.model_dump_json().encode("utf-8"))
    accounted = sum(entry["bytes"] for entry in totals.values())
    add("protocol", text_bytes=max(0, total_bytes - accounted))

    images_total = totals.get("images", {}).get("images", 0)
    text_total = total_bytes - totals.get("images", {}).get("bytes", 0)
    # 与 request_budget 相同的保守口径，便于和总量估算直接核对。
    estimate = math.ceil((text_total * 1.25 + 8192 * images_total) * ratio)
    items, running = [], 0
    for category in BREAKDOWN_ORDER:
        entry = totals.get(category)
        if not entry:
            continue
        # 逐项取整会与总量有差异，差额并入最大项，避免伪造或丢失预算。
        tokens = round((entry["text_bytes"] * 1.25 + 8192 * entry["images"]) * ratio)
        running += tokens
        items.append({"category": category, "label": BREAKDOWN_LABELS[category],
                      "bytes": entry["bytes"], "estimated_tokens": tokens,
                      "measurement": "utf8_share_estimate", "messages": entry["messages"]})
    if items:
        # 取整差额记到最大项，保证分项之和等于总量且不产生负数。
        target = max(items, key=lambda item: item["estimated_tokens"])
        target["estimated_tokens"] += estimate - running
    return {"schema": "context-breakdown/1", "basis": "utf8_share_estimate",
            "measurement_source": "utf8_conservative", "estimate_ratio": ratio,
            "total_bytes": total_bytes, "estimate_tokens": estimate,
            "provider_usage_tokens": provider_usage_tokens,
            "items": items,
            "notice": "分项按同一请求的 UTF-8 字节分摊估算；供应商只返回总输入用量时以该实测总值为准。"}
