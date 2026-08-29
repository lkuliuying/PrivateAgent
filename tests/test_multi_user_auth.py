"""多用户认证、租户隔离与管理员边界。"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

from personal_assistant.api.audit import purge_expired_security_records
from personal_assistant.core.auth import (
    hash_password,
    issue_auth_session,
    verify_password,
)
from personal_assistant.core.models import (
    AuditLog,
    AuthSession,
    ChatSession,
    EmailVerificationCode,
    User,
)
from personal_assistant.core.tenant import enter_tenant, exit_tenant
from personal_assistant.core.timeutil import utcnow


async def _request_registration_code(client, email: str, sent_codes: dict[str, str]) -> str:
    response = await client.post(
        "/auth/email-verification/send",
        json={"email": email},
    )
    assert response.status_code == 202, response.text
    assert response.json() == {
        "expires_in_seconds": 300,
        "retry_after_seconds": 60,
    }
    return sent_codes[email]


def test_password_hash_is_salted_and_verifiable():
    password = "correct horse battery staple"
    first = hash_password(password)
    second = hash_password(password)

    assert first.startswith("scrypt$")
    assert first != second
    assert password not in first
    assert verify_password(password, first) is True
    assert verify_password("wrong password", first) is False


@pytest.mark.asyncio
async def test_security_retention_removes_expired_audit_and_sessions(db):
    suffix = uuid4().hex
    user = User(
        email=f"retention-{suffix}@example.com",
        username=f"retention-{suffix}",
        display_name="Retention",
        password_hash=hash_password("retention-password-123"),
    )
    db.add(user)
    await db.flush()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=suffix.ljust(64, "0")[:64],
            expires_at=utcnow() - timedelta(days=30),
        )
    )
    db.add(
        EmailVerificationCode(
            email=f"expired-{suffix}@example.com",
            code_hash="0" * 64,
            code_salt="0" * 32,
            expires_at=utcnow() - timedelta(days=30),
        )
    )
    db.add(
        AuditLog(
            request_id=str(uuid4()),
            actor_user_id=user.id,
            actor_type="user",
            method="GET",
            path="/expired",
            status_code=200,
            duration_ms=1,
            created_at=utcnow() - timedelta(days=365),
        )
    )
    await db.commit()

    removed = await purge_expired_security_records()

    assert removed["audit_logs"] >= 1
    assert removed["auth_sessions"] >= 1
    assert removed["email_verification_codes"] >= 1
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()


@pytest.mark.asyncio
async def test_user_sessions_isolate_business_rows_and_admin_routes(
    client, db, monkeypatch
):
    suffix = uuid4().hex
    first_email = f"tenant-a-{suffix}@example.com"
    second_email = f"tenant-b-{suffix}@example.com"
    password = "safe-test-password-123"
    sent_codes: dict[str, str] = {}

    def capture_email(recipient: str, code: str, *, valid_minutes: int) -> None:
        assert valid_minutes == 5
        sent_codes[recipient] = code

    monkeypatch.setattr(
        "personal_assistant.api.routes_auth.send_registration_verification_email",
        capture_email,
    )

    first_code = await _request_registration_code(client, first_email, sent_codes)
    second_code = await _request_registration_code(client, second_email, sent_codes)

    first_register = await client.post(
        "/auth/register",
        json={
            "email": first_email,
            "username": f"tenant-a-{suffix}",
            "password": password,
            "verification_code": first_code,
        },
    )
    second_register = await client.post(
        "/auth/register",
        json={
            "email": second_email,
            "username": f"tenant-b-{suffix}",
            "password": password,
            "verification_code": second_code,
        },
    )
    assert first_register.status_code == 201
    assert second_register.status_code == 201
    first_token = first_register.json()["access_token"]
    second_token = second_register.json()["access_token"]
    assert first_register.json()["user"]["username"] == f"tenant-a-{suffix}"

    email_login = await client.post(
        "/auth/login",
        json={"identifier": first_email, "password": password},
    )
    username_login = await client.post(
        "/auth/login",
        json={"identifier": f"tenant-b-{suffix}", "password": password},
    )
    assert email_login.status_code == 200
    assert username_login.status_code == 200

    users = (
        await db.execute(select(User).where(User.email.in_([first_email, second_email])))
    ).scalars().all()
    by_email = {item.email: item for item in users}
    by_email[first_email].role = "admin"
    by_email[second_email].role = "user"
    await db.commit()

    first_headers = {"Authorization": f"Bearer {first_token}"}
    second_headers = {"Authorization": f"Bearer {second_token}"}
    created = await client.post(
        "/sessions",
        headers=first_headers,
        json={"title": "Tenant A private session"},
    )
    assert created.status_code == 201
    session_id = created.json()["id"]

    first_sessions = await client.get("/sessions", headers=first_headers)
    second_sessions = await client.get("/sessions", headers=second_headers)
    assert any(item["id"] == session_id for item in first_sessions.json())
    assert all(item["id"] != session_id for item in second_sessions.json())

    denied = await client.get("/admin/overview", headers=second_headers)
    allowed = await client.get("/admin/overview", headers=first_headers)
    project_allowed = await client.get("/projects", headers=second_headers)
    run_allowed = await client.get(
        "/agent-runs/not-a-real-run", headers=second_headers
    )
    tasks_allowed = await client.get("/agent-tasks", headers=second_headers)
    extensions_allowed = await client.get("/extensions", headers=second_headers)
    settings_allowed = await client.get("/settings", headers=second_headers)

    async def empty_provider_list(_service):
        return []

    monkeypatch.setattr(
        "personal_assistant.api.routes_model_providers.ModelProviderService.list",
        empty_provider_list,
    )
    model_providers_allowed = await client.get(
        "/model-providers", headers=second_headers
    )
    model_profiles_allowed = await client.get(
        "/agent-model-profiles", headers=second_headers
    )
    monkeypatch.setattr(
        "personal_assistant.api.routes_mcp.settings.mcp_enabled", True
    )
    mcp_allowed = await client.get("/mcp/servers", headers=second_headers)
    project_unauthenticated = await client.get(
        "/projects", headers={"Authorization": ""}
    )
    shutdown_denied = await client.post("/internal/shutdown", headers=second_headers)
    assert denied.status_code == 403
    assert project_allowed.status_code == 200
    assert isinstance(project_allowed.json(), list)
    assert run_allowed.status_code == 404
    assert tasks_allowed.status_code == 200
    assert isinstance(tasks_allowed.json(), list)
    assert extensions_allowed.status_code == 200
    assert isinstance(extensions_allowed.json(), list)
    assert settings_allowed.status_code == 200
    assert model_providers_allowed.status_code == 200
    assert isinstance(model_providers_allowed.json(), list)
    assert model_profiles_allowed.status_code in {200, 409}
    if model_profiles_allowed.status_code == 200:
        assert isinstance(model_profiles_allowed.json(), list)
    else:
        assert model_profiles_allowed.json().get("detail") != "Administrator access is required"
    assert mcp_allowed.status_code == 200
    assert isinstance(mcp_allowed.json(), list)
    assert project_unauthenticated.status_code == 401
    assert shutdown_denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["users_total"] >= 2

    me = await client.get("/auth/me", headers=first_headers)
    assert me.status_code == 200
    assert me.json()["email"] == first_email

    rename_denied = await client.patch(
        f"/sessions/{session_id}/title",
        headers=second_headers,
        json={"title": "Tenant B must not change this"},
    )
    assert rename_denied.status_code == 404

    tenant_token = enter_tenant(by_email[second_email].id)
    try:
        updated = await db.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(title="cross-tenant update")
        )
        removed = await db.execute(
            delete(ChatSession).where(ChatSession.id == session_id)
        )
        assert updated.rowcount == 0
        assert removed.rowcount == 0
        await db.rollback()
    finally:
        exit_tenant(tenant_token)

    private_session = await db.get(ChatSession, session_id)
    assert private_session is not None
    assert private_session.title == "Tenant A private session"

    await db.execute(delete(ChatSession).where(ChatSession.id == session_id))
    await db.execute(
        delete(EmailVerificationCode).where(
            EmailVerificationCode.email.in_([first_email, second_email])
        )
    )
    await db.execute(delete(User).where(User.email.in_([first_email, second_email])))
    await db.commit()


@pytest.mark.asyncio
async def test_admin_manages_user_lifecycle_and_protects_own_access(client, db):
    suffix = uuid4().hex
    admin = User(
        email=f"manager-{suffix}@example.com",
        username=f"manager-{suffix}",
        display_name=f"manager-{suffix}",
        password_hash=hash_password("manager-password-123"),
        role="admin",
        status="active",
    )
    ordinary = User(
        email=f"ordinary-{suffix}@example.com",
        username=f"ordinary-{suffix}",
        display_name=f"ordinary-{suffix}",
        password_hash=hash_password("ordinary-password-123"),
        role="user",
        status="active",
    )
    db.add_all([admin, ordinary])
    await db.flush()
    _, admin_token = await issue_auth_session(db, admin)
    _, ordinary_token = await issue_auth_session(db, ordinary)
    await db.commit()

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    ordinary_headers = {"Authorization": f"Bearer {ordinary_token}"}
    managed_email = f"managed-{suffix}@example.com"
    managed_username = f"managed-{suffix}"
    managed_password = "managed-password-123"

    denied = await client.post(
        "/admin/users",
        headers=ordinary_headers,
        json={
            "email": f"denied-{suffix}@example.com",
            "username": f"denied-{suffix}",
            "password": managed_password,
            "role": "user",
        },
    )
    assert denied.status_code == 403

    created = await client.post(
        "/admin/users",
        headers=admin_headers,
        json={
            "email": managed_email,
            "username": managed_username,
            "password": managed_password,
            "role": "user",
        },
    )
    assert created.status_code == 201, created.text
    managed_user_id = created.json()["id"]
    assert created.json()["status"] == "active"

    invalid_username = await client.post(
        "/admin/users",
        headers=admin_headers,
        json={
            "email": f"invalid-{suffix}@example.com",
            "username": " a ",
            "password": managed_password,
            "role": "user",
        },
    )
    duplicate_email = await client.post(
        "/admin/users",
        headers=admin_headers,
        json={
            "email": managed_email,
            "username": f"duplicate-{suffix}",
            "password": managed_password,
            "role": "user",
        },
    )
    assert invalid_username.status_code == 422
    assert duplicate_email.status_code == 409

    filtered = await client.get(
        "/admin/users",
        headers=admin_headers,
        params={"search": managed_username, "role": "user", "status": "active"},
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["results"]] == [managed_user_id]

    promoted = await client.patch(
        f"/admin/users/{managed_user_id}",
        headers=admin_headers,
        json={"role": "admin"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"

    managed_login = await client.post(
        "/auth/login",
        json={"identifier": managed_username, "password": managed_password},
    )
    assert managed_login.status_code == 200
    managed_token = managed_login.json()["access_token"]

    disabled = await client.patch(
        f"/admin/users/{managed_user_id}",
        headers=admin_headers,
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    revoked = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {managed_token}"}
    )
    assert revoked.status_code == 401

    reenabled = await client.patch(
        f"/admin/users/{managed_user_id}",
        headers=admin_headers,
        json={"status": "active", "role": "user"},
    )
    assert reenabled.status_code == 200
    assert reenabled.json()["status"] == "active"
    assert reenabled.json()["role"] == "user"

    self_demote = await client.patch(
        f"/admin/users/{admin.id}",
        headers=admin_headers,
        json={"role": "user"},
    )
    self_disable = await client.patch(
        f"/admin/users/{admin.id}",
        headers=admin_headers,
        json={"status": "disabled"},
    )
    assert self_demote.status_code == 409
    assert self_disable.status_code == 409

    await db.execute(
        delete(User).where(User.email.in_([admin.email, ordinary.email, managed_email]))
    )
    await db.commit()
