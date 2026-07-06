"""统一 UTC 时间工具。

整个应用统一使用 naive UTC 时间戳，避免 MySQL ``CURRENT_TIMESTAMP``（随会话时区，
默认 SYSTEM=OS 时区）与 Python ``datetime.now()``（本地时区）混用导致的时区偏移。

配合 ``core/db.py`` 的 ``SET time_zone='+00:00'``，让 DB 服务端时间与 Python 时间
同处 UTC 基准，保证同一行内 created_at / started_at / finished_at 时间一致。
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """naive UTC now（MySQL DATETIME 不存时区）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)
