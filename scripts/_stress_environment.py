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
import math
import re
import secrets
import shutil
import stat
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, TypeVar
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
_T = TypeVar("_T")


class StressSafetyError(RuntimeError):
    """Raised when isolation or cleanup cannot be proven safe."""


class StressProvisionError(RuntimeError):
    """Raised when an isolated dependency cannot be provisioned."""

    def __init__(self, message: str, *, database_created: bool = False) -> None:
        super().__init__(message)
        self.database_created = database_created


@dataclass(frozen=True, slots=True)
class DatabaseTimeouts:
    """Deadlines for stress-schema I/O and deterministic resource cleanup."""

    connect_seconds: float = 10.0
    operation_seconds: float = 30.0
    cleanup_seconds: float = 10.0

    def __post_init__(self) -> None:
        for name, value in (
            ("connect_seconds", self.connect_seconds),
            ("operation_seconds", self.operation_seconds),
            ("cleanup_seconds", self.cleanup_seconds),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")


DEFAULT_DATABASE_TIMEOUTS = DatabaseTimeouts()


class _DatabasePhaseTimeout(TimeoutError):
    """Internal timeout whose message never contains connection details."""

    def __init__(self, phase: str) -> None:
        super().__init__(f"database {phase} exceeded its configured deadline")
        self.phase = phase


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
    except Exception:  # noqa: BLE001 - discard credential-bearing parser details
        raise StressSafetyError("PA_STRESS_MYSQL_URL is not a valid URL") from None
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


def load_environment_for_cleanup(
    base_url: str,
    *,
    run_id: str,
    allow_remote: bool = False,
    temp_root: Path | None = None,
) -> StressEnvironment:
    """Rebuild a cleanup target from trusted inputs and its exact ownership marker.

    This is intended for an outer watchdog after a worker process is terminated.
    The marker contributes only the nonce; paths, URLs and the database name are
    independently derived from caller-supplied inputs before all fields are
    compared again by :func:`is_cleanup_authorized`.
    """

    source = _validated_mysql_url(base_url, allow_remote=allow_remote)
    validated_run_id = validate_run_id(run_id)
    database_name = generated_database_name(validated_run_id)
    root = (temp_root or Path(tempfile.gettempdir())).resolve()
    expected = root / f"{STRESS_DATA_PREFIX}{validated_run_id}"
    marker_path = expected / _MARKER_NAME
    try:
        if not root.is_dir() or expected.is_symlink() or marker_path.is_symlink():
            raise StressSafetyError("stress cleanup marker path is not a regular path")
        resolved = expected.resolve(strict=True)
        resolved_marker = marker_path.resolve(strict=True)
        if (
            not resolved.is_dir()
            or resolved != expected
            or resolved.parent != root
            or resolved_marker.parent != resolved
            or not resolved_marker.is_file()
        ):
            raise StressSafetyError("stress cleanup marker escaped its expected directory")
        marker = json.loads(resolved_marker.read_text(encoding="utf-8"))
    except StressSafetyError:
        raise
    except (OSError, ValueError, json.JSONDecodeError):
        raise StressSafetyError("unable to load a valid stress cleanup marker") from None
    if not isinstance(marker, dict) or set(marker) != {
        "run_id",
        "database_name",
        "ownership_nonce",
    }:
        raise StressSafetyError("stress cleanup marker has an invalid shape")
    ownership_nonce = marker.get("ownership_nonce")
    if (
        marker.get("run_id") != validated_run_id
        or marker.get("database_name") != database_name
        or not isinstance(ownership_nonce, str)
        or re.fullmatch(r"[0-9a-f]{64}", ownership_nonce) is None
    ):
        raise StressSafetyError("stress cleanup marker ownership fields do not match")
    environment = StressEnvironment(
        database_url=_render_url(source.set(database=database_name)),
        admin_url=_render_url(source.set(database="mysql")),
        database_name=database_name,
        run_id=validated_run_id,
        ownership_nonce=ownership_nonce,
        data_dir=resolved,
    )
    if not is_cleanup_authorized(environment):
        raise StressSafetyError("restored stress environment failed ownership validation")
    return environment


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


async def _bounded_database_await(
    awaitable: Awaitable[_T], *, timeout_seconds: float, phase: str
) -> _T:
    """Await one database phase without allowing its exception to expose a URL."""

    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as exc:
        raise _DatabasePhaseTimeout(phase) from exc


@asynccontextmanager
async def _database_connection(
    url: str,
    *,
    timeouts: DatabaseTimeouts,
    autocommit: bool = False,
) -> AsyncIterator[Any]:
    """Open, close and dispose one NullPool connection under explicit deadlines."""

    engine_kwargs: dict[str, Any] = {
        "poolclass": NullPool,
        # This is a second, driver-level bound underneath the coroutine deadline.
        "connect_args": {"connect_timeout": timeouts.connect_seconds},
    }
    if autocommit:
        engine_kwargs["isolation_level"] = "AUTOCOMMIT"
    engine = create_async_engine(url, **engine_kwargs)
    connection: Any = None
    active_error: BaseException | None = None
    try:
        connection = await _bounded_database_await(
            engine.connect(),
            timeout_seconds=timeouts.connect_seconds,
            phase="connection",
        )
        yield connection
    except BaseException as exc:  # noqa: BLE001 - cleanup before preserving failure
        active_error = exc
        raise
    finally:
        cleanup_errors: list[BaseException] = []
        if connection is not None:
            try:
                await _bounded_database_await(
                    connection.close(),
                    timeout_seconds=timeouts.cleanup_seconds,
                    phase="connection cleanup",
                )
            except BaseException as exc:  # noqa: BLE001 - still dispose the engine
                cleanup_errors.append(exc)
        try:
            await _bounded_database_await(
                engine.dispose(),
                timeout_seconds=timeouts.cleanup_seconds,
                phase="engine disposal",
            )
        except BaseException as exc:  # noqa: BLE001 - aggregate both cleanup phases
            cleanup_errors.append(exc)
        if cleanup_errors:
            if active_error is not None:
                active_error.add_note(
                    "database resource cleanup did not finish within its deadline"
                )
            else:
                raise _DatabasePhaseTimeout("resource cleanup") from cleanup_errors[0]


async def _database_exists(
    environment: StressEnvironment,
    *,
    timeouts: DatabaseTimeouts = DEFAULT_DATABASE_TIMEOUTS,
) -> bool:
    try:
        async with _database_connection(
            environment.admin_url, timeouts=timeouts
        ) as connection:
            found = await _bounded_database_await(
                connection.scalar(
                    text(
                        "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA "
                        "WHERE SCHEMA_NAME = :name"
                    ),
                    {"name": environment.database_name},
                ),
                timeout_seconds=timeouts.operation_seconds,
                phase="schema existence query",
            )
            return found == environment.database_name
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - discard credential-bearing driver details
        raise StressSafetyError(
            "unable to verify isolated stress schema within configured deadlines"
        ) from None


async def provision_database(
    environment: StressEnvironment,
    *,
    timeouts: DatabaseTimeouts = DEFAULT_DATABASE_TIMEOUTS,
) -> str:
    """Create the run-owned schema and return the server version."""

    if not is_cleanup_authorized(environment):
        raise StressSafetyError("stress environment ownership proof is invalid")
    try:
        already_exists = await _database_exists(environment, timeouts=timeouts)
    except asyncio.CancelledError:
        raise StressProvisionError(
            "isolated stress schema provisioning was cancelled before creation",
            database_created=False,
        ) from None
    except Exception:  # noqa: BLE001 - discard credential-bearing driver details
        raise StressProvisionError(
            "unable to verify that the isolated stress schema is unused",
            database_created=False,
        ) from None
    if already_exists:
        raise StressProvisionError(
            f"refusing to reuse existing stress schema {environment.database_name}"
        )

    # Once CREATE is attempted its outcome may be unknown after a timeout.  Mark
    # it conservatively so the caller performs ownership-verified cleanup.
    database_creation_attempted = False
    try:
        async with _database_connection(
            environment.admin_url,
            timeouts=timeouts,
            autocommit=True,
        ) as connection:
            version = str(
                await _bounded_database_await(
                    connection.scalar(text("SELECT VERSION()")),
                    timeout_seconds=timeouts.operation_seconds,
                    phase="server version query",
                )
            )
            database_creation_attempted = True
            await _bounded_database_await(
                connection.exec_driver_sql(
                    f"CREATE DATABASE `{environment.database_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                ),
                timeout_seconds=timeouts.operation_seconds,
                phase="schema creation",
            )
            await _bounded_database_await(
                connection.exec_driver_sql(
                    f"CREATE TABLE `{environment.database_name}`.`{_OWNERSHIP_TABLE}` ("
                    "run_id VARCHAR(64) NOT NULL PRIMARY KEY, "
                    "ownership_nonce CHAR(64) NOT NULL)"
                ),
                timeout_seconds=timeouts.operation_seconds,
                phase="ownership table creation",
            )
            await _bounded_database_await(
                connection.execute(
                    text(
                        f"INSERT INTO `{environment.database_name}`.`{_OWNERSHIP_TABLE}` "
                        "(run_id, ownership_nonce) VALUES (:run_id, :ownership_nonce)"
                    ),
                    {
                        "run_id": environment.run_id,
                        "ownership_nonce": environment.ownership_nonce,
                    },
                ),
                timeout_seconds=timeouts.operation_seconds,
                phase="ownership record creation",
            )
        return version
    except asyncio.CancelledError:
        raise StressProvisionError(
            "isolated stress schema provisioning was cancelled",
            database_created=database_creation_attempted,
        ) from None
    except Exception:  # noqa: BLE001 - discard credential-bearing driver details
        raise StressProvisionError(
            "unable to create isolated pa_stress_* schema within configured deadlines; "
            "grant CREATE/DROP DATABASE",
            database_created=database_creation_attempted,
        ) from None


async def drop_database(
    environment: StressEnvironment,
    *,
    timeouts: DatabaseTimeouts = DEFAULT_DATABASE_TIMEOUTS,
) -> bool:
    """Drop only the exact run-owned schema.  Any proof failure is fatal."""

    if not is_cleanup_authorized(environment):
        raise StressSafetyError("refusing to drop schema without ownership proof")
    try:
        exists = await _database_exists(environment, timeouts=timeouts)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - discard credential-bearing driver details
        raise StressSafetyError(
            "refusing to drop schema because its existence could not be verified"
        ) from None
    if not exists:
        return False

    try:
        async with _database_connection(
            environment.database_url, timeouts=timeouts
        ) as connection:
            result = await _bounded_database_await(
                connection.execute(
                    text(
                        f"SELECT run_id, ownership_nonce FROM `{_OWNERSHIP_TABLE}` "
                        "WHERE run_id = :run_id"
                    ),
                    {"run_id": environment.run_id},
                ),
                timeout_seconds=timeouts.operation_seconds,
                phase="ownership verification",
            )
            row = result.one_or_none()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - discard credential-bearing driver details
        raise StressSafetyError(
            "refusing to drop schema without database ownership proof"
        ) from None
    if row is None or row.ownership_nonce != environment.ownership_nonce:
        raise StressSafetyError(
            "refusing to drop schema whose ownership nonce does not match"
        )

    try:
        async with _database_connection(
            environment.admin_url,
            timeouts=timeouts,
            autocommit=True,
        ) as connection:
            await _bounded_database_await(
                connection.exec_driver_sql(
                    f"DROP DATABASE `{environment.database_name}`"
                ),
                timeout_seconds=timeouts.operation_seconds,
                phase="schema removal",
            )
        if await _database_exists(environment, timeouts=timeouts):
            raise StressProvisionError(
                "DROP DATABASE returned but isolated stress schema still exists"
            )
        return True
    except asyncio.CancelledError:
        raise
    except StressProvisionError:
        raise
    except Exception:  # noqa: BLE001 - discard credential-bearing driver details
        raise StressSafetyError(
            "isolated stress schema cleanup did not finish within configured deadlines"
        ) from None


def remove_data_dir(
    environment: StressEnvironment, *, temp_root: Path | None = None
) -> None:
    """Remove only the marker-verified, direct child created for this run."""

    root = (temp_root or Path(tempfile.gettempdir())).resolve()
    expected = root / f"{STRESS_DATA_PREFIX}{environment.run_id}"
    lexical = environment.data_dir.absolute()
    is_junction = getattr(environment.data_dir, "is_junction", lambda: False)
    if (
        lexical != expected
        or environment.data_dir.is_symlink()
        or is_junction()
    ):
        raise StressSafetyError("refusing linked or unexpected stress data directory")
    resolved = environment.data_dir.resolve(strict=True)
    if (
        resolved != expected
        or resolved.parent != root
        or not is_cleanup_authorized(environment)
    ):
        raise StressSafetyError("refusing to remove unverified stress data directory")
    # Repeat link/identity checks immediately before rmtree. Python 3.12+ on
    # Windows removes a junction itself rather than traversing it, while these
    # checks additionally fail closed if the owned path was swapped after proof.
    if (
        environment.data_dir.is_symlink()
        or is_junction()
        or environment.data_dir.resolve(strict=True) != expected
    ):
        raise StressSafetyError("stress data directory changed during cleanup")

    def _retry_readonly(function, path, error) -> None:
        candidate = Path(path).resolve()
        if candidate != resolved and resolved not in candidate.parents:
            raise StressSafetyError(f"cleanup escaped stress directory: {candidate}")
        if not isinstance(error, PermissionError):
            raise error
        candidate.chmod(candidate.stat().st_mode | stat.S_IWUSR)
        function(path)

    shutil.rmtree(resolved, onexc=_retry_readonly)


def provision_database_sync(
    environment: StressEnvironment,
    *,
    timeouts: DatabaseTimeouts = DEFAULT_DATABASE_TIMEOUTS,
) -> str:
    return asyncio.run(provision_database(environment, timeouts=timeouts))


def drop_database_sync(
    environment: StressEnvironment,
    *,
    timeouts: DatabaseTimeouts = DEFAULT_DATABASE_TIMEOUTS,
) -> bool:
    return asyncio.run(drop_database(environment, timeouts=timeouts))
