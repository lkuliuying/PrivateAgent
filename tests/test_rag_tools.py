from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

import personal_assistant.api.routes_agent_runs as agent_routes
from personal_assistant.agents import CancellationToken, ModelResponse, ToolCall
from personal_assistant.config import settings
from personal_assistant.core.index_versions import content_sha256, provenance_sha256
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import (
    AgentToolExecution,
    DocChunk,
    Document,
    DocumentCollection,
    DocumentCollectionItem,
    DocumentIndexChunk,
    DocumentIndexChunkProvenance,
    DocumentIndexHead,
    DocumentIndexVersion,
)
from personal_assistant.core.rag import RagService, RetrievedChunk
from personal_assistant.core.rag_citation_evidence import (
    RagCitationEvidenceError,
    load_durable_rag_citation_sources,
)
from personal_assistant.core.rag_evidence import EvidenceDecision
from personal_assistant.core.rag_tool_adapter import build_rag_tool_registry
from personal_assistant.core.timeutil import utcnow
from personal_assistant.main_api import app


class RagCitationWorkflowModel:
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request, *, cancellation):
        del cancellation
        self.requests.append(request)
        if len(self.requests) == 1:
            return ModelResponse(
                tool_calls=(
                    ToolCall(
                        id="rag-search-1",
                        name="search_knowledge_base",
                        arguments={"query": "deployment window", "top_k": 1},
                    ),
                )
            )
        quote = "invented time" if len(self.requests) == 2 else "starts at 09:30 UTC"
        return ModelResponse(
            text=json.dumps(
                {
                    "answer": "The deployment window starts at 09:30 UTC.",
                    "citations": [
                        {
                            "chunk_id": 41,
                            "index_version_id": "version-1",
                            "quote": quote,
                        }
                    ],
                }
            )
        )


