"""多用户认证、租户隔离与管理员边界。"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

from personal_assistant.api.audit import purge_expired_security_records
from personal_assistant.core.auth import hash_password, verify_password
from personal_assistant.core.models import AuditLog, AuthSession, ChatSession, User
from personal_assistant.core.tenant import enter_tenant, exit_tenant
from personal_assistant.core.timeutil import utcnow


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
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()


@pytest.mark.asyncio
async def test_user_sessions_isolate_business_rows_and_admin_routes(client, db):
    suffix = uuid4().hex
    first_email = f"tenant-a-{suffix}@example.com"
    second_email = f"tenant-b-{suffix}@example.com"
    password = "safe-test-password-123"

    first_register = await client.post(
        "/auth/register",
        json={
            "email": first_email,
            "display_name": "Tenant A",
            "password": password,
        },
    )
    second_register = await client.post(
        "/auth/register",
        json={
            "email": second_email,
            "display_name": "Tenant B",
            "password": password,
        },
    )
    assert first_register.status_code == 201
    assert second_register.status_code == 201
    first_token = first_register.json()["access_token"]
    second_token = second_register.json()["access_token"]

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
    project_denied = await client.get("/projects", headers=second_headers)
    shutdown_denied = await client.post("/internal/shutdown", headers=second_headers)
    assert denied.status_code == 403
    assert project_denied.status_code == 403
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
    await db.execute(delete(User).where(User.email.in_([first_email, second_email])))
    await db.commit()
