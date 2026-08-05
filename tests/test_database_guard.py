from __future__ import annotations

import pytest

from personal_assistant.testing import UnsafeTestDatabaseError, resolve_test_database_url


APP_URL = "mysql+aiomysql://app:secret@127.0.0.1:3306/personal_assistant?charset=utf8mb4"


def test_derives_a_sibling_test_database_without_exposing_application_database():
    resolved = resolve_test_database_url(APP_URL)

    assert "personal_assistant_test" in resolved
    assert resolved != APP_URL


def test_accepts_an_explicit_dedicated_test_database():
    resolved = resolve_test_database_url(
        APP_URL,
        "mysql+aiomysql://tester:secret@127.0.0.1:3306/test_private_agent",
    )

    assert "test_private_agent" in resolved


@pytest.mark.parametrize(
    "unsafe_url",
    [
        APP_URL,
        "mysql+aiomysql://app:secret@127.0.0.1:3306/personal_assistant?charset=latin1",
        "mysql+aiomysql://app:secret@127.0.0.1:3306/personal_assistant_tests",
        "sqlite+aiosqlite:///personal_assistant_test.db",
    ],
)
def test_rejects_unsafe_test_targets(unsafe_url: str):
    with pytest.raises(UnsafeTestDatabaseError):
        resolve_test_database_url(APP_URL, unsafe_url)

