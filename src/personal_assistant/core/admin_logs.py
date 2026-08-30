"""Bounded, read-only access to explicitly configured service logs.

No shell commands, directory browsing, user-supplied paths, or log downloads.
"""
from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MAX_TAIL_BYTES = 256 * 1024
MAX_LINES = 1000
_HIDDEN = "[已隐藏可能包含凭据的日志内容]"
_SENSITIVE = re.compile(
    r"password|passwd|pwd\s*[:=]|secret|token|api[_ -]?key|authorization|"
    r"cookie|credential|private[_ -]?key|BEGIN .*KEY|END .*KEY",
    re.IGNORECASE,
)
_PEM = re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|\Z)", re.S)
_BASE64_LINE = re.compile(r"^[A-Za-z0-9+/=]{48,}$")
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_URL_CREDENTIALS = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@", re.I)
_QUERY = re.compile(r"\?[^\s\"'<>]*")


@dataclass(frozen=True)
class LogSource:
    id: str
    label: str
    path: Path | None


class LogUnavailable(Exception):
    """Safe public error; never includes a filesystem path or OS error."""


def redact_log(text: str) -> str:
    """Mask credential-bearing lines and URL queries before any filtering."""
    text = _PEM.sub(_HIDDEN, text)
    # A bounded tail may start inside a PEM block: hide its remaining prefix.
    if re.search(r"-----END [^-]*PRIVATE KEY-----", text):
        text = re.sub(r"\A.*?-----END [^-]*PRIVATE KEY-----", _HIDDEN, text, flags=re.S)
    output = []
    for line in _ANSI.sub("", text).splitlines():
        line = "".join(c for c in line if c == "\t" or ord(c) >= 32)
        if _SENSITIVE.search(line) or _BASE64_LINE.fullmatch(line.strip()):
            output.append(_HIDDEN)
        else:
            line = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", line)
            output.append(_QUERY.sub("?[REDACTED]", line))
    return "\n".join(output)


def _open_log(path: Path | None) -> int:
    if path is None:
        raise LogUnavailable("该日志尚未配置")
    if not path.is_absolute() or ".." in path.parts:
        raise LogUnavailable("日志路径配置不可用")
    descriptor = None
    try:
        # Log directories must be controlled by the service administrator.
        if path.resolve(strict=True) != path or path.is_symlink():
            raise LogUnavailable("日志路径包含链接，已拒绝读取")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise LogUnavailable("日志不是普通文件")
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(path, flags)
        actual = os.fstat(descriptor)
        if not stat.S_ISREG(actual.st_mode) or (before.st_dev, before.st_ino) != (actual.st_dev, actual.st_ino):
            raise LogUnavailable("日志正在轮转，请刷新重试")
        return descriptor
    except Exception as error:
        if descriptor is not None:
            os.close(descriptor)
        if isinstance(error, LogUnavailable):
            raise
        if isinstance(error, FileNotFoundError):
            raise LogUnavailable("日志尚未生成或已轮转") from None
        if isinstance(error, PermissionError):
            raise LogUnavailable("服务账号没有该日志的只读权限") from None
        raise LogUnavailable("暂时无法读取该日志") from None


def source_status(source: LogSource) -> dict:
    try:
        descriptor = _open_log(source.path)
        os.close(descriptor)
        return {"id": source.id, "label": source.label, "available": True, "message": ""}
    except LogUnavailable as error:
        return {"id": source.id, "label": source.label, "available": False, "message": str(error)}


def read_log_tail(source: LogSource, *, lines: int = 200, search: str = "") -> dict:
    """Read only a bounded tail; filtering applies to the redacted tail, not the file."""
    if not 1 <= lines <= MAX_LINES or len(search) > 100:
        raise ValueError("日志查询参数超出范围")
    descriptor = _open_log(source.path)
    try:
        with os.fdopen(descriptor, "rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            offset = max(0, size - MAX_TAIL_BYTES)
            stream.seek(offset)
            raw = stream.read(MAX_TAIL_BYTES)
    except OSError:
        raise LogUnavailable("日志读取失败，请刷新重试") from None
    if offset:
        # Never expose a suffix of a truncated line (including partial secrets).
        raw = raw.partition(b"\n")[2]
    safe_lines = redact_log(raw.decode("utf-8", errors="replace")).splitlines()
    query = search.strip().casefold()
    selected = [line for line in safe_lines if not query or query in line.casefold()]
    return {
        "source": source.id,
        "label": source.label,
        "lines": selected[-lines:],
        "truncated": bool(offset or len(selected) > lines),
        "scanned_bytes": len(raw),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
