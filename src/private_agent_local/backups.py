"""可核对的配置及应用数据备份；导入生成新记录，不继承执行授权。"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Literal

from fastapi import Depends
from fastapi.responses import Response
from pydantic import Field

from private_agent_core.history import (
    MAX_BYTES,
    encode_archive,
    validate_archive,
)

from . import files, migration
from .attachments import read_blob
from .backup_models import (
    export_selections,
    normalize_selections,
    restore_selection,
    review_selection,
)
from .drafts import DraftData, Drafts, DraftWrite
from .model_catalog import (
    Input,
    ModelParameters,
    ProfileInput,
    ProviderInput,
    profile_id,
    validate_id,
)
from .store import now

LEGACY_FORMAT = "privateagent.backup.v1"
FORMAT = "privateagent.backup.v2"


class LoadedBackup(dict):
    """保留文件元数据，不把内部字段混入已校验的备份正文。"""

    def __init__(self, payload, backup_format, size_bytes):
        super().__init__(payload)
        self.backup_format = backup_format
        self.size_bytes = size_bytes


class ProviderBackup(Input):
    id: str = Field(max_length=64)
    configuration: ProviderInput


class ProfileBackup(Input):
    id: str = Field(min_length=1, max_length=128)
    configuration: ProfileInput


class ConfigBackup(Input):
    providers: list[ProviderBackup] = Field(max_length=64)
    parameters: ModelParameters
    profiles: list[ProfileBackup] = Field(default_factory=list, max_length=2048)
    default_profile_id: str | None = Field(default=None, max_length=128)


class DraftBackup(Input):
    project_id: int | None = Field(default=None, gt=0)
    workspace_id: int | None = Field(default=None, gt=0)
    session_id: int | None = Field(default=None, gt=0)
    data: DraftData
    orphan: bool


class DraftAttachmentBackup(Input):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    project_id: int = Field(gt=0)
    workspace_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=255)
    kind: Literal["text", "image", "pdf"] = "text"
    size_bytes: int = Field(ge=0, le=10 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_encoding: Literal["base64"]
    content: str = Field(max_length=14 * 1024 * 1024)


class BackupExport(Input):
    kind: Literal["configuration", "application"]
    home_layout: Literal["standard", "compact"] = "standard"


class BackupPath(Input):
    path: str = Field(min_length=1, max_length=4096)


class BackupImport(BackupPath):
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    part: Literal["configuration", "data"]
    mappings: dict[str, str] = Field(default_factory=dict, max_length=5000)
    workspace_mappings: dict[str, str] = Field(default_factory=dict, max_length=5000)


def model_configuration(catalog):
    providers = []
    for identifier, item in catalog.data["providers"].items():
        value = {key: item[key] for key in ProviderInput.model_fields if key != "credential_reference" and key in item}
        value["models"] = [{key: val for key, val in model.items() if key != "profile_id"} for model in item["models"]]
        providers.append({"id": identifier, "configuration": value})
    profiles = [{"id": item["id"], "configuration": {key: item[key] for key in ProfileInput.model_fields if key in item}} for item in catalog.profiles()]
    return ConfigBackup(providers=providers, profiles=profiles, parameters=ModelParameters.model_validate(catalog.data["parameters"]),
                        default_profile_id=next((item["id"] for item in catalog.profiles() if item["is_default"]), None)).model_dump(exclude_none=True)


def export_backup(runtime, kind, home_layout):
    catalog = runtime.cloud.authorized(runtime.token)
    payload = {"kind": kind, "created_at": now(), "home_layout": home_layout, "configuration": model_configuration(catalog)}
    if kind == "application":
        if runtime.store.has_active_run():
            raise ValueError("请先完成或取消当前任务，再创建一致的应用数据备份")
        store = runtime.store
        history = migration.archive_sqlite(store.path, authority=runtime.authority, owner_id=runtime.owner_id)
        drafts = []
        known = set()
        for project, workspace, session, raw in store.db.execute("SELECT project_id,workspace_id,session_id,data FROM composer_drafts ORDER BY scope_key"):
            data = DraftData.model_validate_json(raw).model_dump()
            known.add(data["draftId"])
            drafts.append({"project_id": project, "workspace_id": workspace, "session_id": session, "data": data, "orphan": False})
        for identifier, project, workspace, session in store.db.execute("SELECT * FROM attachment_drafts ORDER BY id"):
            items = store.attachments.list_draft(identifier)
            if identifier not in known and items:
                drafts.append({"project_id": project, "workspace_id": workspace, "session_id": session,
                               "data": DraftData(draftId=identifier, attachments=items).model_dump(), "orphan": True})
        sent = {item["id"] for item in history["records"]["attachments"]}
        draft_ids = {item["id"] for draft in drafts for item in draft["data"]["attachments"]}
        attachments = []
        total_bytes = len(encode_archive(history)) + len(encode_archive({"drafts": drafts}))
        for identifier in sorted(draft_ids - sent):
            item = store.attachments.get(identifier)
            total_bytes += ((item["size_bytes"] + 2) // 3) * 4 + 2048
            if total_bytes > MAX_BYTES:
                raise ValueError("应用数据备份超过 64 MiB，请先导出历史或减少材料；未生成不完整备份")
            raw = read_blob(store.path.parent, item)
            attachments.append({key: item[key] for key in ("id", "name", "size_bytes", "sha256", "project_id", "workspace_id", "kind") if key in item} | {
                "content_encoding": "base64", "content": base64.b64encode(raw).decode("ascii")})
        selections = export_selections(store, payload["configuration"])
        payload.update(history=history, drafts=drafts, draft_attachments=attachments, model_selections=selections)
    # 仅导出白名单业务数据；凭据、凭据草稿、探测状态和模型保存日志均不进入备份。
    data = encode_archive(payload)
    return {"format": FORMAT, "sha256": hashlib.sha256(data).hexdigest(), "payload": payload}


def load_backup(path, runtime):
    source = Path(path)
    if (not source.is_absolute() or source.resolve() != source or any(files.linked(p) for p in (source, *source.parents))
            or files.secret_path(source) or source.suffix.lower() != ".json"):
        raise ValueError("请选择实际位置的普通备份 JSON 文件，不接受链接或凭据文件")
    content, _ = files.safe_file_bytes(source.parent, source.name, max_bytes=MAX_BYTES)
    package = json.loads(content)
    if not isinstance(package, dict) or set(package) != {"format", "sha256", "payload"} or package["format"] not in {LEGACY_FORMAT, FORMAT}:
        raise ValueError("不支持的备份格式；v2 备份需使用支持新版格式的客户端，旧历史包请使用历史导入入口")
    data = package["payload"]
    if not isinstance(data, dict) or hashlib.sha256(encode_archive(data)).hexdigest() != package["sha256"]:
        raise ValueError("备份摘要校验失败，文件可能损坏或被旧客户端改写；未导入数据。请保留原包；原数据仍在时，请用新版客户端重新导出")
    expected = {"kind", "created_at", "home_layout", "configuration"}
    if data.get("kind") == "application":
        expected |= {"history", "drafts", "draft_attachments", "model_selections"}
    elif data.get("kind") != "configuration":
        raise ValueError("备份种类无效")
    if set(data) != expected or data.get("home_layout") not in {"standard", "compact"}:
        raise ValueError("备份包含未知配置字段")
    if not isinstance(data["created_at"], str) or not 1 <= len(data["created_at"]) <= 100:
        raise ValueError("备份创建时间无效")
    config = ConfigBackup.model_validate(data["configuration"])
    identifiers = set()
    for provider in config.providers:
        validate_id(provider.id)
        if provider.id in identifiers or provider.configuration.credential_reference:
            raise ValueError("配置含重复供应商或不可迁移的凭据引用")
        identifiers.add(provider.id)
    expected_profiles = {profile_id(provider.id, model.model_id) for provider in config.providers for model in provider.configuration.models}
    seen_profiles = set()
    for profile in config.profiles:
        if profile.id not in expected_profiles or profile.id in seen_profiles:
            raise ValueError("模型能力配置包含未知或重复的模型引用")
        seen_profiles.add(profile.id)
    if data["kind"] == "application":
        validate_data(data, runtime, backup_format=package["format"])
    return LoadedBackup(data, package["format"], len(content)), hashlib.sha256(content).hexdigest()


def validate_data(data, runtime, *, backup_format=FORMAT):
    history = validate_archive(data["history"], authority=runtime.authority, owner_id=runtime.owner_id)["records"]
    projects = {item["id"]: item for item in history["projects"]}
    workspaces = {item["id"]: item for item in history["workspaces"]}
    sessions = {item["id"]: item for item in history["sessions"]}
    if any(not isinstance(data[key], list) or len(data[key]) > 50000 for key in ("drafts", "draft_attachments", "model_selections")):
        raise ValueError("备份草稿或附件数量超限")
    data["drafts"] = [DraftBackup.model_validate(item).model_dump() for item in data["drafts"]]
    data["draft_attachments"] = [DraftAttachmentBackup.model_validate(item).model_dump() for item in data["draft_attachments"]]
    data["model_selections"] = normalize_selections(data, legacy=backup_format == LEGACY_FORMAT)
    attachments = {item["id"]: item for item in history["attachments"]}
    for item in data["draft_attachments"]:
        if not isinstance(item, dict) or set(item) - {"id", "name", "size_bytes", "sha256", "project_id", "workspace_id", "kind", "content_encoding", "content"}:
            raise ValueError("草稿附件格式无效")
        if item.get("content_encoding") != "base64":
            raise ValueError("草稿附件编码无效")
        raw = base64.b64decode(item["content"], validate=True)
        if len(raw) != item["size_bytes"] or len(raw) > 10 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("草稿附件大小或摘要校验失败")
        if ("/" in item["name"] or "\\" in item["name"] or "\0" in item["name"] or files.secret_path(Path(item["name"]))):
            raise ValueError("草稿附件名称无效")
        if item["kind"] == "text" and (len(raw) > files.MAX_FILE_BYTES or "\0" in raw.decode("utf-8")):
            raise ValueError("草稿文本附件超过 1 MiB 或不是有效文本")
        if item["id"] in attachments:
            raise ValueError("备份附件标识重复")
        attachments[item["id"]] = item
    draft_ids, referenced, scopes = set(), set(), set()
    for item in data["drafts"]:
        if not isinstance(item, dict) or set(item) != {"project_id", "workspace_id", "session_id", "data", "orphan"} or type(item["orphan"]) is not bool:
            raise ValueError("草稿格式无效")
        draft = DraftData.model_validate(item["data"])
        project, workspace, session = item["project_id"], item["workspace_id"], item["session_id"]
        if (project is not None and project not in projects or workspace is not None and (workspace not in workspaces or workspaces[workspace]["project_id"] != project)
                or session is not None and (session not in sessions or (sessions[session]["project_id"], sessions[session]["workspace_id"]) != (project, workspace))):
            raise ValueError("草稿范围与备份项目、会话不匹配")
        scope = (project, workspace, session)
        if draft.draftId in draft_ids or (not item["orphan"] and scope in scopes):
            raise ValueError("备份包含重复草稿")
        draft_ids.add(draft.draftId)
        if not item["orphan"]:
            scopes.add(scope)
        ids = [part.id for part in draft.attachments]
        if len(set(ids)) != len(ids):
            raise ValueError("草稿包含重复附件")
        for identifier in ids:
            material = attachments.get(identifier)
            if not material or (material["project_id"], material["workspace_id"]) != (project, workspace):
                raise ValueError("草稿附件缺失或属于其他工作区")
        referenced.update(ids)
    if {item["id"] for item in data["draft_attachments"]} - referenced:
        raise ValueError("备份包含没有草稿引用的附件")


def preview_backup(path, runtime):
    data, digest = load_backup(path, runtime)
    catalog = runtime.cloud.authorized(runtime.token)
    providers = [{"id": item["id"], "name": item["configuration"]["name"], "base_url": item["configuration"]["base_url"],
                  "conflict": item["id"] in catalog.data["providers"]} for item in data["configuration"]["providers"]]
    records = data.get("history", {}).get("records", {})
    coverage = ["供应商与模型普通配置", "模型参数", "首页布局"]
    if data["kind"] == "application":
        coverage += ["当前项目、工作区、会话与消息", "运行历史子集", "持久草稿与项目引用", "已发送及未发送附件", "模型偏好与待确认来源"]
    return {"sha256": digest, "format": data.backup_format, "created_at": data["created_at"], "size_bytes": data.size_bytes,
            "coverage": coverage, "kind": data["kind"], "providers": providers, "home_layout": data["home_layout"],
            "model_selections": [review_selection(item, catalog) for item in data.get("model_selections", [])],
            "projects": records.get("projects", []), "workspaces": records.get("workspaces", []),
            "counts": {**{key: len(items) for key, items in records.items()}, "drafts": len(data.get("drafts", [])), "draft_attachments": len(data.get("draft_attachments", []))},
            "warnings": ["供应商 ID 冲突时保留现有配置；新增供应商默认禁用，需要重新输入密钥并启用。", "数据导入创建新的项目与会话，不覆盖已有记录。每个工作区必须重新选择本机目录。", "草稿恢复为待发送内容，旧请求标识、授权和任务操作不会恢复。", "模型身份缺失、冲突或禁用时先恢复数据，核对并选择本机模型后才能发送。", "工作树恢复为已映射目录，不自动创建 Git 工作树。项目文件、API Key、加密设置草稿、长期记忆、Skills、MCP 和界面资源不在此备份中。", "应用数据包包含当前工作台记录及运行历史子集，不包含此前导入保留的历史归档。历史导入记录可单独导出历史归档子集，该子集不含配置、草稿、未发送附件或模型选择。"]}


def import_configuration(data, catalog):
    config = ConfigBackup.model_validate(data["configuration"])
    incoming = [item for item in config.providers if item.id not in catalog.data["providers"]]
    skipped = [item.id for item in config.providers if item.id in catalog.data["providers"]]
    before, committed = copy.deepcopy(catalog.data), catalog._committed
    path = Path(catalog.db.execute("PRAGMA database_list").fetchone()[2])
    target = sqlite3.connect(path.with_name(path.stem + ".pre-import-" + uuid.uuid4().hex + ".sqlite3"))
    try:
        catalog.db.backup(target)
        if target.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("配置导入备份校验失败")
    finally:
        target.close()
    try:
        for item in incoming:
            value = item.configuration.model_copy(update={"enabled": False, "is_builtin": False})
            catalog.upsert(item.id, value, persist=False)
        imported_providers = {item.id for item in incoming}
        for item in config.profiles:
            profile = catalog.data["profiles"].get(item.id)
            if profile and profile["provider_id"] in imported_providers:
                catalog.update_profile(item.id, item.configuration.model_copy(update={"enabled": False, "is_default": False}), persist=False)
        if not before["providers"]:
            catalog.data["parameters"] = config.parameters.model_dump()
        catalog.save()
    except BaseException:
        catalog.data, catalog._committed = before, committed
        raise
    return {"imported": [item.id for item in incoming], "skipped": skipped, "home_layout": data["home_layout"], "requires_model_setup": bool(incoming)}


def import_data(data, digest, mappings, workspace_mappings, runtime):
    if data["kind"] != "application":
        raise ValueError("此文件仅包含普通配置")
    prior = runtime.store.db.execute("SELECT data FROM history_imports WHERE sha256=?", (digest,)).fetchone()
    if prior:
        return {**json.loads(prior[0]), "already_imported": True}
    records = data["history"]["records"]
    if set(mappings) != {str(item["id"]) for item in records["projects"]} or set(workspace_mappings) != {str(item["id"]) for item in records["workspaces"]}:
        raise ValueError("请为每个项目和工作区选择本机目录，避免遗漏材料")
    roots = {key: str(files.authorize_root(path)) for key, path in workspace_mappings.items()}
    store = runtime.store
    catalog = runtime.cloud.authorized(runtime.token)
    selections = [review_selection(item, catalog) for item in data["model_selections"]]
    existing_home = Drafts(store).get("pa_coding_draft_v2_none_none_new")["data"]
    if existing_home and (existing_home["text"] or existing_home["chips"] or existing_home["attachments"]) and any(item["project_id"] is None for item in data["drafts"]):
        raise ValueError("当前首页有未绑定项目的草稿，请先为其选择项目并保存，再导入首页草稿")

    def augment(maps, attachment_map):
        orphan_sessions = 0
        for item in data["draft_attachments"]:
            installed = store.attachments.install_bytes(item["name"], base64.b64decode(item["content"], validate=True), maps["projects"][item["project_id"]], maps["workspaces"][item["workspace_id"]], secret_filter=runtime.secret_filter)
            attachment_map[item["id"]] = installed["id"]
        for item in data["drafts"]:
            project, workspace, session = (maps[key].get(item[field]) for key, field in (("projects", "project_id"), ("workspaces", "workspace_id"), ("sessions", "session_id")))
            if item["session_id"] is not None and session is None:
                raise ValueError("草稿所属会话类型不能恢复，请核对备份")
            if item["orphan"]:
                session = store.create("session", {"project_id": project, "workspace_id": workspace, "title": "恢复的附件草稿", "kind": "coding", "last_run_id": None})["id"]
                orphan_sessions += 1
            draft = DraftData.model_validate(item["data"])
            draft.draftId, draft.clientRequestId, draft.requestSignature = uuid.uuid4().hex, "", ""
            for ref in draft.attachments:
                ref.id = attachment_map[ref.id]
            if project and workspace:
                store.attachments.draft(draft.draftId, project, workspace, session)
                store.db.executemany("INSERT INTO attachment_draft_refs VALUES (?,?)", ((draft.draftId, ref.id) for ref in draft.attachments))
            key = f"pa_coding_draft_v2_{project or 'none'}_{workspace or 'none'}_{session or 'new'}"
            current = Drafts(store).get(key)
            Drafts(store).put(key, DraftWrite(revision=current["revision"], mutation_id=uuid.uuid4().hex, data=draft))
        restored_models = pending_models = 0
        for item in selections:
            identifier = maps[item["scope"] + "s"].get(item["id"])
            if identifier:
                pending_models += restore_selection(store, item["scope"], identifier, item)
                restored_models += 1
        return {"sessions": len(maps["sessions"]) + orphan_sessions, "drafts": len(data["drafts"]),
                "draft_attachments": len(data["draft_attachments"]), "model_selections": restored_models,
                "models_pending_confirmation": pending_models}
    imported = migration.apply_archive(store, data["history"], digest, mappings, authority=runtime.authority, owner_id=runtime.owner_id,
                                       workspace_roots=roots, augment=augment, source_kind="application", backup_format=getattr(data, "backup_format", FORMAT))
    return {**imported, "already_imported": False}


def install_backup_routes(app, local):
    @app.post("/local-backups/export")
    async def export(value: BackupExport, runtime=Depends(local)):
        return Response(encode_archive(export_backup(runtime, value.kind, value.home_layout)), media_type="application/json")

    @app.post("/local-backups/preview")
    async def preview(value: BackupPath, runtime=Depends(local)):
        return preview_backup(value.path, runtime)

    @app.post("/local-backups/import")
    async def restore(value: BackupImport, runtime=Depends(local)):
        data, digest = load_backup(value.path, runtime)
        if digest != value.sha256:
            raise ValueError("备份在预览后发生变化，请重新预览；未导入数据")
        if runtime.store.has_active_run():
            raise ValueError("请先完成或取消当前任务，再恢复备份")
        if value.part == "configuration":
            return import_configuration(data, runtime.cloud.authorized(runtime.token))
        return import_data(data, digest, value.mappings, value.workspace_mappings, runtime)
