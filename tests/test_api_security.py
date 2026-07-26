"""Desktop sidecar bearer authentication and constrained CORS tests."""
from __future__ import annotations

import pytest
from pydantic import SecretStr

from personal_assistant.config import Settings, settings


@pytest.mark.asyncio
async def test_empty_token_keeps_explicit_development_mode_compatible(client, monkeypatch):
    monkeypatch.setattr(settings, "api_token", SecretStr(""))

    response = await client.get("/")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_bearer_auth_is_generic_and_keeps_correlation_headers(client, monkeypatch):
    token = "a" * 64
    origin = "https://tauri.localhost"
    monkeypatch.setattr(settings, "api_token", SecretStr(token))

    missing = await client.get(
        "/",
        headers={"Origin": origin, "X-Request-ID": "auth-missing-42"},
    )
    wrong = await client.get(
        "/",
        headers={"Origin": origin, "Authorization": "Bearer wrong"},
    )
    accepted = await client.get(
        "/",
        headers={"Origin": origin, "Authorization": f"bEaReR {token}"},
    )

    for response in (missing, wrong):
        assert response.status_code == 401
        assert response.json() == {"detail": "Unauthorized"}
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["server-timing"].startswith("ttfb;dur=")
        assert token not in response.text
        assert token not in repr(response.headers)
    assert missing.headers["x-request-id"] == "auth-missing-42"
    assert accepted.status_code == 200
    assert accepted.headers["access-control-allow-origin"] == origin


@pytest.mark.asyncio
async def test_cors_preflight_bypasses_auth_for_trusted_origins(client, monkeypatch):
    monkeypatch.setattr(settings, "api_token", SecretStr("b" * 64))

    response = await client.options(
        "/health",
        headers={
            "Origin": "http://127.0.0.1:1420",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-request-id",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:1420"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin",
    [
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "http://localhost:5173",
        "https://127.0.0.1:1420",
    ],
)
async def test_cors_allows_only_supported_desktop_and_dev_origins(client, origin):
    response = await client.options(
        "/",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.asyncio
async def test_cors_rejects_non_loopback_web_origins(client):
    response = await client.options(
        "/",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_api_token_is_redacted_from_settings_representation():
    token = "do-not-persist-or-print"
    configured = Settings(_env_file=None, api_token=token)

    assert configured.api_token.get_secret_value() == token
    assert token not in repr(configured)
