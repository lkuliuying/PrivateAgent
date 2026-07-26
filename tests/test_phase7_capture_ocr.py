"""第七阶段 M3 测试：快速捕获 + OCR 队列。

覆盖（对齐 docs/phase7-plan.md §M3 / docs/phase7-requirements.md §5.3）：
- 捕获草稿 CRUD + 转 inbox/reminder/memory。
- OCR 引擎可用性检测端点。
- /documents/{id}/ocr 创建 OCR job（取代 unavailable 桩）。
- OCR worker：引擎不可用 -> unavailable；成功 -> succeeded（mock 引擎）。
- NeedsOcrError：扫描件 PDF 触发 OCR 路径（parse_document 抛 NeedsOcrError）。
"""
from __future__ import annotations

import asyncio

import pytest

from personal_assistant.core.capture import CaptureService
from personal_assistant.core.background import background_tasks
from personal_assistant.core.models import CaptureItem, Document, OcrJob
from personal_assistant.core.ocr import ocr_engine_available
from personal_assistant.core.rag import NeedsOcrError, is_scanned_pdf, parse_document
from personal_assistant.core.repo_ocr_jobs import OcrJobRepository
from personal_assistant.core.timeutil import utcnow


@pytest.fixture
async def cleanup(db):
    created: list = []
    yield created
    for obj in reversed(created):
        try:
            await db.delete(obj)
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()


async def _add(db, obj):
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


# ============ 捕获 ============


@pytest.mark.asyncio
async def test_capture_crud_and_convert(db, cleanup):
    svc = CaptureService(db)
    cap = await svc.create(content_md="一段捕获文本", source="clipboard", title="捕获1")
    cleanup.append(cap)
    assert cap.status == "pending"

    # 转 inbox
    inbox = await svc.to_inbox(cap.id)
    cleanup.append(inbox)
    assert inbox.title == "捕获1"
    fresh = await svc.repo.get(cap.id)
    assert fresh.status == "handled" and fresh.target_type == "inbox"

    # 新建捕获转 reminder
    cap2 = await svc.create(content_md="提醒事项", title="捕获2")
    cleanup.append(cap2)
    rem = await svc.to_reminder(cap2.id)
    cleanup.append(rem)
    assert (await svc.repo.get(cap2.id)).target_type == "reminder"

    # 新建捕获转 memory（draft）
    cap3 = await svc.create(content_md="记忆候选", title="捕获3")
    cleanup.append(cap3)
    mem = await svc.to_memory(cap3.id)
    cleanup.append(mem)
    assert mem.status == "draft"
    assert (await svc.repo.get(cap3.id)).target_type == "memory"


@pytest.mark.asyncio
async def test_capture_routes(client, db, cleanup):
    r = await client.post("/capture", json={"content_md": "路由捕获", "source": "manual"})
    assert r.status_code == 201
    cid = r.json()["id"]
    cleanup.append(await db.get(CaptureItem, cid))

    r = await client.get("/capture")
    assert r.status_code == 200
    assert any(x["id"] == cid for x in r.json())

    r = await client.post(f"/capture/{cid}/to-inbox", json={"item_type": "note"})
    assert r.status_code == 200
    assert r.json()["target_type"] == "inbox"


# ============ OCR 可用性 ============


@pytest.mark.asyncio
async def test_ocr_availability_route(client):
    r = await client.get("/ocr/availability")
    assert r.status_code == 200
    data = r.json()
    assert "available" in data and "reason" in data
    # 测试环境通常未装 OCR
    assert isinstance(data["available"], bool)


def test_ocr_engine_available_returns_tuple():
    available, reason, engine = ocr_engine_available()
    assert isinstance(available, bool)
    assert isinstance(reason, str)


# ============ OCR 路由 ============


@pytest.mark.asyncio
async def test_ocr_route_creates_job(client, db, cleanup):
    doc = await _add(db, Document(name="scan.pdf", status="needs_ocr"))
    cleanup.append(doc)
    r = await client.post(f"/documents/{doc.id}/ocr")
    assert r.status_code == 200
    data = r.json()
    assert data["job_id"] is not None
    assert data["status"] == "pending"
    # 清理 OCR job（worker 可能已改其状态）
    from sqlalchemy import select

    jobs = (await db.execute(select(OcrJob).where(OcrJob.doc_id == doc.id))).scalars().all()
    for j in jobs:
        cleanup.append(j)


# ============ OCR worker ============


@pytest.mark.asyncio
async def test_ocr_worker_unavailable(db, client, cleanup, monkeypatch):
    """引擎不可用时 job 置 unavailable（不静默失败）。"""
    import personal_assistant.workers.ocr as ocr_mod

    monkeypatch.setattr(
        ocr_mod, "ocr_engine_available", lambda: (False, "未安装 OCR 引擎", None)
    )
    job = await OcrJobRepository(db).create(doc_id=None, file_path=None, source="manual")
    cleanup.append(job)
    await ocr_mod.run_ocr_job(job.id, None)
    # 经 client（test_factory，与 worker 同引擎）读取，避免 db fixture identity map 缓存
    r = await client.get(f"/ocr-jobs/{job.id}")
    assert r.status_code == 200
    fresh = r.json()
    assert fresh["status"] == "unavailable"
    assert "未安装" in (fresh["error_message"] or "")


