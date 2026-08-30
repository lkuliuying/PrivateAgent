"""Stateless cloud gateway: authenticated inference only, no project execution."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from personal_assistant.agents.contracts import ModelResponse
from personal_assistant.api import routes_desktop_model as routes
from personal_assistant.core.auth import Principal


class Gateway:
    def __init__(self):
        self.requests = []
        self.error = False

    async def complete(self, request, *, cancellation):
        self.requests.append(request)
        if self.error:
            raise RuntimeError("fixture-provider-credential-must-not-escape")
        return ModelResponse(text="cloud reply", provider="test", model="test")


def app_for(monkeypatch):
    gateway = Gateway()
    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        if request.headers.get("Authorization") == "Bearer test-account":
            request.state.principal = Principal(user_id=1, role="user", email="test@example.test", actor_type="user")
        return await call_next(request)

    async def db():
        yield None

    async def resolve(db, payload):
        return gateway

    monkeypatch.setattr(routes, "resolve_gateway", resolve)
    app.dependency_overrides[routes.get_session] = db
    app.include_router(routes.router)
    return app, gateway


@pytest.mark.asyncio
async def test_gateway_requires_account_and_forwards_model_contract(monkeypatch):
    app, gateway = app_for(monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://server.test") as client:
        payload = {"model_profile_id": "test", "request": {"messages": [{"role": "user", "content": "hello"}]}}
        assert (await client.post("/desktop/model/complete", json=payload)).status_code == 401
        assert gateway.requests == []
        response = await client.post("/desktop/model/complete", json=payload, headers={"Authorization": "Bearer test-account"})
        assert response.status_code == 200, response.text
        assert response.json()["text"] == "cloud reply"
        assert gateway.requests[0].messages[0].content == "hello"
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_gateway_bounds_input_rejects_project_paths_and_hides_provider_errors(monkeypatch):
    app, gateway = app_for(monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://server.test",
                                 headers={"Authorization": "Bearer test-account"}) as client:
        response = await client.post("/desktop/model/complete", content=b"x" * (routes.MAX_REQUEST_BYTES + 1))
        assert response.status_code == 413
        response = await client.post("/desktop/model/complete", json={"root_path": "C:/private", "request": {"messages": []}})
        assert response.status_code == 422 and "C:/private" not in response.text
        gateway.error = True
        response = await client.post("/desktop/model/complete", json={"request": {"messages": [{"role": "user", "content": "hi"}]}})
        assert response.status_code == 502
        assert "fixture-provider" not in response.text


@pytest.mark.asyncio
async def test_disconnected_desktop_cancels_provider_request(monkeypatch):
    disconnected = asyncio.Event()
    started = asyncio.Event()
    stopped = asyncio.Event()

    class Request:
        class State:
            principal = Principal(user_id=1, role="user", email="test@example.test", actor_type="user")
        state = State()

        async def stream(self):
            yield json.dumps({"request": {"messages": [{"role": "user", "content": "hello"}]}}).encode()

        async def is_disconnected(self):
            return disconnected.is_set()

    class Model:
        async def complete(self, request, *, cancellation):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

    async def resolve(db, payload):
        return Model()

    from fastapi import Response
    monkeypatch.setattr(routes, "resolve_gateway", resolve)
    task = asyncio.create_task(routes.complete_desktop_model(Request(), Response(), None))
    await asyncio.wait_for(started.wait(), 1)
    disconnected.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_resolver_uses_existing_profile_gateway_without_persisting_a_run(monkeypatch):
    from personal_assistant.api import routes_agent_runs
    from personal_assistant.core import model_profiles

    profile = SimpleNamespace(id="default-profile", enabled=True, is_default=True, reasoning_efforts=["low"])

    class Profiles:
        def __init__(self, db):
            pass

        async def list(self):
            return [profile]

        async def get(self, profile_id):
            return profile

    captured = []

    async def gateway(db, run):
        captured.append(run)
        return "resolved"

    monkeypatch.setattr(model_profiles, "ModelProfileService", Profiles)
    monkeypatch.setattr(routes_agent_runs, "_model_gateway_for_run", gateway)
    payload = routes.DesktopModelRequest.model_validate({"request": {"messages": [{"role": "user", "content": "test"}]}})
    assert await routes.resolve_gateway(None, payload) == "resolved"
    assert captured[0].model_profile_id == "default-profile"
    assert captured[0].id is None  # No flush/add or server run creation.
    invalid = routes.DesktopModelRequest.model_validate({"model_profile_id": "default-profile", "request": {
        "messages": [{"role": "user", "content": "test"}], "reasoning_effort": "high"}})
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        await routes.resolve_gateway(None, invalid)
    assert error.value.status_code == 422
