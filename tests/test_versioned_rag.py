from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select

import personal_assistant.api.routes_documents as document_routes
import personal_assistant.core.hybrid_retrieval as hybrid_module
import personal_assistant.workers.importer as importer_module
from personal_assistant.core.hybrid_retrieval import HybridRetriever, RetrievalFilters
from personal_assistant.core.index_versions import (
    ActiveIndexMutationError,
    DocumentIndexRepository,
    IndexBuildInput,
    IndexValidationError,
    VersionedDocumentIndexer,
    provenance_sha256,
)
from personal_assistant.core.models import (
    DocChunk,
    Document,
    DocumentIndexChunk,
    DocumentIndexChunkProvenance,
)
from personal_assistant.core.repo import DocChunkRepository, DocumentRepository
from personal_assistant.core.timeutil import utcnow


class FakeVersionVectorStore:
    def __init__(self) -> None:
        self.vectors: dict[str, set[int]] = {}
        self.omit_next_vector = False
        self.fail_next_delete = False

    async def upsert_version(
        self,
        *,
        index_version_id: str,
        chunk_ids: list[int],
        embeddings: list[list[float]],
        doc_id: int,
    ) -> None:
        del embeddings, doc_id
        stored = chunk_ids[:-1] if self.omit_next_vector else chunk_ids
        self.omit_next_vector = False
        self.vectors[index_version_id] = set(stored)

    async def list_chunk_ids(self, index_version_id: str) -> list[int]:
        return sorted(self.vectors.get(index_version_id, set()))

    async def delete_version(self, index_version_id: str) -> None:
        if self.fail_next_delete:
            self.fail_next_delete = False
            raise RuntimeError("injected vector delete failure")
        self.vectors.pop(index_version_id, None)


class FakeEmbeddingProvider:
    async def embed_one(self, text: str) -> list[float]:
        del text
        return [1.0, 0.0]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def _source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chunks(prefix: str) -> list[IndexBuildInput]:
    return [
        IndexBuildInput(
            ordinal=1,
            content=f"{prefix} first chunk",
            heading=f"{prefix} heading",
        ),
        IndexBuildInput(ordinal=2, content=f"{prefix} second chunk"),
    ]


async def _purge_document(db, doc_id: int) -> None:
    await db.execute(delete(Document).where(Document.id == doc_id))
    await db.commit()


@pytest.mark.asyncio
async def test_side_by_side_build_activation_and_rollback_preserve_both_versions(db):
    document = await DocumentRepository(db).create(
        name="versioned-rag.txt",
        content_hash=_source_hash("source-v1"),
    )
    store = FakeVersionVectorStore()
    doc_id = document.id
    indexer = VersionedDocumentIndexer(db, store)
    repository = DocumentIndexRepository(db)
    try:
        first = await indexer.build_and_activate(
            doc_id=doc_id,
            source_sha256=_source_hash("source-v1"),
            chunker_version="split-text-v1",
            embedding_model="fake-embed",
            chunks=_chunks("v1"),
            embeddings=[[1.0, 0.0], [0.0, 1.0]],
        )
        first_chunk_ids = set(await store.list_chunk_ids(first.id))
        assert first.status == "active"
        assert first.version_number == 1
        assert first.chunk_count == first.vector_count == 2
        assert len(first.manifest_sha256 or "") == 64
        assert (await repository.get_head(doc_id)).active_version_id == first.id
        assert await db.scalar(
            select(func.count(DocChunk.id)).where(DocChunk.doc_id == doc_id)
        ) == 0

        second = await indexer.build_and_activate(
            doc_id=doc_id,
            source_sha256=_source_hash("source-v2"),
            chunker_version="split-text-v2",
            embedding_model="fake-embed-v2",
            chunks=_chunks("v2"),
            embeddings=[[0.5, 0.5], [0.25, 0.75]],
        )
        head = await repository.get_head(doc_id)
        versions = await repository.list_versions(doc_id)

        assert head is not None
        assert head.active_version_id == second.id
        assert head.previous_version_id == first.id
        assert head.lock_version == 2
        assert [(version.version_number, version.status) for version in versions] == [
            (2, "active"),
            (1, "retired"),
        ]
        assert set(await store.list_chunk_ids(first.id)) == first_chunk_ids
        assert len(await repository.list_chunks(first.id)) == 2
        assert len(await repository.list_chunks(second.id)) == 2

        rolled_back = await indexer.rollback(doc_id)
        head = await repository.get_head(doc_id)
        assert rolled_back.id == first.id
        assert rolled_back.status == "active"
        assert head is not None
        assert head.active_version_id == first.id
        assert head.previous_version_id == second.id
        assert head.lock_version == 3
        assert (await repository.get_version(second.id)).status == "retired"
    finally:
        await _purge_document(db, doc_id)


