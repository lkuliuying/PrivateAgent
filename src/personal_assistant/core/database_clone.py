"""Verified MySQL database clones for reversible application upgrades.

The clone is intentionally a separate database on the same MySQL server.  A
logical dump is streamed through an anonymous temporary file and credentials
are passed only in the child-process environment, never in argv or reports.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_$]{1,64}$")


class DatabaseCloneError(RuntimeError):
    """A clone was rejected or could not be verified."""


@dataclass(frozen=True, slots=True)
class DatabaseSnapshot:
    database: str
    schema_head: str | None
    table_counts: dict[str, int]

    @property
    def total_rows(self) -> int:
        return sum(self.table_counts.values())

    @property
    def counts_sha256(self) -> str:
        canonical = "\n".join(
            f"{name}:{self.table_counts[name]}" for name in sorted(self.table_counts)
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DatabaseCloneResult:
    source: DatabaseSnapshot
    clone: DatabaseSnapshot
    created_at: str
    verified: bool

    def to_manifest(self) -> dict:
        payload = asdict(self)
        payload["source"]["total_rows"] = self.source.total_rows
        payload["source"]["counts_sha256"] = self.source.counts_sha256
        payload["clone"]["total_rows"] = self.clone.total_rows
        payload["clone"]["counts_sha256"] = self.clone.counts_sha256
        return payload


def build_clone_name(source_database: str, *, now: datetime | None = None) -> str:
    _require_identifier(source_database, label="source database")
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d%H%M%S")
    suffix = f"_preupgrade_{stamp}"
    prefix = source_database[: 64 - len(suffix)]
    return f"{prefix}{suffix}"


def validate_clone_name(source_database: str, clone_database: str) -> None:
    _require_identifier(source_database, label="source database")
    _require_identifier(clone_database, label="clone database")
    prefix_length = 64 - len("_preupgrade_") - 14
    expected_prefix = f"{source_database[:prefix_length]}_preupgrade_"
    if clone_database == source_database or not clone_database.startswith(expected_prefix):
        raise DatabaseCloneError(
            "clone database must use the source-specific _preupgrade_ prefix"
        )
    timestamp = clone_database.rsplit("_preupgrade_", 1)[-1]
    if not re.fullmatch(r"[0-9]{14}", timestamp):
        raise DatabaseCloneError("clone database must end in a 14-digit UTC timestamp")


def compare_snapshots(source: DatabaseSnapshot, clone: DatabaseSnapshot) -> list[str]:
    issues: list[str] = []
    if source.schema_head != clone.schema_head:
        issues.append("schema head mismatch")
    source_tables = set(source.table_counts)
    clone_tables = set(clone.table_counts)
    if source_tables != clone_tables:
        issues.append("table set mismatch")
    for table in sorted(source_tables & clone_tables):
        if source.table_counts[table] != clone.table_counts[table]:
            issues.append(f"row count mismatch: {table}")
    return issues


async def create_verified_database_clone(
    db_url: str | URL,
    *,
    clone_database: str | None = None,
    mysqldump_executable: str | Path | None = None,
    mysql_executable: str | Path | None = None,
    timeout_seconds: int = 900,
) -> DatabaseCloneResult:
    source_url = make_url(db_url)
    if not source_url.database:
        raise DatabaseCloneError("database URL does not name a source database")
    source_database = source_url.database
    clone_database = clone_database or build_clone_name(source_database)
    validate_clone_name(source_database, clone_database)
    timeout_seconds = max(30, min(int(timeout_seconds), 3_600))

    dump_binary = _resolve_binary(mysqldump_executable, "mysqldump")
    mysql_binary = _resolve_binary(mysql_executable, "mysql")
    source_snapshot = await snapshot_database(source_url)
    await _create_empty_clone_database(source_url, clone_database)

    try:
        await asyncio.to_thread(
            _copy_database,
            source_url,
            clone_database,
            dump_binary,
            mysql_binary,
            timeout_seconds,
        )
        clone_snapshot = await snapshot_database(source_url.set(database=clone_database))
    except Exception as exc:
        raise DatabaseCloneError(
            f"database clone failed; incomplete clone retained as {clone_database}: "
            f"{type(exc).__name__}"
        ) from exc

    issues = compare_snapshots(source_snapshot, clone_snapshot)
    if issues:
        raise DatabaseCloneError(
            f"database clone verification failed for {clone_database}: " + "; ".join(issues[:10])
        )
    return DatabaseCloneResult(
        source=source_snapshot,
        clone=clone_snapshot,
        created_at=datetime.now(timezone.utc).isoformat(),
        verified=True,
    )


async def snapshot_database(db_url: str | URL) -> DatabaseSnapshot:
    url = make_url(db_url)
    database = url.database or ""
    _require_identifier(database, label="database")
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            table_names = list(
                (
                    await connection.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = :database AND table_type = 'BASE TABLE' "
                            "ORDER BY table_name"
                        ),
                        {"database": database},
                    )
                ).scalars()
            )
            counts: dict[str, int] = {}
            for raw_name in table_names:
                name = str(raw_name)
                quoted = name.replace("`", "``")
                total = await connection.scalar(text(f"SELECT COUNT(*) FROM `{quoted}`"))
                counts[name] = int(total or 0)
            try:
                schema_head = await connection.scalar(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                )
            except Exception as exc:  # noqa: BLE001
                raise DatabaseCloneError("source database has no readable Alembic version") from exc
    finally:
        await engine.dispose()
    return DatabaseSnapshot(
        database=database,
        schema_head=str(schema_head) if schema_head is not None else None,
        table_counts=counts,
    )


async def _create_empty_clone_database(source_url: URL, clone_database: str) -> None:
    admin_url = source_url.set(database="mysql")
    engine = create_async_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text(
                    "SELECT COUNT(*) FROM information_schema.schemata "
                    "WHERE schema_name = :database"
                ),
                {"database": clone_database},
            )
            if int(exists or 0) != 0:
                raise DatabaseCloneError(
                    f"refusing to overwrite existing clone database: {clone_database}"
                )
            source_schema = (
                await connection.execute(
                    text(
                        "SELECT default_character_set_name, default_collation_name "
                        "FROM information_schema.schemata WHERE schema_name = :database"
                    ),
                    {"database": source_url.database},
                )
            ).first()
            if source_schema is None:
                raise DatabaseCloneError("source database does not exist")
            charset, collation = map(str, source_schema)
            if not _IDENTIFIER.fullmatch(charset) or not _IDENTIFIER.fullmatch(collation):
                raise DatabaseCloneError("source database has unsafe charset metadata")
            await connection.execute(
                text(
                    f"CREATE DATABASE `{clone_database}` "
                    f"CHARACTER SET {charset} COLLATE {collation}"
                )
            )
    finally:
        await engine.dispose()


def _copy_database(
    source_url: URL,
    clone_database: str,
    dump_binary: Path,
    mysql_binary: Path,
    timeout_seconds: int,
) -> None:
    host = source_url.host or "127.0.0.1"
    port = str(source_url.port or 3306)
    user = source_url.username or ""
    if not user:
        raise DatabaseCloneError("database URL does not contain a user")
    child_env = os.environ.copy()
    child_env["MYSQL_PWD"] = source_url.password or ""
    common = [
        "--no-defaults",
        f"--host={host}",
        f"--port={port}",
        f"--user={user}",
        "--default-character-set=utf8mb4",
    ]
    dump_args = [
        str(dump_binary),
        *common,
        "--single-transaction",
        "--quick",
        "--skip-lock-tables",
        "--hex-blob",
        "--set-gtid-purged=OFF",
        "--triggers",
        source_url.database or "",
    ]
    import_args = [str(mysql_binary), *common, clone_database]

    with tempfile.TemporaryFile(mode="w+b") as dump_file:
        dumped = subprocess.run(  # noqa: S603 - fixed executable and argument array.
            dump_args,
            stdout=dump_file,
            stderr=subprocess.PIPE,
            env=child_env,
            timeout=timeout_seconds,
            check=False,
        )
        if dumped.returncode != 0:
            raise DatabaseCloneError(_safe_process_error("mysqldump", dumped))
        dump_file.seek(0)
        imported = subprocess.run(  # noqa: S603 - fixed executable and argument array.
            import_args,
            stdin=dump_file,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=child_env,
            timeout=timeout_seconds,
            check=False,
        )
        if imported.returncode != 0:
            raise DatabaseCloneError(_safe_process_error("mysql import", imported))


def _resolve_binary(explicit: str | Path | None, name: str) -> Path:
    candidate = str(explicit) if explicit is not None else shutil.which(name)
    if not candidate:
        raise DatabaseCloneError(f"{name} executable was not found")
    path = Path(candidate).resolve()
    if not path.is_file():
        raise DatabaseCloneError(f"{name} executable must be an existing absolute file")
    return path


def _safe_process_error(label: str, completed: subprocess.CompletedProcess) -> str:
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
    stderr = " ".join(stderr.split())[:1_000]
    return f"{label} exited with code {completed.returncode}: {stderr or 'no diagnostic'}"


def _require_identifier(value: str, *, label: str) -> None:
    if not _IDENTIFIER.fullmatch(value):
        raise DatabaseCloneError(f"invalid {label} identifier")
