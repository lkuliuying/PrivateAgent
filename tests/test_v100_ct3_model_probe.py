"""v1.0.0 CT-3 单元测试：模型工具能力 probe 框架（专项计划 §8）。

用 fake 模型客户端验证 runner 的确定性判定、聚合与门禁语义：

- 六类 P0 用例的通过/失败判定（§8.2-1..6）；
- 快照字段完整（digest/provider/样本数/results/requirements）；
- 门禁：无有效快照或未全过 → 只允许最小 JSON Function 工具面（fail-closed）；
- 探测异常按"能力未证明"失败关闭，不伪造成功。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from personal_assistant.agent_v2.application.model_probe import (
    ProbeCapability,
    ProbeCase,
    default_probe_cases,
    minimal_tool_surface_allowed,
    run_probe,
)
from personal_assistant.agents.contracts import ToolCall


@dataclass
class ScriptedModel:
    """按轮次脚本返回 tool_calls / 文本的 fake 客户端。"""

    rounds: list[list[tuple[str, dict[str, Any]]]] = field(default_factory=list)
    raise_on_call: bool = False
    seen_requests: list[Any] = field(default_factory=list)

    async def complete(self, request: Any) -> Any:
        self.seen_requests.append(request)
        if self.raise_on_call:
            raise RuntimeError("provider down")
        index = len(self.seen_requests) - 1

        @dataclass(frozen=True)
        class _Resp:
            text: str = ""
            tool_calls: tuple = ()

        # 脚本耗尽后返回纯文本（无工具调用），模拟模型停止调用。
        if index >= len(self.rounds):
            return _Resp(text="done")
        calls = tuple(
            ToolCall(id=f"call-{len(self.seen_requests)}-{i}", name=name,
                     arguments=dict(arguments))
            for i, (name, arguments) in enumerate(self.rounds[index])
        )
        return _Resp(tool_calls=calls)


def _script(*rounds: list[tuple[str, dict[str, Any]]]) -> ScriptedModel:
    return ScriptedModel(rounds=[list(r) for r in rounds])


# ===========================================================================
# A. 用例判定矩阵
# ===========================================================================


async def test_single_json_call_passes_with_correct_arguments():
    model = _script([("read_note", {"note_id": 42, "format": "plain"})])
    snapshot = await run_probe(model, provider="ollama", model_name="qwen2.5:7b",
                               cases=(default_probe_cases()[0],))
    assert snapshot.results[ProbeCapability.SINGLE_JSON_TOOL_CALL.value] is True
    assert snapshot.provider == "ollama"
    assert len(snapshot.model_digest) == 16
    assert snapshot.sample_count >= 1


async def test_wrong_argument_fails_capability():
    model = _script([("read_note", {"note_id": 43, "format": "plain"})])
    snapshot = await run_probe(model, provider="ollama", model_name="m",
                               cases=(default_probe_cases()[0],))
    assert snapshot.results[ProbeCapability.SINGLE_JSON_TOOL_CALL.value] is False
    assert snapshot.passed is False


async def test_text_only_answer_fails_tool_cases_but_refusal_case_needs_no_tools():
    text_only = _script([])
    cases = (default_probe_cases()[0], default_probe_cases()[5])
    snapshot = await run_probe(text_only, provider="p", model_name="m", cases=cases)
    assert snapshot.results[ProbeCapability.SINGLE_JSON_TOOL_CALL.value] is False
    # 拒绝编造用例：不调用任何工具才算通过。
    assert snapshot.results[ProbeCapability.NO_FABRICATION_WITHOUT_TOOLS.value] is True


async def test_two_round_case_requires_tool_calls_in_both_rounds():
    good = _script(
        [("search_notes", {"query": "部署"})],
        [("read_note", {"note_id": 1, "format": "plain"})],
    )
    ok = await run_probe(good, provider="p", model_name="m",
                         cases=(default_probe_cases()[2],))
    assert ok.results[ProbeCapability.MULTI_TURN_TOOL_CALLS.value] is True

    single_round = _script([("search_notes", {"query": "部署"})])
    bad = await run_probe(single_round, provider="p", model_name="m",
                          cases=(default_probe_cases()[2],))
    assert bad.results[ProbeCapability.MULTI_TURN_TOOL_CALLS.value] is False


async def test_same_turn_multi_call_requires_two_calls_in_first_round():
    parallel = _script([
        ("read_note", {"note_id": 1, "format": "plain"}),
        ("read_note", {"note_id": 2, "format": "plain"}),
    ])
    ok = await run_probe(parallel, provider="p", model_name="m",
                         cases=(default_probe_cases()[3],))
    assert ok.results[ProbeCapability.SAME_TURN_MULTI_CALL.value] is True

    sequential = _script([("read_note", {"note_id": 1, "format": "plain"})])
    bad = await run_probe(sequential, provider="p", model_name="m",
                          cases=(default_probe_cases()[3],))
    assert bad.results[ProbeCapability.SAME_TURN_MULTI_CALL.value] is False


async def test_correction_case_requires_integer_fix_in_second_round():
    corrected = _script(
        [("read_note", {"note_id": "abc"})],
        [("read_note", {"note_id": 12, "format": "plain"})],
    )
    ok = await run_probe(corrected, provider="p", model_name="m",
                         cases=(default_probe_cases()[4],))
    assert ok.results[ProbeCapability.CORRECTION_AFTER_FAILURE.value] is True

    repeated = _script(
        [("read_note", {"note_id": "abc"})],
        [("read_note", {"note_id": "abc"})],
    )
    bad = await run_probe(repeated, provider="p", model_name="m",
                          cases=(default_probe_cases()[4],))
    assert bad.results[ProbeCapability.CORRECTION_AFTER_FAILURE.value] is False


# ===========================================================================
# B. 失败关闭与聚合语义
# ===========================================================================


async def test_provider_exception_is_recorded_as_unproven_not_crash():
    model = ScriptedModel(rounds=[], raise_on_call=True)
    snapshot = await run_probe(model, provider="p", model_name="m",
                               cases=(default_probe_cases()[0],))
    assert snapshot.passed is False
    assert snapshot.results[ProbeCapability.SINGLE_JSON_TOOL_CALL.value] is False


async def test_full_suite_aggregates_all_capabilities_and_gate_semantics():
    # 全绿模型：每类用例给合法脚本。
    model = _script(
        [("read_note", {"note_id": 42, "format": "plain"})],   # single
        [("read_note", {"note_id": 7, "format": "markdown"})],  # strict
        [("search_notes", {"query": "部署"})],
        [("read_note", {"note_id": 1, "format": "plain"})],     # two rounds
        [("read_note", {"note_id": 1, "format": "plain"}),
         ("read_note", {"note_id": 2, "format": "plain"})],     # parallel
        [("read_note", {"note_id": "abc"})],
        [("read_note", {"note_id": 12, "format": "plain"})],    # correction
        [],                                                     # refusal
    )
    snapshot = await run_probe(model, provider="ollama", model_name="qwen2.5:7b",
                               repeats=1)
    assert snapshot.passed is True, snapshot.results
    assert set(snapshot.results) == {
        capability.value for capability in ProbeCapability
    }
    # 有有效且全过的快照 → 不再受"最小工具面"限制。
    assert minimal_tool_surface_allowed(snapshot) is False
    # 无快照/未通过 → fail-closed 最小面。
    assert minimal_tool_surface_allowed(None) is True
    assert minimal_tool_surface_allowed(snapshot.model_copy(update={
        "results": {**snapshot.results,
                    ProbeCapability.SINGLE_JSON_TOOL_CALL.value: False}}
    )) is True


async def test_repeats_bounds_enforced():
    with pytest.raises(ValueError):
        await run_probe(_script(), provider="p", model_name="m", repeats=0)


def test_default_dataset_covers_p0_capabilities():
    capabilities = {case.capability for case in default_probe_cases()}
    assert capabilities == set(ProbeCapability)
    for case in default_probe_cases():
        assert isinstance(case, ProbeCase)
