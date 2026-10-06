"""历史迁移验证数据守恒、身份隔离、无副作用重放与可核对回滚。"""
import hashlib
import json
import uuid
from types import SimpleNamespace

import pytest
from test_local_executor import close, setup

from private_agent_core.history import FIELDS, FORMAT, encode_archive
from private_agent_local.mcp_library import McpLibrary, PrepareInput, SourceInput
from private_agent_local.migration import (
    apply_history,
    archive_sqlite,
    preview_history,
    rollback_history,
)
from private_agent_local.secret_filter import SecretFilter
from private_agent_local.store import SCHEMA_VERSION, Store, encode

AUTHORITY = "https://account.example.test"


def archive_fixture():
    records = {kind: [] for kind in FIELDS}
    records.update(projects=[{"id": 1, "name": "旧项目", "root_path": "C:/old", "status": "active"}],
        workspaces=[{"id": 1, "project_id": 1, "kind": "root", "root_path": "C:/old"}],
        sessions=[{"id": 1, "project_id": 1, "workspace_id": 1, "kind": "coding", "title": "旧会话", "last_run_id": "old-run"}],
        messages=[{"id": 1, "session_id": 1, "role": "user", "content": "原始中文内容"}],
        runs=[{"id": "old-run", "session_id": 1, "project_id": 1, "workspace_id": 1, "status": "running", "permission_mode": "full_access"}],
        events=[{"id": 1, "run_id": "old-run", "sequence": 1, "event_type": "run.started", "payload_json": {}}],
        approvals=[{"id": "approval", "run_id": "old-run", "tool_name": "write_project_file", "status": "pending", "arguments_json": {"rel_path": "never.txt", "content": "不可重放"}}],
        executions=[{"id": "execution", "run_id": "old-run", "tool_name": "run_project_command", "status": "running"}],
        agent_tasks=[{"id": 1, "session_id": 1, "title": "长期计划", "goal": "不是一次运行", "status": "planned"}],
        agent_task_steps=[{"id": 1, "task_id": 1, "title": "原计划步骤", "status": "planned"}],
        agent_evidence=[{"id": 1, "task_id": 1, "step_id": 1, "content_md": "原证据"}])
    return {"format": FORMAT, "source": {"authority": AUTHORITY, "owner_id": 7}, "records": records}


def prepare(tmp_path):
    source = tmp_path / "history.json"
    source.write_bytes(encode_archive(archive_fixture()))
    store = Store(tmp_path / "current" / "projects.sqlite3")
    root = tmp_path / "project"
    root.mkdir()
    args = {"authority": AUTHORITY, "owner_id": 7}
    preview = preview_history(str(source), **args)
    return source, store, root, args, preview


def test_import_preserves_archive_remaps_ids_and_never_replays(tmp_path):
    source, store, root, args, preview = prepare(tmp_path)
    try:
        existing = store.create("project", {"name": "已有项目", "root_path": "unchanged"})
        result = apply_history(store, str(source), preview["sha256"], {"1": str(root)}, **args)
        assert result["rollback_fingerprint_version"] == 2
        assert result["imported_counts"] == {"projects": 1, "workspaces": 1, "sessions": 1, "messages": 1, "runs": 1,
                                             "attachments": 0, "sent_attachments": 0}
        assert result["skipped_counts"] == {"projects": 0, "workspaces": 0, "sessions": 0, "messages": 0, "runs": 0,
                                            "attachments": 0}
        run = store.runs()[0]
        assert run["project_id"] != existing["id"]
        assert run["status"] == "failed" and run["error_code"] == "history_import_interrupted"
        assert run["permission_mode"] == "confirm" and run["full_access_grant_id"] is None
        assert run["approvals"][0]["status"] == "cancelled"
        assert run["executions"][0]["status"] == "unknown"
        assert not list(root.iterdir())
        original = store._unpack(store.db.execute("SELECT archive FROM history_imports").fetchone()[0])
        assert original == archive_fixture()
        assert original["records"]["agent_tasks"][0]["status"] == "planned"
        assert store.list("message")[0]["content"] == "原始中文内容"
        assert apply_history(store, str(source), preview["sha256"], {"1": str(root)}, **args)["id"] == result["id"]
        assert len(store.list("project")) == 2
        assert rollback_history(store, result["id"])["rolled_back"]
        assert store.list("project") == [existing] and not store.runs()
    finally:
        store.db.close()


