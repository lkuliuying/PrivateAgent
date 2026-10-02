"""附件清理必须核对引用，保留正文、历史和外部源文件。"""
import uuid

import pytest
from test_local_attachments import fixture_store, staged

from private_agent_local.attachment_storage import AttachmentStorage, CleanupInput
from private_agent_local.drafts import DraftData, Drafts, DraftWrite
from private_agent_local.model_errors import CloudError


def test_cleanup_keeps_text_and_rejects_stale_preview(tmp_path):
    store, pid, wid, session = fixture_store(tmp_path)
    try:
        item, draft, source = staged(tmp_path, store, pid, wid, session["id"])
        service, drafts = AttachmentStorage(store), Drafts(store)
        key = f"pa_coding_draft_v2_{pid}_{wid}_{session['id']}"
        data = DraftData(text="仍然保留", draftId=draft, attachments=[item], clientRequestId="old")
        drafts.put(key, DraftWrite(revision=0, mutation_id=uuid.uuid4().hex, data=data))
        preview = service.preview(item["id"], draft)
        assert preview["reclaim_bytes"] == item["size_bytes"]
        data.text = "后续输入"
        drafts.put(key, DraftWrite(revision=1, mutation_id=uuid.uuid4().hex, data=data))
        value = CleanupInput(attachment_id=item["id"], draft_id=draft, version=preview["version"])
        with pytest.raises(CloudError, match="范围在预览后"):
            service.remove(value)
        value.version = service.preview(item["id"], draft)["version"]
        service.remove(value)
        assert drafts.get(key)["data"]["text"] == "后续输入"
        assert drafts.get(key)["data"]["attachments"] == []
        assert drafts.get(key)["data"]["clientRequestId"] == ""
        assert source.read_text(encoding="utf-8") == "原始材料"
        assert service.list(0, 30)["total"] == 0
    finally:
        store.db.close()


def test_shared_history_material_is_not_removed_and_missing_copy_is_reported(tmp_path):
    store, pid, wid, session = fixture_store(tmp_path)
    try:
        item, draft, _ = staged(tmp_path, store, pid, wid, session["id"])
        with store.transaction():
            message = store.create("message", {"session_id": session["id"], "role": "user", "content": "引用"})
            store.db.execute("INSERT INTO message_attachments VALUES (?,?,?)", (message["id"], item["id"], 0))
        service = AttachmentStorage(store)
        preview = service.preview(item["id"], draft)
        assert preview["reclaim_bytes"] == 0 and len(preview["sessions"]) == 1
        service.remove(CleanupInput(attachment_id=item["id"], draft_id=draft, version=preview["version"]))
        assert store.attachments.read(item["id"], session_id=session["id"])["content"] == "原始材料"
        (store.attachments.directory / (item["id"] + ".txt")).unlink()
        listing = service.list(0, 30)
        assert "缺失" in listing["items"][0]["read_status"]
        assert listing["cache_bytes"] == 0
    finally:
        store.db.close()
