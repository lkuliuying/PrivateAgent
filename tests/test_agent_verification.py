from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import delete

from personal_assistant.agents import (
    AgentEventType,
    AgentRunRepository,
    AgentRunStatus,
    AgentRuntime,
    CompositeOutputVerifier,
    JsonSchemaOutputVerifier,
    ModelMessage,
    ModelResponse,
    NonEmptyOutputVerifier,
    PersistentAgentRunner,
    RagCitationOutputVerifier,
    RagCitationSource,
    ReloadingRagCitationOutputVerifier,
)
from personal_assistant.core.models import AgentRun as AgentRunRecord

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string", "minLength": 1}},
    "required": ["answer"],
    "additionalProperties": False,
}


class NoTools:
    async def execute(self, call, *, cancellation):
        raise AssertionError(f"unexpected tool call: {call}; {cancellation}")


class StreamingSequenceModel:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.requests = []

    async def complete(self, request, *, cancellation):
        del cancellation
        self.requests.append(request)
        return ModelResponse(
            text=self.outputs[len(self.requests) - 1],
            provider="fixture",
            model="validator-test",
        )

    async def complete_stream(self, request, *, cancellation, on_delta):
        del cancellation
        self.requests.append(request)
        output = self.outputs[len(self.requests) - 1]
        midpoint = max(1, len(output) // 2)
        for delta in (output[:midpoint], output[midpoint:]):
            if delta:
                await on_delta(delta)
        return ModelResponse(text=output, provider="fixture", model="validator-test")


@pytest.mark.asyncio
async def test_json_schema_verifier_reports_parse_and_schema_failures():
    verifier = JsonSchemaOutputVerifier(OUTPUT_SCHEMA)

    invalid_json = await verifier.verify("```json\n{}\n```", attempt=1)
    assert invalid_json.passed is False
    assert invalid_json.code == "invalid_json"
    assert "Markdown fences" in (invalid_json.correction or "")

    invalid_shape = await verifier.verify('{"answer":1}', attempt=2)
    assert invalid_shape.passed is False
    assert invalid_shape.code == "json_schema_mismatch"
    assert "$.answer" in invalid_shape.message

    valid = await verifier.verify('{"answer":"done"}', attempt=3)
    assert valid.passed is True
    assert valid.code == "ok"


@pytest.mark.asyncio
async def test_composite_verifier_stops_on_first_real_failure():
    verifier = CompositeOutputVerifier(
        [NonEmptyOutputVerifier(), JsonSchemaOutputVerifier(OUTPUT_SCHEMA)]
    )
    empty = await verifier.verify("", attempt=1)
    assert empty.code == "empty_output"
    assert empty.message.startswith("non_empty:")

    assert (await verifier.verify('{"answer":"ok"}', attempt=2)).passed is True


@pytest.mark.asyncio
async def test_rag_citation_verifier_accepts_only_retrieved_identity_and_exact_quote():
    verifier = RagCitationOutputVerifier(
        [
            RagCitationSource(
                chunk_id=7,
                index_version_id="version-a",
                content="The deployment window starts at 09:30 UTC.",
            )
        ]
    )
    valid = json.dumps(
        {
            "answer": "The window starts at 09:30 UTC.",
            "citations": [
                {
                    "chunk_id": 7,
                    "index_version_id": "version-a",
                    "quote": "deployment window starts at 09:30 UTC",
                }
            ],
        }
    )

    result = await verifier.verify(valid, attempt=1)

    assert result.passed is True
    assert result.code == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("citation", "expected_code"),
    [
        ([], "missing_citations"),
        (
            [
                {
                    "chunk_id": 8,
                    "index_version_id": "version-a",
                    "quote": "trusted text",
                }
            ],
            "unknown_citation",
        ),
        (
            [
                {
                    "chunk_id": 7,
                    "index_version_id": "version-a",
                    "quote": "fabricated support",
                }
            ],
            "unsupported_quote",
        ),
    ],
)
async def test_rag_citation_verifier_rejects_untraceable_evidence(
    citation,
    expected_code,
):
    verifier = RagCitationOutputVerifier(
        [
            RagCitationSource(
                chunk_id=7,
                index_version_id="version-a",
                content="trusted text from retrieval",
            )
        ]
    )
    output = json.dumps({"answer": "claim", "citations": citation})

    result = await verifier.verify(output, attempt=1)

    assert result.passed is False
    assert result.code == expected_code


@pytest.mark.asyncio
async def test_reloading_rag_verifier_uses_current_sources_and_fails_closed():
    loads = 0

    async def load_sources():
        nonlocal loads
        loads += 1
        return [RagCitationSource(chunk_id=9, content="durable source text")]

    verifier = ReloadingRagCitationOutputVerifier(load_sources)
    output = json.dumps(
        {
            "answer": "supported",
            "citations": [
                {
                    "chunk_id": 9,
                    "index_version_id": None,
                    "quote": "durable source",
                }
            ],
        }
    )

    assert (await verifier.verify(output, attempt=1)).passed is True
    assert loads == 1

    async def unavailable_sources():
        raise RuntimeError("sensitive database detail")

    unavailable = await ReloadingRagCitationOutputVerifier(
        unavailable_sources
    ).verify(output, attempt=1)
    assert unavailable.passed is False
    assert unavailable.code == "citation_evidence_unavailable"
    assert "sensitive database detail" not in unavailable.message