def test_tampering_wrong_account_or_new_changes_block_import_or_rollback(tmp_path):
    source, store, root, args, preview = prepare(tmp_path)
    try:
        with pytest.raises(ValueError, match="不匹配"):
            preview_history(str(source), authority=AUTHORITY, owner_id=8)
        changed = archive_fixture()
        changed["records"]["messages"][0]["content"] = "预览后修改"
        source.write_bytes(encode_archive(changed))
        with pytest.raises(ValueError, match="已变化"):
            apply_history(store, str(source), preview["sha256"], {"1": str(root)}, **args)
        assert not store.list("project")
        preview = preview_history(str(source), **args)
        result = apply_history(store, str(source), preview["sha256"], {"1": str(root)}, **args)
        store.create("project", {"name": "导入后新增", "root_path": "new"})
        with pytest.raises(ValueError, match="其他修改"):
            rollback_history(store, result["id"])
        assert len(store.list("project")) == 2
    finally:
        store.db.close()


def test_mid_import_failure_rolls_back_every_normalized_record(tmp_path, monkeypatch):
    source, store, root, args, preview = prepare(tmp_path)
    try:
        def failed(_run):
            raise OSError("fixture write failure")
        monkeypatch.setattr(store, "save_run", failed)
        with pytest.raises(OSError):
            apply_history(store, str(source), preview["sha256"], {"1": str(root)}, **args)
        assert not store.list("project") and not store.list("message")
        assert store.db.execute("SELECT count(*) FROM history_imports").fetchone()[0] == 0
        assert list((tmp_path / "current").glob(f"*.pre-v{SCHEMA_VERSION}-*.sqlite3"))
    finally:
        store.db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["create", "update", "prepare"])
async def test_mcp_changes_after_import_block_rollback_and_preserve_data(tmp_path, change):
    source, store, root, args, preview = prepare(tmp_path)
    owner = SimpleNamespace(store=store, secret_filter=SecretFilter())
    library = McpLibrary(owner)
    configuration = SourceInput(name="独立服务", transport="https", url="https://example.test/mcp")
    try:
        service = library.create(configuration) if change == "update" else None
        result = apply_history(store, str(source), preview["sha256"], {"1": str(root)}, **args)
        if change == "create":
            library.create(configuration)
        else:
            prepared = await library.prepare(PrepareInput(
                request_id=uuid.uuid4().hex,
                configuration=configuration.model_copy(update={"name": "导入后的配置"}),
                service_id=service["id"] if service else None,
                expected_version=service["version"] if service else None,
            ))
            if change == "update":
                await library.commit(prepared["id"], None)
                assert library.service(service["id"])["name"] == "导入后的配置"
            else:
                assert library.change(prepared["id"])["status"] == "prepared"
        before = tuple(store.db.iterdump())
        backup = store.path.parent / result["backup"]["filename"]
        backup_digest = hashlib.sha256(backup.read_bytes()).hexdigest()
        with pytest.raises(ValueError, match="其他修改"):
            rollback_history(store, result["id"])
        assert tuple(store.db.iterdump()) == before
        assert hashlib.sha256(backup.read_bytes()).hexdigest() == backup_digest
    finally:
        if getattr(owner, "mcp_credentials", None) is not None:
            owner.mcp_credentials.close()
        store.db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [None, 1, 3, "2", 2.0])
