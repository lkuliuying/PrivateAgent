"""第八阶段 M9 测试：备份恢复硬化。

覆盖（对齐 docs/archive/phases/phase8-plan.md §M9 / docs/archive/phases/phase8-requirements.md §5.9/§10.1）：
- 备份 manifest 含 app_version / schema_head / checksum / modules。
- checksum = sha256(tables.json 字节)，篡改可检测。
- BACKUP_TABLES 覆盖 phase6/7/8 表（inbox/reminders/notifications/capture/ocr/integration）。
- validate_manifest：合法备份 valid=True；篡改 valid=False。
- restore_drill：预览 + manifest 校验 + Chroma/MySQL 一致性，不实际恢复。
- 迁移失败 runbook 路由。
- _check_backup_manifest 对篡改的最新备份产生 warning 发现项。
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from personal_assistant import __version__
from personal_assistant.core.backup import BackupService
from personal_assistant.core.integrity import IntegrityService


@pytest.fixture
async def backup_cleanup():
    """清理测试创建的备份 zip（export 写入 data/backups/）。"""
    paths: list[str] = []
    yield paths
    for p in paths:
        Path(p).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_export_manifest_has_new_fields(client, backup_cleanup):
    resp = await client.post("/backup/export")
    assert resp.status_code == 200
    data = resp.json()
    backup_cleanup.append(data["path"])
    assert data["app_version"] == __version__
    assert data["schema_head"]  # 记录了当前 alembic head（不硬编码，随迁移演进）
    assert "checksum" in data and data["checksum"]

    with zipfile.ZipFile(data["path"]) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        raw_tables = zf.read("tables.json")
    assert manifest["version"] == 2
    assert manifest["app_version"] == __version__
    assert manifest["schema_head"]  # 不硬编码 head
    assert manifest["checksum"] == hashlib.sha256(raw_tables).hexdigest()
    assert "modules" in manifest
    assert "app_notifications" in manifest["modules"]


@pytest.mark.asyncio
async def test_backup_includes_phase678_tables(db, backup_cleanup):
    result = await BackupService(db).export()
    backup_cleanup.append(result["path"])
    with zipfile.ZipFile(result["path"]) as zf:
        tables = json.loads(zf.read("tables.json"))
    for t in (
        "inbox_items",
        "reminders",
        "personal_goals",
        "briefings",
        "provider_call_audits",
        "app_notifications",
        "capture_items",
        "ocr_jobs",
        "data_integrity_findings",
        "search_recent_items",
        "integration_sources",
        "integration_imports",
        "extension_registry_items",
        "agent_runs",
        "tool_approvals",
        "agent_run_checkpoints",
        "agent_tool_executions",
        "memory_facts",
        "document_index_versions",
        "document_index_chunks",
        "document_index_heads",
        "mcp_servers",
        "mcp_call_logs",
        "http_endpoint_profiles",
        "sql_readonly_profiles",
    ):
        assert t in tables, f"备份缺少表 {t}"


@pytest.mark.asyncio
async def test_backup_sanitizes_workflow_profile_secrets(db, backup_cleanup):
    """B0：v0.5.0 profile 表备份导出不携带 header/连接选项明文值。

    保留键名（配置状态）与 keyring 引用标识，清空可能含 secret 的值。
    """
    from sqlalchemy import text

    marker = "backup-must-not-contain-7f3b9d"
    await db.execute(
        text(
            "INSERT INTO http_endpoint_profiles "
            "(name, scheme, host, port, allowed_methods_json, headers_json, "
            "secret_refs_json) VALUES "
            "('b0-backup-http', 'https', 'api.example.test', 443, "
            "JSON_ARRAY('GET'), JSON_OBJECT('X-Api-Key', :marker), "
            "JSON_OBJECT('X-Api-Key', 'keyring://http-profiles/b0-backup-http/api-key'))"
        ),
        {"marker": marker},
    )
    await db.execute(
        text(
            "INSERT INTO sql_readonly_profiles "
            "(name, dialect, host, port, `database`, username, password_secret_ref, "
            "connect_args_json) VALUES "
            "('b0-backup-sql', 'mysql', 'db.example.test', 3306, 'app', 'appuser', "
            "'keyring://sql-profiles/b0-backup-sql/password', "
            "JSON_OBJECT('password', :marker))"
        ),
        {"marker": marker},
    )
    await db.commit()
    try:
        http_rows = await BackupService(db)._dump_table("http_endpoint_profiles")
        http_row = next(row for row in http_rows if row["name"] == "b0-backup-http")
        assert http_row["headers_json"] == {"X-Api-Key": ""}
        assert http_row["secret_refs_json"] == {
            "X-Api-Key": "keyring://http-profiles/b0-backup-http/api-key"
        }
        assert marker not in str(http_row)

        sql_rows = await BackupService(db)._dump_table("sql_readonly_profiles")
        sql_row = next(row for row in sql_rows if row["name"] == "b0-backup-sql")
        assert sql_row["connect_args_json"] == {"password": ""}
        assert sql_row["password_secret_ref"].startswith("keyring://")
        assert marker not in str(sql_row)
    finally:
        await db.execute(
            text("DELETE FROM http_endpoint_profiles WHERE name = 'b0-backup-http'")
        )
        await db.execute(
            text("DELETE FROM sql_readonly_profiles WHERE name = 'b0-backup-sql'")
        )
        await db.commit()


@pytest.mark.asyncio
async def test_validate_manifest_valid(db, backup_cleanup):
    svc = BackupService(db)
    result = await svc.export()
    backup_cleanup.append(result["path"])
    validation = await svc.validate_manifest(result["path"])
    assert validation["valid"] is True
    assert validation["issues"] == []
    assert validation["schema_head"]  # 不硬编码 head
    assert validation["app_version"] == __version__


@pytest.mark.asyncio
async def test_validate_manifest_detects_tamper(db, tmp_path, backup_cleanup):
    svc = BackupService(db)
    result = await svc.export()
    backup_cleanup.append(result["path"])
    orig = Path(result["path"])
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(orig) as zin:
        with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.namelist():
                data = zin.read(item)
                if item == "tables.json":
                    data = data + b" "
                zout.writestr(item, data)
    validation = await svc.validate_manifest(str(tampered))
    assert validation["valid"] is False
    assert "checksum mismatch" in validation["issues"]


@pytest.mark.asyncio
async def test_restore_drill(client, backup_cleanup):
    resp = await client.post("/backup/export")
    path = resp.json()["path"]
    backup_cleanup.append(path)
    resp = await client.post("/backup/restore/drill", json={"path": path})
    assert resp.status_code == 200
    drill = resp.json()
    assert "preview" in drill
    assert drill["manifest_validation"]["valid"] is True
    assert "chroma_mysql" in drill
    assert drill["ready"] is True


@pytest.mark.asyncio
async def test_migration_runbook_route(client):
    resp = await client.get("/backup/migration-runbook")
    assert resp.status_code == 200
    rb = resp.json()["runbook"]
    for k in (
        "mysql_unavailable",
        "alembic_failed",
        "chroma_inconsistent",
        "backup_incompatible",
    ):
        assert k in rb and rb[k]


@pytest.mark.asyncio
async def test_check_backup_manifest_flags_tampered(db, backup_cleanup):
    svc = BackupService(db)
    result = await svc.export()
    backup_cleanup.append(result["path"])
    orig = Path(result["path"])
    # 原地篡改 tables.json
    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(orig) as zin:
        for item in zin.infolist():
            entries[item.filename] = zin.read(item.filename)
    entries["tables.json"] = entries["tables.json"] + b" "
    with zipfile.ZipFile(orig, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in entries.items():
            zout.writestr(name, data)
    # _check_backup_manifest 返回 raw 发现项（不持久化）
    raw = await IntegrityService(db)._check_backup_manifest()
    assert any(f["check_name"] == "backup_manifest" for f in raw)
    flagged = [f for f in raw if f["check_name"] == "backup_manifest"]
    assert flagged[0]["severity"] == "warning"
