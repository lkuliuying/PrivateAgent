"""异步数据库引擎与 Session 工厂。"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config import settings

# pool_pre_ping：连接前 ping，避免 MySQL 断连后首请求失败
# pool_recycle：MySQL 默认 wait_timeout 8h，这里保守回收
# init_command：每条新连接设会话时区为 UTC，使 CURRENT_TIMESTAMP 与 Python naive UTC
#   （core/timeutil.utcnow）一致，避免 activities 等表内时间戳时区偏移。
engine = create_async_engine(
    settings.db_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    future=True,
    connect_args={"init_command": "SET time_zone='+00:00'"},
)

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：提供一个异步 Session，请求结束自动关闭。"""
    async with async_session_factory() as session:
        yield session