@pytest.mark.asyncio
async def test_failed_staging_never_replaces_active_index(db):
    document = await DocumentRepository(db).create(name="safe-reindex.txt")
    doc_id = document.id
    store = FakeVersionVectorStore()
    indexer = VersionedDocumentIndexer(db, store)
    repository = DocumentIndexRepository(db)
    try:
        active = await indexer.build_and_activate(
            doc_id=doc_id,
            source_sha256=_source_hash("stable source"),
            chunker_version="split-text-v1",
            embedding_model="fake-embed",
            chunks=_chunks("stable"),
            embeddings=[[1.0, 0.0], [0.0, 1.0]],
        )
        active_id = active.id
        active_chunk_count = active.chunk_count
        active_vector_ids = set(await store.list_chunk_ids(active_id))
        store.omit_next_vector = True

        with pytest.raises(IndexValidationError, match="vector manifest mismatch"):
            await indexer.build_and_activate(
                doc_id=doc_id,
                source_sha256=_source_hash("broken source"),
                chunker_version="split-text-v2",
                embedding_model="fake-embed-v2",
                chunks=_chunks("broken"),
                embeddings=[[0.1, 0.9], [0.2, 0.8]],
            )

        versions = await repository.list_versions(doc_id)
        head = await repository.get_head(doc_id)
        current_document = await db.get(Document, doc_id)
        assert head is not None and head.active_version_id == active_id
        assert [(version.version_number, version.status) for version in versions] == [
            (2, "failed"),
            (1, "active"),
        ]
        assert versions[0].failure_code == "validation_failed"
        assert set(await store.list_chunk_ids(active_id)) == active_vector_ids
        assert current_document is not None
        assert current_document.status == "ready"
        assert current_document.chunk_count == active_chunk_count
    finally:
        await _purge_document(db, doc_id)


@pytest.mark.asyncio
async def test_active_version_cannot_be_deleted_and_inactive_cleanup_is_scoped(db):
    document = await DocumentRepository(db).create(name="index-cleanup.txt")
    doc_id = document.id
    store = FakeVersionVectorStore()
    indexer = VersionedDocumentIndexer(db, store)
    repository = DocumentIndexRepository(db)
    try:
        first = await indexer.build_and_activate(
            doc_id=doc_id,
            source_sha256=_source_hash("one"),
            chunker_version="split-text-v1",
            embedding_model="fake-embed",
            chunks=_chunks("one"),
            embeddings=[[1.0], [2.0]],
        )
        second = await indexer.build_and_activate(
            doc_id=doc_id,
            source_sha256=_source_hash("two"),
            chunker_version="split-text-v1",
            embedding_model="fake-embed",
            chunks=_chunks("two"),
            embeddings=[[3.0], [4.0]],
        )

        first_id = first.id
        second_id = second.id
        with pytest.raises(ActiveIndexMutationError, match="active"):
            await indexer.delete_inactive_version(second_id)

        assert await indexer.delete_inactive_version(first_id)
        assert await repository.get_version(first_id) is None
        assert await store.list_chunk_ids(first_id) == []
        assert len(await store.list_chunk_ids(second_id)) == 2
        head = await repository.get_head(doc_id)
        assert head is not None
        assert head.active_version_id == second_id
        assert head.previous_version_id is None
    finally:
        await _purge_document(db, doc_id)


@pytest.mark.asyncio
async def test_rollback_revalidates_vectors_before_switching_head(db):
    document = await DocumentRepository(db).create(name="rollback-guard.txt")
    doc_id = document.id
    store = FakeVersionVectorStore()
    indexer = VersionedDocumentIndexer(db, store)
    repository = DocumentIndexRepository(db)
    try:
        first = await indexer.build_and_activate(
            doc_id=doc_id,
            source_sha256=_source_hash("rollback-one"),
            chunker_version="split-text-v1",
            embedding_model="fake-embed",
            chunks=_chunks("rollback-one"),
            embeddings=[[1.0], [2.0]],
        )
        second = await indexer.build_and_activate(
            doc_id=doc_id,
            source_sha256=_source_hash("rollback-two"),
            chunker_version="split-text-v1",
            embedding_model="fake-embed",
            chunks=_chunks("rollback-two"),
            embeddings=[[3.0], [4.0]],
        )
        first_ids = sorted(store.vectors[first.id])
        store.vectors[first.id].remove(first_ids[-1])

        with pytest.raises(IndexValidationError, match="no longer match"):
            await indexer.rollback(doc_id)

        head = await repository.get_head(doc_id)
        assert head is not None
        assert head.active_version_id == second.id
        assert (await repository.get_version(second.id)).status == "active"
        assert (await repository.get_version(first.id)).status == "retired"
    finally:
        await _purge_document(db, doc_id)


