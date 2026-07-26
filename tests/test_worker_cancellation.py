"""Shutdown cancellation must leave retryable, truthful worker state."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


class _SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


def _session_factory() -> _SessionContext:
    return _SessionContext()


@pytest.mark.asyncio
async def test_import_cancel_marks_document_and_activity_failed(monkeypatch):
    import personal_assistant.workers.importer as importer

    document_updates: list[dict] = []
    activity_updates: list[dict] = []
    started = asyncio.Event()
    never_finish = asyncio.Event()

    class FakeDocumentRepository:
        def __init__(self, db) -> None:
            pass

        async def get(self, doc_id: int):
            return SimpleNamespace(id=doc_id, name="cancelled.pdf")

        async def update_status(self, doc_id: int, **values) -> None:
            document_updates.append({"doc_id": doc_id, **values})

    async def fake_sync_activity(
        activity_kind: str,
        doc_id: int,
        doc_name: str,
        doc_status: str,
        error_message: str | None = None,
    ) -> None:
        activity_updates.append(
            {
                "kind": activity_kind,
                "doc_id": doc_id,
                "name": doc_name,
                "status": doc_status,
                "error": error_message,
            }
        )

    async def blocked_index(doc_id: int, file_path: str) -> int:
        started.set()
        await never_finish.wait()
        return 0

    monkeypatch.setattr(importer, "async_session_factory", _session_factory)
    monkeypatch.setattr(importer, "DocumentRepository", FakeDocumentRepository)
    monkeypatch.setattr(importer, "_sync_activity", fake_sync_activity)
    monkeypatch.setattr(importer, "_index_core", blocked_index)

    task = asyncio.create_task(importer.import_document(42, "cancelled.pdf"))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [item["status"] for item in document_updates] == ["processing", "failed"]
    assert [item["status"] for item in activity_updates] == ["processing", "failed"]
    assert "可重试" in document_updates[-1]["error_message"]
    assert "可重试" in activity_updates[-1]["error"]


@pytest.mark.asyncio
async def test_ocr_cancel_marks_processing_job_failed(monkeypatch):
    import personal_assistant.workers.ocr as ocr

    marks: list[dict] = []
    started = asyncio.Event()
    never_finish = asyncio.Event()
    job = SimpleNamespace(id=7, doc_id=3)

    class FakeOcrJobRepository:
        def __init__(self, db) -> None:
            pass

        async def get(self, job_id: int):
            return job

        async def mark(self, job_id: int, **values) -> None:
            marks.append({"job_id": job_id, **values})

    async def blocked_extract(file_path: str) -> str:
        started.set()
        await never_finish.wait()
        return ""

    monkeypatch.setattr(ocr, "async_session_factory", _session_factory)
    monkeypatch.setattr(ocr, "OcrJobRepository", FakeOcrJobRepository)
    monkeypatch.setattr(
        ocr,
        "ocr_engine_available",
        lambda: (True, "available", "test-engine"),
    )
    monkeypatch.setattr(ocr, "_extract_ocr_text", blocked_extract)

    task = asyncio.create_task(ocr.run_ocr_job(job.id, "scan.png"))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [item["status"] for item in marks] == ["processing", "failed"]
    assert "可重试" in marks[-1]["error_message"]
    assert marks[-1]["finished_at"] is not None


@pytest.mark.asyncio
async def test_project_scan_cancel_marks_running_activity_failed(monkeypatch):
    import personal_assistant.workers.project_scanner as scanner

    activity_updates: list[dict] = []
    started = asyncio.Event()
    never_finish = asyncio.Event()
    project = SimpleNamespace(id=9, name="cancelled-project", root_path="C:/project")

    class FakeProjectRepository:
        def __init__(self, db) -> None:
            pass

        async def get(self, project_id: int):
            return project

    async def fake_sync(
        project_id: int,
        project_name: str,
        status: str,
        detail: dict,
        *,
        error_message: str | None = None,
    ) -> None:
        activity_updates.append(
            {
                "project_id": project_id,
                "name": project_name,
                "status": status,
                "detail": detail,
                "error": error_message,
            }
        )

    async def blocked_walk(root: str) -> list[dict]:
        started.set()
        await never_finish.wait()
        return []

    monkeypatch.setattr(scanner, "async_session_factory", _session_factory)
    monkeypatch.setattr(scanner, "ProjectRepository", FakeProjectRepository)
    monkeypatch.setattr(scanner, "_sync", fake_sync)
    monkeypatch.setattr(scanner, "_walk_files", blocked_walk)

    task = asyncio.create_task(scanner.scan_project(project.id))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [item["status"] for item in activity_updates] == ["running", "failed"]
    assert "可重试" in activity_updates[-1]["error"]
