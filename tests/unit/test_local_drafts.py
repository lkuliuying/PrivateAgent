"""持久草稿在隔离数据库中的迁移、并发、引用与回执回归。"""
import json
import sqlite3
import uuid

import pytest
from test_local_attachments import commit_attachment, fixture_store, staged
from test_local_executor import close, setup

from private_agent_local.drafts import (
    DraftAcknowledgement,
    DraftData,
    Drafts,
    DraftTransfer,
    DraftWrite,
)
from private_agent_local.model_errors import CloudError
from private_agent_local.store import SCHEMA_VERSION, Store, encode, now


def key(project, workspace, session=None):
    return f"pa_coding_draft_v2_{project}_{workspace}_{session or 'new'}"


def payload(text="待发送", **fields):
    return DraftData(text=text, draftId=uuid.uuid4().hex, **fields)


def save(service, scope, data, revision=0, mutation=None):
    return service.put(scope, DraftWrite(revision=revision, mutation_id=mutation or uuid.uuid4().hex, data=data))


def test_restart_preserves_text_references_and_request_identity(tmp_path):
    store, pid, wid, session = fixture_store(tmp_path)
    item, draft, _ = staged(tmp_path, store, pid, wid, session["id"])
    scope = key(pid, wid, session["id"])
    data = DraftData(text="正文", draftId=draft, attachments=[{"id": item["id"]}], clientRequestId="same-request", requestSignature="signature")
    result = save(Drafts(store), scope, data)
    store.db.close()
    restored = Store(store.path)
    try:
        assert Drafts(restored).get(scope) == result
        assert result["data"]["attachments"][0]["name"] == item["name"]
    finally:
        restored.db.close()


def test_revision_and_duplicate_write_guard(tmp_path):
    store, pid, wid, _ = fixture_store(tmp_path)
    try:
        drafts, scope = Drafts(store), key(pid, wid)
        data, mutation = payload(), uuid.uuid4().hex
        first = save(drafts, scope, data, mutation=mutation)
        assert save(drafts, scope, data, mutation=mutation) == first
        with pytest.raises(CloudError, match="内容发生变化"):
            save(drafts, scope, payload("其他输入"), mutation=mutation)
        with pytest.raises(CloudError, match="其他窗口"):
            save(drafts, scope, payload("迟到的旧输入"))
        assert drafts.get(scope) == first
    finally:
        store.db.close()


def test_acknowledgement_preserves_new_input_and_sent_material(tmp_path):
    store, pid, wid, session = fixture_store(tmp_path)
    try:
        drafts, scope = Drafts(store), key(pid, wid, session["id"])
        item, draft, _ = staged(tmp_path, store, pid, wid, session["id"])
        data = DraftData(text="原消息", draftId=draft, attachments=[{"id": item["id"]}], clientRequestId="one")
        save(drafts, scope, data)
        commit_attachment(store, item, draft, session)
        data.text = "之后的新草稿"
        save(drafts, scope, data, revision=1)
        ack = DraftAcknowledgement(client_request_id="one", message="原消息", attachment_ids=[item["id"]])
        assert drafts.acknowledge(scope, ack)["data"]["text"] == "之后的新草稿"
        ack.message = "之后的新草稿"
        assert drafts.acknowledge(scope, ack)["data"]["text"] == ""
        assert store.attachments.read(item["id"], session_id=session["id"])["content"] == "原始材料"
    finally:
        store.db.close()


def test_home_transfer_is_atomic_and_keeps_new_home_draft(tmp_path):
    store, pid, wid, session = fixture_store(tmp_path)
    try:
        drafts, home, target = Drafts(store), key(pid, wid), key(pid, wid, session["id"])
        item, draft, _ = staged(tmp_path, store, pid, wid)
        original = DraftData(text="第一条", draftId=draft, attachments=[{"id": item["id"]}], clientRequestId="one")
        save(drafts, home, original)
        changed = original.model_copy(update={"text": "之后的输入"})
        save(drafts, home, changed, revision=1)
        transfer = DraftTransfer(destination=target, revision=1, draft_id=draft, data=original)
        result = drafts.transfer(home, transfer)
        assert result["data"]["text"] == "第一条"
        assert drafts.transfer(home, transfer) == result
        kept = drafts.get(home)["data"]
        assert kept["text"] == "之后的输入" and kept["draftId"] != draft
        commit_attachment(store, item, draft, session)
        assert store.attachments.read(item["id"], draft_id=kept["draftId"])["content"] == "原始材料"
    finally:
        store.db.close()


