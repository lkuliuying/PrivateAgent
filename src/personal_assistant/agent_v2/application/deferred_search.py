"""本地 Deferred Tool Search（专项计划 §9.3 / CT-7）。

组成：
- :class:`DeferredToolIndex`：只索引**已授权 deferred** 工具集的 BM25
  索引（字段：名称、描述、参数标题、effect、namespace、tags）；构建时
  防御性过滤非 deferred 条目；
- :class:`TurnSearchSession`：单 Turn 的搜索/激活会话——搜索次数与激活
  数量双上限、越权拒绝、重复激活拒绝；每次激活产出
  :class:`ExposureChangedRecord` 并返回更新后的 ToolPlan（visible_hash
  重算，direct 集合并入被激活工具）；
- :func:`handle_search_tools`：``search_tools`` Function 入口（输入
  query/namespace/effect/risk_max/limit，输出可激活的精简 ToolSpec 摘要），
  供 v2 Runtime 以 JSON Function 形式暴露给模型；
- :func:`schema_bytes_baseline` / 计数辅助：§19.3 Schema token 对照口径。

纯应用层：不导入传输/存储/Provider SDK，不依赖 exec-host。
"""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict

from ..domain.bm25 import Bm25Index, FrozenBm25
from ..domain.effects import EffectClass
from ..domain.tool_catalog import ToolExposure, ToolSpecV2
from ..domain.tool_search import (
    DEFAULT_MAX_ACTIVATIONS_PER_TURN,
    DEFAULT_MAX_QUERY_CHARS,
    DEFAULT_MAX_RESULTS,
    DEFAULT_MAX_SEARCHES_PER_TURN,
    ExposureChangedRecord,
    SearchHit,
    ToolSearchErrorCode,
)
from .planner import PlannedTool, compute_visible_hash


