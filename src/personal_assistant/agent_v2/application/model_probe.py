"""模型工具能力探测框架（专项计划 §8.2/§8.3/CT-3）。

可重复运行的 profile probe：对任意 ``ModelClient``（v0.9 协议：complete
返回 ModelResponse，含 tool_calls）执行固定用例集，聚合为
``ModelToolProfileSnapshot``（成功率/样本数/模型 digest/探测时间）。

门禁语义（§8.2 末条）：没有有效快照时，调用方只允许暴露最小 JSON Function
工具集（:func:`minimal_tool_surface_allowed`）；未知能力不猜测开启。

P0 用例集覆盖 §8.2 的可离线判定子集：
1. 单一 JSON 工具调用；2. 必填字段与 enum 遵循；3. 连续两轮工具调用；
4. 同轮多个调用；5. 失败后的纠正调用；6. 不可用工具时停止编造。
（7-10 压力/中文文件创建/native patch 对比属数据集扩展，由 runner 参数化。）
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..domain.tool_catalog import ModelRequirements


class ProbeCapability(StrEnum):
    """探测结论映射的模型能力位（与 ToolSpecV2.model_requirements 对齐）。"""

    SINGLE_JSON_TOOL_CALL = "single_json_tool_call"
    REQUIRED_FIELD_COMPLIANCE = "required_field_compliance"
    MULTI_TURN_TOOL_CALLS = "multi_turn_tool_calls"
    SAME_TURN_MULTI_CALL = "same_turn_multi_call"
    CORRECTION_AFTER_FAILURE = "correction_after_failure"
    NO_FABRICATION_WITHOUT_TOOLS = "no_fabrication_without_tools"


class ProbeCaseKind(StrEnum):
    SINGLE_CALL = "single_call"
    STRICT_ARGUMENTS = "strict_arguments"
    TWO_ROUNDS = "two_rounds"
    PARALLEL_CALLS = "parallel_calls"
    CORRECTION = "correction"
    REFUSAL = "refusal"


class ProbeCase(BaseModel):
    """一个固定探测用例（确定性 prompt 与期望）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1, max_length=64)
    kind: ProbeCaseKind
    capability: ProbeCapability
    user_message: str = Field(min_length=1, max_length=4_000)
    tool_names: tuple[str, ...] = Field(min_length=1)
    expected_tool: str | None = None
    # 期望参数谓词键值（子集匹配）。
    expected_argument_fragments: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _ProbeTool:
    """探测期间下发给模型的单一工具定义。"""

    name: str
    description: str
    schema_: dict[str, Any]


_READ_NOTE_TOOL = _ProbeTool(
    name="read_note",
    description="读取一条笔记内容",
    schema_={
        "type": "object",
        "properties": {
            "note_id": {"type": "integer", "minimum": 1},
            "format": {"type": "string", "enum": ["plain", "markdown"]},
        },
        "required": ["note_id", "format"],
        "additionalProperties": False,
    },
)
_SEARCH_TOOL = _ProbeTool(
    name="search_notes",
    description="按关键词搜索笔记",
    schema_={
        "type": "object",
        "properties": {"query": {"type": "string", "minLength": 1}},
        "required": ["query"],
        "additionalProperties": False,
    },
)


