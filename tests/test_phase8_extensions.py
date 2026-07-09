"""第八阶段 M7 测试：扩展注册表。

覆盖（对齐 docs/phase8-plan.md §M7 / docs/phase8-requirements.md §5.7/§10.1）：
- 注册项 schema：重复 id、缺权限声明、未知 kind 注册失败。
- 内置 command / diagnostic / maintenance 三类已注册。
- GET /extensions 列出注册项（合并持久化 enabled）。
- PATCH /extensions/{id} 启用/禁用可配置扩展；不可配置扩展 403。
- 禁用的 maintenance_check 不被执行。
- diagnostic_check 出现在诊断快照（诊断中心 + 诊断包）；带 runner 的新检查自动并入。
"""
from __future__ import annotations

import pytest

from personal_assistant.core.extensions import (
    ExtensionDescriptor,
    ExtensionKind,
    extension_registry,
)
from personal_assistant.core.integrity import IntegrityService
from personal_assistant.core.models import ExtensionRegistryItem


@pytest.fixture
async def ext_cleanup(db):
    """清理测试创建的 extension_registry_items 持久化行（real DB 不自动回滚）。"""
    ids: list[str] = []
    yield ids
    for ext_id in ids:
        row = await db.get(ExtensionRegistryItem, ext_id)
        if row is not None:
            await db.delete(row)
    await db.commit()


# ============ 注册项 schema 校验 ============


def test_register_duplicate_id_raises():
    """重复 id 注册失败。"""
    desc = ExtensionDescriptor(
        id="test.dup", title="dup", kind=ExtensionKind.COMMAND, permissions=[]
    )
    extension_registry.register(desc)
    try:
        with pytest.raises(ValueError, match="重复"):
            extension_registry.register(
                ExtensionDescriptor(
                    id="test.dup",
                    title="dup2",
                    kind=ExtensionKind.COMMAND,
                    permissions=[],
                )
            )
    finally:
        extension_registry.unregister("test.dup")


def test_register_missing_permissions_raises():
    """缺权限声明（permissions=None）注册失败。"""
    desc = ExtensionDescriptor(
        id="test.noperm", title="np", kind=ExtensionKind.COMMAND, permissions=None
    )
    with pytest.raises(ValueError, match="权限"):
        extension_registry.register(desc)


def test_register_invalid_kind_raises():
    """未知 kind 注册失败。"""
    desc = ExtensionDescriptor(
        id="test.badkind", title="bk", kind="unknown_kind", permissions=[]
    )
    with pytest.raises(ValueError, match="kind"):
        extension_registry.register(desc)


def test_builtin_three_kinds_registered():
    """扩展注册表覆盖 command / diagnostic / maintenance 至少三类。"""
    kinds = {d.kind for d in extension_registry.list()}
    assert ExtensionKind.COMMAND in kinds
    assert ExtensionKind.DIAGNOSTIC_CHECK in kinds
    assert ExtensionKind.MAINTENANCE_CHECK in kinds
    cmds = extension_registry.list(kind=ExtensionKind.COMMAND)
    assert len(cmds) >= 6
    assert extension_registry.get("cmd.new_reminder") is not None
    # 内置体检检查至少 7 个
    assert len(extension_registry.list(kind=ExtensionKind.MAINTENANCE_CHECK)) >= 7
    # 内置诊断检查至少 8 个
    assert len(extension_registry.list(kind=ExtensionKind.DIAGNOSTIC_CHECK)) >= 8


# ============ 路由 ============


@pytest.mark.asyncio
async def test_get_extensions_route(client):
    r = await client.get("/extensions")
    assert r.status_code == 200
    items = r.json()
    assert any(i["id"] == "cmd.new_reminder" for i in items)
    # 按 kind 过滤
    r = await client.get("/extensions?kind=command")
    assert r.status_code == 200
    assert all(i["kind"] == "command" for i in r.json())


@pytest.mark.asyncio
async def test_patch_extension_persists(client, ext_cleanup):
    ext_id = "cmd.new_reminder"
    ext_cleanup.append(ext_id)
    r = await client.patch(f"/extensions/{ext_id}", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    # 持久化：新请求仍为 False
    r = await client.get("/extensions?kind=command")
    item = next(i for i in r.json() if i["id"] == ext_id)
    assert item["enabled"] is False


@pytest.mark.asyncio
async def test_patch_non_configurable_returns_403(client):
    """内置体检检查 configurable=False，禁用返回 403。"""
    r = await client.patch(
        "/extensions/goal_links_dangling", json={"enabled": False}
    )
    assert r.status_code == 403


# ============ 禁用项不执行 ============


@pytest.mark.asyncio
async def test_disabled_maintenance_check_not_executed(db, ext_cleanup):
    """禁用的 maintenance_check 不被执行；启用后执行。"""
    ext_id = "test.maintenance.custom"
    ext_cleanup.append(ext_id)
    called = {"count": 0}

    async def my_runner(svc) -> list:
        called["count"] += 1
        return []

    extension_registry.register(
        ExtensionDescriptor(
            id=ext_id,
            title="测试自定义体检",
            kind=ExtensionKind.MAINTENANCE_CHECK,
            risk_level="safe",
            permissions=["read:integrity"],
            runner=my_runner,
            configurable=True,
        )
    )
    try:
        await extension_registry.set_enabled(db, ext_id, False)
        await IntegrityService(db).check()
        assert called["count"] == 0, "禁用的检查不应被执行"
        # 启用后应被执行
        await extension_registry.set_enabled(db, ext_id, True)
        await IntegrityService(db).check()
        assert called["count"] >= 1
    finally:
        extension_registry.unregister(ext_id)


# ============ diagnostic_check 出现在诊断中心 + 诊断包 ============


@pytest.mark.asyncio
async def test_diagnostic_checks_in_snapshot(client):
    """diagnostic_check 列表出现在诊断快照（进入诊断中心 + 诊断包）。"""
    r = await client.get("/diagnostics")
    assert r.status_code == 200
    snap = r.json()
    assert "diagnostic_checks" in snap
    ids = [c["id"] for c in snap["diagnostic_checks"]]
    assert "diag.health" in ids
    assert len(snap["diagnostic_checks"]) >= 8


@pytest.mark.asyncio
async def test_custom_diagnostic_check_runner_merges_into_snapshot(db, ext_cleanup):
    """带 runner 的 diagnostic_check 输出自动并入快照（新增检查不改 snapshot）。"""
    ext_id = "test.diag.custom"
    ext_cleanup.append(ext_id)

    async def my_diag_runner(session) -> dict:
        return {"custom_diag_field": {"ok": True}}

    extension_registry.register(
        ExtensionDescriptor(
            id=ext_id,
            title="测试自定义诊断",
            kind=ExtensionKind.DIAGNOSTIC_CHECK,
            risk_level="safe",
            permissions=["read:diagnostics"],
            runner=my_diag_runner,
            configurable=True,
        )
    )
    try:
        from personal_assistant.core.diagnostics import DiagnosticsService

        snap = await DiagnosticsService(db).snapshot()
        assert snap["custom_diag_field"] == {"ok": True}
        assert any(c["id"] == ext_id for c in snap["diagnostic_checks"])
    finally:
        extension_registry.unregister(ext_id)