async def _wait_for_run_status(client, run_id: str, expected: str) -> dict:
    for _ in range(200):
        response = await client.get(f"/agent-runs/{run_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] == expected:
            return body
        await asyncio.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach {expected}")


@pytest.mark.asyncio
async def test_search_knowledge_base_tool_returns_traceable_bounded_sources(
    db, monkeypatch
):
    captured = {}
    collection = DocumentCollection(title=f"search-kb-{uuid4().hex}")
    document = Document(
        name=f"guide-{uuid4().hex}.pdf",
        status="ready",
        enabled=True,
        chunk_count=1,
    )
    db.add_all([collection, document])
    await db.flush()
    db.add(
        DocumentCollectionItem(
            collection_id=collection.id,
            doc_id=document.id,
            order_index=1,
        )
    )
    await db.commit()

    async def fake_retrieve_with_evidence(
        self, query, top_k=5, filters=None, policy=None
    ):
        del self, policy
        captured.update(query=query, top_k=top_k, filters=filters)
        return (
            [
                RetrievedChunk(
                    chunk_id=41,
                    doc_id=document.id,
                    doc_name=document.name,
                    ordinal=2,
                    content="source evidence " * 200,
                    heading="Install",
                    index_version_id="version-1",
                    page_start=3,
                    page_end=3,
                    source_kind="pdf_page",
                    parser_version="pypdf:v1",
                    heading_path=["Install"],
                )
            ],
            EvidenceDecision(
                abstain=False,
                reason_code="sufficient_evidence",
                policy_version="rag-evidence-v1",
            ),
        )

    monkeypatch.setattr(RagService, "retrieve_with_evidence", fake_retrieve_with_evidence)
    spec = build_rag_tool_registry(db).get("search_knowledge_base")
    assert spec is not None
    try:
        output = await spec.executor(
            {
                "query": "how to install",
                "top_k": 3,
                "collection_id": collection.id,
                "tags": ["manual"],
            },
            CancellationToken(),
        )

        assert captured["top_k"] == 3
        assert captured["filters"].collection_id == collection.id
        assert captured["filters"].tags == ["manual"]
        assert output["count"] == 1
        assert output["results"][0]["chunk_id"] == 41
        assert output["results"][0]["page_start"] == 3
        assert output["results"][0]["source_kind"] == "pdf_page"
        assert output["results"][0]["knowledge_bases"] == [
            {"id": collection.id, "name": collection.title}
        ]
        assert len(output["results"][0]["content_excerpt"]) == 2_000
        spec._output_validator.validate(output)

        fail_closed = await spec.executor(
            {
                "query": "how to install",
                "collection_id": collection.id + 1_000_000,
            },
            CancellationToken(),
        )
        assert fail_closed == {"count": 0, "results": []}
        spec._output_validator.validate(fail_closed)
    finally:
        await db.execute(
            delete(DocumentCollection).where(DocumentCollection.id == collection.id)
        )
        await db.execute(delete(Document).where(Document.id == document.id))
        await db.commit()


@pytest.mark.asyncio
async def test_rag_document_tools_enforce_collection_scope_and_bound_content(db):
    collection = DocumentCollection(
        title=f"tool-kb-{uuid4().hex}",
        goal="A bounded knowledge base",
        tags_json=["manual"],
    )
    other_collection = DocumentCollection(title=f"other-kb-{uuid4().hex}")
    document = Document(
        name=f"tool-doc-{uuid4().hex}.md",
        status="ready",
        enabled=True,
        chunk_count=1,
        content_hash="a" * 64,
        doc_type="markdown",
        tags_json=["manual"],
        language="zh-CN",
    )
    db.add_all([collection, other_collection, document])
    await db.flush()
    content = "evidence " * 3_000
    chunk = DocChunk(
        doc_id=document.id,
        ordinal=0,
        heading="Evidence",
        content=content,
        token_count=3_000,
    )
    db.add_all(
        [
            chunk,
            DocumentCollectionItem(
                collection_id=collection.id,
                doc_id=document.id,
                order_index=1,
            ),
        ]
    )
    await db.commit()

    try:
        registry = build_rag_tool_registry(db)
        chunk_spec = registry.get("get_document_chunk")
        document_spec = registry.get("get_document")
        list_spec = registry.get("list_knowledge_bases")
        assert chunk_spec is not None
        assert document_spec is not None
        assert list_spec is not None

        chunk_output = await chunk_spec.executor(
            {
                "doc_id": document.id,
                "chunk_id": chunk.id,
                "collection_id": collection.id,
            },
            CancellationToken(),
        )
        assert chunk_output["found"] is True
        assert len(chunk_output["chunk"]["content"]) == 20_000
        assert chunk_output["chunk"]["content_truncated"] is True
        assert chunk_output["chunk"]["knowledge_bases"] == [
            {"id": collection.id, "name": collection.title}
        ]
        chunk_spec._output_validator.validate(chunk_output)

        out_of_scope = await chunk_spec.executor(
            {
                "doc_id": document.id,
                "chunk_id": chunk.id,
                "collection_id": other_collection.id,
            },
            CancellationToken(),
        )
        assert out_of_scope == {
            "found": False,
            "reason": "not_found_or_unavailable",
            "chunk": None,
        }
        chunk_spec._output_validator.validate(out_of_scope)

        document_output = await document_spec.executor(
            {"doc_id": document.id, "collection_id": collection.id},
            CancellationToken(),
        )
        assert document_output["found"] is True
        assert document_output["document"]["name"] == document.name
        assert "source_path" not in document_output["document"]
        assert document_output["document"]["knowledge_bases"][0]["name"] == collection.title
        document_spec._output_validator.validate(document_output)

        list_output = await list_spec.executor(
            {"limit": 50, "offset": 0}, CancellationToken()
        )
        listed = next(
            item
            for item in list_output["knowledge_bases"]
            if item["id"] == collection.id
        )
        assert listed["document_count"] == 1
        assert listed["ready_document_count"] == 1
        list_spec._output_validator.validate(list_output)
    finally:
        await db.execute(
            delete(DocumentCollection).where(
                DocumentCollection.id.in_([collection.id, other_collection.id])
            )
        )
        await db.execute(delete(Document).where(Document.id == document.id))
        await db.commit()


@pytest.mark.asyncio
async def test_get_document_chunk_requires_active_version_and_valid_provenance(db):
    document = Document(
        name=f"versioned-tool-doc-{uuid4().hex}.md",
        status="ready",
        enabled=True,
        chunk_count=1,
    )
    db.add(document)
    await db.flush()
    version_id = str(uuid4())
    now = utcnow()
    version = DocumentIndexVersion(
        id=version_id,
        doc_id=document.id,
        version_number=1,
        status="active",
        source_sha256="b" * 64,
        chunker_version="structured:v1",
        embedding_model="test-embedding",
        embedding_dimensions=3,
        chunk_count=1,
        vector_count=1,
        manifest_sha256="c" * 64,
        build_started_at=now,
        validated_at=now,
        activated_at=now,
    )
    db.add(version)
    await db.flush()
    content = "traceable evidence"
    max_heading = "H" * 512
    chunk = DocumentIndexChunk(
        index_version_id=version_id,
        doc_id=document.id,
        ordinal=0,
        content=content,
        content_sha256=content_sha256(content),
        token_count=4,
        heading=max_heading,
        bm25_text=content,
    )
    db.add(chunk)
    await db.flush()
    heading_path = ["Guide", "Trace"]
    provenance = DocumentIndexChunkProvenance(
        chunk_id=chunk.id,
        doc_id=document.id,
        source_kind="markdown_block",
        parser_version="markdown:v1",
        char_start=10,
        char_end=10 + len(content),
        line_start=2,
        line_end=2,
        heading_path_json=heading_path,
        provenance_sha256=provenance_sha256(
            source_kind="markdown_block",
            parser_version="markdown:v1",
            page_start=None,
            page_end=None,
            char_start=10,
            char_end=10 + len(content),
            line_start=2,
            line_end=2,
            heading_path=heading_path,
        ),
    )
    head = DocumentIndexHead(doc_id=document.id, active_version_id=version_id)
    db.add_all([provenance, head])
    await db.commit()

    try:
        spec = build_rag_tool_registry(db).get("get_document_chunk")
        assert spec is not None
        chunk_schema = spec.output_schema["properties"]["chunk"]["oneOf"][0]
        assert chunk_schema["properties"]["heading"]["maxLength"] == 512
        arguments = {
            "doc_id": document.id,
            "chunk_id": chunk.id,
            "index_version_id": version_id,
        }
        output = await spec.executor(arguments, CancellationToken())
        assert output["found"] is True
        assert output["chunk"]["heading"] == max_heading
        assert output["chunk"]["heading_path"] == heading_path
        assert output["chunk"]["char_start"] == 10
        spec._output_validator.validate(output)

        provenance.provenance_sha256 = "0" * 64
        await db.commit()
        tampered = await spec.executor(arguments, CancellationToken())
        assert tampered == {
            "found": False,
            "reason": "integrity_validation_failed",
            "chunk": None,
        }
        spec._output_validator.validate(tampered)
    finally:
        await db.execute(delete(Document).where(Document.id == document.id))
        await db.commit()


@pytest.mark.asyncio
async def test_agent_tool_bundle_registers_rag_only_behind_default_off_flag(
    db, monkeypatch
):
    monkeypatch.setattr(settings, "mcp_enabled", False)
    monkeypatch.setattr(settings, "agent_run_read_only_tools_enabled", False)
    monkeypatch.setattr(settings, "agent_rag_tools_enabled", False)
    assert await agent_routes.get_agent_tool_bundle(db) is None

    monkeypatch.setattr(settings, "agent_rag_tools_enabled", True)
    bundle = await agent_routes.get_agent_tool_bundle(db)
    assert bundle is not None
    assert [definition.name for definition in bundle.definitions] == [
        "search_knowledge_base",
        "get_document_chunk",
        "get_document",
        "list_knowledge_bases",
    ]
    assert bundle.output_verifier_factory is not None


@pytest.mark.asyncio
async def test_agent_rag_workflow_verifies_only_durable_retrieved_citations(
    client,
    db,
    monkeypatch,
):
    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "agent_run_read_only_tools_enabled", False)
    monkeypatch.setattr(settings, "agent_rag_tools_enabled", True)
    monkeypatch.setattr(settings, "mcp_enabled", False)
    monkeypatch.setattr(settings, "agent_output_verification_enabled", True)
    monkeypatch.setattr(settings, "agent_output_verification_max_retries", 1)
    document = Document(
        name=f"citation-workflow-{uuid4().hex}.md",
        status="ready",
        enabled=True,
        chunk_count=1,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    document_id = document.id
    document_name = document.name

    async def fake_retrieve_with_evidence(
        self, query, top_k=5, filters=None, policy=None
    ):
        del self, query, top_k, filters, policy
        return (
            [
                RetrievedChunk(
                    chunk_id=41,
                    doc_id=document_id,
                    doc_name=document_name,
                    ordinal=0,
                    content="The deployment window starts at 09:30 UTC.",
                    heading="Deployment",
                    index_version_id="version-1",
                    source_kind="markdown_block",
                    parser_version="markdown:v2",
                    heading_path=["Deployment"],
                )
            ],
            EvidenceDecision(
                abstain=False,
                reason_code="sufficient_evidence",
                policy_version="rag-evidence-v1",
            ),
        )

    monkeypatch.setattr(RagService, "retrieve_with_evidence", fake_retrieve_with_evidence)
    model = RagCitationWorkflowModel()
    app.dependency_overrides[agent_routes.get_agent_model_client] = lambda: model
    run_id: str | None = None
    try:
        created = await client.post(
            "/agent-runs",
            json={"message": "When is the deployment window?"},
        )
        assert created.status_code == 202
        run_id = created.json()["id"]

        completed = await _wait_for_run_status(client, run_id, "completed")
        assert json.loads(completed["output"])["answer"].startswith("The deployment")
        assert len(model.requests) == 3
        assert all(request.output_format is not None for request in model.requests)
        assert model.requests[0].output_format.json_schema["required"] == [
            "answer",
            "citations",
        ]

        await db.rollback()
        sources = await load_durable_rag_citation_sources(db, run_id=run_id)
        assert [(source.index_version_id, source.chunk_id) for source in sources] == [
            ("version-1", 41)
        ]
        assert sources[0].content == "The deployment window starts at 09:30 UTC."

        events = (await client.get(f"/agent-runs/{run_id}/events")).json()["items"]
        failures = [
            event
            for event in events
            if event["type"] == "output.validation_failed"
        ]
        assert len(failures) == 1
        assert failures[0]["payload"]["code"] == "unsupported_quote"
        assert "deployment window starts" not in str(failures[0]["payload"])

        execution = (
            await db.execute(
                select(AgentToolExecution).where(
                    AgentToolExecution.run_id == run_id,
                    AgentToolExecution.tool_name == "search_knowledge_base",
                )
            )
        ).scalar_one()
        execution.output_sha256 = "0" * 64
        await db.commit()
        with pytest.raises(RagCitationEvidenceError, match="integrity check failed"):
            await load_durable_rag_citation_sources(db, run_id=run_id)
    finally:
        app.dependency_overrides.pop(agent_routes.get_agent_model_client, None)
        if run_id is not None:
            await db.execute(
                delete(AgentRunRecord).where(AgentRunRecord.id == run_id)
            )
        await db.execute(delete(Document).where(Document.id == document_id))
        await db.commit()