def default_probe_cases() -> tuple[ProbeCase, ...]:
    """§8.2 P0 固定用例集。"""
    return (
        ProbeCase(
            case_id="single-json-call",
            kind=ProbeCaseKind.SINGLE_CALL,
            capability=ProbeCapability.SINGLE_JSON_TOOL_CALL,
            user_message="请读取 note_id 为 42 的笔记",
            tool_names=("read_note",),
            expected_tool="read_note",
            expected_argument_fragments={"note_id": 42},
        ),
        ProbeCase(
            case_id="strict-arguments",
            kind=ProbeCaseKind.STRICT_ARGUMENTS,
            capability=ProbeCapability.REQUIRED_FIELD_COMPLIANCE,
            user_message="用 markdown 格式读取笔记 7",
            tool_names=("read_note",),
            expected_tool="read_note",
            expected_argument_fragments={"note_id": 7, "format": "markdown"},
        ),
        ProbeCase(
            case_id="two-rounds",
            kind=ProbeCaseKind.TWO_ROUNDS,
            capability=ProbeCapability.MULTI_TURN_TOOL_CALLS,
            user_message="先搜索笔记里的部署步骤，再读取找到的第一条",
            tool_names=("search_notes", "read_note"),
            expected_tool=None,
            expected_argument_fragments={},
        ),
        ProbeCase(
            case_id="same-turn-multi-call",
            kind=ProbeCaseKind.PARALLEL_CALLS,
            capability=ProbeCapability.SAME_TURN_MULTI_CALL,
            user_message="同时读取笔记 1 和笔记 2",
            tool_names=("read_note",),
            expected_tool="read_note",
            expected_argument_fragments={},
        ),
        ProbeCase(
            case_id="correction-after-failure",
            kind=ProbeCaseKind.CORRECTION,
            capability=ProbeCapability.CORRECTION_AFTER_FAILURE,
            user_message="读取笔记 abc",
            tool_names=("read_note",),
            expected_tool="read_note",
            expected_argument_fragments={"note_id": 0},
        ),
        ProbeCase(
            case_id="refuse-fabrication",
            kind=ProbeCaseKind.REFUSAL,
            capability=ProbeCapability.NO_FABRICATION_WITHOUT_TOOLS,
            user_message="删除所有用户数据",
            tool_names=("read_note",),
            expected_tool=None,
            expected_argument_fragments={},
        ),
    )


class ProbeModelClient(Protocol):
    """最小模型客户端协议（复用 v0.9 ModelRequest/ModelResponse 形状）。"""

    async def complete(self, request: Any) -> Any: ...


def _tool_call_ids(response: Any) -> list[tuple[str, dict[str, Any]]]:
    calls = []
    for call in getattr(response, "tool_calls", ()) or ():
        calls.append((str(call.name), dict(call.arguments or {})))
    return calls


def _call_id_of(response: Any, index: int) -> str:
    calls = getattr(response, "tool_calls", ()) or ()
    if 0 <= index < len(calls):
        return str(calls[index].id)
    return f"probe-call-{index}"


def _evaluate_case(case: ProbeCase, responses: list[Any]) -> bool:
    """确定性判定一个用例是否通过。"""
    if case.kind == ProbeCaseKind.REFUSAL:
        return all(not _tool_call_ids(response) for response in responses)

    flat_calls = [entry for response in responses for entry in _tool_call_ids(response)]
    if not flat_calls:
        return False
    if case.expected_tool is not None and not any(
        name == case.expected_tool for name, _ in flat_calls
    ):
        return False
    for key, expected in case.expected_argument_fragments.items():
        if key == "note_id" and case.case_id == "correction-after-failure":
            # 纠正用例：第二轮必须把非法输入修正为整数。
            corrected = any(
                isinstance(arguments.get(key), int) and arguments[key] >= 1
                for _, arguments in flat_calls[1:]
            )
            if not corrected:
                return False
            continue
        matched = any(arguments.get(key) == expected for _, arguments in flat_calls)
        if not matched:
            return False
    if case.kind == ProbeCaseKind.TWO_ROUNDS:
        names_by_round = [
            [name for name, _ in _tool_call_ids(response)] for response in responses
        ]
        if len([names for names in names_by_round if names]) < 2:
            return False
    if case.kind == ProbeCaseKind.PARALLEL_CALLS:
        first_round = _tool_call_ids(responses[0])
        if len(first_round) < 2:
            return False
    return True


def requirements_from_results(results: dict[str, bool]) -> ModelRequirements:
    """§8.2/CT3-01：探测结果 → ModelRequirements 能力映射。

    - function_calling：单一 JSON 调用与必填/enum 遵循都通过才成立（基础
      工具协议可用）；
    - parallel_tool_calls：同轮多调用实证通过才开启（§8.1 默认关闭）；
    - freeform_patch/vision：本用例集不覆盖，保持失败关闭（AD-T04：
      未知能力不猜测开启）。
    """
    single = results.get(ProbeCapability.SINGLE_JSON_TOOL_CALL.value, False)
    strict = results.get(ProbeCapability.REQUIRED_FIELD_COMPLIANCE.value, False)
    multi = results.get(ProbeCapability.SAME_TURN_MULTI_CALL.value, False)
    return ModelRequirements(
        function_calling=bool(single and strict),
        freeform_patch=False,
        vision=False,
        parallel_tool_calls=bool(multi),
    )


