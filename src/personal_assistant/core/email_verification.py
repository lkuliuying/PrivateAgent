"""短期邮箱验证码的安全生成与摘要校验。"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import string

VERIFICATION_CODE_LENGTH = 6
VERIFICATION_TTL_MINUTES = 5
VERIFICATION_RESEND_SECONDS = 60
VERIFICATION_MAX_ATTEMPTS = 5

_LETTERS = string.ascii_uppercase
_DIGITS = string.digits
_ALPHANUMERIC = _LETTERS + _DIGITS


def generate_verification_code() -> str:
    """生成 6 位验证码，并保证至少包含一个字母和一个数字。"""
    characters = [
        secrets.choice(_LETTERS),
        secrets.choice(_DIGITS),
        *(secrets.choice(_ALPHANUMERIC) for _ in range(VERIFICATION_CODE_LENGTH - 2)),
    ]
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


def new_verification_digest(code: str) -> tuple[str, str]:
    """为短验证码生成独立盐和 SHA-256 摘要，数据库不保存原文。"""
    salt = secrets.token_hex(16)
    return salt, _verification_digest(code, salt)


def verification_code_matches(code: str, salt: str, expected: str) -> bool:
    actual = _verification_digest(code, salt)
    return hmac.compare_digest(actual, expected)


def _verification_digest(code: str, salt: str) -> str:
    normalized = code.strip().upper()
    return hashlib.sha256(f"{salt}:{normalized}".encode("utf-8")).hexdigest()