@pytest.mark.asyncio
async def test_crash_recovery_resumes_building_and_validated_versions(db):
    building_doc = await DocumentRepository(db).create(name="recover-building.txt")
    validated_doc = await DocumentRepository(db).create(name="recover-validated.txt")
    building_doc_id = building_doc.id
    validated_doc_id = validated_doc.id
    store = FakeVersionVectorStore()
    repository = DocumentIndexRepository(db)
    indexer = VersionedDocumentIndexer(db, store)
    try:
        building = await repository.create_version(
            doc_id=building_doc_id,
            source_sha256=_source_hash("recover-building"),
            chunker_version="split-text-v1",
            embedding_model="fake-embed",
            embedding_dimensions=2,
        )
        building_id = building.id
        await repository.add_chunks(building_id, _chunks("recover-building"))

        recovered_building = await indexer.resume_and_activate(
            building_id,
            embeddings=[[1.0, 0.0], [0.0, 1.0]],
        )
        assert recovered_building.status == "active"
        assert (
            await repository.get_head(building_doc_id)
        ).active_version_id == building_id

        validated = await repository.create_version(
            doc_id=validated_doc_id,
            source_sha256=_source_hash("recover-validated"),
            chunker_version="split-text-v1",
            embedding_model="fake-embed",
            embedding_dimensions=2,
        )
        validated_id = validated.id
        validated_chunks = await repository.add_chunks(
            validated_id,
            _chunks("recover-validated"),
        )
        await store.upsert_version(
            index_version_id=validated_id,
            chunk_ids=[chunk.id for chunk in validated_chunks],
            embeddings=[[1.0, 0.0], [0.0, 1.0]],
            doc_id=validated_doc_id,
        )
        await repository.validate_version(
            validated_id,
            vector_chunk_ids=await store.list_chunk_ids(validated_id),
        )

        recovered_validated = await indexer.resume_and_activate(validated_id)
        assert recovered_validated.status == "active"
        assert (
            await repository.get_head(validated_doc_id)
        ).active_version_id == validated_id
        assert await repository.list_recoverable_versions() == []
    finally:
        await _purge_document(db, validated_doc_id)
        await _purge_document(db, building_doc_id)


@pytest.mark.asyncio
async def test_retention_preserves_active_previous_and_resumes_failed_cleanup(db):
    document = await DocumentRepository(db).create(name="retention-index.txt")
    doc_id = document.id
    store = FakeVersionVectorStore()
    repository = DocumentIndexRepository(db)
    indexer = VersionedDocumentIndexer(db, store)
    try:
        versions = []
        for number in range(1, 4):
            versions.append(
                await indexer.build_and_activate(
                    doc_id=doc_id,
                    source_sha256=_source_hash(f"retention-{number}"),
                    chunker_version="split-text-v1",
                    embedding_model="fake-embed",
                    chunks=[
                        IndexBuildInput(
                            ordinal=1,
                            content=f"retention version {number}",
                        )
                    ],
                    embeddings=[[float(number)]],
                )
            )
        first_id, second_id, third_id = [version.id for version in versions]
        old = utcnow() - timedelta(days=30)
        for version_id in (first_id, second_id):
            version = await repository.get_version(version_id)
            assert version is not None
            version.retired_at = old
        await db.commit()

        deleted = await indexer.cleanup_retired_versions(
            retired_before=utcnow() - timedelta(days=14),
            keep_retired_per_doc=1,
        )
        assert deleted == [first_id]
        assert await repository.get_version(first_id) is None
        head = await repository.get_head(doc_id)
        assert head is not None
        assert head.active_version_id == third_id
        assert head.previous_version_id == second_id

        store.fail_next_delete = True
        with pytest.raises(RuntimeError, match="vector delete"):
            await indexer.delete_inactive_version(second_id)
        pending = await repository.get_version(second_id)
        assert pending is not None and pending.status == "deleting"
        assert (await repository.get_head(doc_id)).active_version_id == third_id

        assert await indexer.resume_pending_deletions() == [second_id]
        assert await repository.get_version(second_id) is None
        assert len(await store.list_chunk_ids(third_id)) == 1
        assert (await repository.get_head(doc_id)).active_version_id == third_id
    finally:
        await _purge_document(db, doc_id)


