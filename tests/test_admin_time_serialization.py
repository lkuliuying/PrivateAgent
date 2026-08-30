"""管理员响应中的 UTC 时间必须携带时区，供客户端无歧义地转换显示。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from personal_assistant.api.routes_admin import (
    AdminOverview,
    AdminUserAccount,
    AdminUserList,
    AdminUserRow,
    AuditLogList,
    AuditLogRow,
)

EXPECTED_UTC = "2026-08-30T16:49:02.123Z"


@pytest.fixture(params=[
    datetime(2026, 8, 30, 16, 49, 2, 123000),
    datetime(2026, 8, 30, 16, 49, 2, 123000, tzinfo=timezone.utc),
    datetime(2026, 8, 31, 0, 49, 2, 123000, tzinfo=timezone(timedelta(hours=8))),
], ids=["naive-utc", "aware-utc", "shanghai-next-day"])
def timestamp(request):
    return request.param


@pytest.fixture
def user_fields(timestamp):
    return {
        "id": 1,
        "email": "admin-time@example.test",
        "username": "admin-time",
        "display_name": "Admin time",
        "role": "user",
        "status": "active",
        "last_login_at": timestamp,
        "created_at": timestamp,
    }


def test_overview_serializes_generated_at_as_utc(timestamp):
    overview = AdminOverview(
        users_total=0,
        users_active=0,
        admins_total=0,
        sessions_total=0,
        projects_total=0,
        operations_24h=0,
        errors_24h=0,
        health={},
        generated_at=timestamp,
    )

    assert json.loads(overview.model_dump_json())["generated_at"] == EXPECTED_UTC
    assert overview.generated_at == timestamp


def test_audit_list_serializes_created_at_as_utc(timestamp):
    response = AuditLogList(total=1, results=[AuditLogRow(
        id=1,
        request_id="admin-time",
        actor_user_id=None,
        actor_type="anonymous",
        method="GET",
        path="/",
        status_code=200,
        duration_ms=0,
        client_ip=None,
        created_at=timestamp,
    )])

    assert json.loads(response.model_dump_json())["results"][0]["created_at"] == EXPECTED_UTC


@pytest.mark.parametrize("missing_login", [False, True], ids=["logged-in", "never-logged-in"])
def test_user_responses_serialize_utc_and_preserve_null(user_fields, missing_login):
    if missing_login:
        user_fields["last_login_at"] = None
    row = AdminUserRow(
        **user_fields,
        session_count=0,
        project_count=0,
        document_count=0,
        operation_count=0,
    )
    user_list = AdminUserList(total=1, results=[row])
    account = AdminUserAccount(**user_fields)
    responses = [
        json.loads(user_list.model_dump_json())["results"][0],
        json.loads(account.model_dump_json()),
    ]

    for response in responses:
        assert response["created_at"] == EXPECTED_UTC
        assert response["last_login_at"] == (None if missing_login else EXPECTED_UTC)
