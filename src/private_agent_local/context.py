"""上下文计量只使用配置容量与供应商返回的最近一次请求用量。"""
from __future__ import annotations


def token_count(value) -> int | None:
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else None


def context_budget(profile: dict | None, run: dict | None) -> dict:
    capacity = token_count((profile or {}).get("context_tokens")) or 0
    usage = (run or {}).get("context_usage") or {}
    used = token_count(usage.get("input_tokens"))
    cached = token_count(usage.get("cached_tokens"))
    result = {"used_tokens": used or 0, "max_context_tokens": capacity, "reserved_output_tokens": 0,
              "cache_hit_percent": round(cached / used * 100, 1) if used and cached is not None and cached <= used else None,
              "cache_hit_scope": "latest_request", "source": "unavailable", "usage_percent": None, "compaction_state": "idle",
              "last_compacted_at": None, "error_code": None, "error_reason": None}
    if not capacity:
        result.update(error_code="context_capacity_unknown", error_reason="所选模型未配置上下文容量，请在模型配置中填写服务实际支持的容量")
    elif used is None:
        result.update(error_code="context_usage_unavailable", error_reason="容量已配置；尚无该模型的供应商用量，完成一次请求后更新")
    else:
        result.update(source="provider_usage", usage_percent=min(100, round(used / capacity * 100)))
        if used >= capacity:
            result.update(error_code="budget_exceeded", error_reason="最近一次请求已达到配置容量，请新建会话或缩小上下文")
    return result
