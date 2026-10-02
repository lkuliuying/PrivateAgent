"""附件生命周期、隔离及历史格式的临时目录回归，不调用真实模型。"""
import hashlib
import json
import os
import sqlite3
import uuid

import pytest
from test_local_executor import TERMINAL, call, close, response, setup, until

from private_agent_core.history import (
    LEGACY_FIELDS,
    LEGACY_FORMAT,
    encode_archive,
    validate_archive,
)
from private_agent_local.attachments import read_blob
from private_agent_local.migration import (
    apply_history,
    archive_sqlite,
    preview_history,
    rollback_history,
)
from private_agent_local.store import SCHEMA_VERSION, Store

AUTHORITY = "local-fixture://attachments"


class NoSecrets:
    def contains_secret(self, text):
        return False


def fixture_store(tmp_path, name="source"):
    account = hashlib.sha256(f"{AUTHORITY}\0{1}".encode()).hexdigest()
    store = Store(tmp_path / name / account / "projects.sqlite3")
    project = store.create("project", {"name": "材料测试", "status": "active", "root_path": str(tmp_path), "authorized": True})
    workspace = store.create("workspace", {"project_id": project["id"], "root_path": str(tmp_path), "kind": "root", "status": "active"})
    session = store.create("session", {"project_id": project["id"], "workspace_id": workspace["id"], "kind": "coding", "title": "材料"})
    return store, project["id"], workspace["id"], session


def staged(tmp_path, store, project, workspace, session=None, text="原始材料", draft=None):
    source = tmp_path / (uuid.uuid4().hex + ".txt")
    source.write_text(text, encoding="utf-8")
    draft = draft or uuid.uuid4().hex
    return store.attachments.stage(source, draft, project, workspace, session, secret_filter=NoSecrets()), draft, source


def commit_attachment(store, item, draft, session):
    with store.transaction():
        message = store.create("message", {"session_id": session["id"], "role": "user", "content": "请参考材料"})
        store.attachments.bind([item["id"]], draft, session, message["id"])
    return message


def test_restart_snapshot_pagination_and_draft_removal(tmp_path):
    store, pid, wid, session = fixture_store(tmp_path)
    item, draft, source = staged(tmp_path, store, pid, wid, text="中" * 8000)
    source.write_text("原文件后来修改", encoding="utf-8")
    path = store.path
    store.db.close()
    restored = Store(path)
    try:
        page = restored.attachments.read(item["id"], 0, 6000, draft_id=draft)
        assert page["content"] == "中" * 6000 and page["next_offset"] == 6000
        assert restored.attachments.read(item["id"], 6000, 6000, draft_id=draft)["content"] == "中" * 2000
        with pytest.raises(ValueError, match="未提交"):
            restored.attachments.read(item["id"], session_id=session["id"])
        restored.attachments.remove(item["id"], draft)
        assert not (path.parent / "task-attachments" / (item["id"] + ".txt")).exists()
        assert source.read_text(encoding="utf-8") == "原文件后来修改"
    finally:
        restored.db.close()


@pytest.mark.parametrize("name,raw", [
    ("large.txt", b"x" * (1024 * 1024 + 1)), ("binary.txt", b"a\x00b"),
    ("legacy.txt", b"\xff\xfe"), ("document.pdf", b"%PDF-1.4"),
    (".env", b"PRIVATE_VALUE=test-only"),
], ids=["too-large", "binary", "encoding", "pdf", "credential-file"])
def test_invalid_sources_never_create_metadata_or_project_files(tmp_path, name, raw):
    store, pid, wid, _ = fixture_store(tmp_path)
    source = tmp_path / name
    source.write_bytes(raw)
    try:
        with pytest.raises((ValueError, UnicodeError)):
            store.attachments.stage(source, uuid.uuid4().hex, pid, wid, None, secret_filter=NoSecrets())
        assert store.db.execute("SELECT count(*) FROM task_attachments").fetchone()[0] == 0
    finally:
        store.db.close()


def test_hard_link_count_and_eight_file_limit(tmp_path):
    store, pid, wid, _ = fixture_store(tmp_path)
    source = tmp_path / "linked.txt"
    source.write_text("same", encoding="utf-8")
    os.link(source, tmp_path / "alias.txt")
    try:
        with pytest.raises(ValueError, match="硬链接"):
            store.attachments.stage(source, uuid.uuid4().hex, pid, wid, None, secret_filter=NoSecrets())
        draft = uuid.uuid4().hex
        for _ in range(8):
            staged(tmp_path, store, pid, wid, text="", draft=draft)
        with pytest.raises(ValueError, match="8 个"):
            staged(tmp_path, store, pid, wid, draft=draft)
        assert len(store.attachments.list_draft(draft)) == 8
    finally:
        store.db.close()


