"""窗口占用使用最近请求，缓存命中率使用同一会话与模型的有效累计用量。"""
from __future__ import annotations

from collections.abc import Iterable


def token_count(value) -> int | None:
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else None


def matches_profile(profile: dict, run: dict) -> bool:
    return (not run.get("model_profile_id") or run["model_profile_id"] == profile.get("id")) and (
        not profile.get("model_name") or run.get("model") == profile["model_name"])


def average_cache_hit_percent(profile: dict | None, runs: Iterable[dict]) -> float | None:
    used_total = cached_total = 0
    for run in runs:
        if not profile or not matches_profile(profile, run):
            continue
        # 旧记录没有有效累计字段时，仅计入仍可核实的最后一次请求。
        usage = run.get("cache_usage", run.get("context_usage")) or {}
        used, cached = (usage.get(key) for key in ("input_tokens", "cached_tokens"))
        if type(used) is int and used > 0 and type(cached) is int and 0 <= cached <= used:
            used_total += used
            cached_total += cached
    return round(cached_total * 100 / used_total, 1) if used_total else None


def context_budget(profile: dict | None, run: dict | None, *, cache_hit_percent: float | None = None) -> dict:
    capacity = token_count((profile or {}).get("context_tokens")) or 0
    usage = (run or {}).get("context_usage") or {}
    used = token_count(usage.get("input_tokens"))
    result = {"used_tokens": used or 0, "max_context_tokens": capacity, "reserved_output_tokens": 0,
              "cache_hit_percent": cache_hit_percent,
              "cache_hit_scope": "session", "source": "unavailable", "usage_percent": None, "compaction_state": "idle",
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