@pytest.mark.asyncio
async def test_late_older_build_cannot_replace_newer_active_version(db):
    document = await DocumentRepository(db).create(name="stale-build.txt")
    doc_id = document.id
    store = FakeVersionVectorStore()
    repository = DocumentIndexRepository(db)
    indexer = VersionedDocumentIndexer(db, store)
    try:
        older = await repository.create_version(
            doc_id=doc_id,
            source_sha256=_source_hash("older-slow-build"),
            chunker_version="split-text-v1",
            embedding_model="fake-embed",
            embedding_dimensions=1,
        )
        older_id = older.id
        older_chunks = await repository.add_chunks(
            older_id,
            [IndexBuildInput(ordinal=1, content="older slow content")],
        )

        newer = await indexer.build_and_activate(
            doc_id=doc_id,
            source_sha256=_source_hash("newer-fast-build"),
            chunker_version="split-text-v1",
            embedding_model="fake-embed",
            chunks=[IndexBuildInput(ordinal=1, content="newer active content")],
            embeddings=[[2.0]],
        )
        newer_id = newer.id
        await store.upsert_version(
            index_version_id=older_id,
            chunk_ids=[chunk.id for chunk in older_chunks],
            embeddings=[[1.0]],
            doc_id=doc_id,
        )
        await repository.validate_version(
            older_id,
            vector_chunk_ids=await store.list_chunk_ids(older_id),
        )

        with pytest.raises(IndexValidationError, match="stale index build"):
            await repository.activate(older_id)

        head = await repository.get_head(doc_id)
        assert head is not None and head.active_version_id == newer_id
        assert (await repository.get_version(newer_id)).status == "active"
        assert (await repository.get_version(older_id)).status == "validated"
    finally:
        await _purge_document(db, doc_id)


@pytest.mark.asyncio
async def test_staged_chunks_are_immutable_and_hash_validation_fails_closed(db):
    document = await DocumentRepository(db).create(name="immutable-index.txt")
    doc_id = document.id
    repository = DocumentIndexRepository(db)
    try:
        version = await repository.create_version(
            doc_id=doc_id,
            source_sha256=_source_hash("immutable"),
            chunker_version="split-text-v1",
            embedding_model="fake-embed",
            embedding_dimensions=2,
        )
        version_id = version.id
        chunks = await repository.add_chunks(version_id, _chunks("immutable"))
        chunk_ids = [chunk.id for chunk in chunks]

        with pytest.raises(ActiveIndexMutationError, match="immutable"):
            await repository.add_chunks(version_id, _chunks("replacement"))

        chunk = await db.get(DocumentIndexChunk, chunk_ids[0])
        assert chunk is not None
        chunk.content = "tampered after staging"
        await db.commit()

        with pytest.raises(IndexValidationError, match="content hash"):
            await repository.validate_version(
                version_id,
                vector_chunk_ids=chunk_ids,
            )
        assert await repository.get_head(doc_id) is None
    finally:
        await _purge_document(db, doc_id)


@pytest.mark.asyncio
async def test_chunk_provenance_is_persisted_and_tampering_fails_closed(db):
    document = await DocumentRepository(db).create(name="provenance-index.md")
    doc_id = document.id
    store = FakeVersionVectorStore()
    indexer = VersionedDocumentIndexer(db, store)
    repository = DocumentIndexRepository(db)
    try:
        active = await indexer.build_and_activate(
            doc_id=doc_id,
            source_sha256=_source_hash("provenance source"),
            chunker_version="structured-blocks:v1",
            embedding_model="fake-embed",
            chunks=[
                IndexBuildInput(
                    ordinal=1,
                    content="source-backed chunk",
                    token_count=7,
                    heading="Child",
                    source_kind="markdown_block",
                    parser_version="markdown:v1",
                    char_start=24,
                    char_end=43,
                    line_start=4,
                    line_end=4,
                    heading_path=("Root", "Child"),
                )
            ],
            embeddings=[[1.0, 0.0]],
        )
        chunk = (await repository.list_chunks(active.id))[0]
        provenance = await db.get(DocumentIndexChunkProvenance, chunk.id)

        assert provenance is not None
        assert chunk.token_count == 7
        assert provenance.doc_id == doc_id
        assert provenance.source_kind == "markdown_block"
        assert provenance.heading_path_json == ["Root", "Child"]
        assert provenance.provenance_sha256 == provenance_sha256(
            source_kind="markdown_block",
            parser_version="markdown:v1",
            page_start=None,
            page_end=None,
            char_start=24,
            char_end=43,
            line_start=4,
            line_end=4,
            heading_path=("Root", "Child"),
        )

        provenance.heading_path_json = ["Root", "Changed"]
        await db.commit()
        with pytest.raises(IndexValidationError, match="provenance hash"):
            await repository.verify_version_manifest(
                active.id,
                vector_chunk_ids=await store.list_chunk_ids(active.id),
            )
    finally:
        await _purge_document(db, doc_id)