def test_binding_is_transactional_scoped_and_preserves_shared_reference(tmp_path):
    store, pid, wid, session = fixture_store(tmp_path)
    item, draft, _ = staged(tmp_path, store, pid, wid)
    try:
        with pytest.raises(ValueError):
            with store.transaction():
                message = store.create("message", {"session_id": session["id"], "role": "user", "content": "不提交"})
                store.attachments.bind([item["id"], "f" * 32], draft, session, message["id"])
        assert not store.list("message")
        assert len(store.attachments.list_draft(draft)) == 1
        other = store.create("session", {**session, "id": None, "title": "其他"})
        second_draft = uuid.uuid4().hex
        with store.transaction():
            store.attachments.draft(second_draft, pid, wid, other["id"])
            store.db.execute("INSERT INTO attachment_draft_refs VALUES (?,?)", (second_draft, item["id"]))
        message = commit_attachment(store, item, draft, session)
        assert store.attachments.for_message(message["id"])[0]["id"] == item["id"]
        with pytest.raises(ValueError, match="未提交"):
            store.attachments.read(item["id"], session_id=other["id"])
        store.delete_session(session["id"])
        assert read_blob(store.path.parent, item) == "原始材料".encode()
        store.attachments.remove(item["id"], second_draft)
        assert not (store.attachments.directory / (item["id"] + ".txt")).exists()
    finally:
        store.db.close()