async def test_unsupported_rollback_version_keeps_history_readable_and_idempotent(tmp_path, version):
    app, client, _, root, _ = await setup(tmp_path)
    store = app.state.desktop.runtime.store
    try:
        archive = archive_fixture()
        runtime = app.state.desktop.runtime
        archive["source"] = {"authority": runtime.authority, "owner_id": runtime.owner_id}
        source = tmp_path / "history.json"
        source.write_bytes(encode_archive(archive))
        args = {"authority": runtime.authority, "owner_id": runtime.owner_id}
        preview = preview_history(str(source), **args)
        mappings = {"1": str(root)}
        imported = apply_history(store, str(source), preview["sha256"], mappings, **args)
        if version is None:
            imported.pop("rollback_fingerprint_version")
        else:
            imported["rollback_fingerprint_version"] = version
        with store.transaction():
            store.db.execute("UPDATE history_imports SET data=? WHERE id=?", (encode(imported), imported["id"]))
        before = tuple(store.db.iterdump())
        backup = store.path.parent / imported["backup"]["filename"]
        backup_digest = hashlib.sha256(backup.read_bytes()).hexdigest()
        base = f"/local-history/imports/{imported['id']}"
        rejected = await client.post(base + "/rollback")
        assert rejected.status_code == 422 and "回滚校验版本" in rejected.json()["detail"]
        listed = await client.get("/local-history/imports")
        assert listed.status_code == 200 and listed.json() == [imported]
        records = await client.get(base + "/records", params={"kind": "messages"})
        assert records.status_code == 200 and records.json()["items"] == archive["records"]["messages"]
        exported = await client.get(base + "/export")
        assert exported.status_code == 200 and exported.json() == archive
        repeated = await client.post("/local-history/import", json={"path": str(source), "sha256": preview["sha256"], "mappings": mappings})
        assert repeated.status_code == 200 and repeated.json() == imported
        assert tuple(store.db.iterdump()) == before
        assert hashlib.sha256(backup.read_bytes()).hexdigest() == backup_digest
    finally:
        await close(app, client)


def test_tampered_rollback_backup_preserves_current_database(tmp_path):
    source, store, root, args, preview = prepare(tmp_path)
    try:
        imported = apply_history(store, str(source), preview["sha256"], {"1": str(root)}, **args)
        backup = store.path.parent / imported["backup"]["filename"]
        backup.write_bytes(backup.read_bytes() + b"controlled-corruption")
        before = tuple(store.db.iterdump())
        with pytest.raises(ValueError, match="备份校验失败"):
            rollback_history(store, imported["id"])
        assert tuple(store.db.iterdump()) == before
    finally:
        store.db.close()


@pytest.mark.parametrize("version", [4, 5, 6, 7])
def test_readonly_sqlite_export_checks_account_and_leaves_source_unchanged(tmp_path, version):
    account = hashlib.sha256(f"{AUTHORITY}\0{7}".encode()).hexdigest()
    path = tmp_path / account / "projects.sqlite3"
    store = Store(path)
    store.create("project", {"name": "联网旧记录", "root_path": "C:/project"})
    store.save_run({"id": "fixture-run", "status": "completed", "steps": [
        {"id": "fixture-step", "ordinal": 1, "kind": "tool", "status": "failed", "error": "保留原错误"}]})
    # 这些版本共享基础记录表；附加表不进入历史交换包。
    store.db.execute(f"PRAGMA user_version={version}")
    store.db.close()
    before = path.read_bytes()
    archive = archive_sqlite(path, authority=AUTHORITY, owner_id=7)
    assert archive["records"]["projects"][0]["name"] == "联网旧记录"
    assert archive["records"]["run_steps"][0]["error_message"] == "保留原错误"
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="账号目录"):
        archive_sqlite(path, authority=AUTHORITY, owner_id=8)


def test_export_rejects_future_schema_without_modifying_it(tmp_path):
    account = hashlib.sha256(f"{AUTHORITY}\0{7}".encode()).hexdigest()
    path = tmp_path / account / "projects.sqlite3"
    store = Store(path)
    store.db.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    store.db.close()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="不支持的版本"):
        archive_sqlite(path, authority=AUTHORITY, owner_id=7)
    assert path.read_bytes() == before


def test_unknown_authorization_fields_and_broken_relations_are_rejected(tmp_path):
    source = tmp_path / "history.json"
    archive = archive_fixture()
    archive["records"]["approvals"][0]["approval_token_sha256"] = "must-not-import"
    source.write_bytes(encode_archive(archive))
    with pytest.raises(ValueError, match="未知字段"):
        preview_history(str(source), authority=AUTHORITY, owner_id=7)
    archive = archive_fixture()
    archive["records"]["messages"][0]["session_id"] = 999
    source.write_text(json.dumps(archive), encoding="utf-8")
    with pytest.raises(ValueError, match="关联"):
        preview_history(str(source), authority=AUTHORITY, owner_id=7)
