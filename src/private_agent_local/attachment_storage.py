"""附件清理预览与引用版本核对；正文及历史引用始终保留。"""
import hashlib
import uuid

from fastapi import Depends, Query
from pydantic import Field

from . import files
from .drafts import DraftData, Drafts, DraftWrite
from .model_catalog import Input
from .model_errors import CloudError
from .store import encode


class CleanupInput(Input):
    attachment_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    draft_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    version: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class AttachmentStorage:
    def __init__(self, store):
        self.store = store

    def references(self, identifier):
        drafts = []
        for draft_id, project_id, workspace_id, session_id in self.store.db.execute("SELECT d.* FROM attachment_drafts d JOIN attachment_draft_refs r ON d.id=r.draft_id WHERE r.attachment_id=? ORDER BY d.id", (identifier,)):
            composer = self.store.db.execute("SELECT scope_key,revision FROM composer_drafts WHERE json_extract(data,'$.draftId')=?", (draft_id,)).fetchone()
            drafts.append({"id": draft_id, "project_id": project_id, "workspace_id": workspace_id, "session_id": session_id,
                           "title": self.store.get("session", session_id).get("title", "会话") if session_id else "首页草稿",
                           "scope_key": composer[0] if composer else None, "revision": composer[1] if composer else None})
        sessions = []
        for session_id, count in self.store.db.execute("SELECT m.session_id,count(*) FROM messages m JOIN message_attachments r ON m.id=r.message_id WHERE r.attachment_id=? GROUP BY m.session_id ORDER BY m.session_id", (identifier,)):
            sessions.append({"id": session_id, "title": self.store.get("session", session_id).get("title", "会话"), "messages": count})
        return {"drafts": drafts, "sessions": sessions}

    def entry(self, identifier):
        item = self.store.attachments.get(identifier)
        root = self.store.attachments.directory
        target = root / (identifier + (".txt" if item.get("kind", "text") == "text" else ".blob"))
        if files.linked(root) or files.linked(target) or root.resolve() != root:
            status = "附件路径身份变化，请重新选择材料"
        else:
            try:
                status = "可预览；预览时校验摘要" if target.stat().st_size == item["size_bytes"] else "副本大小不符，可能已损坏"
            except OSError:
                status = "副本缺失或不可访问"
        return {**item, "project_name": self.store.get("project", item["project_id"]).get("name", "项目"), "read_status": status, **self.references(identifier)}

    def list(self, offset, limit):
        total, size = self.store.db.execute("SELECT count(*),coalesce(sum(json_extract(data,'$.size_bytes')),0) FROM task_attachments").fetchone()
        ids = self.store.db.execute("SELECT id FROM task_attachments ORDER BY rowid DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return {"total": total, "size_bytes": size, "offset": offset, "items": [self.entry(row[0]) for row in ids],
                "cache_bytes": 0, "cache_policy": "图片和 PDF 页面按需解码，当前没有可单独清理的持久化解析缓存。",
                "retention": "未发送材料持续保留；移除草稿引用或删除会话后，仅在没有其他引用时清理应用副本。项目原件不受影响。"}

    def preview(self, attachment_id, draft_id):
        item = self.entry(attachment_id)
        chosen = next((draft for draft in item["drafts"] if draft["id"] == draft_id), None)
        if not chosen:
            raise CloudError(409, "草稿引用已改变，请刷新附件清单", code="attachment_cleanup_conflict")
        version = hashlib.sha256(encode({"id": item["id"], "sha256": item["sha256"], "drafts": item["drafts"], "sessions": item["sessions"]}).encode()).hexdigest()
        reclaim = item["size_bytes"] if len(item["drafts"]) == 1 and not item["sessions"] else 0
        return {"version": version, "attachment_id": item["id"], "draft_id": draft_id, "name": item["name"],
                "draft": chosen, "remaining_drafts": len(item["drafts"]) - 1, "sessions": item["sessions"], "reclaim_bytes": reclaim}

    def remove(self, value):
        with self.store.transaction():
            preview = self.preview(value.attachment_id, value.draft_id)
            if not value.version or value.version != preview["version"]:
                raise CloudError(409, "清理范围在预览后已改变，未移除材料；请重新核对", code="attachment_cleanup_conflict")
            scope = preview["draft"]["scope_key"]
            if scope:
                current = Drafts(self.store).get(scope)
                data = DraftData.model_validate(current["data"])
                data.attachments = [item for item in data.attachments if item.id != value.attachment_id]
                data.clientRequestId, data.requestSignature = "", ""
                Drafts(self.store).put(scope, DraftWrite(revision=current["revision"], mutation_id=uuid.uuid4().hex, data=data))
            self.store.attachments.remove(value.attachment_id, value.draft_id)
        return {"removed": True, "cleanup_pending": self.store.attachments.needs_cleanup, "reclaim_bytes": preview["reclaim_bytes"]}


def install_attachment_storage_routes(app, local):
    @app.get("/attachment-storage")
    async def list_materials(offset: int = Query(default=0, ge=0), limit: int = Query(default=30, ge=1, le=100), runtime=Depends(local)):
        return AttachmentStorage(runtime.store).list(offset, limit)

    @app.post("/attachment-storage/preview")
    async def preview(value: CleanupInput, runtime=Depends(local)):
        return AttachmentStorage(runtime.store).preview(value.attachment_id, value.draft_id)

    @app.post("/attachment-storage/cleanup")
    async def cleanup(value: CleanupInput, runtime=Depends(local)):
        return AttachmentStorage(runtime.store).remove(value)