@pytest.mark.asyncio
async def test_api_snapshot_import_idempotency_cancel_and_delete(tmp_path):
    app, client, _, root, body = await setup(tmp_path)
    owner = app.state.desktop.runtime
    source = tmp_path / "notes.txt"
    source.write_text("不隐式创建项目文件", encoding="utf-8")
    draft = uuid.uuid4().hex
    scope = {key: body[key] for key in ("project_id", "workspace_id")}
    try:
        result = await client.post("/task-attachments", json={**scope, "draft_id": draft, "source_path": str(source)})
        assert result.status_code == 201, result.text
        item = result.json()
        assert not list(root.iterdir())
        assert (await client.get(f"/task-attachments/{item['id']}/content", params={"session_id": body["session_id"]})).status_code == 422
        target = {"draft_id": draft, "rel_path": "notes.txt"}
        assert (await client.post(f"/task-attachments/{item['id']}/import", json=target)).status_code == 200
        assert (await client.post(f"/task-attachments/{item['id']}/import", json=target)).status_code == 422
        assert (root / "notes.txt").read_text(encoding="utf-8") == "不隐式创建项目文件"
        request = {**body, "attachment_ids": [item["id"]], "attachment_draft_id": draft, "client_request_id": "once", "permission_mode": "readonly"}
        first = owner.create(request, launch=True)
        assert owner.create(request, launch=False)["id"] == first["id"]
        assert len(owner.store.list("message")) == 1
        confirmed = (await client.get("/agent-runs/by-request/once")).json()
        assert confirmed["id"] == first["id"] and confirmed["attachment_ids"] == [item["id"]]
        with pytest.raises(ValueError, match="正文或附件"):
            owner.create({**request, "message": "改变输入"}, launch=False)
        with pytest.raises(ValueError, match="当前会话"):
            owner.store.attachments.read(item["id"], session_id=body["session_id"] + 100)
        assert (await client.post(f"/agent-runs/{first['id']}/cancel")).status_code == 200
        await until(client, first["id"], TERMINAL)
        assert owner.store.attachments.read(item["id"], session_id=body["session_id"])["content"] == "不隐式创建项目文件"
        assert (await client.delete(f"/sessions/{body['session_id']}")).status_code == 200
        assert not (owner.store.attachments.directory / (item["id"] + ".txt")).exists()
        assert (root / "notes.txt").exists()
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_model_receives_manifest_and_reads_only_submitted_material(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    owner = app.state.desktop.runtime
    item, draft, _ = staged(tmp_path, owner.store, body["project_id"], body["workspace_id"], text="仅工具读取到的材料正文")
    unsent, _, _ = staged(tmp_path, owner.store, body["project_id"], body["workspace_id"], text="不应出现在模型上下文")
    server.responses = [response(call("read_task_attachment", {"attachment_id": item["id"], "offset": 0, "limit": 6000})), response(text="已读取参考材料")]
    try:
        result = await client.post("/agent-runs", json={**body, "permission_mode": "readonly", "attachment_ids": [item["id"]], "attachment_draft_id": draft})
        assert result.status_code == 201, result.text
        await until(client, result.json()["id"], TERMINAL)
        model_requests = [json.loads(raw) for path, raw in server.calls if path.endswith("complete")]
        first_request = json.dumps(model_requests[0], ensure_ascii=False)
        assert item["id"] in first_request and unsent["id"] not in first_request
        assert "仅工具读取到的材料正文" not in first_request
        executions = owner.store.run(result.json()["id"])["executions"]
        attachment_read = next(row for row in executions if row["tool_name"] == "read_task_attachment")
        assert attachment_read["status"] == "completed", attachment_read
        assert "仅工具读取到的材料正文" in json.dumps(attachment_read["output"], ensure_ascii=False)
    finally:
        await close(app, client)


@pytest.mark.parametrize("fail", [False, True])
def test_v7_migration_backup_and_failure_rollback(tmp_path, monkeypatch, fail):
    store, pid, _, _ = fixture_store(tmp_path)
    path = store.path
    for table in ("composer_drafts", "message_attachments", "attachment_draft_refs", "attachment_drafts", "task_attachments"):
        store.db.execute("DROP TABLE " + table)
    store.db.execute("DELETE FROM schema_migrations WHERE version>=8")
    store.db.execute("PRAGMA user_version=7")
    store.db.commit()
    store.db.close()
    if fail:
        def broken(_):
            raise RuntimeError("受控迁移失败")
        monkeypatch.setattr("private_agent_local.attachments.create_schema", broken)
        with pytest.raises(RuntimeError, match="受控"):
            Store(path)
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 7
            assert not db.execute("SELECT name FROM sqlite_master WHERE name='task_attachments'").fetchall()
    else:
        upgraded = Store(path)
        assert upgraded.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert upgraded.get("project", pid)["name"] == "材料测试"
        upgraded.db.close()
    backups = list(path.parent.glob(f"*.pre-v{SCHEMA_VERSION}-*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 7


def test_v2_roundtrip_digest_limit_v1_and_rollback(tmp_path, monkeypatch):
    store, pid, wid, session = fixture_store(tmp_path)
    item, draft, _ = staged(tmp_path, store, pid, wid)
    commit_attachment(store, item, draft, session)
    staged(tmp_path, store, pid, wid, text="不导出的草稿")
    destination, _, _, _ = fixture_store(tmp_path, "destination")
    args = {"authority": AUTHORITY, "owner_id": 1}
    try:
        archive = archive_sqlite(store.path, **args)
        assert len(archive["records"]["attachments"]) == 1
        source = tmp_path / "history.json"
        source.write_bytes(encode_archive(archive))
        preview = preview_history(str(source), **args)
        root = tmp_path / "imported"
        root.mkdir()
        imported = apply_history(destination, str(source), preview["sha256"], {str(pid): str(root)}, **args)
        message = destination.list("message")[0]
        copied = destination.attachments.for_message(message["id"])[0]
        assert copied["id"] != item["id"]
        assert destination.attachments.read(copied["id"], session_id=message["session_id"])["content"] == "原始材料"
        assert rollback_history(destination, imported["id"])["rolled_back"]
        assert not (destination.attachments.directory / (copied["id"] + ".txt")).exists()
        apply_history(destination, str(source), preview["sha256"], {str(pid): str(root)}, **args)
        message = destination.list("message")[0]
        mapped = destination.attachments.for_message(message["id"])[0]
        destination.context.import_legacy(message["session_id"])
        assert mapped["id"] in json.dumps(destination.context.items(message["session_id"]), ensure_ascii=False)
        legacy = {**archive, "format": LEGACY_FORMAT, "records": {key: archive["records"][key] for key in LEGACY_FIELDS}}
        validate_archive(legacy, **args)
        source.write_bytes(encode_archive(legacy))
        legacy_preview = preview_history(str(source), **args)
        assert apply_history(destination, str(source), legacy_preview["sha256"], {str(pid): str(root)}, **args)
        archive["records"]["attachments"][0]["content"] = "损坏"
        with pytest.raises(ValueError):
            validate_archive(archive, **args)
        (store.attachments.directory / (item["id"] + ".txt")).write_text("损坏", encoding="utf-8")
        with pytest.raises(ValueError, match="损坏"):
            archive_sqlite(store.path, **args)
        monkeypatch.setattr("private_agent_core.history.MAX_BYTES", 100)
        with pytest.raises(ValueError, match="64 MiB"):
            encode_archive(legacy)
    finally:
        destination.db.close()
        store.db.close()
