"""Side-by-side RAG index builds with validation and atomic activation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Document,
    DocumentIndexChunk,
    DocumentIndexChunkProvenance,
    DocumentIndexHead,
    DocumentIndexVersion,
)
from .timeutil import utcnow


class IndexValidationError(RuntimeError):
    """A staged index is incomplete or does not match its declared manifest."""


class ActiveIndexMutationError(RuntimeError):
    """An operation would mutate or remove the currently served index."""


class VersionVectorStore(Protocol):
    async def upsert_version(
        self,
        *,
        index_version_id: str,
        chunk_ids: list[int],
        embeddings: list[list[float]],
        doc_id: int,
    ) -> None: ...

    async def list_chunk_ids(self, index_version_id: str) -> list[int]: ...

    async def delete_version(self, index_version_id: str) -> None: ...


def content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def chunk_manifest_sha256(chunks: Sequence[DocumentIndexChunk]) -> str:
    digest = hashlib.sha256()
    for chunk in sorted(chunks, key=lambda item: item.ordinal):
        digest.update(f"{chunk.ordinal}:{chunk.content_sha256}\n".encode("ascii"))
    return digest.hexdigest()


def provenance_sha256(
    *,
    source_kind: str,
    parser_version: str,
    page_start: int | None,
    page_end: int | None,
    char_start: int | None,
    char_end: int | None,
    line_start: int | None,
    line_end: int | None,
    heading_path: Sequence[str],
) -> str:
    heading_value = (
        json.dumps(list(heading_path), ensure_ascii=False, separators=(",", ":"))
        if heading_path
        else ""
    )
    values = (
        source_kind,
        parser_version,
        page_start,
        page_end,
        char_start,
        char_end,
        line_start,
        line_end,
        heading_value,
    )
    canonical = "\x1f".join("" if value is None else str(value) for value in values)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IndexBuildInput:
    ordinal: int
    content: str
    token_count: int | None = None
    heading: str | None = None
    keywords: list | None = None
    bm25_text: str | None = None
    source_kind: str = "unspecified"
    parser_version: str = "legacy-index:v1"
    page_start: int | None = None
    page_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    heading_path: tuple[str, ...] = ()


class DocumentIndexRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_version(
        self,
        *,
        doc_id: int,
        source_sha256: str,
        chunker_version: str,
        embedding_model: str,
        embedding_dimensions: int | None,
    ) -> DocumentIndexVersion:
        if len(source_sha256) != 64:
            raise ValueError("source_sha256 must be a SHA-256 hex digest")
        if not chunker_version.strip() or not embedding_model.strip():
            raise ValueError("chunker_version and embedding_model are required")
        document = (
            await self.db.execute(
                select(Document).where(Document.id == doc_id).with_for_update()
            )
        ).scalar_one_or_none()
        if document is None:
            await self.db.rollback()
            raise LookupError(f"document does not exist: {doc_id}")
        latest = await self.db.scalar(
            select(func.max(DocumentIndexVersion.version_number)).where(
                DocumentIndexVersion.doc_id == doc_id
            )
        )
        version = DocumentIndexVersion(
            id=str(uuid4()),
            doc_id=doc_id,
            version_number=int(latest or 0) + 1,
            status="building",
            source_sha256=source_sha256.lower(),
            chunker_version=chunker_version.strip(),
            embedding_model=embedding_model.strip(),
            embedding_dimensions=embedding_dimensions,
            chunk_count=0,
            vector_count=0,
            build_started_at=utcnow(),
        )
        self.db.add(version)
        await self.db.commit()
        await self.db.refresh(version)
        return version

    async def get_version(self, version_id: str) -> DocumentIndexVersion | None:
        return await self.db.get(DocumentIndexVersion, version_id)

    async def list_versions(self, doc_id: int) -> list[DocumentIndexVersion]:
        result = await self.db.execute(
            select(DocumentIndexVersion)
            .where(DocumentIndexVersion.doc_id == doc_id)
            .order_by(DocumentIndexVersion.version_number.desc())
        )
        return list(result.scalars().all())

    async def list_recoverable_versions(
        self, *, limit: int = 100
    ) -> list[DocumentIndexVersion]:
        result = await self.db.execute(
            select(DocumentIndexVersion)
            .where(DocumentIndexVersion.status.in_(["building", "validated"]))
            .order_by(DocumentIndexVersion.build_started_at.asc())
            .limit(max(1, min(limit, 1_000)))
        )
        return list(result.scalars().all())

    async def list_retention_candidates(
        self,
        *,
        retired_before: datetime,
        keep_retired_per_doc: int = 1,
        limit: int = 100,
    ) -> list[DocumentIndexVersion]:
        keep = max(0, keep_retired_per_doc)
        heads = (
            await self.db.execute(
                select(
                    DocumentIndexHead.doc_id,
                    DocumentIndexHead.active_version_id,
                    DocumentIndexHead.previous_version_id,
                )
            )
        ).all()
        protected_ids = {
            version_id
            for _, active_id, previous_id in heads
            for version_id in (active_id, previous_id)
            if version_id is not None
        }
        protected_per_doc = {
            int(doc_id): int(previous_id is not None)
            for doc_id, _, previous_id in heads
        }
        rows = (
            await self.db.execute(
                select(DocumentIndexVersion)
                .where(
                    DocumentIndexVersion.status == "retired",
                    DocumentIndexVersion.retired_at.is_not(None),
                    DocumentIndexVersion.retired_at < retired_before,
                )
                .order_by(
                    DocumentIndexVersion.doc_id.asc(),
                    DocumentIndexVersion.version_number.desc(),
                )
            )
        ).scalars().all()
        retained_counts = dict(protected_per_doc)
        candidates: list[DocumentIndexVersion] = []
        for version in rows:
            if version.id in protected_ids:
                continue
            retained = retained_counts.get(version.doc_id, 0)
            if retained < keep:
                retained_counts[version.doc_id] = retained + 1
                continue
            candidates.append(version)
            if len(candidates) >= max(1, min(limit, 1_000)):
                break
        return candidates

    async def add_chunks(
        self,
        version_id: str,
        chunks: Sequence[IndexBuildInput],
    ) -> list[DocumentIndexChunk]:
        version = (
            await self.db.execute(
                select(DocumentIndexVersion)
                .where(DocumentIndexVersion.id == version_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if version is None:
            await self.db.rollback()
            raise LookupError(f"index version does not exist: {version_id}")
        if version.status != "building":
            await self.db.rollback()
            raise ActiveIndexMutationError(
                f"cannot add chunks to index in status {version.status}"
            )
        existing_count = await self.db.scalar(
            select(func.count(DocumentIndexChunk.id)).where(
                DocumentIndexChunk.index_version_id == version_id
            )
        )
        if existing_count:
            await self.db.rollback()
            raise ActiveIndexMutationError("staged index chunks are immutable")
        if not chunks:
            await self.db.rollback()
            raise IndexValidationError("an index must contain at least one chunk")
        ordinals = [chunk.ordinal for chunk in chunks]
        if ordinals != list(range(1, len(chunks) + 1)):
            await self.db.rollback()
            raise IndexValidationError("chunk ordinals must be contiguous and start at 1")
        if any(not chunk.content.strip() for chunk in chunks):
            await self.db.rollback()
            raise IndexValidationError("index chunks cannot be empty")
        try:
            for chunk in chunks:
                self._validate_provenance_input(chunk)
        except IndexValidationError:
            await self.db.rollback()
            raise
        records = [
            DocumentIndexChunk(
                index_version_id=version.id,
                doc_id=version.doc_id,
                ordinal=chunk.ordinal,
                content=chunk.content,
                content_sha256=content_sha256(chunk.content),
                token_count=chunk.token_count,
                heading=chunk.heading,
                keywords_json=chunk.keywords,
                bm25_text=chunk.bm25_text or chunk.content,
            )
            for chunk in chunks
        ]
        self.db.add_all(records)
        await self.db.flush()
        provenance_records = [
            DocumentIndexChunkProvenance(
                chunk_id=record.id,
                doc_id=record.doc_id,
                source_kind=chunk.source_kind,
                parser_version=chunk.parser_version,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
                heading_path_json=list(chunk.heading_path) or None,
                provenance_sha256=provenance_sha256(
                    source_kind=chunk.source_kind,
                    parser_version=chunk.parser_version,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    line_start=chunk.line_start,
                    line_end=chunk.line_end,
                    heading_path=chunk.heading_path,
                ),
            )
            for record, chunk in zip(records, chunks, strict=True)
        ]
        self.db.add_all(provenance_records)
        version.chunk_count = len(records)
        await self.db.commit()
        for record in records:
            await self.db.refresh(record)
        return records

    @staticmethod
    def _validate_provenance_input(chunk: IndexBuildInput) -> None:
        if not chunk.source_kind.strip() or len(chunk.source_kind) > 32:
            raise IndexValidationError("source_kind must contain 1..32 characters")
        if not chunk.parser_version.strip() or len(chunk.parser_version) > 64:
            raise IndexValidationError("parser_version must contain 1..64 characters")
        for label, start, end, minimum in (
            ("page", chunk.page_start, chunk.page_end, 1),
            ("char", chunk.char_start, chunk.char_end, 0),
            ("line", chunk.line_start, chunk.line_end, 1),
        ):
            if (start is None) != (end is None):
                raise IndexValidationError(f"{label} range must provide both endpoints")
            if start is not None and (start < minimum or end < start):
                raise IndexValidationError(f"{label} range is invalid")
        if (
            chunk.char_start is not None
            and chunk.char_end - chunk.char_start != len(chunk.content)
        ):
            raise IndexValidationError(
                "character range must match the stored chunk content length"
            )
        if len(chunk.heading_path) > 16 or any(
            not item.strip() or len(item) > 512 for item in chunk.heading_path
        ):
            raise IndexValidationError("heading_path is invalid")

    async def list_chunks(self, version_id: str) -> list[DocumentIndexChunk]:
        result = await self.db.execute(
            select(DocumentIndexChunk)
            .where(DocumentIndexChunk.index_version_id == version_id)
            .order_by(DocumentIndexChunk.ordinal.asc())
        )
        return list(result.scalars().all())

    async def get_chunks_by_ids(
        self, chunk_ids: Sequence[int]
    ) -> dict[int, DocumentIndexChunk]:
        if not chunk_ids:
            return {}
        result = await self.db.execute(
            select(DocumentIndexChunk).where(DocumentIndexChunk.id.in_(chunk_ids))
        )
        return {chunk.id: chunk for chunk in result.scalars().all()}

    async def get_provenance_by_chunk_ids(
        self, chunk_ids: Sequence[int]
    ) -> dict[int, DocumentIndexChunkProvenance]:
        if not chunk_ids:
            return {}
        result = await self.db.execute(
            select(DocumentIndexChunkProvenance).where(
                DocumentIndexChunkProvenance.chunk_id.in_(chunk_ids)
            )
        )
        return {item.chunk_id: item for item in result.scalars().all()}

    async def validate_version(
        self,
        version_id: str,
        *,
        vector_chunk_ids: Sequence[int],
    ) -> DocumentIndexVersion:
        version = (
            await self.db.execute(
                select(DocumentIndexVersion)
                .where(DocumentIndexVersion.id == version_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if version is None:
            await self.db.rollback()
            raise LookupError(f"index version does not exist: {version_id}")
        if version.status not in {"building", "validated"}:
            await self.db.rollback()
            raise IndexValidationError(
                f"index in status {version.status} cannot be validated"
            )
        chunks = (
            await self.db.execute(
                select(DocumentIndexChunk)
                .where(DocumentIndexChunk.index_version_id == version_id)
                .order_by(DocumentIndexChunk.ordinal.asc())
            )
        ).scalars().all()
        if not chunks:
            await self.db.rollback()
            raise IndexValidationError("staged index has no chunks")
        expected_ids = {chunk.id for chunk in chunks}
        actual_ids = set(vector_chunk_ids)
        if actual_ids != expected_ids:
            await self.db.rollback()
            missing = len(expected_ids - actual_ids)
            unexpected = len(actual_ids - expected_ids)
            raise IndexValidationError(
                f"vector manifest mismatch: missing={missing}, unexpected={unexpected}"
            )
        if [chunk.ordinal for chunk in chunks] != list(range(1, len(chunks) + 1)):
            await self.db.rollback()
            raise IndexValidationError("stored chunk ordinals are not contiguous")
        provenance = await self.get_provenance_by_chunk_ids(
            [chunk.id for chunk in chunks]
        )
        if set(provenance) != {chunk.id for chunk in chunks}:
            await self.db.rollback()
            raise IndexValidationError("stored chunks do not have complete provenance")
        for chunk in chunks:
            if chunk.doc_id != version.doc_id:
                await self.db.rollback()
                raise IndexValidationError("chunk document does not match index version")
            if content_sha256(chunk.content) != chunk.content_sha256:
                await self.db.rollback()
                raise IndexValidationError("stored chunk content hash mismatch")
            try:
                self._validate_provenance_record(chunk, provenance[chunk.id])
            except IndexValidationError:
                await self.db.rollback()
                raise
        manifest = chunk_manifest_sha256(chunks)
        if version.status == "validated" and version.manifest_sha256 != manifest:
            await self.db.rollback()
            raise IndexValidationError("validated index manifest changed")
        version.chunk_count = len(chunks)
        version.vector_count = len(actual_ids)
        version.manifest_sha256 = manifest
        version.status = "validated"
        version.validated_at = version.validated_at or utcnow()
        version.failure_code = None
        version.error_message = None
        await self.db.commit()
        await self.db.refresh(version)
        return version

    async def mark_failed(
        self,
        version_id: str,
        *,
        failure_code: str,
        error_message: str,
    ) -> DocumentIndexVersion | None:
        version = (
            await self.db.execute(
                select(DocumentIndexVersion)
                .where(DocumentIndexVersion.id == version_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if version is None:
            await self.db.rollback()
            return None
        if version.status == "active":
            await self.db.rollback()
            raise ActiveIndexMutationError("cannot mark the active index as failed")
        version.status = "failed"
        version.failure_code = failure_code[:64]
        version.error_message = error_message[:1_000]
        await self.db.commit()
        await self.db.refresh(version)
        return version

    async def reopen_failed(self, version_id: str) -> DocumentIndexVersion:
        version = (
            await self.db.execute(
                select(DocumentIndexVersion)
                .where(DocumentIndexVersion.id == version_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if version is None:
            await self.db.rollback()
            raise LookupError(f"index version does not exist: {version_id}")
        if version.status != "failed":
            await self.db.rollback()
            raise ActiveIndexMutationError(
                f"only failed indexes can be reopened, got {version.status}"
            )
        version.status = "building"
        version.vector_count = 0
        version.manifest_sha256 = None
        version.validated_at = None
        version.failure_code = None
        version.error_message = None
        await self.db.commit()
        await self.db.refresh(version)
        return version

    async def verify_version_manifest(
        self,
        version_id: str,
        *,
        vector_chunk_ids: Sequence[int],
    ) -> DocumentIndexVersion:
        """Recheck an already validated version before rollback or serving it."""

        version = await self.get_version(version_id)
        if version is None:
            raise LookupError(f"index version does not exist: {version_id}")
        if version.status not in {"validated", "active", "retired"}:
            raise IndexValidationError(
                f"index in status {version.status} has no valid manifest"
            )
        chunks = await self.list_chunks(version_id)
        expected_ids = {chunk.id for chunk in chunks}
        if expected_ids != set(vector_chunk_ids):
            raise IndexValidationError("stored vectors no longer match the index manifest")
        if len(chunks) != version.chunk_count or len(expected_ids) != version.vector_count:
            raise IndexValidationError("stored index counts no longer match the manifest")
        if any(content_sha256(chunk.content) != chunk.content_sha256 for chunk in chunks):
            raise IndexValidationError("stored chunk content hash mismatch")
        provenance = await self.get_provenance_by_chunk_ids(
            [chunk.id for chunk in chunks]
        )
        if set(provenance) != {chunk.id for chunk in chunks}:
            raise IndexValidationError("stored chunks do not have complete provenance")
        for chunk in chunks:
            self._validate_provenance_record(chunk, provenance[chunk.id])
        if chunk_manifest_sha256(chunks) != version.manifest_sha256:
            raise IndexValidationError("stored chunk manifest hash mismatch")
        return version

    @staticmethod
    def _validate_provenance_record(
        chunk: DocumentIndexChunk,
        provenance: DocumentIndexChunkProvenance,
    ) -> None:
        if provenance.doc_id != chunk.doc_id:
            raise IndexValidationError("chunk provenance document mismatch")
        if not provenance.source_kind.strip() or len(provenance.source_kind) > 32:
            raise IndexValidationError("stored chunk source_kind is invalid")
        if not provenance.parser_version.strip() or len(provenance.parser_version) > 64:
            raise IndexValidationError("stored chunk parser_version is invalid")
        for label, start, end, minimum in (
            ("page", provenance.page_start, provenance.page_end, 1),
            ("char", provenance.char_start, provenance.char_end, 0),
            ("line", provenance.line_start, provenance.line_end, 1),
        ):
            if (start is None) != (end is None):
                raise IndexValidationError(f"stored chunk {label} range is incomplete")
            if start is not None and (start < minimum or end < start):
                raise IndexValidationError(f"stored chunk {label} range is invalid")
        if (
            provenance.char_start is not None
            and provenance.char_end - provenance.char_start != len(chunk.content)
        ):
            raise IndexValidationError(
                "stored chunk character range does not match its content"
            )
        heading_path = tuple(provenance.heading_path_json or [])
        if len(heading_path) > 16 or any(
            not isinstance(item, str)
            or not item.strip()
            or len(item) > 512
            for item in heading_path
        ):
            raise IndexValidationError("stored chunk heading_path is invalid")
        expected = provenance_sha256(
            source_kind=provenance.source_kind,
            parser_version=provenance.parser_version,
            page_start=provenance.page_start,
            page_end=provenance.page_end,
            char_start=provenance.char_start,
            char_end=provenance.char_end,
            line_start=provenance.line_start,
            line_end=provenance.line_end,
            heading_path=heading_path,
        )
        if expected != provenance.provenance_sha256:
            raise IndexValidationError("stored chunk provenance hash mismatch")

    async def get_head(self, doc_id: int) -> DocumentIndexHead | None:
        return await self.db.get(DocumentIndexHead, doc_id)

    async def list_active_version_ids(self) -> list[str]:
        result = await self.db.scalars(
            select(DocumentIndexHead.active_version_id).where(
                DocumentIndexHead.active_version_id.is_not(None)
            )
        )
        return [version_id for version_id in result if version_id]

    async def list_active_heads(self) -> dict[int, str]:
        result = await self.db.execute(
            select(
                DocumentIndexHead.doc_id,
                DocumentIndexHead.active_version_id,
            ).where(DocumentIndexHead.active_version_id.is_not(None))
        )
        return {
            int(doc_id): str(version_id)
            for doc_id, version_id in result.all()
            if version_id is not None
        }

    async def _switch_locked(
        self,
        *,
        document: Document,
        head: DocumentIndexHead,
        target: DocumentIndexVersion,
        allow_retired: bool,
    ) -> DocumentIndexVersion:
        allowed = {"validated", "active"}
        if allow_retired:
            allowed.add("retired")
        if target.status not in allowed:
            raise IndexValidationError(
                f"index in status {target.status} cannot be activated"
            )
        if target.doc_id != document.id:
            raise IndexValidationError("index version belongs to another document")
        if not target.manifest_sha256 or target.chunk_count <= 0:
            raise IndexValidationError("index version has not passed manifest validation")
        if target.chunk_count != target.vector_count:
            raise IndexValidationError("index chunk/vector counts differ")
        if head.active_version_id == target.id:
            return target
        previous_id = head.active_version_id
        if previous_id:
            previous = (
                await self.db.execute(
                    select(DocumentIndexVersion)
                    .where(DocumentIndexVersion.id == previous_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if previous is not None:
                if (
                    not allow_retired
                    and previous.version_number > target.version_number
                ):
                    raise IndexValidationError(
                        "stale index build cannot replace a newer active version"
                    )
                previous.status = "retired"
                previous.retired_at = utcnow()
        now = utcnow()
        target.status = "active"
        target.activated_at = now
        target.retired_at = None
        head.previous_version_id = previous_id
        head.active_version_id = target.id
        head.lock_version += 1
        head.switched_at = now
        document.status = "ready"
        document.error_message = None
        document.chunk_count = target.chunk_count
        document.embedding_model = target.embedding_model
        document.indexed_at = now
        return target

    async def activate(self, version_id: str) -> DocumentIndexVersion:
        target = (
            await self.db.execute(
                select(DocumentIndexVersion)
                .where(DocumentIndexVersion.id == version_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if target is None:
            await self.db.rollback()
            raise LookupError(f"index version does not exist: {version_id}")
        document = (
            await self.db.execute(
                select(Document)
                .where(Document.id == target.doc_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if document is None:
            await self.db.rollback()
            raise LookupError(f"document does not exist: {target.doc_id}")
        head = (
            await self.db.execute(
                select(DocumentIndexHead)
                .where(DocumentIndexHead.doc_id == target.doc_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if head is None:
            head = DocumentIndexHead(doc_id=target.doc_id, lock_version=0)
            self.db.add(head)
            await self.db.flush()
        try:
            activated = await self._switch_locked(
                document=document,
                head=head,
                target=target,
                allow_retired=False,
            )
        except Exception:
            await self.db.rollback()
            raise
        await self.db.commit()
        await self.db.refresh(activated)
        return activated

    async def rollback(
        self, doc_id: int, *, target_version_id: str | None = None
    ) -> DocumentIndexVersion:
        document = (
            await self.db.execute(
                select(Document).where(Document.id == doc_id).with_for_update()
            )
        ).scalar_one_or_none()
        if document is None:
            await self.db.rollback()
            raise LookupError(f"document does not exist: {doc_id}")
        head = (
            await self.db.execute(
                select(DocumentIndexHead)
                .where(DocumentIndexHead.doc_id == doc_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if head is None or head.active_version_id is None:
            await self.db.rollback()
            raise LookupError("document has no active versioned index")
        target_id = target_version_id or head.previous_version_id
        if not target_id:
            await self.db.rollback()
            raise LookupError("document has no rollback index version")
        target = (
            await self.db.execute(
                select(DocumentIndexVersion)
                .where(DocumentIndexVersion.id == target_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if target is None:
            await self.db.rollback()
            raise LookupError(f"rollback index does not exist: {target_id}")
        try:
            activated = await self._switch_locked(
                document=document,
                head=head,
                target=target,
                allow_retired=True,
            )
        except Exception:
            await self.db.rollback()
            raise
        await self.db.commit()
        await self.db.refresh(activated)
        return activated

    async def prepare_inactive_deletion(self, version_id: str) -> bool:
        version = (
            await self.db.execute(
                select(DocumentIndexVersion)
                .where(DocumentIndexVersion.id == version_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if version is None:
            await self.db.rollback()
            return False
        head = (
            await self.db.execute(
                select(DocumentIndexHead)
                .where(DocumentIndexHead.doc_id == version.doc_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if head is not None and head.active_version_id == version_id:
            await self.db.rollback()
            raise ActiveIndexMutationError("cannot delete the active index version")
        if version.status == "deleting":
            await self.db.commit()
            return True
        if head is not None and head.previous_version_id == version_id:
            head.previous_version_id = None
        version.status = "deleting"
        await self.db.commit()
        return True

    async def finalize_inactive_deletion(self, version_id: str) -> bool:
        version = (
            await self.db.execute(
                select(DocumentIndexVersion)
                .where(DocumentIndexVersion.id == version_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if version is None:
            await self.db.rollback()
            return False
        head = (
            await self.db.execute(
                select(DocumentIndexHead)
                .where(DocumentIndexHead.doc_id == version.doc_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if head is not None and head.active_version_id == version_id:
            await self.db.rollback()
            raise ActiveIndexMutationError("cannot delete the active index version")
        if version.status != "deleting":
            await self.db.rollback()
            raise ActiveIndexMutationError(
                f"index must be claimed for deletion, got {version.status}"
            )
        await self.db.delete(version)
        await self.db.commit()
        return True

    async def list_deleting_versions(
        self, *, limit: int = 100
    ) -> list[DocumentIndexVersion]:
        result = await self.db.execute(
            select(DocumentIndexVersion)
            .where(DocumentIndexVersion.status == "deleting")
            .order_by(DocumentIndexVersion.updated_at.asc())
            .limit(max(1, min(limit, 1_000)))
        )
        return list(result.scalars().all())


class VersionedDocumentIndexer:
    """Coordinate DB staging, vector validation and a single atomic head switch."""

    def __init__(self, db: AsyncSession, vector_store: VersionVectorStore) -> None:
        self.repository = DocumentIndexRepository(db)
        self.vector_store = vector_store

    async def build_and_activate(
        self,
        *,
        doc_id: int,
        source_sha256: str,
        chunker_version: str,
        embedding_model: str,
        chunks: Sequence[IndexBuildInput],
        embeddings: list[list[float]],
    ) -> DocumentIndexVersion:
        if len(chunks) != len(embeddings):
            raise IndexValidationError("embedding count does not match chunk count")
        dimensions = {len(vector) for vector in embeddings}
        if not embeddings or len(dimensions) != 1 or 0 in dimensions:
            raise IndexValidationError("embeddings must share one non-zero dimension")
        version: DocumentIndexVersion | None = None
        version_id: str | None = None
        try:
            version = await self.repository.create_version(
                doc_id=doc_id,
                source_sha256=source_sha256,
                chunker_version=chunker_version,
                embedding_model=embedding_model,
                embedding_dimensions=next(iter(dimensions)),
            )
            version_id = version.id
            records = await self.repository.add_chunks(version_id, chunks)
            await self.vector_store.upsert_version(
                index_version_id=version_id,
                chunk_ids=[record.id for record in records],
                embeddings=embeddings,
                doc_id=doc_id,
            )
            vector_ids = await self.vector_store.list_chunk_ids(version_id)
            await self.repository.validate_version(
                version_id,
                vector_chunk_ids=vector_ids,
            )
            return await self.repository.activate(version_id)
        except Exception as exc:
            if version_id is not None:
                failure_code = (
                    "validation_failed"
                    if isinstance(exc, IndexValidationError)
                    else "build_failed"
                )
                await self.repository.mark_failed(
                    version_id,
                    failure_code=failure_code,
                    error_message=str(exc) or exc.__class__.__name__,
                )
            raise

    async def rollback(
        self, doc_id: int, *, target_version_id: str | None = None
    ) -> DocumentIndexVersion:
        target_id = target_version_id
        if target_id is None:
            head = await self.repository.get_head(doc_id)
            if head is None or not head.previous_version_id:
                raise LookupError("document has no rollback index version")
            target_id = head.previous_version_id
        vector_ids = await self.vector_store.list_chunk_ids(target_id)
        await self.repository.verify_version_manifest(
            target_id,
            vector_chunk_ids=vector_ids,
        )
        return await self.repository.rollback(
            doc_id,
            target_version_id=target_id,
        )

    async def resume_and_activate(
        self,
        version_id: str,
        *,
        embeddings: list[list[float]] | None = None,
        retry_failed: bool = False,
    ) -> DocumentIndexVersion:
        version = await self.repository.get_version(version_id)
        if version is None:
            raise LookupError(f"index version does not exist: {version_id}")
        status = version.status
        if status == "active":
            return version
        if status == "failed":
            if not retry_failed:
                raise ActiveIndexMutationError(
                    "failed indexes require an explicit retry request"
                )
            version = await self.repository.reopen_failed(version_id)
            status = version.status
        if status not in {"building", "validated"}:
            raise ActiveIndexMutationError(
                f"index in status {status} cannot be resumed"
            )
        try:
            chunks = await self.repository.list_chunks(version_id)
            if not chunks:
                raise IndexValidationError("recoverable index has no persisted chunks")
            if status == "building":
                if embeddings is None or len(embeddings) != len(chunks):
                    raise IndexValidationError(
                        "recovery embeddings do not match persisted chunks"
                    )
                dimensions = {len(vector) for vector in embeddings}
                if len(dimensions) != 1 or 0 in dimensions:
                    raise IndexValidationError(
                        "recovery embeddings must share one non-zero dimension"
                    )
                dimension = next(iter(dimensions))
                if (
                    version.embedding_dimensions is not None
                    and dimension != version.embedding_dimensions
                ):
                    raise IndexValidationError(
                        "recovery embedding dimension changed"
                    )
                await self.vector_store.upsert_version(
                    index_version_id=version_id,
                    chunk_ids=[chunk.id for chunk in chunks],
                    embeddings=embeddings,
                    doc_id=version.doc_id,
                )
                vector_ids = await self.vector_store.list_chunk_ids(version_id)
                await self.repository.validate_version(
                    version_id,
                    vector_chunk_ids=vector_ids,
                )
            else:
                vector_ids = await self.vector_store.list_chunk_ids(version_id)
                await self.repository.verify_version_manifest(
                    version_id,
                    vector_chunk_ids=vector_ids,
                )
            return await self.repository.activate(version_id)
        except Exception as exc:
            await self.repository.mark_failed(
                version_id,
                failure_code="recovery_failed",
                error_message=str(exc) or exc.__class__.__name__,
            )
            raise

    async def delete_inactive_version(self, version_id: str) -> bool:
        claimed = await self.repository.prepare_inactive_deletion(version_id)
        if not claimed:
            return False
        # The DB status claim makes the version impossible to activate before
        # vectors are removed. If vector deletion fails, the durable `deleting`
        # row is picked up by startup cleanup instead of becoming an orphan.
        await self.vector_store.delete_version(version_id)
        return await self.repository.finalize_inactive_deletion(version_id)

    async def resume_pending_deletions(self, *, limit: int = 100) -> list[str]:
        pending = await self.repository.list_deleting_versions(limit=limit)
        deleted: list[str] = []
        for version in pending:
            version_id = version.id
            await self.vector_store.delete_version(version_id)
            if await self.repository.finalize_inactive_deletion(version_id):
                deleted.append(version_id)
        return deleted

    async def cleanup_retired_versions(
        self,
        *,
        retired_before: datetime,
        keep_retired_per_doc: int = 1,
        limit: int = 100,
    ) -> list[str]:
        candidates = await self.repository.list_retention_candidates(
            retired_before=retired_before,
            keep_retired_per_doc=keep_retired_per_doc,
            limit=limit,
        )
        deleted: list[str] = []
        for candidate in candidates:
            version_id = candidate.id
            if await self.delete_inactive_version(version_id):
                deleted.append(version_id)
        return deleted
