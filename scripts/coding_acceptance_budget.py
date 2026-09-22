"""单次与整场实验的顺序预算；未知用量不能被下一次尝试清零。"""
from __future__ import annotations

import math

DIMENSIONS = {"model_requests": "max_model_requests", "tool_calls": "max_tool_calls",
              "active_seconds": "max_active_seconds", "tokens": "max_attempt_tokens", "cost_usd": "cost_usd"}
TOTALS = {"model_requests": "max_total_model_requests", "tool_calls": "max_total_tool_calls",
          "active_seconds": "max_total_active_seconds", "tokens": "max_total_tokens", "cost_usd": "total_cost_usd"}


def finite(value):
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


class ExperimentBudget:
    def __init__(self, budget, count, *, model=None, enforce_model_usage=True):
        self.enforce_model_usage = enforce_model_usage
        self.limit = {key: budget.get(TOTALS[key], budget.get(field) * count if budget.get(field) is not None else None)
                      for key, field in DIMENSIONS.items()}
        if model:
            self.limit["tokens"] = min(self.limit["tokens"], model["max_total_tokens"])
            for key, field in TOTALS.items():
                cap = model.get("budget", {}).get(field)
                if cap is not None:
                    self.limit[key] = min(self.limit[key], cap) if self.limit[key] is not None else cap
        self.known = dict.fromkeys(DIMENSIONS, 0)
        self.unknown = dict.fromkeys(DIMENSIONS, False)
        self.settled = set()

    def remaining(self):
        return {key: None if self.unknown[key] or cap is None else max(0, cap - self.known[key]) for key, cap in self.limit.items()}

    def allocate(self, budget):
        result = dict(budget)
        for key, field in DIMENSIONS.items():
            # 回环暂停场景可有未知模拟用量；不能阻断后续协议校准，也不能改写为零。
            if key in {"tokens", "cost_usd"} and not self.enforce_model_usage:
                continue
            cap = self.limit[key]
            if cap is None:
                continue
            if self.unknown[key]:
                raise ValueError("total_" + key + "_unknown")
            remaining = cap - self.known[key]
            if remaining < (1 if key != "cost_usd" else 1e-12):
                raise ValueError("total_" + key + "_exhausted")
            result[field] = min(result[field], remaining) if result.get(field) is not None else remaining
            if key != "cost_usd":
                result[field] = math.floor(result[field])
        return result

    def settle(self, row):
        identity = row["attempt_id"]
        if identity in self.settled:
            raise ValueError("预算结算不得重复")
        self.settled.add(identity)
        if not row.get("started"):
            return
        for key in DIMENSIONS:
            value = row.get(key)
            if finite(value):
                self.known[key] += value
            else:
                self.unknown[key] = True

    def snapshot(self):
        return {"version": "s6-budget-2", "limits": self.limit, "known_usage": self.known,
                "usage": {key: None if self.unknown[key] else value for key, value in self.known.items()},
                "remaining": self.remaining(),
                "token_enforcement": "response_settled_soft_limit" if self.enforce_model_usage else "fixture_simulation_not_enforced",
                "cost_enforcement": "reported_usage_only_not_billing_hard_cap" if self.enforce_model_usage else "fixture_simulation_not_enforced"}