@pytest.mark.asyncio
async def test_versioned_retrieval_uses_active_head_and_legacy_fallback(
    db, monkeypatch
):
    legacy_doc = await DocumentRepository(db).create(name="legacy-source.txt")
    migrated_doc = await DocumentRepository(db).create(name="migrated-source.txt")
    legacy_doc_id = legacy_doc.id
    migrated_doc_id = migrated_doc.id
    chunks = DocChunkRepository(db)
    legacy_chunk = (
        await chunks.add_many(
            legacy_doc_id,
            [{"ordinal": 1, "content": "legacy live content", "bm25_text": "legacy"}],
        )
    )[0]
    stale_chunk = (
        await chunks.add_many(
            migrated_doc_id,
            [{"ordinal": 1, "content": "stale legacy content", "bm25_text": "stale"}],
        )
    )[0]
    store = FakeVersionVectorStore()
    indexer = VersionedDocumentIndexer(db, store)
    repository = DocumentIndexRepository(db)
    try:
        active = await indexer.build_and_activate(
            doc_id=migrated_doc_id,
            source_sha256=_source_hash("new source"),
            chunker_version="split-text-v2",
            embedding_model="fake-embed",
            chunks=[IndexBuildInput(ordinal=1, content="new active content")],
            embeddings=[[1.0, 0.0]],
        )
        active_chunk = (await repository.list_chunks(active.id))[0]

        async def fake_legacy_query(embedding, top_k=5):
            del embedding, top_k
            return [stale_chunk.id, legacy_chunk.id]

        async def fake_versioned_query(
            embedding, *, active_version_ids, top_k=5
        ):
            del embedding, top_k
            assert active.id in active_version_ids
            return [active_chunk.id]

        async def no_bm25(query, terms, limit, filters):
            del query, terms, limit, filters
            return []

        monkeypatch.setattr(hybrid_module.chroma_store, "query", fake_legacy_query)
        monkeypatch.setattr(
            hybrid_module.versioned_chroma_store,
            "query_active",
            fake_versioned_query,
        )
        retriever = HybridRetriever(
            db,
            provider=FakeEmbeddingProvider(),
            use_versioned=True,
        )
        monkeypatch.setattr(retriever, "_bm25_recall", no_bm25)

        results = await retriever.retrieve(
            "content",
            top_k=5,
            filters=RetrievalFilters(),
        )

        assert {result.content for result in results} == {
            "new active content",
            "legacy live content",
        }
        assert "stale legacy content" not in {result.content for result in results}
        active_result = next(
            result for result in results if result.content == "new active content"
        )
        legacy_result = next(
            result for result in results if result.content == "legacy live content"
        )
        assert active_result.index_version_id == active.id
        assert active_result.source_kind == "unspecified"
        assert active_result.parser_version == "legacy-index:v1"
        assert legacy_result.index_version_id is None
    finally:
        await _purge_document(db, migrated_doc_id)
        await _purge_document(db, legacy_doc_id)


