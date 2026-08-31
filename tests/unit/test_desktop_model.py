"""Stateless cloud gateway: authenticated inference only, no project execution."""
import asyncio
import json

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
    from personal_assistant.core.models import ModelProfile

    profile = ModelProfile(id="default-profile", enabled=True, is_default=True, reasoning_efforts_json=["low"])

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
    assert len(captured) == 1

    supported = routes.DesktopModelRequest.model_validate({"model_profile_id": "default-profile", "request": {
        "messages": [{"role": "user", "content": "test"}], "reasoning_effort": "low"}})
    assert await routes.resolve_gateway(None, supported) == "resolved"
    assert len(captured) == 2
    profile.reasoning_efforts_json = None
    with pytest.raises(HTTPException) as error:
        await routes.resolve_gateway(None, supported)
    assert error.value.status_code == 422
    assert len(captured) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("profiles", [[], [dict(enabled=False, is_default=True)], [dict(enabled=True, is_default=False)]])
async def test_desktop_without_enabled_default_does_not_use_legacy_provider(monkeypatch, profiles):
    from personal_assistant.api import routes_agent_runs
    from personal_assistant.core import model_profiles
    from personal_assistant.core.models import ModelProfile

    class Profiles:
        def __init__(self, db):
            pass

        async def list(self):
            return [ModelProfile(id=str(index), **data) for index, data in enumerate(profiles)]

    async def unexpected_gateway(db, run):
        pytest.fail("缺少默认模型时不得调用旧全局模型")

    monkeypatch.setattr(model_profiles, "ModelProfileService", Profiles)
    monkeypatch.setattr(routes_agent_runs, "_model_gateway_for_run", unexpected_gateway)
    payload = routes.DesktopModelRequest.model_validate({"request": {"messages": [{"role": "user", "content": "test"}]}})
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        await routes.resolve_gateway(None, payload)
    assert error.value.status_code == 422
    assert error.value.headers["X-Model-Error-Code"] == "not_configured"


@pytest.mark.asyncio
async def test_invalid_model_configuration_is_safe_and_does_not_start_inference(monkeypatch):
    from fastapi import HTTPException

    from personal_assistant.api import routes_agent_runs

    async def invalid_configuration(db, run):
        raise ValueError("fixture-secret-url-or-setting")

    monkeypatch.setattr(routes_agent_runs, "_model_gateway_for_run", invalid_configuration)
    payload = routes.DesktopModelRequest.model_validate({
        "model_profile_id": "fixture", "request": {"messages": [{"role": "user", "content": "test"}]},
    })
    with pytest.raises(HTTPException) as error:
        await routes.resolve_gateway(None, payload)
    assert error.value.status_code == 422
    assert error.value.headers["X-Model-Error-Code"] == "invalid_configuration"
    assert "fixture-secret" not in error.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("code,status", [
    ("missing_api_key", 503), ("unauthorized", 502), ("model_not_found", 422),
    ("unsupported_capability", 422), ("provider_rejected_request", 502),
    ("rate_limited", 429), ("network_error", 503), ("provider_unavailable", 503),
    ("timeout", 504), ("invalid_response", 502), ("unknown-secret-code", 502),
])
async def test_gateway_preserves_safe_error_classification_and_releases_slot(monkeypatch, code, status):
    from structlog.testing import capture_logs

    from personal_assistant.llm.contracts import ModelGatewayError

    app, gateway = app_for(monkeypatch)
    slots = asyncio.Semaphore(1)
    monkeypatch.setattr(routes, "_inference_slots", slots)

    async def fail(request, *, cancellation):
        raise ModelGatewayError("fixture-provider-secret", code=code, provider="fixture-provider-secret")

    monkeypatch.setattr(gateway, "complete", fail)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://server.test",
                                 headers={"Authorization": "Bearer test-account"}) as client:
        with capture_logs() as logs:
            response = await client.post("/desktop/model/complete", json={
                "request": {"messages": [{"role": "user", "content": "fixture-prompt-secret"}]},
            })
        expected_code = "provider_error" if code == "unknown-secret-code" else code
        assert response.status_code == status
        assert response.headers["X-Model-Error-Code"] == expected_code
        assert response.headers["Cache-Control"] == "no-store"
        assert isinstance(response.json()["detail"], str)
        assert "secret" not in response.text + str(response.headers) + json.dumps(logs)
        assert logs[0]["error_code"] == expected_code
        assert slots._value == 1