def test_scope_and_unsent_attachments_are_isolated(tmp_path):
    store, pid, wid, session = fixture_store(tmp_path)
    try:
        drafts = Drafts(store)
        item, _, _ = staged(tmp_path, store, pid, wid)
        with pytest.raises(ValueError, match="未提交"):
            save(drafts, key(pid, wid, session["id"]), payload(attachments=[{"id": item["id"]}]))
        with pytest.raises(ValueError, match="不匹配"):
            drafts.get(key(pid, "none", session["id"]))
        assert drafts.get("pa_coding_draft_v2_none_none_new")["data"] is None
    finally:
        store.db.close()


def test_removed_attachment_does_not_block_saving_remaining_draft(tmp_path):
    store, pid, wid, _ = fixture_store(tmp_path)
    try:
        item, draft, _ = staged(tmp_path, store, pid, wid)
        drafts, scope = Drafts(store), key(pid, wid)
        data = DraftData(text="保留正文", draftId=draft, attachments=[{"id": item["id"]}])
        save(drafts, scope, data)
        store.attachments.remove(item["id"], draft)
        data.attachments = []
        assert save(drafts, scope, data, revision=1)["data"]["text"] == "保留正文"
    finally:
        store.db.close()


def test_v8_migration_backups_before_new_table(tmp_path):
    store, pid, wid, session = fixture_store(tmp_path)
    originals = {"project": store.get("project", pid), "workspace": store.get("workspace", wid), "session": session}
    # 还原 v8 的真实对象边界，不能只降低版本号而留下后续版本的迁移记录。
    for table in ("composer_drafts", "mcp_service_changes", "mcp_services"):
        store.db.execute("DROP TABLE " + table)
    store.db.execute("DROP INDEX session_creation_request")
    store.db.execute("DELETE FROM schema_migrations WHERE version>=9")
    store.db.execute("INSERT OR IGNORE INTO schema_migrations VALUES (?,?,?)", (8, now(), encode({"fixture": "v8"})))
    store.db.execute("PRAGMA user_version=8")
    store.db.commit()
    store.db.close()
    restored = Store(store.path)
    try:
        assert restored.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        backups = list(store.path.parent.glob(f"projects.pre-v{SCHEMA_VERSION}-*.sqlite3"))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as backup:
            assert backup.execute("PRAGMA user_version").fetchone()[0] == 8
            assert backup.execute("SELECT version FROM schema_migrations").fetchall() == [(8,)]
            later_objects = {"composer_drafts", "session_creation_request", "mcp_services", "mcp_service_changes"}
            assert not later_objects.intersection(row[0] for row in backup.execute("SELECT name FROM sqlite_master"))
            for kind, original in originals.items():
                assert json.loads(backup.execute(f"SELECT data FROM {kind}s WHERE id=?", (original["id"],)).fetchone()[0]) == original
        assert later_objects <= {row[0] for row in restored.db.execute("SELECT name FROM sqlite_master")}
        for kind, original in originals.items():
            assert restored.get(kind, original["id"]) == original
        assert save(Drafts(restored), key(pid, wid), payload())["revision"] == 1
    finally:
        restored.db.close()


@pytest.mark.asyncio
async def test_api_validation_does_not_echo_body_and_projects_isolate_drafts(tmp_path):
    app, client, _, _, binding = await setup(tmp_path)
    try:
        scope = key(binding["project_id"], binding["workspace_id"], binding["session_id"])
        data = {"revision": 0, "mutation_id": uuid.uuid4().hex, "data": payload().model_dump()}
        assert (await client.put(f"/composer-drafts/{scope}", json=data)).status_code == 200
        data["data"]["text"] = "synthetic-sensitive-input" * 2000
        rejected = await client.put(f"/composer-drafts/{scope}", json=data)
        assert rejected.status_code == 422 and "synthetic-sensitive-input" not in rejected.text
        assert (await client.get(f"/composer-drafts/{key(999,999)}")).status_code == 404
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_first_session_request_is_idempotent_after_lost_response(tmp_path):
    app, client, _, _, binding = await setup(tmp_path)
    try:
        body = {"project_id": binding["project_id"], "workspace_id": binding["workspace_id"],
                "kind": "coding", "title": "同一个首页请求", "client_request_id": "first-request"}
        first = await client.post("/sessions", json=body)
        repeated = await client.post("/sessions", json=body)
        assert first.status_code == repeated.status_code == 201
        assert first.json()["id"] == repeated.json()["id"]
        conflict = await client.post("/sessions", json={**body, "title": "不同请求"})
        assert conflict.status_code == 409
    finally:
        await close(app, client)
