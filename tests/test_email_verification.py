"""邮箱验证码生成、摘要与 HTML 邮件契约。"""
from __future__ import annotations

import re
import smtplib
import socket
import ssl
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from personal_assistant.config import settings
from personal_assistant.core.email_verification import (
    generate_verification_code,
    new_verification_digest,
    verification_code_matches,
)
from personal_assistant.core.models import EmailVerificationCode, User
from personal_assistant.core.smtp_email import (
    SmtpConfigurationError,
    _delivery_error_message,
    _validate_smtp_host,
    build_verification_email,
)


def test_verification_code_is_six_alphanumeric_characters_with_both_classes():
    for _ in range(100):
        code = generate_verification_code()
        assert re.fullmatch(r"[A-Z0-9]{6}", code)
        assert any(character.isalpha() for character in code)
        assert any(character.isdigit() for character in code)


def test_verification_digest_is_salted_and_case_insensitive():
    first_salt, first_digest = new_verification_digest("A1B2C3")
    second_salt, second_digest = new_verification_digest("A1B2C3")

    assert first_salt != second_salt
    assert first_digest != second_digest
    assert verification_code_matches("a1b2c3", first_salt, first_digest)
    assert not verification_code_matches("A1B2C4", first_salt, first_digest)


def test_html_email_contains_code_and_expiry_without_exposing_password(monkeypatch):
    monkeypatch.setattr(settings, "smtp_username", "sender@example.com")
    monkeypatch.setattr(settings, "smtp_from_email", "sender@example.com")
    monkeypatch.setattr(settings, "smtp_from_name", "PrivateAgent")
    monkeypatch.setattr(settings, "smtp_password", SecretStr("smtp-secret"))

    message = build_verification_email(
        "receiver@example.com",
        "A1B2C3",
        valid_minutes=5,
    )
    content = message.as_string()

    assert "text/plain" in content
    assert "text/html" in content
    assert "A1B2C3" in content
    assert "smtp-secret" not in content


def test_smtp_example_host_is_rejected_with_actionable_message():
    with pytest.raises(SmtpConfigurationError, match="SMTP 主机仍是示例地址"):
        _validate_smtp_host("smtp.example.com")


@pytest.mark.parametrize(
    ("error", "expected"),
    (
        (socket.gaierror(11001, "name resolution failed"), "SMTP 主机无法解析"),
        (smtplib.SMTPAuthenticationError(535, b"auth failed"), "SMTP 认证失败"),
        (TimeoutError(), "连接 SMTP 服务超时"),
        (ConnectionRefusedError(), "SMTP 服务拒绝连接"),
        (ssl.SSLError("handshake failed"), "SMTP SSL/TLS 握手失败"),
    ),
)
def test_smtp_delivery_errors_have_actionable_messages_without_server_details(
    error, expected
):
    message = _delivery_error_message(error)

    assert expected in message
    assert "auth failed" not in message
    assert "name resolution failed" not in message


@pytest.mark.asyncio
async def test_registration_requires_the_latest_five_minute_email_code(
    client, db, monkeypatch
):
    suffix = uuid4().hex
    email = f"verification-{suffix}@example.com"
    username = f"verification-{suffix}"
    password = "verification-password-123"
    sent_codes: dict[str, str] = {}

    def capture_email(recipient: str, code: str, *, valid_minutes: int) -> None:
        assert valid_minutes == 5
        sent_codes[recipient] = code

    monkeypatch.setattr(
        "personal_assistant.api.routes_auth.send_registration_verification_email",
        capture_email,
    )
    sent = await client.post(
        "/auth/email-verification/send",
        json={"email": email},
    )
    assert sent.status_code == 202, sent.text

    record = (
        await db.execute(
            select(EmailVerificationCode).where(EmailVerificationCode.email == email)
        )
    ).scalar_one()
    assert record.expires_at - record.created_at == timedelta(minutes=5)
    assert sent_codes[email] not in record.code_hash

    throttled = await client.post(
        "/auth/email-verification/send",
        json={"email": email},
    )
    assert throttled.status_code == 429

    wrong_code = "A0A0A0" if sent_codes[email] != "A0A0A0" else "B1B1B1"
    wrong = await client.post(
        "/auth/register",
        json={
            "email": email,
            "username": username,
            "password": password,
            "verification_code": wrong_code,
        },
    )
    assert wrong.status_code == 400

    registered = await client.post(
        "/auth/register",
        json={
            "email": email,
            "username": username,
            "password": password,
            "verification_code": sent_codes[email],
        },
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["user"]["username"] == username

    await db.rollback()
    await db.execute(
        delete(EmailVerificationCode).where(EmailVerificationCode.email == email)
    )
    await db.execute(delete(User).where(User.email == email))
    await db.commit()
