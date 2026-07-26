"""Fail-closed MySQL isolation helpers for tests and release checks.

This module deliberately has no dependency on ``personal_assistant`` so callers can
select and activate an isolated database before importing the application's global
engine or FastAPI app.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import stat
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

TEST_DATABASE_PREFIX = "pa_test_"
_TEST_DATABASE_RE = re.compile(r"^pa_test_[a-z0-9_]{1,56}$")
_SAFE_MYSQL_DRIVERS = {"aiomysql", "asyncmy"}
_TEST_DATA_PREFIX = "pa-test-data-"


class DatabaseSafetyError(RuntimeError):
    """Raised when a URL or cleanup target is not demonstrably test-only."""


class DatabaseProvisionError(RuntimeError):
    """Raised when an isolated database cannot be created or reached."""


@dataclass(frozen=True, slots=True)
class IsolatedDatabasePlan:
    """A database target plus the evidence needed to authorize cleanup."""

    database_url: str
    admin_url: str
    database_name: str
    run_token: str
    worker_id: str
    created_by_run: bool


def validate_test_database_name(name: str | None) -> str:
    """Return *name* only when it is an unambiguously test-only identifier."""

    if not name or len(name) > 64 or not _TEST_DATABASE_RE.fullmatch(name):
        raise DatabaseSafetyError(
            "测试数据库名必须严格匹配 pa_test_[a-z0-9_]+，且不超过 64 个字符"
        )
    return name


def generated_database_name(run_token: str, worker_id: str = "master") -> str:
    """Build a deterministic safe name whose suffix is bound to the run token."""

    if not run_token or not run_token.strip():
        raise DatabaseSafetyError("测试运行 token 不能为空")
    raw = f"{run_token}:{worker_id or 'master'}"
    slug = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_") or "run"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    name = f"{TEST_DATABASE_PREFIX}{slug[:36].rstrip('_')}_{digest}"
    return validate_test_database_name(name)


def _validated_mysql_url(raw_url: str) -> URL:
    try:
        url = make_url(raw_url)
    except Exception as exc:  # noqa: BLE001 - translated into a safe error
        raise DatabaseSafetyError("数据库 URL 无法解析") from exc
    if url.get_backend_name() != "mysql" or url.get_driver_name() not in _SAFE_MYSQL_DRIVERS:
        raise DatabaseSafetyError("测试隔离仅支持 mysql+aiomysql 或 mysql+asyncmy URL")
    if not url.host:
        raise DatabaseSafetyError("测试数据库 URL 必须包含主机名")
    return url


def _render_url(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def build_database_plan(
    base_url: str,
    *,
    explicit_test_url: str | None = None,
    run_token: str | None = None,
    worker_id: str | None = None,
) -> IsolatedDatabasePlan:
    """Select an explicit test DB or derive a unique DB from server credentials.

    The base database name is never reused. Without ``explicit_test_url`` a new
    name is generated and owned by this run. Explicit databases are validated but
    never considered owned, so cleanup will not drop them.
    """

    worker = worker_id or os.environ.get("PYTEST_XDIST_WORKER", "master")
    token = run_token or os.environ.get("PYTEST_XDIST_TESTRUNUID") or uuid.uuid4().hex

    if explicit_test_url:
        test_url = _validated_mysql_url(explicit_test_url)
        name = validate_test_database_name(test_url.database)
        return IsolatedDatabasePlan(
            database_url=_render_url(test_url),
            admin_url=_render_url(test_url.set(database="mysql")),
            database_name=name,
            run_token=token,
            worker_id=worker,
            created_by_run=False,
        )

    source_url = _validated_mysql_url(base_url)
    name = generated_database_name(token, worker)
    return IsolatedDatabasePlan(
        database_url=_render_url(source_url.set(database=name)),
        admin_url=_render_url(source_url.set(database="mysql")),
        database_name=name,
        run_token=token,
        worker_id=worker,
        created_by_run=True,
    )


def is_drop_authorized(plan: IsolatedDatabasePlan) -> bool:
    """Authorize DROP only for the exact generated name bound to this token."""

    if not plan.created_by_run:
        return False
    try:
        validate_test_database_name(plan.database_name)
        expected = generated_database_name(plan.run_token, plan.worker_id)
        url_name = _validated_mysql_url(plan.database_url).database
    except DatabaseSafetyError:
        return False
    return plan.database_name == expected == url_name


def make_test_data_dir(database_name: str, *, temp_root: Path | None = None) -> Path:
    """Create an isolated data directory under an explicit or OS temp root."""

    validate_test_database_name(database_name)
    root = (temp_root or Path(tempfile.gettempdir())).resolve()
    root.mkdir(parents=True, exist_ok=True)
    # tempfile.mkdtemp applies owner-only ACLs on Windows. Sandboxed subprocesses can
    # then lose access to their own directory when the token is impersonated. A normal
    # mkdir inherits the workspace ACL while UUID entropy still prevents collisions.
    for _ in range(10):
        candidate = root / f"{_TEST_DATA_PREFIX}{database_name}-{uuid.uuid4().hex[:10]}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise DatabaseProvisionError("无法分配唯一测试数据目录")


def activate_test_environment(plan: IsolatedDatabasePlan, data_dir: Path) -> None:
    """Activate isolation before application database modules are imported."""

    os.environ["PA_DB_URL"] = plan.database_url
    os.environ["PA_DATA_DIR"] = str(data_dir)
    os.environ["PA_TEST_DATABASE_NAME"] = plan.database_name
    os.environ["PA_TEST_RUN_TOKEN"] = plan.run_token


async def _database_exists(plan: IsolatedDatabasePlan) -> bool:
    engine = create_async_engine(plan.admin_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            found = await conn.scalar(
                text(
                    "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA "
                    "WHERE SCHEMA_NAME = :name"
                ),
                {"name": plan.database_name},
            )
            return found == plan.database_name
    finally:
        await engine.dispose()


async def _provision_database(plan: IsolatedDatabasePlan) -> None:
    if not plan.created_by_run:
        engine = create_async_engine(plan.database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                selected = await conn.scalar(text("SELECT DATABASE()"))
                if selected != plan.database_name:
                    raise DatabaseSafetyError("显式测试数据库连接到了意外的 schema")
                await conn.scalar(text("SELECT 1"))
        finally:
            await engine.dispose()
        return

    if await _database_exists(plan):
        raise DatabaseProvisionError(
            f"拒绝复用已存在的自动测试数据库 {plan.database_name}"
        )

    engine = create_async_engine(
        plan.admin_url,
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql(
                f"CREATE DATABASE `{plan.database_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    except Exception as exc:  # noqa: BLE001 - provide actionable, secret-free context
        raise DatabaseProvisionError(
            f"无法创建隔离测试数据库 {plan.database_name}；"
            "请授予 CREATE/DROP DATABASE 权限，或设置严格命名的 PA_TEST_DB_URL"
        ) from exc
    finally:
        await engine.dispose()


def provision_database(plan: IsolatedDatabasePlan) -> None:
    """Synchronously create or verify the selected test database."""

    try:
        asyncio.run(_provision_database(plan))
    except (DatabaseSafetyError, DatabaseProvisionError):
        raise
    except Exception as exc:  # noqa: BLE001
        mode = "连接显式" if not plan.created_by_run else "创建"
        raise DatabaseProvisionError(
            f"无法{mode}测试数据库 {plan.database_name}；绝不回退到开发数据库"
        ) from exc


def upgrade_database(project_root: Path) -> None:
    """Run Alembic to head against the already activated test URL."""

    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("prepend_sys_path", str(project_root / "src"))
    command.upgrade(config, "head")


async def _drop_database(plan: IsolatedDatabasePlan) -> bool:
    if not is_drop_authorized(plan):
        raise DatabaseSafetyError(
            f"拒绝删除未通过名称/token 双重校验的数据库 {plan.database_name}"
        )
    if not await _database_exists(plan):
        return False
    engine = create_async_engine(
        plan.admin_url,
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"DROP DATABASE `{plan.database_name}`")
        return True
    finally:
        await engine.dispose()


def drop_database(plan: IsolatedDatabasePlan) -> bool:
    """Drop only a database proven to have been generated by this run."""

    return asyncio.run(_drop_database(plan))


def remove_test_data_dir(data_dir: Path, *, temp_root: Path | None = None) -> None:
    """Remove only helper-created directories directly under the selected root."""

    resolved = data_dir.resolve()
    expected_root = (temp_root or Path(tempfile.gettempdir())).resolve()
    if resolved.parent != expected_root or not resolved.name.startswith(_TEST_DATA_PREFIX):
        raise DatabaseSafetyError(f"拒绝删除非测试临时目录: {resolved}")
    if resolved.exists():
        def _retry_readonly(function, path, error) -> None:
            candidate = Path(path).resolve()
            if candidate != resolved and resolved not in candidate.parents:
                raise DatabaseSafetyError(
                    f"拒绝在测试临时目录之外修复删除权限: {candidate}"
                )
            if not isinstance(error, PermissionError):
                raise error
            # Git object files are commonly read-only on Windows.  Clear only that
            # attribute on the already-validated test subtree, retry once, and still
            # surface every other cleanup failure.
            os.chmod(candidate, candidate.stat().st_mode | stat.S_IWUSR)
            function(path)

        shutil.rmtree(resolved, onexc=_retry_readonly)