@pytest.mark.asyncio
async def test_ocr_worker_success(db, client, cleanup, monkeypatch):
    """引擎可用 + run_ocr 成功时 job 置 succeeded 并存 output_text。"""
    import personal_assistant.workers.ocr as ocr_mod

    monkeypatch.setattr(
        ocr_mod, "ocr_engine_available", lambda: (True, "tesseract 可用", "tesseract")
    )
    monkeypatch.setattr(ocr_mod, "run_ocr_text", lambda path: "识别出的中文文本")
    job = await OcrJobRepository(db).create(
        doc_id=None, file_path="/tmp/fake.png", source="manual"
    )
    cleanup.append(job)
    await ocr_mod.run_ocr_job(job.id, "/tmp/fake.png")
    r = await client.get(f"/ocr-jobs/{job.id}")
    assert r.status_code == 200
    fresh = r.json()
    assert fresh["status"] == "succeeded"
    assert fresh["output_text"] == "识别出的中文文本"
    assert fresh["engine"] == "tesseract"


@pytest.mark.asyncio
async def test_ocr_retry_worker_resets_terminal_fields_only_when_started(
    db,
    client,
    cleanup,
    monkeypatch,
):
    import personal_assistant.workers.ocr as ocr_mod

    job = await OcrJobRepository(db).create(
        doc_id=None,
        file_path="/tmp/retry.png",
        source="manual",
    )
    cleanup.append(job)
    now = utcnow()
    await OcrJobRepository(db).mark(
        job.id,
        status="failed",
        engine="old-engine",
        output_text="partial",
        error_message="old failure",
        started_at=now,
        finished_at=now,
    )
    observed: list[dict] = []

    async def observe_reset(job_id: int, file_path: str | None) -> None:
        async with ocr_mod.async_session_factory() as session:
            fresh = await OcrJobRepository(session).get(job_id)
            observed.append(
                {
                    "status": fresh.status,
                    "engine": fresh.engine,
                    "output_text": fresh.output_text,
                    "error_message": fresh.error_message,
                    "started_at": fresh.started_at,
                    "finished_at": fresh.finished_at,
                }
            )

    monkeypatch.setattr(ocr_mod, "run_ocr_job", observe_reset)
    await ocr_mod.retry_ocr_job(job.id, job.file_path)

    assert observed == [
        {
            "status": "pending",
            "engine": None,
            "output_text": None,
            "error_message": None,
            "started_at": None,
            "finished_at": None,
        }
    ]


@pytest.mark.asyncio
async def test_ocr_retry_route_deduplicates_without_regressing_status(
    db,
    client,
    cleanup,
    monkeypatch,
):
    import personal_assistant.workers.ocr as ocr_mod

    job = await OcrJobRepository(db).create(
        doc_id=None,
        file_path="/tmp/retry-race.png",
        source="manual",
    )
    cleanup.append(job)
    await OcrJobRepository(db).mark(
        job.id,
        status="failed",
        error_message="original failure",
        finished_at=utcnow(),
    )
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def blocked_retry(job_id: int, file_path: str | None) -> None:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()

    monkeypatch.setattr(ocr_mod, "retry_ocr_job", blocked_retry)
    responses = await asyncio.gather(
        *(client.post(f"/ocr-jobs/{job.id}/retry") for _ in range(10))
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, *([409] * 9)]
    assert all(
        response.json()["detail"] == "OCR job retry is already in progress"
        for response in responses
        if response.status_code == 409
    )
    assert calls == 1
    current = await client.get(f"/ocr-jobs/{job.id}")
    assert current.json()["status"] == "failed"
    assert current.json()["error_message"] == "original failure"

    release.set()
    await background_tasks.drain(timeout=1.0)


@pytest.mark.parametrize("status", ["pending", "processing"])
@pytest.mark.asyncio
async def test_ocr_retry_route_is_idempotent_for_active_states(
    status,
    db,
    client,
    cleanup,
):
    job = await OcrJobRepository(db).create(doc_id=None, file_path=None, source="manual")
    cleanup.append(job)
    await OcrJobRepository(db).mark(job.id, status=status)

    response = await client.post(f"/ocr-jobs/{job.id}/retry")

    assert response.status_code == 200
    assert response.json()["status"] == status


@pytest.mark.asyncio
async def test_ocr_retry_route_rejects_succeeded_job(db, client, cleanup):
    job = await OcrJobRepository(db).create(doc_id=None, file_path=None, source="manual")
    cleanup.append(job)
    await OcrJobRepository(db).mark(job.id, status="succeeded", finished_at=utcnow())

    response = await client.post(f"/ocr-jobs/{job.id}/retry")

    assert response.status_code == 409


# ============ NeedsOcrError ============


def test_parse_scanned_pdf_raises_needs_ocr(tmp_path):
    """parse_document 对扫描件 PDF 抛 NeedsOcrError（而非普通 ValueError）。"""
    # 构造一个空内容 PDF（is_scanned_pdf 会判定为扫描件：每页文本 < 50）
    try:
        from pypdf import PdfWriter
    except ImportError:
        pytest.skip("pypdf 未安装")
    pdf_path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with pdf_path.open("wb") as f:
        writer.write(f)
    with pytest.raises(NeedsOcrError):
        parse_document(str(pdf_path))