class ToolSearchError(Exception):
    """结构化检索/激活错误；code 为公开错误码。"""

    def __init__(self, code: ToolSearchErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def _index_text(spec: ToolSpecV2) -> str:
    """索引字段（§9.3）：名称、描述、参数标题、effect、namespace、tags。"""
    param_titles = " ".join(
        str(key)
        for key in (spec.input_schema or {}).get("properties", {}).keys()
    )
    effects = " ".join(effect.value for effect in spec.effects)
    tags = " ".join(sorted(spec.intent_tags))
    return " ".join(
        [
            spec.canonical_name,
            spec.namespace,
            spec.description,
            param_titles,
            effects,
            tags,
        ]
    )


class DeferredToolIndex:
    """已授权 deferred 工具集的只读检索视图。"""

    def __init__(self, entries: Mapping[str, ToolSpecV2]) -> None:
        self._entries: dict[str, ToolSpecV2] = dict(entries)
        builder = Bm25Index()
        for name, spec in self._entries.items():
            builder.add(name, _index_text(spec))
        self._bm25: FrozenBm25 = builder.freeze()

    @classmethod
    def build(cls, specs: list[ToolSpecV2] | tuple[ToolSpecV2, ...]) -> "DeferredToolIndex":
        """防御性构建：仅接受 exposure==deferred 的条目；其余静默丢弃
        （调用方若误传 direct/hidden/policy-denied 工具，不会进入索引）。"""
        entries: dict[str, ToolSpecV2] = {}
        for spec in specs:
            if spec.exposure != ToolExposure.DEFERRED:
                continue
            entries[spec.canonical_name] = spec
        return cls(entries)

    @property
    def size(self) -> int:
        return len(self._entries)

    def contains(self, canonical_name: str) -> bool:
        return canonical_name in self._entries

    def get(self, canonical_name: str) -> ToolSpecV2 | None:
        return self._entries.get(canonical_name)

    def search(
        self,
        query: str,
        *,
        namespace: str | None = None,
        effect: str | None = None,
        risk_max: str | None = None,
        limit: int = DEFAULT_MAX_RESULTS,
    ) -> list[SearchHit]:
        """BM25 检索；过滤器先于排序应用；确定性顺序（分数降序 + 名称）。"""
        if not query.strip():
            raise ToolSearchError(
                ToolSearchErrorCode.TOOL_SEARCH_NO_MATCH, "query 不能为空"
            )
        if len(query) > DEFAULT_MAX_QUERY_CHARS:
            raise ToolSearchError(
                ToolSearchErrorCode.TOOL_SEARCH_NO_MATCH, "query 超长"
            )
        limit = max(1, min(int(limit), DEFAULT_MAX_RESULTS))
        risk_order = {"safe": 0, "confirm": 1, "restricted": 2}
        risk_cap = risk_order.get(risk_max or "restricted", 2)
        hits: list[SearchHit] = []
        for doc_id, score in self._bm25.score(query):
            spec = self._entries.get(doc_id)
            if spec is None:
                continue
            if namespace is not None and spec.namespace != namespace:
                continue
            if (
                effect is not None
                and effect not in {e.value for e in spec.effects}
            ):
                continue
            if risk_order.get(spec.risk_level.value, 2) > risk_cap:
                continue
            hits.append(
                SearchHit(
                    namespace=spec.namespace,
                    canonical_name=spec.canonical_name,
                    version=spec.version,
                    score=round(score, 6),
                    effects=tuple(e.value for e in sorted(spec.effects)),
                    risk_level=spec.risk_level.value,
                )
            )
            if len(hits) >= limit:
                break
        if not hits:
            raise ToolSearchError(
                ToolSearchErrorCode.TOOL_SEARCH_NO_MATCH,
                f"无匹配工具：{query[:64]}",
            )
        return hits


class TurnSearchSession:
    """单 Turn 的搜索/激活会话（上限与越权防护的状态载体）。

    与不可变 ``ToolPlan`` 配合使用：激活后返回更新后的计划与
    `tool_exposure_changed` 记录；原计划不被修改（§7.2 不变性）。
    """

    def __init__(
        self,
        index: DeferredToolIndex,
        *,
        visible_hash_before: str,
        max_activations: int = DEFAULT_MAX_ACTIVATIONS_PER_TURN,
        max_searches: int = DEFAULT_MAX_SEARCHES_PER_TURN,
        catalog_hash: str | None = None,
    ) -> None:
        self._index = index
        self.visible_hash_before = visible_hash_before
        self.max_activations = max_activations
        self.max_searches = max_searches
        self.searches_used = 0
        self.activations_used = 0
        self.activated_names: list[str] = []
        # §7.2：绑定创建时目录哈希；变化即显式失效，不静默换工具。
        self._catalog_hash = catalog_hash
        self._invalidated = False
        self._invalidation_reason = ""

    # ---- 失效（§7.2 tool_plan_invalidated）---------------------------

    def invalidate(self, *, reason: str = "tool surface changed") -> None:
        """显式失效：MCP 断开/目录重建/健康变化时由可信代码调用。"""
        self._invalidated = True
        self._invalidation_reason = reason

    def guard_catalog(self, current_catalog_hash: str) -> None:
        """目录哈希变化 → 失效（后续搜索/激活一律结构化拒绝）。"""
        if self._catalog_hash is not None and (
            current_catalog_hash != self._catalog_hash
        ):
            self.invalidate(reason="catalog hash changed")

    def _ensure_valid(self) -> None:
        if self._invalidated:
            raise ToolSearchError(
                ToolSearchErrorCode.TOOL_PLAN_INVALIDATED,
                f"本轮工具计划已失效：{self._invalidation_reason}",
            )

    # ---- 搜索 -----------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        namespace: str | None = None,
        effect: str | None = None,
        risk_max: str | None = None,
        limit: int = DEFAULT_MAX_RESULTS,
    ) -> list[SearchHit]:
        self._ensure_valid()
        if self.searches_used >= self.max_searches:
            raise ToolSearchError(
                ToolSearchErrorCode.SEARCH_LIMIT_REACHED,
                f"本 Turn 搜索次数已达上限 {self.max_searches}",
            )
        self.searches_used += 1
        return self._index.search(
            query, namespace=namespace, effect=effect, risk_max=risk_max, limit=limit
        )

    # ---- 激活 -----------------------------------------------------------

    def activate(
        self,
        names: list[str],
        *,
        plan: Any,
    ) -> tuple[Any, ExposureChangedRecord]:
        """激活一批已授权 deferred 工具。

        越权/重复/超限一律结构化失败；成功则返回更新后的 ToolPlan
        （frozen 副本）与 `tool_exposure_changed` 记录。
        """
        self._ensure_valid()
        if not names:
            raise ToolSearchError(
                ToolSearchErrorCode.ACTIVATION_UNAUTHORIZED, "激活列表为空"
            )
        remaining_slots = self.max_activations - self.activations_used
        fresh = [name for name in names if name not in self.activated_names]
        if not fresh:
            raise ToolSearchError(
                ToolSearchErrorCode.ACTIVATION_DUPLICATE, "全部工具已处于可见集"
            )
        if len(fresh) > remaining_slots:
            raise ToolSearchError(
                ToolSearchErrorCode.ACTIVATION_LIMIT_REACHED,
                f"剩余可激活名额 {remaining_slots}，请求 {len(fresh)} 个",
            )
        for name in fresh:
            # 越权防护核心：不在已授权 deferred 索引内的名字一律拒绝。
            if not self._index.contains(name):
                raise ToolSearchError(
                    ToolSearchErrorCode.ACTIVATION_UNAUTHORIZED,
                    f"工具不在本轮已授权 deferred 集：{name[:64]}",
                )

        existing = {item.canonical_name: item for item in plan.direct_tools}
        new_direct: list[PlannedTool] = []
        for name in sorted(fresh):
            spec = self._index.get(name)
            assert spec is not None
            new_direct.append(
                PlannedTool(
                    namespace=spec.namespace,
                    canonical_name=spec.canonical_name,
                    version=spec.version,
                )
            )
            existing[name] = new_direct[-1]
        merged_direct = tuple(
            sorted(existing.values(), key=lambda item: item.canonical_name)
        )
        new_visible_hash = compute_visible_hash(list(merged_direct))
        updated_plan = plan.model_copy(
            update={
                "direct_tools": merged_direct,
                "deferred_tools": tuple(
                    item
                    for item in plan.deferred_tools
                    if item.canonical_name not in set(fresh)
                ),
                "visible_hash": new_visible_hash,
            }
        )

        self.activated_names.extend(fresh)
        self.activations_used += len(fresh)
        record = ExposureChangedRecord(
            activated=tuple(item.canonical_name for item in new_direct),
            visible_hash_before=self.visible_hash_before,
            visible_hash_after=new_visible_hash,
            searches_used=self.searches_used,
            activations_used=self.activations_used,
        )
        # 滚动基线：下一次激活的 before 必须等于本次 after（链式一致）。
        self.visible_hash_before = new_visible_hash
        return updated_plan, record


