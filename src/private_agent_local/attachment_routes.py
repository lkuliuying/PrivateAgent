"""附件 API 只管理用户明确选择的快照，不隐式写入项目。"""
from pathlib import Path

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from . import files
from .model_errors import CloudError


class AttachmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    source_path: str = Field(min_length=1, max_length=4096)
    draft_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    project_id: int = Field(gt=0)
    workspace_id: int = Field(gt=0)
    session_id: int | None = Field(default=None, gt=0)


class AttachmentImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rel_path: str = Field(min_length=1, max_length=1024)
    draft_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    session_id: int | None = Field(default=None, gt=0)


def install_attachment_routes(app, local):
    @app.post("/task-attachments", status_code=201)
    async def stage(data: AttachmentInput, runtime=Depends(local)):
        runtime.root(data.project_id, data.workspace_id)
        try:
            return runtime.store.attachments.stage(Path(data.source_path), data.draft_id, data.project_id, data.workspace_id,
                                                   data.session_id, secret_filter=runtime.secret_filter)
        except (OSError, UnicodeError) as error:
            raise CloudError(422, "附件不可访问或内容损坏；未修改原始文件，请重新选择", code="attachment_unavailable") from error

    @app.get("/task-attachments")
    async def list_draft(draft_id: str = Query(pattern=r"^[a-f0-9]{32}$"), runtime=Depends(local)):
        items = runtime.store.attachments.list_draft(draft_id)
        for item in items:
            try:
                runtime.store.attachments.read(item["id"], 0, 1, draft_id=draft_id)
                item["error"] = None
            except (ValueError, OSError):
                item["error"] = "附件缺失或损坏，请移除后重新选择"
        return items

    @app.get("/task-attachments/{identifier}/content")
    async def preview(identifier: str, draft_id: str | None = None, session_id: int | None = None,
                      offset: int = Query(default=0, ge=0), limit: int = Query(default=6000, ge=1, le=32000),
                      page: int = Query(default=1, ge=1, le=50), runtime=Depends(local)):
        try:
            result = runtime.store.attachments.read(identifier, offset, limit, draft_id=draft_id, session_id=session_id, page=page)
            if result.get("kind") in {"image", "pdf"}:
                image = runtime.store.attachments.image(identifier, page, draft_id=draft_id, session_id=session_id)
                result["image_data_url"] = f"data:{image['mime_type']};base64,{image['data']}"
            return result
        except OSError as error:
            raise CloudError(422, "附件副本缺失或不可访问，请重新选择", code="attachment_unavailable") from error

    @app.delete("/task-attachments/{identifier}")
    async def remove(identifier: str, draft_id: str = Query(pattern=r"^[a-f0-9]{32}$"), runtime=Depends(local)):
        runtime.store.attachments.remove(identifier, draft_id)
        return {"removed": True, "cleanup_pending": runtime.store.attachments.needs_cleanup}

    @app.post("/task-attachments/{identifier}/import")
    async def import_file(identifier: str, data: AttachmentImport, runtime=Depends(local)):
        item = runtime.store.attachments.visible(identifier, draft_id=data.draft_id, session_id=data.session_id)
        root = runtime.root(item["project_id"], item["workspace_id"])
        from .attachments import read_blob
        try:
            raw = read_blob(runtime.store.path.parent, item)
            with runtime.workspaces.exclusive(root):
                if item.get("kind", "text") == "text":
                    content = raw.decode("utf-8")
                    preview = files.patch_preview(root, data.rel_path, content)
                    if not preview["creates_file"]:
                        raise ValueError("目标文件已经存在，请选择其他名称；未覆盖文件")
                    files.apply_patch(root, preview, content)
                else:
                    from .attachment_media import inspect
                    inspect(raw, Path(data.rel_path).name)
                    files.create_binary_file(root, data.rel_path, raw)
        except OSError as error:
            raise CloudError(422, "导入未完成，请检查目标路径和文件权限；不会覆盖已有文件", code="attachment_import_failed") from error
        return {"rel_path": data.rel_path, "name": Path(data.rel_path).name, "language": item["language"]}
