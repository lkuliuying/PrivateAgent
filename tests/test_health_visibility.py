"""健康信息的角色边界；所有数据库访问与依赖探测均使用测试替身。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from personal_assistant.api import routes_admin, routes_health, security
from personal_assistant.core import db as db_module
from personal_assistant.core.auth import Principal
from personal_assistant.core.health import HealthService

SERVICE_TOKEN = "health-visibility-test-service-token"
PRIVATE_HEALTH = {
    "api": {"ok": True},
    "mysql": {"ok": False, "error": "private diagnostic detail"},
    "chroma": {"ok": True, "path": "/private/test-data", "collections": 7},
}


@pytest.fixture
def health_app(monkeypatch):
    probe = AsyncMock(return_value=PRIVATE_HEALTH)
    monkeypatch.setattr(HealthService, "check_all", probe)
    db = AsyncMock()
    db.execute.return_value = Mock(scalar_one=Mock(return_value=0))

    @asynccontextmanager
    async def fake_session():
        yield db

    async def dependency_session():
        yield db

    async def token_principal(_db, token):
        if token not in {"admin-session", "user-session"}:
            return None
        return Principal(
            user_id=1 if token == "admin-session" else 2,
            role="admin" if token == "admin-session" else "user",
            email=None,
            actor_type="user",
        )

    monkeypatch.setattr(db_module, "async_session_factory", fake_session)
    monkeypatch.setattr(security, "principal_for_token", token_principal)
    app = FastAPI()
    app.include_router(routes_health.router)
    app.include_router(routes_admin.router)
    app.dependency_overrides[db_module.get_session] = dependency_session
    app.add_middleware(
        security.LocalApiSecurityMiddleware,
        auth_enabled=True,
        token=SERVICE_TOKEN,
        allowed_hosts=("testserver",),
        allowed_origins=(),
    )
    return app, probe


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [None, "invalid-session"])
async def test_health_still_requires_valid_authentication(health_app, token):
    app, probe = health_app
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/health", headers=headers)
    assert response.status_code == 401
    probe.assert_not_awaited()


@pytest.mark.asyncio
async def test_regular_user_only_receives_liveness_without_dependency_probe(health_app):
    app, probe = health_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(
            "/health",
            headers={"Authorization": "Bearer user-session", "X-Role": "admin"},
        )
    assert response.status_code == 200
    assert response.json() == {"api": {"ok": True}}
    probe.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["admin-session", SERVICE_TOKEN])
async def test_admin_and_maintenance_token_keep_detailed_health(health_app, token):
    app, probe = health_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/health", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == PRIVATE_HEALTH
    probe.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("principal", [None, SimpleNamespace(is_admin=True)])
async def test_missing_or_unverified_principal_never_receives_details(monkeypatch, principal):
    probe = AsyncMock(return_value=PRIVATE_HEALTH)
    monkeypatch.setattr(HealthService, "check_all", probe)
    request = Request({"type": "http", "method": "GET", "path": "/health"})
    request.state.principal = principal
    assert await routes_health.health(request) == {"api": {"ok": True}}
    probe.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("token, status", [("user-session", 403), ("admin-session", 200)])
async def test_admin_overview_keeps_health_behind_admin_authorization(health_app, token, status):
    app, probe = health_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/admin/overview", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == status
    if status == 200:
        assert response.json()["health"] == PRIVATE_HEALTH
        probe.assert_awaited_once()
    else:
        assert "health" not in response.json()
        probe.assert_not_awaited()