# ---------------------------------------------------------------------------
# search_tools Function 入口
# ---------------------------------------------------------------------------


class SearchToolsResult(BaseModel):
    """``search_tools`` Function 的输出（可激活精简摘要 + 会话余量）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hits: list[SearchHit]
    searches_used: int
    searches_limit: int
    activations_used: int
    activations_limit: int


SEARCH_TOOLS_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "minLength": 1,
            "maxLength": DEFAULT_MAX_QUERY_CHARS,
            "description": "检索关键词（名称/描述/参数/effect/tags）",
        },
        "namespace": {"type": "string", "maxLength": 128},
        "effect": {
            "type": "string",
            "enum": sorted(e.value for e in EffectClass),
        },
        "risk_max": {"type": "string", "enum": ["safe", "confirm", "restricted"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": DEFAULT_MAX_RESULTS},
    },
    "required": ["query"],
    "additionalProperties": False,
}


def handle_search_tools(
    session: TurnSearchSession,
    arguments: Mapping[str, Any],
) -> SearchToolsResult:
    """``search_tools`` Function 执行入口（可信代码路径）。"""
    query = str(arguments.get("query") or "")
    hits = session.search(
        query,
        namespace=(
            str(arguments["namespace"]) if arguments.get("namespace") else None
        ),
        effect=(str(arguments["effect"]) if arguments.get("effect") else None),
        risk_max=(
            str(arguments["risk_max"]) if arguments.get("risk_max") else None
        ),
        limit=int(arguments.get("limit") or DEFAULT_MAX_RESULTS),
    )
    return SearchToolsResult(
        hits=hits,
        searches_used=session.searches_used,
        searches_limit=session.max_searches,
        activations_used=session.activations_used,
        activations_limit=session.max_activations,
    )


def serialize_result(result: SearchToolsResult) -> dict[str, Any]:
    """喂给模型的 JSON 输出（不含 schema 全文/secret）。"""
    payload = result.model_dump(mode="json")
    payload["hits"] = [
        {key: hit[key] for key in ("namespace", "canonical_name", "version", "effects", "risk_level")}
        for hit in payload["hits"]
    ]
    return payload
