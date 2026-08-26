"""pytest fixtures。"""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from personal_assistant.config import settings as cfg
from personal_assistant.testing import (
    UnsafeTestDatabaseError,
    resolve_test_database_url,
)

try:
    TEST_DB_URL = resolve_test_database_url(cfg.db_url, os.environ.get("PA_TEST_DB_URL"))
except UnsafeTestDatabaseError as exc:
    raise pytest.UsageError(f"数据库测试安全检查失败：{exc}") from exc

# Set this before importing core.db/main_api.  Those modules create global
# engines and background-session factories at import time.
cfg.db_url = TEST_DB_URL
# 通用套件默认走 legacy 检索路径（测试用 3/8 维 fake embedder，且只 mock
# chroma_store.query）。versioned 相关测试在用例内通过 monkeypatch 显式
# 开启 flag 并注入 FakeVersionVectorStore，不依赖全局开关。
cfg.versioned_rag_indexing_enabled = False
cfg.versioned_rag_retrieval_enabled = False
# Agent Runtime 灰度开关：测试环境显式重置为默认关闭，与生产 .env 解耦；
# 需要开启的用例用 monkeypatch 显式设置（保持确定性）。
cfg.agent_runs_api_enabled = False
cfg.agent_run_read_only_tools_enabled = False
cfg.agent_rag_tools_enabled = False
cfg.agent_context_builder_enabled = False
cfg.agent_output_verification_enabled = False
cfg.chat_agent_runtime_enabled = False
cfg.compatibility_telemetry_persist_enabled = False
# v0.9.0 H0：v0.6.0/v0.7.0 编码 flag 同样与生产 .env 解耦（开发 .env 会显式
# 开启 project-bound 等供前端联调；需要开启的用例用 monkeypatch 显式设置）。
cfg.project_bound_runs_enabled = False
cfg.agent_run_plan_enabled = False
cfg.agent_run_event_stream_enabled = False
# v0.9.0 H1-B/H1-C：开发 .env 新增命令工作流等纠偏 flag，测试环境同样解耦。
cfg.agent_command_workflow_enabled = False
cfg.coding_patchset_enabled = False
cfg.coding_command_profiles_enabled = False
cfg.coding_artifacts_enabled = False
cfg.coding_permission_models_enabled = False
cfg.coding_agent_ui_enabled = False
cfg.coding_workspace_auto_approve_enabled = False
cfg.coding_full_access_enabled = False
cfg.coding_context_budget_enabled = False
cfg.coding_execution_detail_enabled = False
cfg.coding_worktree_enabled = False
TEST_API_TOKEN = "test-api-token-0123456789abcdef0123456789abcdef"
cfg.api_auth_enabled = True
cfg.api_token = SecretStr(TEST_API_TOKEN)

import personal_assistant.core.db as dbmod  # noqa: E402
import personal_assistant.core.reminders as reminders_mod  # noqa: E402
import personal_assistant.workers.importer as importer_mod  # noqa: E402
import personal_assistant.workers.ocr as ocr_mod  # noqa: E402
import personal_assistant.workers.project_scanner as scanner_mod  # noqa: E402
from personal_assistant.core.db import get_session  # noqa: E402
from personal_assistant.main_api import app  # noqa: E402


@pytest.fixture
def tmp_path():
    """Windows/sandbox-safe replacement for pytest's built-in ``tmp_path``.

    Python 3.13 applies a private ACL when pytest creates its base directory with
    mode ``0o700``.  Under the Codex Windows sandbox that ACL can exclude the
    restricted process token that created it.  Use an isolated workspace leaf
    with normal inherited ACLs instead.
    """

    workspace = Path(__file__).resolve().parents[1]
    root = (workspace / ".tmp" / "pytest-safe").resolve()
    if workspace != root and workspace not in root.parents:
        raise RuntimeError(f"unsafe pytest temporary root: {root}")
    root.mkdir(parents=True, exist_ok=True, mode=0o777)
    path = root / uuid4().hex
    path.mkdir(mode=0o777)
    try:
        yield path
    finally:
        resolved = path.resolve()
        if root not in resolved.parents:
            raise RuntimeError(f"refusing to remove unsafe pytest path: {resolved}")
        shutil.rmtree(resolved, ignore_errors=True)


