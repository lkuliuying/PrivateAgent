"""正文和附件组合的持久草稿；版本检查保护迟到的保存和发送回执。"""
from __future__ import annotations

import json
import re
import uuid

from pydantic import BaseModel, ConfigDict, Field

from .model_errors import CloudError
from .store import encode, now

KEY = re.compile(r"^pa_coding_draft_v2_(none|[1-9][0-9]*)_(none|[1-9][0-9]*)_(new|[1-9][0-9]*)$")


class ProjectReference(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    relPath: str = Field(min_length=1, max_length=1024)
    name: str = Field(default="", max_length=255)
    language: str | None = Field(default=None, max_length=64)


class AttachmentReference(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    id: str = Field(pattern=r"^[a-f0-9]{32}$")


class DraftData(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    text: str = Field(default="", max_length=32000)
    chips: list[ProjectReference] = Field(default_factory=list, max_length=128)
    attachments: list[AttachmentReference] = Field(default_factory=list, max_length=8)
    draftId: str = Field(pattern=r"^[a-f0-9]{32}$")
    clientRequestId: str = Field(default="", max_length=100)
    requestSignature: str = Field(default="", max_length=40000)


class DraftWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    revision: int = Field(ge=0)
    mutation_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    data: DraftData


class DraftAcknowledgement(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    client_request_id: str = Field(min_length=1, max_length=100)
    message: str = Field(max_length=32000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=8)


class DraftTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    destination: str = Field(max_length=160)
    revision: int = Field(ge=1)
    draft_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    data: DraftData


def create_schema(db):
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS session_creation_request ON sessions(json_extract(data,'$.client_request_id')) WHERE json_extract(data,'$.client_request_id') IS NOT NULL")
    db.execute("CREATE TABLE IF NOT EXISTS composer_drafts(scope_key TEXT PRIMARY KEY, project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE, workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE, session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE, revision INTEGER NOT NULL, mutation_id TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL)")


class Drafts:
    def __init__(self, store):
        self.store = store

    def scope(self, key):
        match = KEY.fullmatch(key)
        if not match:
            raise ValueError("草稿范围无效")
        project, workspace, session = (None if value in {"none", "new"} else int(value) for value in match.groups())
        if project is not None:
            self.store.get("project", project)
        if workspace is not None and (project is None or self.store.get("workspace", workspace)["project_id"] != project):
            raise ValueError("草稿工作区与项目不匹配")
        if session is not None:
            item = self.store.get("session", session)
            if (item.get("project_id"), item.get("workspace_id")) != (project, workspace):
                raise ValueError("草稿会话与项目或工作区不匹配")
        return project, workspace, session

    def get(self, key):
        self.scope(key)
        row = self.store.db.execute("SELECT revision,mutation_id,data,updated_at FROM composer_drafts WHERE scope_key=?", (key,)).fetchone()
        if not row:
            return {"revision": 0, "mutation_id": None, "data": None, "updated_at": None}
        data = json.loads(row[2])
        # 元数据以附件目录为准；不把文件正文或图片数据写进草稿。
        items = []
        for item in data["attachments"]:
            try:
                items.append(self.store.attachments.get(item["id"]))
            except ValueError:
                items.append({**item, "name": "已移除附件", "size_bytes": 0, "sha256": "", "language": None,
                              "error": "附件已移除，请核对草稿"})
        data["attachments"] = items
        return {"revision": row[0], "mutation_id": row[1], "data": data, "updated_at": row[3]}

    def put(self, key, value: DraftWrite):
        binding = self.scope(key)
        data = value.data.model_dump()
        identifiers = [item["id"] for item in data["attachments"]]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("草稿附件重复")
        with self.store.transaction():
            current = self.get(key)
            if current["mutation_id"] == value.mutation_id:
                if DraftData.model_validate(current["data"]).model_dump() != data:
                    raise CloudError(409, "同一保存标识的内容发生变化，草稿未覆盖", code="draft_conflict")
                return current
            if current["revision"] != value.revision:
                raise CloudError(409, "草稿已在其他窗口更新，当前输入已保留；请核对已保存版本后再保存", code="draft_conflict")
            if binding[0] is not None and binding[1] is not None:
                self.store.attachments.draft(data["draftId"], *binding)
            for identifier in identifiers:
                try:
                    item = self.store.attachments.visible(identifier, draft_id=data["draftId"])
                except ValueError:
                    if binding[2] is None:
                        raise
                    item = self.store.attachments.visible(identifier, session_id=binding[2])
                self.store.attachments.check_scope(item, *binding[:2])
            self.store.db.execute("INSERT INTO composer_drafts VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(scope_key) DO UPDATE SET revision=excluded.revision,mutation_id=excluded.mutation_id,data=excluded.data,updated_at=excluded.updated_at",
                                  (key, *binding, current["revision"] + 1, value.mutation_id, encode(data), now()))
        return self.get(key)

    def acknowledge(self, key, value: DraftAcknowledgement):
        with self.store.transaction():
            current = self.get(key)
            data = current["data"]
            if data:
                message = "\n".join(filter(None, [data["text"].strip(), *("@" + item["relPath"] for item in data["chips"])])) or ("附件材料" if data["attachments"] else "")
                if (data["clientRequestId"] == value.client_request_id and message == value.message
                        and [item["id"] for item in data["attachments"]] == value.attachment_ids):
                    return self.put(key, DraftWrite(revision=current["revision"], mutation_id=uuid.uuid4().hex,
                                                   data=DraftData(draftId=uuid.uuid4().hex)))
        return current

    def transfer(self, key, value: DraftTransfer):
        origin, target = self.scope(key), self.scope(value.destination)
        if origin[:2] != target[:2] or origin[2] is not None or target[2] is None:
            raise ValueError("只能把同一工作区的首页草稿转入新会话")
        with self.store.transaction():
            source, destination = self.get(key), self.get(value.destination)
            if destination["data"] and destination["data"]["draftId"] == value.draft_id:
                return destination
            if not source["data"] or value.data.draftId != value.draft_id:
                raise CloudError(409, "首页草稿已变化，未转移或清除输入", code="draft_conflict")
            if destination["data"]:
                raise CloudError(409, "目标会话已有草稿，未覆盖", code="draft_conflict")
            submitted = value.data.model_dump()
            current = DraftData.model_validate(source["data"]).model_dump()
            changed = current != submitted
            if changed:
                # 首次创建会话期间的新输入继续留在首页，附件引用单独保留。
                previous_id = current["draftId"]
                current["draftId"] = uuid.uuid4().hex
                self.store.attachments.draft(current["draftId"], *origin)
                self.store.db.execute("INSERT INTO attachment_draft_refs SELECT ?,attachment_id FROM attachment_draft_refs WHERE draft_id=?",
                                      (current["draftId"], previous_id))
            result = self.put(value.destination, DraftWrite(revision=0, mutation_id=uuid.uuid4().hex, data=value.data))
            self.put(key, DraftWrite(revision=source["revision"], mutation_id=uuid.uuid4().hex,
                                    data=DraftData.model_validate(current) if changed else DraftData(draftId=uuid.uuid4().hex)))
            return result


def install_draft_routes(app, local):
    from fastapi import Depends

    @app.get("/composer-drafts/{key}")
    async def read(key: str, runtime=Depends(local)):
        return Drafts(runtime.store).get(key)

    @app.put("/composer-drafts/{key}")
    async def write(key: str, value: DraftWrite, runtime=Depends(local)):
        return Drafts(runtime.store).put(key, value)

    @app.post("/composer-drafts/{key}/acknowledge")
    async def acknowledge(key: str, value: DraftAcknowledgement, runtime=Depends(local)):
        return Drafts(runtime.store).acknowledge(key, value)

    @app.post("/composer-drafts/{key}/transfer")
    async def transfer(key: str, value: DraftTransfer, runtime=Depends(local)):
        return Drafts(runtime.store).transfer(key, value)