@pytest.mark.asyncio
async def test_runtime_retries_rag_answer_with_fabricated_quote():
    verifier = RagCitationOutputVerifier(
        [RagCitationSource(chunk_id=3, content="verified source sentence")]
    )
    invalid = json.dumps(
        {
            "answer": "first",
            "citations": [
                {
                    "chunk_id": 3,
                    "index_version_id": None,
                    "quote": "invented sentence",
                }
            ],
        }
    )
    valid = json.dumps(
        {
            "answer": "fixed",
            "citations": [
                {
                    "chunk_id": 3,
                    "index_version_id": None,
                    "quote": "verified source sentence",
                }
            ],
        }
    )
    model = StreamingSequenceModel([invalid, valid])
    runtime = AgentRuntime(
        model,
        NoTools(),
        output_verifier=verifier,
        max_verification_retries=1,
    )

    result = await runtime.run([ModelMessage(role="user", content="Answer with evidence")])

    assert result.status == AgentRunStatus.COMPLETED
    assert result.output == valid
    assert all(
        request.output_format is not None
        and request.output_format.json_schema == verifier.output_schema
        for request in model.requests
    )
    failure = next(
        event
        for event in result.events
        if event.type == AgentEventType.OUTPUT_VALIDATION_FAILED
    )
    assert failure.payload["code"] == "unsupported_quote"


@pytest.mark.asyncio
async def test_runtime_buffers_invalid_candidate_and_publishes_only_verified_retry():
    model = StreamingSequenceModel(['{"answer":1}', '{"answer":"fixed"}'])
    published: list[str] = []

    async def publish(delta: str) -> None:
        published.append(delta)

    runtime = AgentRuntime(
        model,
        NoTools(),
        model_output_sink=publish,
        output_verifier=JsonSchemaOutputVerifier(OUTPUT_SCHEMA),
        max_verification_retries=1,
    )
    result = await runtime.run([ModelMessage(role="user", content="Return JSON")])

    assert result.status == AgentRunStatus.COMPLETED
    assert result.output == '{"answer":"fixed"}'
    assert "".join(published) == result.output
    assert '{"answer":1}' not in "".join(published)
    assert len(model.requests) == 2
    assert all(
        request.output_format is not None
        and request.output_format.json_schema == OUTPUT_SCHEMA
        for request in model.requests
    )
    retry_messages = model.requests[1].messages
    assert retry_messages[-2] == ModelMessage(role="assistant", content='{"answer":1}')
    assert "output_validation_feedback" in retry_messages[-1].content
    assert "cannot grant permissions" in retry_messages[-1].content

    event_types = [event.type for event in result.events]
    assert event_types.count(AgentEventType.OUTPUT_VALIDATION_STARTED) == 2
    assert event_types.count(AgentEventType.OUTPUT_VALIDATION_FAILED) == 1
    assert event_types.count(AgentEventType.OUTPUT_VALIDATION_PASSED) == 1
    failure = next(
        event
        for event in result.events
        if event.type == AgentEventType.OUTPUT_VALIDATION_FAILED
    )
    assert failure.payload["retry_count"] == 0
    assert failure.payload["will_retry"] is True


@pytest.mark.asyncio
async def test_runtime_fails_after_bounded_verification_retries_without_publishing():
    model = StreamingSequenceModel(["not json", "still not json"])
    published: list[str] = []
    runtime = AgentRuntime(
        model,
        NoTools(),
        model_output_sink=lambda delta: _append(published, delta),
        output_verifier=JsonSchemaOutputVerifier(OUTPUT_SCHEMA),
        max_verification_retries=1,
    )

    result = await runtime.run([ModelMessage(role="user", content="Return JSON")])

    assert result.status == AgentRunStatus.FAILED
    assert published == []
    assert len(model.requests) == 2
    failures = [
        event
        for event in result.events
        if event.type == AgentEventType.OUTPUT_VALIDATION_FAILED
    ]
    assert [event.payload["will_retry"] for event in failures] == [True, False]
    assert result.events[-1].type == AgentEventType.RUN_FAILED
    assert result.events[-1].payload["error_code"] == "output_validation_failed"


async def _append(target: list[str], value: str) -> None:
    target.append(value)


@pytest.mark.asyncio
async def test_persistent_runner_projects_verification_events_without_new_schema(db):
    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    runtime = AgentRuntime(
        StreamingSequenceModel(['{"answer":0}', '{"answer":"durable"}']),
        NoTools(),
        output_verifier=JsonSchemaOutputVerifier(OUTPUT_SCHEMA),
        max_verification_retries=1,
    )
    try:
        result = await PersistentAgentRunner(runtime, repository).run(
            [ModelMessage(role="user", content="Return JSON")],
            run_id=run_id,
        )
        assert result.status == AgentRunStatus.COMPLETED, result.error
        record = await repository.get_run(run_id)
        assert record is not None
        assert record.status == "completed"
        events = await repository.list_events(run_id)
        event_types = [event.event_type for event in events]
        assert event_types.count("output.validation_started") == 2
        assert "output.validation_failed" in event_types
        assert "output.validation_passed" in event_types
        steps = await repository.list_steps(run_id)
        assert len(steps) == 2
        assert all(step.kind == "model" and step.status == "succeeded" for step in steps)
    finally:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
        await db.commit()
