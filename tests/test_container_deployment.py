"""Static safety contracts for the optional container deployment."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_uses_lockfile_non_root_user_and_authenticated_healthcheck():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "python:3.13.13-slim-bookworm" in dockerfile
    assert "uv sync --frozen --no-dev --no-editable" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "PA_API_TOKEN" in dockerfile
    assert 'CMD ["python", "-m", "personal_assistant.server_entry"]' in dockerfile
    assert ":latest" not in dockerfile


def test_compose_requires_secrets_and_publishes_api_only_to_loopback():
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "${PA_API_TOKEN_SECRET_FILE:?" in compose
    assert "${PA_MYSQL_PASSWORD_SECRET_FILE:?" in compose
    assert "${PA_MYSQL_ROOT_PASSWORD_SECRET_FILE:?" in compose
    assert "PA_API_TOKEN_FILE: /run/secrets/api_token" in compose
    assert "PA_DB_PASSWORD_FILE: /run/secrets/mysql_password" in compose
    assert "127.0.0.1:${PA_DOCKER_API_PORT:-8000}:8000" in compose
    assert "PA_API_ALLOW_NON_LOOPBACK_BIND: \"true\"" in compose
    assert "PA_API_AUTH_ENABLED: \"true\"" in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose and "- ALL" in compose
    assert ":latest" not in compose


def test_container_example_does_not_contain_secret_values():
    example = (PROJECT_ROOT / ".env.container.example").read_text(encoding="utf-8")

    assert "PA_API_TOKEN=" not in example
    assert "PA_MYSQL_PASSWORD=" not in example
    assert "PA_MYSQL_ROOT_PASSWORD=" not in example
    assert "PA_API_TOKEN_SECRET_FILE=.secrets/api_token" in example
