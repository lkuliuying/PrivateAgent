"""Shared pytest fixtures with fail-closed MySQL isolation."""
from __future__ import annotations

import asyncio
import atexit
import logging
import os
import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _test_database import (  # noqa: E402
    IsolatedDatabasePlan,
    activate_test_environment,
    build_database_plan,
    drop_database,
    make_test_data_dir,
    provision_database,
    remove_test_data_dir,
    upgrade_database,
)

# Reading application configuration is safe here; the global DB engine and FastAPI app
# must not be imported until PA_DB_URL and PA_DATA_DIR have been replaced below.
import personal_assistant.config as config_module  # noqa: E402


def _bootstrap_isolated_database() -> tuple[IsolatedDatabasePlan, Path]:
    plan = build_database_plan(
        config_module.settings.db_url,
        explicit_test_url=os.environ.get("PA_TEST_DB_URL"),
    )
    data_dir = make_test_data_dir(
        plan.database_name,
        temp_root=PROJECT_ROOT / ".run" / "pytest",
    )
    activate_test_environment(plan, data_dir)
    # config.py was imported to read the base URL, so update its singleton before any
    # core module can capture settings or create an engine.
    config_module.settings.db_url = plan.database_url
    config_module.settings.data_dir = data_dir
    try:
        provision_database(plan)
        upgrade_database(PROJECT_ROOT)
    except BaseException:
        try:
            if plan.created_by_run:
                drop_database(plan)
        finally:
            remove_test_data_dir(
                data_dir,
                temp_root=PROJECT_ROOT / ".run" / "pytest",
            )
        raise
    return plan, data_dir


TEST_DATABASE_PLAN, TEST_DATA_DIR = _bootstrap_isolated_database()
_cleanup_complete = False


def _emergency_cleanup() -> None:
    """Clean isolation even when a later conftest import fails."""

    global _cleanup_complete
    if _cleanup_complete:
        return
    try:
        if TEST_DATABASE_PLAN.created_by_run:
            drop_database(TEST_DATABASE_PLAN)
    finally:
        remove_test_data_dir(
            TEST_DATA_DIR,
            temp_root=PROJECT_ROOT / ".run" / "pytest",
        )
    _cleanup_complete = True


atexit.register(_emergency_cleanup)

# Application imports are intentionally below the isolation bootstrap.
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

import personal_assistant.core.db as dbmod  # noqa: E402
import personal_assistant.core.reminders as reminders_mod  # noqa: E402
import personal_assistant.workers.importer as importer_mod  # noqa: E402
import personal_assistant.workers.ocr as ocr_mod  # noqa: E402
import personal_assistant.workers.project_scanner as scanner_mod  # noqa: E402
from personal_assistant.core.background import background_tasks  # noqa: E402
from personal_assistant.core.db import get_session  # noqa: E402
from personal_assistant.core.store_chroma import chroma_store  # noqa: E402
from personal_assistant.main_api import app  # noqa: E402

cfg = config_module.settings


def pytest_report_header() -> str:
    ownership = "generated/drop-on-exit" if TEST_DATABASE_PLAN.created_by_run else "explicit/preserved"
    return f"isolated mysql: {TEST_DATABASE_PLAN.database_name} ({ownership})"


def _cleanup_isolated_database() -> None:
    global _cleanup_complete
    if _cleanup_complete:
        return

    # Close the application engine before DROP. Per-test engines are disposed by their
    # fixtures, and logging.shutdown releases the temporary log file on Windows.
    async def _close_runtime_resources() -> None:
        await chroma_store.close()
        await dbmod.engine.dispose()

    try:
        asyncio.run(_close_runtime_resources())
    finally:
        logging.shutdown()
        try:
            if TEST_DATABASE_PLAN.created_by_run:
                drop_database(TEST_DATABASE_PLAN)
        finally:
            remove_test_data_dir(
                TEST_DATA_DIR,
                temp_root=PROJECT_ROOT / ".run" / "pytest",
            )
    _cleanup_complete = True


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    try:
        _cleanup_isolated_database()
    except Exception as exc:  # noqa: BLE001 - teardown failures must fail the run
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        message = f"isolated database cleanup failed: {type(exc).__name__}: {exc}"
        if reporter is not None:
            reporter.write_line(message, red=True)
        else:
            print(message, file=sys.stderr)


@pytest_asyncio.fixture
async def db():
    """Provide a per-test engine/session connected only to the isolated schema."""

    engine = create_async_engine(
        cfg.db_url,
        pool_pre_ping=True,
        connect_args={"init_command": "SET time_zone='+00:00'"},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await dbmod.engine.dispose()
        await engine.dispose()


@pytest.fixture
def tmp_path() -> Path:
    """Create test paths with inherited ACLs inside the isolated data directory."""

    root = TEST_DATA_DIR / "pytest-tmp"
    root.mkdir(parents=True, exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir()
    return path


@pytest_asyncio.fixture
async def client():
    """Provide an in-process FastAPI client backed by a per-test DB engine."""

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
    # These modules imported the factory name directly. Keep their test binding aligned
    # until the later dependency-injection refactor removes the import-time globals.
    scanner_mod.async_session_factory = test_factory
    importer_mod.async_session_factory = test_factory
    reminders_mod.async_session_factory = test_factory
    ocr_mod.async_session_factory = test_factory
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        await background_tasks.drain(timeout=10.0)
        # HealthService holds the application engine directly. Dispose it in the same
        # event loop that served the request so aiomysql transports are not finalized
        # after pytest has already closed that loop.
        await dbmod.engine.dispose()
        app.dependency_overrides.pop(get_session, None)
        dbmod.async_session_factory = orig_factory
        scanner_mod.async_session_factory = orig_factory
        importer_mod.async_session_factory = orig_factory
        reminders_mod.async_session_factory = orig_factory
        ocr_mod.async_session_factory = orig_factory
        await test_engine.dispose()


@pytest_asyncio.fixture
async def fresh_session():
    """Provide a fresh session for cross-session visibility assertions."""

    engine = create_async_engine(
        cfg.db_url,
        pool_pre_ping=True,
        connect_args={"init_command": "SET time_zone='+00:00'"},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
