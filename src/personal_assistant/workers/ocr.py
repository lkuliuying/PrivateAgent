"""OCR 队列后台 worker（第七阶段 M3）。

fire-and-forget：路由 asyncio.create_task(run_ocr_job(...)) 触发。
OCR 引擎为同步阻塞，用 asyncio.to_thread 隔离。
未安装引擎时 job 置 unavailable 并写维护通知；失败入维护报告（phase7 §4.4/§5.3）。

注意：本模块 `from ..core.db import async_session_factory` 直接导入名字，
测试须在 tests/conftest.py 的 client fixture 重绑本模块属性，否则跨 event loop
泄漏 aiomysql 连接（MEMORY phase4-conftest-background-workers）。
"""
from __future__ import annotations

import asyncio

from ..core.db import async_session_factory
from ..core.notifications import NotificationService
from ..core.ocr import ocr_engine_available, run_ocr_text
from ..core.repo_ocr_jobs import OcrJobRepository
from ..core.timeutil import utcnow
from ..logging_setup import get_logger

logger = get_logger(__name__)


async def run_ocr_job(job_id: int, file_path: str | None) -> None:
    """执行单个 OCR job 的状态机：pending -> processing -> succeeded/failed/unavailable。"""
    async with async_session_factory() as db:
        repo = OcrJobRepository(db)
        job = await repo.get(job_id)
        if job is None:
            return
        available, reason, engine = ocr_engine_available()
        if not available:
            await repo.mark(
                job_id, status="unavailable", error_message=reason, finished_at=utcnow()
            )
            await _notify(
                db,
                level="warning",
                title=f"OCR 不可用：{reason}",
                message=f"job #{job_id}（doc_id={job.doc_id}）已标记为不可用，请安装 OCR 引擎或手动处理。",
                source_id=job_id,
            )
            return

        await repo.mark(
            job_id, status="processing", engine=engine, started_at=utcnow()
        )
        logger.info("ocr job start", job_id=job_id, engine=engine)
        try:
            if not file_path:
                raise RuntimeError("OCR job 缺少文件路径")
            text = await asyncio.to_thread(run_ocr_text, file_path)
            await repo.mark(
                job_id, status="succeeded", output_text=text, finished_at=utcnow()
            )
            await _notify(
                db,
                level="success",
                title=f"OCR 完成：job #{job_id}",
                message=f"识别 {len(text)} 字符，请在 OCR 队列查看并导入文本。",
                source_id=job_id,
            )
            logger.info("ocr job done", job_id=job_id, chars=len(text))
        except Exception as e:  # noqa: BLE001
            logger.exception("ocr job failed", job_id=job_id)
            await repo.mark(
                job_id,
                status="failed",
                error_message=str(e)[:1000],
                finished_at=utcnow(),
            )
            await _notify(
                db,
                level="error",
                title=f"OCR 失败：job #{job_id}",
                message=str(e)[:200],
                source_id=job_id,
            )


async def _notify(
    db, *, level: str, title: str, message: str, source_id: int
) -> None:
    try:
        await NotificationService(db).notify(
            kind="ocr",
            title=title,
            level=level,
            message=message,
            source_type="ocr_job",
            source_id=source_id,
        )
    except Exception:  # noqa: BLE001
        logger.warning("ocr notify failed", exc_info=True)
