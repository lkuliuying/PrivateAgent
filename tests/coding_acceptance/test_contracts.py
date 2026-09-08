"""跨阶段契约的结构、语义、兼容与生成一致性验证。"""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from private_agent_core.coding_contracts import (
    CONTRACTS,
    CapabilitySnapshot,
    ContextItem,
    ExecutionResult,
    RunOutcome,
)
from private_agent_core.contracts import AgentRunResult

ROOT = Path(__file__).resolve().parents[2]


def test_generated_contracts_and_examples_are_in_sync():
    from protocol_codegen import generate

    for path, content in generate().items():
        assert Path(path).read_text(encoding="utf-8") == content, path
    bundle = json.loads((ROOT / "src/private_agent_core/coding_contracts.schema.json").read_text(encoding="utf-8"))
    examples = json.loads((Path(__file__).parent / "contract_examples.json").read_text(encoding="utf-8"))
    assert set(examples) == {model.__name__ for model in CONTRACTS}
    for model in CONTRACTS:
        model.model_validate(examples[model.__name__])
        schema = {**bundle, "$ref": f"#/$defs/{model.__name__}"}
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(examples[model.__name__])


def test_verified_requires_complete_evidence():
    with pytest.raises(ValidationError):
        RunOutcome(run_id="r", goal_outcome="verified")
    value = {"run_id": "r", "goal_outcome": "verified", "requirements": [
        {"requirement_id": "q", "description": "测试通过"}], "evidence_ids": ["e"],
        "verification_results": [{"requirement_id": "q", "status": "passed", "evidence_ids": ["e"]}]}
    assert RunOutcome.model_validate(value).goal_outcome == "verified"
    for change in ({"evidence_ids": []}, {"unverified_items": ["未运行测试"]},
                   {"verification_results": []}, {"requirements": []}):
        with pytest.raises(ValidationError):
            RunOutcome.model_validate({**value, **change})


def test_execution_facts_do_not_infer_business_success():
    assert ExecutionResult(execution_id="e", operation_id="o", outcome="exited", exit_code=1).exit_code == 1
    for value in ({"outcome": "exited"}, {"outcome": "unknown", "exit_code": 0}):
        with pytest.raises(ValidationError):
            ExecutionResult(execution_id="e", operation_id="o", **value)
    with pytest.raises(ValidationError):
        ExecutionResult(execution_id="e", operation_id="o", outcome="exited", exit_code=True)


def test_s1_wire_examples_have_valid_bound_evidence():
    examples = json.loads((Path(__file__).parent / "s1-wire-examples.json").read_text(encoding="utf-8"))
    for sample in examples.values():
        snapshot = sample["snapshot"]
        outcome = RunOutcome.model_validate(snapshot["run_outcome"])
        assert outcome.goal_outcome == snapshot["goal_outcome"]
        assert sample["events"][-1]["payload"]["run_outcome"] == snapshot["run_outcome"]
        for execution in sample["executions"]:
            if execution.get("execution_result"):
                ExecutionResult.model_validate(execution["execution_result"])


def test_context_and_capabilities_fail_closed():
    with pytest.raises(ValidationError):
        CapabilitySnapshot(pty=True)
    with pytest.raises(ValidationError):
        CapabilitySnapshot(protocol_version="2.0")
    sample = {"item_id": "i", "session_id": 1, "run_id": "r", "ordinal": 1,
              "role": "tool", "kind": "tool_result", "source": "tool",
              "created_at": "2026-09-08T00:00:00Z", "content_ref": {"sha256": "a" * 64, "bytes": 1}}
    with pytest.raises(ValidationError, match="关联调用"):
        ContextItem.model_validate(sample)
    assert ContextItem.model_validate({**sample, "tool_call_id": "call"}).tool_call_id == "call"
    with pytest.raises(ValidationError, match="时区"):
        ContextItem.model_validate({**sample, "tool_call_id": "call", "created_at": "2026-09-08T00:00:00"})


def test_legacy_contract_is_not_silently_extended():
    assert AgentRunResult.model_config["extra"] == "forbid"
    assert "goal_outcome" not in AgentRunResult.model_fields
    for model in CONTRACTS:
        with pytest.raises(ValidationError):
            model.model_validate({"unexpected": True})
