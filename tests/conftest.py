"""pytest fixtures。"""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from personal_assistant.config import settings as cfg
from personal_assistant.core.db import engine
from personal_assistant.main_api import app


@pytest_asyncio.fixture
async def db():
    """独立 engine 的 db session。

    每个测试用独立 engine，测试结束 dispose，避免跨测试 event loop
    共享 aiomysql 连接导致的清理错误（Windows proactor）。
    """
    engine = create_async_engine(
        cfg.db_url,
        pool_pre_ping=True,
        connect_args={"init_command": "SET time_zone='+00:00'"},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    """FastAPI 测试客户端（ASGITransport，不走真实端口）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await engine.dispose()
