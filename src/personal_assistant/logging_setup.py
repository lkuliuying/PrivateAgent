"""结构化日志初始化。

标准 logging 输出到控制台 + 每日滚动文件，structlog 作为上层封装提供
键值化日志接口。文件按 ``PA_LOG_RETENTION_DAYS`` 自动清理。
"""
from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler

import structlog

from .config import settings


def setup_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    settings.log_dir.mkdir(parents=True, exist_ok=True)
    log_file = settings.log_dir / "personal_assistant.log"

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)
    # 避免重复添加（reload 场景）
    if not any(
        getattr(h, "_personal_assistant_stream_handler", False)
        for h in root.handlers
    ):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler._personal_assistant_stream_handler = True  # type: ignore[attr-defined]
        root.addHandler(stream_handler)
    if not any(
        getattr(h, "_personal_assistant_file_handler", False) for h in root.handlers
    ):
        file_handler = TimedRotatingFileHandler(
            log_file,
            when="midnight",
            interval=1,
            backupCount=settings.log_retention_days,
            encoding="utf-8",
            utc=True,
        )
        file_handler.setFormatter(formatter)
        file_handler._personal_assistant_file_handler = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """获取一个结构化日志器。"""
    return structlog.get_logger(name)