@pytest_asyncio.fixture
async def db():
    """独立 engine 的 db session。

    每个测试用独立 engine，测试结束 dispose，避免跨测试 event loop
    共享 aiomysql 连接导致的清理错误（Windows proactor）。
    """
    engine = create_async_engine(
        TEST_DB_URL,
        pool_pre_ping=True,
        connect_args={"init_command": "SET time_zone='+00:00'"},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    # v0.6.0：RunPlan/RunArtifact 服务用独立 session 写 durable 事件（直接
    # 导入 async_session_factory 名字），须重绑到本 fixture 的 engine，
    # 避免测试中写入全局（生产）数据库。
    from personal_assistant.api import routes_agent_runs as runs_mod
    from personal_assistant.core import db as dbmod
    from personal_assistant.core import run_artifact as run_artifact_mod
    from personal_assistant.core import run_plan as run_plan_mod
    from personal_assistant.workers import conversation_summarizer as summarizer_mod

    orig_factory = dbmod.async_session_factory
    orig_plan_factory = run_plan_mod.async_session_factory
    orig_artifact_factory = run_artifact_mod.async_session_factory
    orig_runs_factory = runs_mod.async_session_factory
    orig_summarizer_factory = summarizer_mod.async_session_factory
    dbmod.async_session_factory = factory
    run_plan_mod.async_session_factory = factory
    run_artifact_mod.async_session_factory = factory
    runs_mod.async_session_factory = factory
    summarizer_mod.async_session_factory = factory
    try:
        async with factory() as session:
            yield session
    finally:
        dbmod.async_session_factory = orig_factory
        run_plan_mod.async_session_factory = orig_plan_factory
        run_artifact_mod.async_session_factory = orig_artifact_factory
        runs_mod.async_session_factory = orig_runs_factory
        summarizer_mod.async_session_factory = orig_summarizer_factory
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
        TEST_DB_URL,
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
    # v0.6.0：RunPlan/RunArtifact 服务同样直接导入 async_session_factory 名字。
    from personal_assistant.api import routes_agent_runs as runs_mod
    from personal_assistant.core import run_artifact as run_artifact_mod
    from personal_assistant.core import run_plan as run_plan_mod
    from personal_assistant.workers import conversation_summarizer as summarizer_mod

    orig_plan_factory = run_plan_mod.async_session_factory
    orig_artifact_factory = run_artifact_mod.async_session_factory
    orig_runs_factory = runs_mod.async_session_factory
    orig_summarizer_factory = summarizer_mod.async_session_factory
    run_plan_mod.async_session_factory = test_factory
    run_artifact_mod.async_session_factory = test_factory
    runs_mod.async_session_factory = test_factory
    summarizer_mod.async_session_factory = test_factory
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {TEST_API_TOKEN}"},
        ) as c:
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
        run_plan_mod.async_session_factory = orig_plan_factory
        run_artifact_mod.async_session_factory = orig_artifact_factory
        runs_mod.async_session_factory = orig_runs_factory
        summarizer_mod.async_session_factory = orig_summarizer_factory
        await test_engine.dispose()


@pytest.fixture(autouse=True)
def _disable_model_probe_in_tests(monkeypatch):
    """v1.0 CT-3：测试期默认关闭模型自动探测（不真实调用模型）。

    需要验证探测接线的用例自行 monkeypatch 开启并注入受控网关。
    """
    from personal_assistant.config import settings as cfg

    monkeypatch.setattr(cfg, "agent_v2_model_probe_enabled", False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _clean_stale_test_data():
    """session 开始时清理历史测试残留（perf-*/upgrade-smoke-*/integration:ics 等）。

    共享 DB 无事务回滚，跨 session 会积累脏数据（perf 样本、孤儿 trusted_path 等）。
    此 fixture 仅删测试特征前缀的数据，不影响用户真实数据。第八阶段审查修复。
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import delete, update

    from personal_assistant.core.models import (
        AgentRun,
        AppNotification,
        ChatSession,
        DataIntegrityFinding,
        Document,
        InboxItem,
        IntegrationImport,
        IntegrationSource,
        Message,
        ModelProfile,
        ModelToolProfileSnapshotRecord,
        Reminder,
        UpgradeSmokeRun,
    )

    eng = create_async_engine(TEST_DB_URL, pool_pre_ping=True)
    try:
        async with async_sessionmaker(eng, expire_on_commit=False)() as s:
            # v0.9.0 H1-A：共享 DB 跨会话会残留非终态 agent run（中断/被 mock
            # 的协调器遗留），导致顺序敏感的 recovery 用例把残留计入孤儿数。
            # 会话启动时将其终态化（仅测试库，不影响真实数据）。
            await s.execute(
                update(AgentRun)
                .where(
                    AgentRun.status.in_(
                        ("created", "running", "waiting_approval")
                    )
                )
                .values(
                    status="cancelled",
                    error_code="process_restarted",
                    error_message="conftest session cleanup",
                )
            )
            await s.execute(delete(Message).where(Message.content.like("perf message%")))
            # v0.9.0 H1-D：共享库会残留测试创建的 model profile（全部是测试
            # 产物，用例各自创建；清空保证导入/默认绑定类用例确定性，仅测试库）。
            await s.execute(delete(ModelProfile))
            # v1.0 CT-3：探测快照随 profile 一并清空（仅测试库）。
            await s.execute(delete(ModelToolProfileSnapshotRecord))
            await s.execute(delete(ChatSession).where(ChatSession.title.like("perf-session-%")))
            await s.execute(delete(InboxItem).where(InboxItem.title.like("perf-inbox-%")))
            # v0.9.0 H1-B/C：共享测试库会跨会话积压未处理 inbox 条目，超过
            # TodayService 的 list_open(limit=200) 后新建条目不可见，导致
            # 顺序无关的 today 过滤用例失败。只清理一天前的测试遗留条目，
            # 当次用例自建自清不受影响（仅测试库，不影响真实数据）。
            await s.execute(
                delete(InboxItem).where(
                    InboxItem.status.in_(("open", "snoozed")),
                    InboxItem.created_at < datetime.now(timezone.utc) - timedelta(days=1),
                )
            )
            await s.execute(delete(Document).where(Document.name.like("perf-doc-%")))
            await s.execute(
                delete(Document).where(
                    Document.name.in_(
                        [
                            "versioned-rag.txt",
                            "safe-reindex.txt",
                            "index-cleanup.txt",
                            "immutable-index.txt",
                            "legacy-source.txt",
                            "migrated-source.txt",
                            "version-api.txt",
                            "preserved-reindex.txt",
                            "rollback-guard.txt",
                            "recover-building.txt",
                            "recover-validated.txt",
                            "retention-index.txt",
                            "stale-build.txt",
                        ]
                    )
                )
            )
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
        TEST_DB_URL,
        pool_pre_ping=True,
        connect_args={"init_command": "SET time_zone='+00:00'"},
    )
    factory = async_sessionmaker(eng, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session
    await eng.dispose()
