"""Container secret-file configuration contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from personal_assistant.config import Settings


def test_mcp_is_enabled_by_default(monkeypatch):
    monkeypatch.delenv("PA_MCP_ENABLED", raising=False)
    assert Settings(_env_file=None).mcp_enabled is True


def _secret(tmp_path: Path, name: str, value: str) -> Path:
    path = tmp_path / name
    path.write_text(value, encoding="utf-8")
    return path


def test_settings_load_api_and_database_secrets_from_files(tmp_path):
    token_file = _secret(tmp_path, "api-token", "a" * 64 + "\n")
    password_file = _secret(tmp_path, "db-password", "p@ss:/word?value\n")

    configured = Settings(
        _env_file=None,
        api_token=None,
        api_token_file=token_file,
        db_url="mysql+aiomysql://private_agent:@mysql:3306/personal_assistant",
        db_password_file=password_file,
    )

    assert configured.api_token is not None
    assert configured.api_token.get_secret_value() == "a" * 64
    assert make_url(configured.db_url).password == "p@ss:/word?value"
    assert "p@ss:/word?value" not in configured.db_url


def test_settings_reject_ambiguous_direct_and_file_api_token(tmp_path):
    token_file = _secret(tmp_path, "api-token", "a" * 64)

    with pytest.raises(ValueError, match="only one"):
        Settings(
            _env_file=None,
            api_token="b" * 64,
            api_token_file=token_file,
        )


def test_settings_load_smtp_credentials_from_dedicated_env_file(tmp_path):
    smtp_env = tmp_path / "smtp.env"
    smtp_env.write_text(
        "\n".join(
            (
                "PA_SMTP_HOST=smtp.example.com",
                "PA_SMTP_PORT=465",
                "PA_SMTP_USERNAME=sender@example.com",
                "PA_SMTP_PASSWORD=authorization-code",
                "PA_SMTP_FROM_EMAIL=sender@example.com",
                "PA_SMTP_USE_SSL=true",
            )
        ),
        encoding="utf-8",
    )

    configured = Settings(_env_file=smtp_env)

    assert configured.smtp_host == "smtp.example.com"
    assert configured.smtp_username == "sender@example.com"
    assert configured.smtp_password is not None
    assert configured.smtp_password.get_secret_value() == "authorization-code"


@pytest.mark.parametrize("value", ["", "line-one\nline-two", "bad\x00value"])
def test_settings_reject_invalid_secret_file_content(tmp_path, value):
    token_file = _secret(tmp_path, "api-token", value)

    with pytest.raises(ValueError, match="secret file"):
        Settings(_env_file=None, api_token=None, api_token_file=token_file)
