from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from personal_assistant.api.security import validate_local_api_security
from personal_assistant.config import settings
from personal_assistant.main_api import app


def _token() -> str:
    assert settings.api_token is not None
    return settings.api_token.get_secret_value()


@pytest.mark.asyncio
async def test_api_rejects_missing_and_incorrect_bearer_tokens():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1",
    ) as client:
        missing = await client.get("/")
        incorrect = await client.get(
            "/", headers={"Authorization": "Bearer definitely-wrong"}
        )

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert incorrect.status_code == 401


@pytest.mark.asyncio
async def test_api_accepts_token_from_allowed_webview_origin_and_sets_cors_header():
    origin = "http://localhost:1420"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {_token()}", "Origin": origin},
    ) as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.asyncio
async def test_api_rejects_disallowed_origin_and_host_even_with_valid_token():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {_token()}"},
    ) as client:
        bad_origin = await client.get(
            "/", headers={"Origin": "https://attacker.example"}
        )
        bad_host = await client.get("/", headers={"Host": "attacker.example"})

    assert bad_origin.status_code == 403
    assert bad_host.status_code == 400


@pytest.mark.asyncio
async def test_allowed_cors_preflight_does_not_require_bearer_token():
    origin = "https://tauri.localhost"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1",
    ) as client:
        response = await client.options(
            "/sessions",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"bind_host": "0.0.0.0"}, "loopback"),
        ({"allowed_hosts": ["*"]}, "ALLOWED_HOSTS"),
        ({"allowed_origins": ["*"]}, "ALLOWED_ORIGINS"),
        ({"token": "short"}, "at least 32"),
    ],
)
def test_security_configuration_fails_closed(overrides, message):
    kwargs = {
        "bind_host": "127.0.0.1",
        "auth_enabled": True,
        "token": "a" * 32,
        "allowed_hosts": ["127.0.0.1"],
        "allowed_origins": ["http://localhost:1420"],
    }
    kwargs.update(overrides)

    with pytest.raises(RuntimeError, match=message):
        validate_local_api_security(**kwargs)


def test_authenticated_container_wildcard_bind_requires_explicit_opt_in():
    kwargs = {
        "bind_host": "0.0.0.0",
        "auth_enabled": True,
        "token": "a" * 32,
        "allowed_hosts": ["127.0.0.1"],
        "allowed_origins": ["http://127.0.0.1:8000"],
        "allow_non_loopback_bind": True,
    }

    validate_local_api_security(**kwargs)

    with pytest.raises(RuntimeError, match="requires API authentication"):
        validate_local_api_security(**(kwargs | {"auth_enabled": False}))


@pytest.mark.parametrize("bind_host", ["192.168.1.20", "private-agent.local"])
def test_container_opt_in_does_not_allow_specific_network_interfaces(bind_host):
    with pytest.raises(RuntimeError, match="loopback"):
        validate_local_api_security(
            bind_host=bind_host,
            auth_enabled=True,
            token="a" * 32,
            allowed_hosts=["127.0.0.1"],
            allowed_origins=["http://127.0.0.1:8000"],
            allow_non_loopback_bind=True,
        )