@pytest.mark.asyncio
async def test_index_version_api_exposes_head_chunks_and_validated_rollback(
    client, db, monkeypatch
):
    document = await DocumentRepository(db).create(name="version-api.txt")
    doc_id = document.id
    store = FakeVersionVectorStore()
    indexer = VersionedDocumentIndexer(db, store)
    repository = DocumentIndexRepository(db)
    try:
        first = await indexer.build_and_activate(
            doc_id=doc_id,
            source_sha256=_source_hash("api-v1"),
            chunker_version="split-text-v1",
            embedding_model="fake-embed",
            chunks=[IndexBuildInput(ordinal=1, content="api version one")],
            embeddings=[[1.0]],
        )
        second = await indexer.build_and_activate(
            doc_id=doc_id,
            source_sha256=_source_hash("api-v2"),
            chunker_version="split-text-v2",
            embedding_model="fake-embed",
            chunks=[
                IndexBuildInput(
                    ordinal=1,
                    content="api version two",
                    heading="API source",
                    source_kind="pdf_page",
                    parser_version="pypdf:v1",
                    page_start=7,
                    page_end=7,
                    char_start=100,
                    char_end=115,
                    line_start=2,
                    line_end=2,
                    heading_path=("API source",),
                )
            ],
            embeddings=[[2.0]],
        )
        second_chunk = (await repository.list_chunks(second.id))[0]
        monkeypatch.setattr(document_routes, "versioned_chroma_store", store)

        versions_response = await client.get(f"/documents/{doc_id}/index-versions")
        assert versions_response.status_code == 200, versions_response.text
        assert [item["status"] for item in versions_response.json()] == [
            "active",
            "retired",
        ]
        head_response = await client.get(f"/documents/{doc_id}/index-head")
        assert head_response.status_code == 200, head_response.text
        assert head_response.json()["active_version_id"] == second.id
        chunk_response = await client.get(f"/index-chunks/{second_chunk.id}")
        assert chunk_response.status_code == 200, chunk_response.text
        assert chunk_response.json()["content_sha256"] == second_chunk.content_sha256
        assert chunk_response.json()["page_start"] == 7
        assert chunk_response.json()["page_end"] == 7
        assert chunk_response.json()["heading_path"] == ["API source"]
        assert chunk_response.json()["source_kind"] == "pdf_page"
        assert chunk_response.json()["parser_version"] == "pypdf:v1"

        rollback_response = await client.post(
            f"/documents/{doc_id}/index-rollback",
            json={"target_version_id": first.id},
        )
        assert rollback_response.status_code == 200, rollback_response.text
        assert rollback_response.json()["id"] == first.id
        assert rollback_response.json()["status"] == "active"
    finally:
        await _purge_document(db, doc_id)


@pytest.mark.asyncio
async def test_reindex_worker_uses_non_destructive_versioned_branch(monkeypatch):
    calls: list[dict] = []

    async def fake_import_document(doc_id, file_path, **kwargs):
        calls.append({"doc_id": doc_id, "file_path": file_path, **kwargs})

    monkeypatch.setattr(
        importer_module.settings,
        "versioned_rag_indexing_enabled",
        True,
    )
    monkeypatch.setattr(importer_module, "import_document", fake_import_document)

    await importer_module.reindex_document(42, "F:/safe/source.md")

    assert calls == [
        {
            "doc_id": 42,
            "file_path": "F:/safe/source.md",
            "activity_kind": "reindex",
            "use_versioned": True,
        }
    ]


@pytest.mark.parametrize(
    ("revision", "expected"),
    [
        (None, False),
        ("0019", False),
        ("0020", True),
        ("0021", True),
        ("20", False),
        ("head", False),
    ],
)
def test_structured_versioned_rag_requires_schema_0020_or_later(
    revision, expected
):
    assert importer_module.schema_supports_structured_versioned_rag(revision) is expected


@pytest.mark.asyncio
async def test_failed_versioned_reindex_preserves_ready_document_projection(
    client, db, fresh_session, monkeypatch
):
    del client
    document = await DocumentRepository(db).create(name="preserved-reindex.txt")
    doc_id = document.id
    await DocumentRepository(db).update_status(
        doc_id,
        status="ready",
        chunk_count=3,
        embedding_model="stable-model",
    )

    async def fail_index(doc_id, file_path):
        del doc_id, file_path
        raise RuntimeError("injected staging failure")

    async def no_side_effect(*args, **kwargs):
        del args, kwargs

    monkeypatch.setattr(importer_module, "_index_core_versioned", fail_index)
    monkeypatch.setattr(importer_module, "_sync_activity", no_side_effect)
    monkeypatch.setattr(importer_module, "_notify", no_side_effect)
    try:
        await importer_module.import_document(
            doc_id,
            "F:/safe/source.md",
            activity_kind="reindex",
            use_versioned=True,
        )

        preserved = await fresh_session.get(Document, doc_id)
        assert preserved is not None
        assert preserved.status == "ready"
        assert preserved.chunk_count == 3
        assert preserved.embedding_model == "stable-model"
    finally:
        await _purge_document(db, doc_id)
