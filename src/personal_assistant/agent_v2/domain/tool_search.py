"""Deferred Tool Search 领域契约（专项计划 §9.3 / CT-7）。

红线：
- 只索引**本轮已获授权且 deferred** 的工具集——policy-denied /
  model-unsupported / hidden 工具永远不可检索、不可激活（§9.3 末条）；
- 激活结果只改变可见性，不扩大任何 capability/approval 权限（ADR-008）；
- 同一 Turn 的激活数量与搜索次数有上限。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ToolSearchErrorCode(StrEnum):
    """公开错误码（专项计划 §7.7 冻结子集 + CT-7 新增）。"""

    TOOL_SEARCH_NO_MATCH = "tool_search_no_match"
    ACTIVATION_UNAUTHORIZED = "activation_unauthorized"
    ACTIVATION_LIMIT_REACHED = "activation_limit_reached"
    SEARCH_LIMIT_REACHED = "search_limit_reached"
    ACTIVATION_DUPLICATE = "activation_duplicate"
    #: §7.2：Turn 运行中工具面变化（MCP 断开/健康变化）→ 显式失效。
    TOOL_PLAN_INVALIDATED = "tool_plan_invalidated"


# 上限默认值（§9.3：同一 Turn 激活数量和搜索次数有上限；确切阈值由
# eval 决定——P0 取保守值，可通过构造参数覆盖）。
DEFAULT_MAX_ACTIVATIONS_PER_TURN = 4
DEFAULT_MAX_SEARCHES_PER_TURN = 8
DEFAULT_MAX_QUERY_CHARS = 512
DEFAULT_MAX_RESULTS = 8


class SearchHit(BaseModel):
    """一条检索结果（精简摘要，不含 schema 全文/secret）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: str
    canonical_name: str
    version: str
    score: float = Field(ge=0.0)
    effects: tuple[str, ...] = ()
    risk_level: str = ""


class ExposureChangedRecord(BaseModel):
    """`tool_exposure_changed` 事件语义（经 Item/Event payload 投影，
    不新增协议公共类型——专项计划 §13.2）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    activated: tuple[str, ...]
    visible_hash_before: str
    visible_hash_after: str
    searches_used: int
    activations_used: int
