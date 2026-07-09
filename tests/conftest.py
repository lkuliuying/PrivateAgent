"""pytest fixtures。"""
from __future__ import annotations

import asyncio

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from personal_assistant.config import settings as cfg
from personal_assistant.core.db import get_session
import personal_assistant.core.db as dbmod
import personal_assistant.workers.importer as importer_mod
import personal_assistant.workers.ocr as ocr_mod
import personal_assistant.workers.project_scanner as scanner_mod
import personal_assistant.core.reminders as reminders_mod
from personal_assistant.main_api import app


@pytest_asyncio.fixture
async def db():
    """独立 engine 的 db session。

    每个测试用独立 engine，测试结束 dispose，避免跨测试 event loop
    共享 aiomysql 连接导致的清理错误（Windows proactor）。
    """
    engine = create_async_engine(
        cfg.db_url,
        pool_pre_ping=True,
        connect_args={"init_command": "SET time_zone='+00:00'"},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    """FastAPI 测试客户端（ASGITransport，不走真实端口）。

    每个测试用独立 engine，覆盖 get_session 依赖并重绑定
    dbmod.async_session_factory，使 fire-and-forget 后台任务
    （scan_project / import_document）也走 per-test engine，
    避免跨 event loop 泄漏 aiomysql 连接。
    """
    test_engine = create_async_engine(
        cfg.db_url,
        pool_pre_ping=True,
        connect_args={"init_command": "SET time_zone='+00:00'"},
    )
    test_factory = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)

    async def _get_test_session():
        async with test_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _get_test_session
    orig_factory = dbmod.async_session_factory
    dbmod.async_session_factory = test_factory
    # 后台任务（scan_project / import_document）用 `from ..core.db import async_session_factory`
    # 直接导入名字，重绑 dbmod 属性对它们无效；需同步重绑这些模块的属性，否则它们仍走全局
    # engine（import 时绑定到别的 event loop），跨 loop 写入失败 + 连接泄漏警告。
    scanner_mod.async_session_factory = test_factory
    importer_mod.async_session_factory = test_factory
    # 提醒后台 tick 用 reminders_mod.async_session_factory（lifespan 不在测试运行，
    # 但若未来测试触发，重绑可避免跨 event loop 泄漏 aiomysql 连接）。
    reminders_mod.async_session_factory = test_factory
    # OCR 后台 worker 同样直接导入 async_session_factory 名字，须重绑（phase7 M3）。
    ocr_mod.async_session_factory = test_factory
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        # 先排空后台任务（scan/import 等 fire-and-forget，factory 仍指向 test_factory），
        # 让其 session 关闭、连接归还，再 dispose 测试 engine，避免 GC 终结未归还连接的警告。
        current = asyncio.current_task()
        pending = [t for t in asyncio.all_tasks() if t is not current]
        if pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=10.0,
                )
            except asyncio.TimeoutError:
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        app.dependency_overrides.pop(get_session, None)
        dbmod.async_session_factory = orig_factory
        scanner_mod.async_session_factory = orig_factory
        importer_mod.async_session_factory = orig_factory
        reminders_mod.async_session_factory = orig_factory
        ocr_mod.async_session_factory = orig_factory
        await test_engine.dispose()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _clean_stale_test_data():
    """session 开始时清理历史测试残留（perf-*/upgrade-smoke-*/integration:ics 等）。

    共享 DB 无事务回滚，跨 session 会积累脏数据（perf 样本、孤儿 trusted_path 等）。
    此 fixture 仅删测试特征前缀的数据，不影响用户真实数据。第八阶段审查修复。
    """
    from sqlalchemy import delete

    from personal_assistant.core.models import (
        AppNotification,
        CaptureItem,
        ChatSession,
        DataIntegrityFinding,
        Document,
        InboxItem,
        IntegrationImport,
        IntegrationSource,
        Message,
        Reminder,
        UpgradeSmokeRun,
    )

    eng = create_async_engine(cfg.db_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(eng, expire_on_commit=False)() as s:
            await s.execute(delete(Message).where(Message.content.like("perf message%")))
            await s.execute(delete(ChatSession).where(ChatSession.title.like("perf-session-%")))
            await s.execute(delete(InboxItem).where(InboxItem.title.like("perf-inbox-%")))
            await s.execute(delete(Document).where(Document.name.like("perf-doc-%")))
            await s.execute(delete(AppNotification).where(AppNotification.title.like("perf-notif-%")))
            await s.execute(
                delete(DataIntegrityFinding).where(
                    DataIntegrityFinding.check_name == "perf_test"
                )
            )
            await s.execute(delete(Reminder).where(Reminder.source_type == "integration:ics"))
            await s.execute(delete(InboxItem).where(InboxItem.source_type == "integration:ics"))
            await s.execute(delete(IntegrationImport))
            await s.execute(delete(IntegrationSource))
            await s.execute(delete(UpgradeSmokeRun))
            await s.commit()
    finally:
        await eng.dispose()
    yield


@pytest_asyncio.fixture
async def fresh_session():
    """独立 fresh engine session，用于跨 session 读 client/worker 写入的数据。

    db fixture 的 session 可能持有旧事务快照（REPEATABLE READ），读不到其它 session
    提交的行；需要跨 session 验证时用本 fixture。第八阶段审查修复。
    """
    eng = create_async_engine(
        cfg.db_url,
        pool_pre_ping=True,
        connect_args={"init_command": "SET time_zone='+00:00'"},
    )
    factory = async_sessionmaker(eng, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session
    await eng.dispose()