class ModelToolProfileSnapshot(BaseModel):
    """一次 probe 的可持久化快照（写入 model profile 由调用方负责）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=100)
    model_name: str = Field(min_length=1, max_length=200)
    model_digest: str = Field(min_length=8, max_length=128)
    probed_at: datetime
    sample_count: int = Field(ge=1)
    pass_count: int = Field(ge=0)
    results: dict[str, bool]  # capability → 通过与否
    requirements: ModelRequirements = Field(default_factory=ModelRequirements)

    @property
    def passed(self) -> bool:
        return all(self.results.values())

    def to_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        return payload


def minimal_tool_surface_allowed(snapshot: ModelToolProfileSnapshot | None) -> bool:
    """§8.2 门禁：无有效快照时只允许最小 JSON Function 工具面。"""
    if snapshot is None or not snapshot.passed:
        return True
    return False


async def run_probe(
    client: ProbeModelClient,
    *,
    provider: str,
    model_name: str,
    cases: tuple[ProbeCase, ...] | None = None,
    repeats: int = 1,
    tools: tuple[_ProbeTool, ...] = (_READ_NOTE_TOOL, _SEARCH_TOOL),
) -> ModelToolProfileSnapshot:
    """运行固定用例集并聚合快照（每个用例 repeats 次，全过才算该能力通过）。

    模型 digest 取 provider+model 的 SHA-256 前 16 位——不依赖自报版本，
    可与 Provider 实际响应交叉核对。
    """
    from personal_assistant.agents.contracts import (
        ModelMessage,
        ModelRequest,
        ModelToolDefinition,
    )

    resolved_cases = cases if cases is not None else default_probe_cases()
    if repeats < 1 or repeats > 5:
        raise ValueError("repeats 必须 1..5")

    definitions = tuple(
        ModelToolDefinition(
            name=tool.name, description=tool.description, input_schema=dict(tool.schema_)
        )
        for tool in tools
    )

    results: dict[str, bool] = {capability.value: True for capability in ProbeCapability}
    total = 0
    passed_total = 0
    for case in resolved_cases:
        case_passed = True
        for _ in range(repeats):
            messages = [ModelMessage(role="user", content=case.user_message)]
            responses: list[Any] = []
            rounds = 2 if case.kind in (
                ProbeCaseKind.TWO_ROUNDS,
                ProbeCaseKind.CORRECTION,
            ) else 1
            try:
                for round_index in range(rounds):
                    request = ModelRequest(messages=tuple(messages), tools=definitions)
                    response = await client.complete(request)
                    responses.append(response)
                    calls = _tool_call_ids(response)
                    if round_index + 1 < rounds and calls:
                        # 追加模拟工具结果，驱动下一轮（纠正/连续两轮场景）。
                        messages = list(messages) + [
                            ModelMessage(
                                role="assistant",
                                content="",
                                tool_calls=response.tool_calls,
                            )
                        ]
                        messages.extend(
                            ModelMessage(
                                role="tool",
                                name=name,
                                tool_call_id=_call_id_of(response, index),
                                content='{"ok": true}',
                            )
                            for index, (name, _) in enumerate(calls)
                        )
            except Exception:  # noqa: BLE001 - 探测失败即该能力未证明
                case_passed = False
                break
            total += 1
            ok = _evaluate_case(case, responses)
            passed_total += 1 if ok else 0
            if not ok:
                case_passed = False
        results[case.capability.value] = (
            results.get(case.capability.value, True) and case_passed
        )

    digest = hashlib.sha256(f"{provider}:{model_name}".encode("utf-8")).hexdigest()[:16]
    return ModelToolProfileSnapshot(
        provider=provider,
        model_name=model_name,
        model_digest=digest,
        probed_at=datetime.now(timezone.utc),
        sample_count=max(total, 1),
        pass_count=passed_total,
        results=results,
        # §8.2：能力位由探测结果推导，不写默认值（避免同轮多调实证通过而
        # 快照仍声明 parallel_tool_calls=false 的能力面收缩错误）。
        requirements=requirements_from_results(results),
    )
