"""Safety helpers for integration-test infrastructure.

This module deliberately has no database side effects.  It only resolves and
validates the database URL that test tooling is allowed to use.
"""

from __future__ import annotations

import re

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

_TEST_DATABASE_NAME = re.compile(r"(?:^|_)test(?:_|$)", re.IGNORECASE)


class UnsafeTestDatabaseError(ValueError):
    """Raised before a test process can connect to an unsafe database target."""


def _parse_database_url(raw_url: str, *, label: str) -> URL:
    try:
        url = make_url(raw_url.strip())
    except (ArgumentError, AttributeError) as exc:
        raise UnsafeTestDatabaseError(f"{label} 不是有效的 SQLAlchemy 数据库 URL") from exc
    if url.get_backend_name() != "mysql":
        raise UnsafeTestDatabaseError(f"{label} 必须使用 MySQL，当前为 {url.get_backend_name()!r}")
    if not url.database:
        raise UnsafeTestDatabaseError(f"{label} 必须包含数据库名")
    return url


def _database_identity(url: URL) -> tuple[str, str | None, str | None, int, str]:
    """Return an identity that cannot be bypassed by changing URL query options."""

    return (
        url.get_backend_name(),
        url.username,
        url.host.casefold() if url.host else None,
        url.port or 3306,
        (url.database or "").casefold(),
    )


def resolve_test_database_url(
    application_url: str,
    explicit_test_url: str | None = None,
) -> str:
    """Resolve a dedicated test URL and reject application-database targets.

    When ``explicit_test_url`` is absent, a sibling database named
    ``<application database>_test`` is selected.  The function never creates or
    connects to that database.
    """

    application = _parse_database_url(application_url, label="PA_DB_URL")
    if explicit_test_url and explicit_test_url.strip():
        candidate = _parse_database_url(explicit_test_url, label="PA_TEST_DB_URL")
    else:
        candidate = application.set(database=f"{application.database}_test")

    database_name = candidate.database or ""
    if not _TEST_DATABASE_NAME.search(database_name):
        raise UnsafeTestDatabaseError(
            "测试数据库名必须包含独立的 'test' 段，例如 personal_assistant_test"
        )
    if _database_identity(candidate) == _database_identity(application):
        raise UnsafeTestDatabaseError("测试数据库不得与 PA_DB_URL 指向同一数据库")

    return candidate.render_as_string(hide_password=False)


def display_database_target(raw_url: str) -> str:
    """Return a credential-free host/database label for operator confirmation."""

    url = _parse_database_url(raw_url, label="测试数据库 URL")
    host = url.host or "localhost"
    port = url.port or 3306
    return f"{host}:{port}/{url.database}"

