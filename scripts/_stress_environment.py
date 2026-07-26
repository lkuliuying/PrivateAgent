"""Fail-closed isolation helpers for real-service stress runs.

The stress harness needs real MySQL credentials, but it must never point the
application at the configured application schema.  This module derives a fresh
``pa_stress_*`` schema for every run and only authorizes deletion when the
schema name, URL and run token all agree.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import secrets
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

STRESS_DATABASE_PREFIX = "pa_stress_"
STRESS_DATA_PREFIX = "pa-stress-data-"
_DATABASE_RE = re.compile(r"^pa_stress_[a-z0-9_]{1,53}$")
_SAFE_MYSQL_DRIVERS = {"aiomysql", "asyncmy"}
_MARKER_NAME = ".pa-stress-run.json"
_OWNERSHIP_TABLE = "_pa_stress_ownership"


class StressSafetyError(RuntimeError):
    """Raised when isolation or cleanup cannot be proven safe."""


class StressProvisionError(RuntimeError):
    """Raised when an isolated dependency cannot be provisioned."""

    def __init__(self, message: str, *, database_created: bool = False) -> None:
        super().__init__(message)
        self.database_created = database_created


@dataclass(frozen=True, slots=True)
class StressEnvironment:
    database_url: str
    admin_url: str
    database_name: str
    run_id: str
    ownership_nonce: str
    data_dir: Path
    created_by_run: bool = True


def validate_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{7,63}", run_id):
        raise StressSafetyError(
            "stress run id must be 8-64 lowercase letters, digits, '_' or '-'"
        )
    return run_id


def generated_database_name(run_id: str) -> str:
    """Return a bounded MySQL identifier cryptographically bound to *run_id*."""

    validate_run_id(run_id)
    slug = re.sub(r"[^a-z0-9]+", "_", run_id).strip("_")
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12]
    name = f"{STRESS_DATABASE_PREFIX}{slug[:35].rstrip('_')}_{digest}"
    return validate_database_name(name)


def validate_database_name(name: str | None) -> str:
    if not name or len(name) > 64 or not _DATABASE_RE.fullmatch(name):
        raise StressSafetyError(
            "stress database name must strictly match pa_stress_[a-z0-9_]+"
        )
    return name


def _validated_mysql_url(raw_url: str, *, allow_remote: bool) -> URL:
    try:
        url = make_url(raw_url)
    except Exception as exc:  # noqa: BLE001 - convert to secret-free error
        raise StressSafetyError("PA_STRESS_MYSQL_URL is not a valid URL") from exc
    if url.get_backend_name() != "mysql" or url.get_driver_name() not in _SAFE_MYSQL_DRIVERS:
        raise StressSafetyError(
            "stress MySQL URL must use mysql+aiomysql or mysql+asyncmy"
        )
    if not url.host or not url.username:
        raise StressSafetyError("stress MySQL URL must include a host and username")
    if not allow_remote and not _is_loopback_host(url.host):
        raise StressSafetyError(
            "remote MySQL is disabled; pass --allow-remote-mysql explicitly"
        )
    return url


def _is_loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _render_url(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def redact_url(raw_url: str) -> str:
    """Return a report-safe endpoint without credentials, path or query values."""

    try:
        url = make_url(raw_url)
        host = url.host or "unknown"
        port = f":{url.port}" if url.port else ""
        return f"{url.get_backend_name()}://{host}{port}/<isolated>"
    except Exception:  # noqa: BLE001
        parts = urlsplit(raw_url)
        host = parts.hostname or "unknown"
        port = f":{parts.port}" if parts.port else ""
        return urlunsplit((parts.scheme, f"{host}{port}", "", "", ""))


def make_environment(
    base_url: str,
    *,
    run_id: str,
    allow_remote: bool = False,
    temp_root: Path | None = None,
) -> StressEnvironment:
    source = _validated_mysql_url(base_url, allow_remote=allow_remote)
    database_name = generated_database_name(run_id)
    root = (temp_root or Path(tempfile.gettempdir())).resolve()
    root.mkdir(parents=True, exist_ok=True)
    data_dir = (root / f"{STRESS_DATA_PREFIX}{run_id}").resolve()
    if data_dir.parent != root or not data_dir.name.startswith(STRESS_DATA_PREFIX):
        raise StressSafetyError("refusing unsafe stress data directory")
    try:
        data_dir.mkdir()
    except FileExistsError as exc:
        raise StressProvisionError(
            f"refusing to reuse existing stress data directory: {data_dir}"
        ) from exc
    ownership_nonce = secrets.token_hex(32)
    marker = {
        "run_id": run_id,
        "database_name": database_name,
        "ownership_nonce": ownership_nonce,
    }
    (data_dir / _MARKER_NAME).write_text(
        json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8"
    )
    return StressEnvironment(
        database_url=_render_url(source.set(database=database_name)),
        admin_url=_render_url(source.set(database="mysql")),
        database_name=database_name,
        run_id=run_id,
        ownership_nonce=ownership_nonce,
        data_dir=data_dir,
    )


def is_cleanup_authorized(environment: StressEnvironment) -> bool:
    if not environment.created_by_run:
        return False
    try:
        validate_run_id(environment.run_id)
        validate_database_name(environment.database_name)
        url = _validated_mysql_url(environment.database_url, allow_remote=True)
        admin_url = _validated_mysql_url(environment.admin_url, allow_remote=True)
        marker = json.loads(
            (environment.data_dir / _MARKER_NAME).read_text(encoding="utf-8")
        )
    except (OSError, ValueError, StressSafetyError, json.JSONDecodeError):
        return False
    return (
        environment.database_name == generated_database_name(environment.run_id)
        and url.database == environment.database_name
        and admin_url.database == "mysql"
        and (
            url.drivername,
            url.username,
            url.password,
            url.host,
            url.port,
            dict(url.query),
        )
        == (
            admin_url.drivername,
            admin_url.username,
            admin_url.password,
            admin_url.host,
            admin_url.port,
            dict(admin_url.query),
        )
        and marker
        == {
            "run_id": environment.run_id,
            "database_name": environment.database_name,
            "ownership_nonce": environment.ownership_nonce,
        }
        and environment.data_dir.name == f"{STRESS_DATA_PREFIX}{environment.run_id}"
    )


async def _database_exists(environment: StressEnvironment) -> bool:
    engine = create_async_engine(environment.admin_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            found = await connection.scalar(
                text(
                    "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA "
                    "WHERE SCHEMA_NAME = :name"
                ),
                {"name": environment.database_name},
            )
            return found == environment.database_name
    finally:
        await engine.dispose()


async def provision_database(environment: StressEnvironment) -> str:
    """Create the run-owned schema and return the server version."""

    if not is_cleanup_authorized(environment):
        raise StressSafetyError("stress environment ownership proof is invalid")
    if await _database_exists(environment):
        raise StressProvisionError(
            f"refusing to reuse existing stress schema {environment.database_name}"
        )
    engine = create_async_engine(
        environment.admin_url,
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    database_created = False
    try:
        async with engine.connect() as connection:
            version = str(await connection.scalar(text("SELECT VERSION()")))
            await connection.exec_driver_sql(
                f"CREATE DATABASE `{environment.database_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            database_created = True
            await connection.exec_driver_sql(
                f"CREATE TABLE `{environment.database_name}`.`{_OWNERSHIP_TABLE}` ("
                "run_id VARCHAR(64) NOT NULL PRIMARY KEY, "
                "ownership_nonce CHAR(64) NOT NULL)"
            )
            await connection.execute(
                text(
                    f"INSERT INTO `{environment.database_name}`.`{_OWNERSHIP_TABLE}` "
                    "(run_id, ownership_nonce) VALUES (:run_id, :ownership_nonce)"
                ),
                {
                    "run_id": environment.run_id,
                    "ownership_nonce": environment.ownership_nonce,
                },
            )
        return version
    except Exception as exc:  # noqa: BLE001 - never include credential-bearing URL
        raise StressProvisionError(
            "unable to create isolated pa_stress_* schema; grant CREATE/DROP DATABASE",
            database_created=database_created,
        ) from exc
    finally:
        await engine.dispose()


async def drop_database(environment: StressEnvironment) -> bool:
    """Drop only the exact run-owned schema.  Any proof failure is fatal."""

    if not is_cleanup_authorized(environment):
        raise StressSafetyError("refusing to drop schema without ownership proof")
    if not await _database_exists(environment):
        return False
    ownership_engine = create_async_engine(
        environment.database_url, poolclass=NullPool
    )
    try:
        async with ownership_engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        f"SELECT run_id, ownership_nonce FROM `{_OWNERSHIP_TABLE}` "
                        "WHERE run_id = :run_id"
                    ),
                    {"run_id": environment.run_id},
                )
            ).one_or_none()
    except Exception as exc:  # noqa: BLE001 - absence/mismatch must fail closed
        raise StressSafetyError(
            "refusing to drop schema without database ownership proof"
        ) from exc
    finally:
        await ownership_engine.dispose()
    if row is None or row.ownership_nonce != environment.ownership_nonce:
        raise StressSafetyError(
            "refusing to drop schema whose ownership nonce does not match"
        )
    engine = create_async_engine(
        environment.admin_url,
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql(
                f"DROP DATABASE `{environment.database_name}`"
            )
        if await _database_exists(environment):
            raise StressProvisionError(
                "DROP DATABASE returned but isolated stress schema still exists"
            )
        return True
    finally:
        await engine.dispose()


def remove_data_dir(
    environment: StressEnvironment, *, temp_root: Path | None = None
) -> None:
    """Remove only the marker-verified, direct child created for this run."""

    root = (temp_root or Path(tempfile.gettempdir())).resolve()
    resolved = environment.data_dir.resolve()
    if resolved.parent != root or not is_cleanup_authorized(environment):
        raise StressSafetyError("refusing to remove unverified stress data directory")
    if not resolved.exists():
        return

    def _retry_readonly(function, path, error) -> None:
        candidate = Path(path).resolve()
        if candidate != resolved and resolved not in candidate.parents:
            raise StressSafetyError(f"cleanup escaped stress directory: {candidate}")
        if not isinstance(error, PermissionError):
            raise error
        candidate.chmod(candidate.stat().st_mode | stat.S_IWUSR)
        function(path)

    shutil.rmtree(resolved, onexc=_retry_readonly)


def provision_database_sync(environment: StressEnvironment) -> str:
    return asyncio.run(provision_database(environment))


def drop_database_sync(environment: StressEnvironment) -> bool:
    return asyncio.run(drop_database(environment))
