"""统一 UTC 时间工具。

整个应用统一使用 naive UTC 时间戳，避免 MySQL ``CURRENT_TIMESTAMP``（随会话时区，
默认 SYSTEM=OS 时区）与 Python ``datetime.now()``（本地时区）混用导致的时区偏移。

配合 ``core/db.py`` 的 ``SET time_zone='+00:00'``，让 DB 服务端时间与 Python 时间
同处 UTC 基准，保证同一行内 created_at / started_at / finished_at 时间一致。

v0.9.0 H0 §5（会话时间与产品时区）：
- 数据库继续保存 naive UTC instant 作为唯一排序事实（不改写历史值）；
- API 序列化统一使用带 ``Z`` 的 RFC 3339（``format_rfc3339_utc``）；
- 产品时区固定为 IANA ``Asia/Shanghai``（24 小时制），由客户端统一转换显示。
"""
from __future__ import annotations

from datetime import datetime, timezone

# 产品时区（v0.9.0 H0 §5）：固定 IANA 名称，不随操作系统时区漂移。
PRODUCT_TIMEZONE = "Asia/Shanghai"


def utcnow() -> datetime:
    """naive UTC now（MySQL DATETIME 不存时区）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def format_rfc3339_utc(value: datetime | None) -> str | None:
    """将（naive/aware）datetime 统一序列化为带 ``Z`` 的 RFC 3339 UTC 字符串。

    - naive 值按 UTC 解释（与 ``utcnow``/DB ``time_zone='+00:00'`` 约定一致）；
    - aware 值先转换到 UTC 再格式化；
    - 毫秒精度（fsp=3）与 DB 列对齐；
    - None 返回 None（可空时间字段）。
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="milliseconds") + "Z"
