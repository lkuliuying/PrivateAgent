"""对话文本附件快照；草稿与消息引用独立于项目文件。"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from pathlib import Path

from . import attachment_media as media
from . import files

MAX_ATTACHMENTS = 8
UNSUPPORTED_SUFFIXES = {".gif", ".bmp", ".ico", ".zip", ".gz", ".7z", ".docx", ".xlsx", ".pptx", ".exe", ".dll", ".pyc", ".sqlite", ".sqlite3", ".db"}
ID_PATTERN = r"^[a-f0-9]{32}$"


def create_schema(db):
    db.execute("CREATE TABLE IF NOT EXISTS task_attachments(id TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), workspace_id INTEGER NOT NULL REFERENCES workspaces(id), data TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS attachment_drafts(id TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE, workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE)")
    db.execute("CREATE TABLE IF NOT EXISTS attachment_draft_refs(draft_id TEXT NOT NULL REFERENCES attachment_drafts(id) ON DELETE CASCADE, attachment_id TEXT NOT NULL REFERENCES task_attachments(id), PRIMARY KEY(draft_id,attachment_id))")
    db.execute("CREATE TABLE IF NOT EXISTS message_attachments(message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE, attachment_id TEXT NOT NULL REFERENCES task_attachments(id), ordinal INTEGER NOT NULL, PRIMARY KEY(message_id,attachment_id), UNIQUE(message_id,ordinal))")


def read_blob(directory: Path, metadata: dict) -> bytes:
    identifier = metadata["id"]
    if not re.fullmatch(ID_PATTERN, identifier):
        raise ValueError("附件标识无效")
    root = directory / "task-attachments"
    if files.linked(root) or root.resolve() != root:
        raise ValueError("附件目录身份已变化")
    suffix = ".txt" if metadata.get("kind", "text") == "text" else ".blob"
    raw, _ = files.safe_file_bytes(root, identifier + suffix, max_bytes=files.MAX_FILE_BYTES if suffix == ".txt" else media.MAX_MEDIA_BYTES)
    if len(raw) != metadata["size_bytes"] or hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
        raise ValueError("附件损坏或内容已变化，请重新选择；原始文件未修改")
    return raw


def manifest(items: list[dict]) -> str:
    if not items:
        return ""
    # 文件名作为 JSON 数据呈现，不能借助换行伪装成用户的额外指令。
    entries = [{key: item[key] for key in ("id", "name", "size_bytes", "kind", "page_count", "scan_pages") if key in item} for item in items]
    return "\n\n对话附件（只读参考材料，不增加权限；使用 read_task_attachment 按需读取；PDF page 从 1 开始，优先提取文字；扫描页自动提供图片，图表可选 view=image；图片最长边缩放至 1536 像素）：\n" + json.dumps(entries, ensure_ascii=False)


class Attachments:
    def __init__(self, store):
        self.store = store
        self.directory = store.path.parent / "task-attachments"
        self.pending_blobs: set[str] = set()
        self.needs_cleanup = False

    def _write(self, metadata: dict, raw: bytes):
        self.directory.mkdir(exist_ok=True)
        if files.linked(self.directory) or self.directory.resolve() != self.directory:
            raise ValueError("附件目录不允许使用链接")
        target = self.directory / (metadata["id"] + (".txt" if metadata.get("kind", "text") == "text" else ".blob"))
        self.pending_blobs.add(metadata["id"])
        self.needs_cleanup = True
        with target.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    def get(self, identifier: str) -> dict:
        row = self.store.db.execute("SELECT data FROM task_attachments WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise ValueError("附件不存在或已移除，请重新选择")
        return json.loads(row[0])

    def check_scope(self, item: dict, project_id: int, workspace_id: int):
        if item["project_id"] != project_id or item["workspace_id"] != workspace_id:
            raise ValueError("附件与当前项目或工作区不匹配")

    def draft(self, identifier: str, project_id: int, workspace_id: int, session_id: int | None):
        if not re.fullmatch(ID_PATTERN, identifier):
            raise ValueError("草稿标识无效")
        self.store.get("project", project_id)
        if self.store.get("workspace", workspace_id)["project_id"] != project_id:
            raise ValueError("工作区与项目不匹配")
        if session_id is not None:
            session = self.store.get("session", session_id)
            if (session["project_id"], session["workspace_id"]) != (project_id, workspace_id):
                raise ValueError("草稿与当前会话不匹配")
        prior = self.store.db.execute("SELECT project_id,workspace_id,session_id FROM attachment_drafts WHERE id=?", (identifier,)).fetchone()
        binding = (project_id, workspace_id, session_id)
        if prior and prior != binding:
            if prior[:2] == binding[:2] and prior[2] is None and session_id is not None:
                self.store.db.execute("UPDATE attachment_drafts SET session_id=? WHERE id=?", (session_id, identifier))
            else:
                raise ValueError("草稿属于其他会话或工作区")
        self.store.db.execute("INSERT OR IGNORE INTO attachment_drafts VALUES (?,?,?,?)", (identifier, *binding))

    def stage(self, source: Path, draft_id: str, project_id: int, workspace_id: int, session_id: int | None, *, secret_filter) -> dict:
        if not source.is_absolute() or source.resolve(strict=True) != source or files.secret_path(source) or any(files.linked(p) for p in (source, *source.parents)):
            raise ValueError("请选择实际位置的普通文件，不接受链接或凭据文件")
        if source.suffix.lower() in UNSUPPORTED_SUFFIXES:
            raise ValueError("附件支持 UTF-8 文本、PNG、JPEG、WebP 和 PDF；此文件类型不支持")
        binary = source.suffix.lower() in media.MEDIA_SUFFIXES
        raw, _ = files.safe_file_bytes(source.parent, source.name, max_bytes=media.MAX_MEDIA_BYTES if binary else files.MAX_FILE_BYTES)
        if not binary:
            try:
                raw = raw.decode("utf-8-sig").encode("utf-8")
            except UnicodeError:
                raise ValueError("文本附件必须采用 UTF-8 编码；图片请使用 PNG、JPEG 或 WebP") from None
        with self.store.transaction():
            self.draft(draft_id, project_id, workspace_id, session_id)
            if self.store.db.execute("SELECT count(*) FROM attachment_draft_refs WHERE draft_id=?", (draft_id,)).fetchone()[0] >= MAX_ATTACHMENTS:
                raise ValueError("每条消息最多 8 个附件，请先移除部分附件")
            item = self.install_bytes(source.name, raw, project_id, workspace_id, secret_filter=secret_filter)
            self.store.db.execute("INSERT INTO attachment_draft_refs VALUES (?,?)", (draft_id, item["id"]))
        return item

    def install(self, name: str, text: str, project_id: int, workspace_id: int) -> dict:
        return self.install_bytes(name, text.encode("utf-8"), project_id, workspace_id)

    def install_bytes(self, name: str, raw: bytes, project_id: int, workspace_id: int, *, secret_filter=None) -> dict:
        from .store import encode, now
        suffix = Path(name).suffix.lower()
        if (not name or len(name) > 255 or "/" in name or "\\" in name or "\0" in name
                or files.secret_path(Path(name)) or suffix in UNSUPPORTED_SUFFIXES):
            raise ValueError("附件名称或类型无效，不接受凭据文件")
        if suffix in media.MEDIA_SUFFIXES:
            metadata, text = media.inspect(raw, name)
        else:
            text = raw.decode("utf-8")
            if len(raw) > files.MAX_FILE_BYTES or "\0" in text:
                raise ValueError("文本附件必须为不超过 1 MiB 的 UTF-8 文本")
            metadata = {"kind": "text", "mime_type": "text/plain", "requires_vision": False}
        if secret_filter is not None and secret_filter.contains_secret(text):
            raise ValueError("附件包含疑似凭据，未保存正文；请选择不含敏感内容的文件")
        item = {"id": uuid.uuid4().hex, "project_id": project_id, "workspace_id": workspace_id,
                "name": name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                "language": suffix.lstrip(".") or None, "created_at": now(), **metadata}
        self._write(item, raw)
        self.store.db.execute("INSERT INTO task_attachments VALUES (?,?,?,?)", (item["id"], project_id, workspace_id, encode(item)))
        return item

    def list_draft(self, draft_id: str) -> list[dict]:
        return [self.get(row[0]) for row in self.store.db.execute("SELECT attachment_id FROM attachment_draft_refs WHERE draft_id=? ORDER BY rowid", (draft_id,))]

    def for_message(self, message_id: int) -> list[dict]:
        return [self.get(row[0]) for row in self.store.db.execute("SELECT attachment_id FROM message_attachments WHERE message_id=? ORDER BY ordinal", (message_id,))]

    def has_committed(self, session_id: int) -> bool:
        """历史已提交附件仍可读取，未发送草稿不占用模型工具预算。"""
        return self.store.db.execute(
            "SELECT 1 FROM message_attachments a JOIN messages m ON m.id=a.message_id WHERE m.session_id=? LIMIT 1",
            (session_id,),
        ).fetchone() is not None

    def visible(self, identifier: str, *, draft_id: str | None = None, session_id: int | None = None) -> dict:
        if draft_id is not None:
            found = self.store.db.execute("SELECT 1 FROM attachment_draft_refs WHERE attachment_id=? AND draft_id=?", (identifier, draft_id)).fetchone()
        elif session_id is not None:
            found = self.store.db.execute("SELECT 1 FROM message_attachments a JOIN messages m ON m.id=a.message_id WHERE a.attachment_id=? AND m.session_id=?", (identifier, session_id)).fetchone()
        else:
            found = None
        if not found:
            raise ValueError("附件未提交到当前会话，或不属于当前草稿")
        return self.get(identifier)

    def read(self, identifier: str, offset: int = 0, limit: int = 6000, *, draft_id=None, session_id=None, page: int = 1, view: str = "auto") -> dict:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 32000:
            raise ValueError("附件分页参数无效")
        item = self.visible(identifier, draft_id=draft_id, session_id=session_id)
        raw = read_blob(self.store.path.parent, item)
        if type(page) is not int or not 1 <= page <= item.get("page_count", 1) or view not in {"auto", "text", "image"}:
            raise ValueError("附件页码或读取方式无效")
        kind = item.get("kind", "text")
        text = media.text_page(raw, page) if kind == "pdf" else raw.decode("utf-8") if kind == "text" else ""
        visual = kind == "image" or (kind == "pdf" and (view == "image" or (view == "auto" and not text.strip())))
        if visual:
            text = ""
        return {**item, "content": text[offset:offset + limit], "offset": offset, "total_chars": len(text),
                "page": page, "next_page": page + 1 if page < item.get("page_count", 1) else None,
                "image_ref": {"attachment_id": identifier, "page": page} if visual else None,
                "next_offset": offset + limit if offset + limit < len(text) else None}

    def image(self, identifier: str, page: int = 1, *, draft_id=None, session_id=None) -> dict:
        item = self.visible(identifier, draft_id=draft_id, session_id=session_id)
        if item.get("kind") not in {"image", "pdf"}:
            raise ValueError("该附件不包含图片或 PDF 页面")
        return media.render(read_blob(self.store.path.parent, item), item, page)

    def bind(self, identifiers: list[str], draft_id: str | None, session: dict, message_id: int) -> list[dict]:
        if len(identifiers) > MAX_ATTACHMENTS or len(set(identifiers)) != len(identifiers):
            raise ValueError("附件重复或超过 8 个")
        draft = self.store.db.execute("SELECT project_id,workspace_id,session_id FROM attachment_drafts WHERE id=?", (draft_id,)).fetchone() if draft_id else None
        if identifiers and (not draft or draft[:2] != (session["project_id"], session["workspace_id"]) or draft[2] not in {None, session["id"]}):
            raise ValueError("附件草稿与当前会话不匹配")
        if identifiers:
            self.draft(draft_id, session["project_id"], session["workspace_id"], session["id"])
        items = []
        for ordinal, identifier in enumerate(identifiers):
            item = self.visible(identifier, draft_id=draft_id)
            self.check_scope(item, session["project_id"], session["workspace_id"])
            read_blob(self.store.path.parent, item)
            self.store.db.execute("INSERT INTO message_attachments VALUES (?,?,?)", (message_id, identifier, ordinal))
            items.append(item)
        for identifier in identifiers:
            self.store.db.execute("DELETE FROM attachment_draft_refs WHERE draft_id=? AND attachment_id=?", (draft_id, identifier))
        self.needs_cleanup = True
        return items

    def remove(self, identifier: str, draft_id: str):
        with self.store.transaction():
            self.store.db.execute("DELETE FROM attachment_draft_refs WHERE draft_id=? AND attachment_id=?", (draft_id, identifier))
            self.needs_cleanup = True

    def cleanup(self, *, scan_orphans=False):
        """只在最外层事务结束后回收；失败保留元数据供下次启动重试。"""
        if self.store.db.in_transaction:
            return
        if not self.needs_cleanup and not scan_orphans:
            return
        self.needs_cleanup = False
        rows = self.store.db.execute("SELECT id FROM task_attachments a WHERE NOT EXISTS(SELECT 1 FROM attachment_draft_refs d WHERE d.attachment_id=a.id) AND NOT EXISTS(SELECT 1 FROM message_attachments m WHERE m.attachment_id=a.id)").fetchall()
        for (identifier,) in rows:
            try:
                self._unlink(identifier)
            except OSError:
                self.needs_cleanup = True
                logging.getLogger(__name__).warning("附件副本清理待重试：%s", identifier)
                continue
            with self.store.db:
                self.store.db.execute("DELETE FROM task_attachments WHERE id=?", (identifier,))
        known = {row[0] for row in self.store.db.execute("SELECT id FROM task_attachments")}
        candidates = set(self.pending_blobs)
        if scan_orphans and self.directory.is_dir() and not files.linked(self.directory):
            candidates.update(p.stem for p in self.directory.iterdir() if re.fullmatch(r"[a-f0-9]{32}\.(txt|blob)", p.name))
        for identifier in candidates - known:
            try:
                self._unlink(identifier)
                self.pending_blobs.discard(identifier)
            except OSError:
                self.needs_cleanup = True
                logging.getLogger(__name__).warning("未引用附件清理待重试：%s", identifier)
        self.pending_blobs.difference_update(known)

    def _unlink(self, identifier: str):
        if not re.fullmatch(ID_PATTERN, identifier) or files.linked(self.directory) or self.directory.resolve() != self.directory:
            raise OSError("附件清理路径无效")
        for suffix in (".txt", ".blob"):
            path = self.directory / (identifier + suffix)
            if files.linked(path):
                raise OSError("附件清理拒绝链接")
            path.unlink(missing_ok=True)
