"""备份模型身份与待确认状态；恢复不通过同名标识猜测供应商。"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .model_catalog import Input, endpoint_url, profile_id, valid_format, validate_id


class ModelIdentity(Input):
    provider_id: str = Field(min_length=1, max_length=64)
    protocol: Literal["ollama", "openai", "claude"]
    api_format: Literal["ollama_chat", "chat_completions", "responses", "anthropic_messages"]
    base_url: str = Field(min_length=1, max_length=500)
    model_id: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_identity(self):
        validate_id(self.provider_id)
        self.base_url = endpoint_url(self.base_url, self.protocol)
        if not valid_format(self.protocol, self.api_format):
            raise ValueError("备份模型身份的协议与接口格式不一致")
        return self


class LegacySelectionBackup(Input):
    scope: Literal["project", "session"]
    id: int = Field(gt=0)
    profile_id: str = Field(min_length=1, max_length=128)


class SelectionBackup(Input):
    scope: Literal["project", "session"]
    id: int = Field(gt=0)
    profile_id: str | None = Field(max_length=128)
    source_scope: Literal["global", "project", "session"]
    source_identity: ModelIdentity | None
    requires_confirmation: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_identity_reference(self):
        if self.profile_id == "" or self.scope == "project" and self.source_scope == "session":
            raise ValueError("备份模型选择范围无效")
        if self.source_identity is not None:
            expected = profile_id(self.source_identity.provider_id, self.source_identity.model_id)
            if self.profile_id != expected:
                raise ValueError("备份模型标识与来源身份不一致")
        return self


def configuration_identity(configuration: dict, identifier: str | None) -> dict | None:
    if identifier is None:
        return None
    for item in configuration["providers"]:
        provider = item["configuration"]
        for model in provider["models"]:
            if profile_id(item["id"], model["model_id"]) == identifier:
                return ModelIdentity(provider_id=item["id"], protocol=provider["protocol"],
                                     api_format=provider["api_format"], base_url=provider["base_url"],
                                     model_id=model["model_id"]).model_dump()
    return None


def source_selection(scope: str, item: dict, configuration: dict) -> dict | None:
    pending = item.get("model_restore_pending")
    if pending is not None:
        # 待确认来源必须沿用原备份，不能被本机同 ID 的配置洗成已确认。
        return SelectionBackup(scope=scope, id=item["id"], profile_id=pending["profile_id"],
                               source_scope=pending["source_scope"], source_identity=pending["source_identity"],
                               requires_confirmation=True).model_dump()
    identifier = item.get("model_profile_id")
    if not identifier and scope == "session":
        return None
    source_scope = scope if identifier else "global"
    identifier = identifier or configuration.get("default_profile_id")
    return SelectionBackup(scope=scope, id=item["id"], profile_id=identifier, source_scope=source_scope,
                           source_identity=configuration_identity(configuration, identifier),
                           requires_confirmation=False).model_dump()


def export_selections(store, configuration: dict) -> list[dict]:
    selections = []
    for scope in ("project", "session"):
        for item in store.list(scope):
            selection = source_selection(scope, item, configuration)
            if selection is not None:
                selections.append(selection)
    return selections


def normalize_selections(data: dict, *, legacy: bool) -> list[dict]:
    selections, seen = [], set()
    records = data["history"]["records"]
    identifiers = {scope: {item["id"] for item in records[scope + "s"]} for scope in ("project", "session")}
    for raw in data["model_selections"]:
        if legacy:
            choice = LegacySelectionBackup.model_validate(raw).model_dump()
            choice.update(source_scope=choice["scope"], source_identity=configuration_identity(data["configuration"], choice["profile_id"]),
                          requires_confirmation=False)
        else:
            choice = SelectionBackup.model_validate(raw).model_dump()
        key = (choice["scope"], choice["id"])
        if choice["id"] not in identifiers[choice["scope"]] or key in seen:
            raise ValueError("模型选择范围无效或重复")
        selections.append(choice)
        seen.add(key)
    # v1 只保存显式偏好；缺少项目项仍须核对原全局默认，避免落到目标电脑的默认模型。
    for project in records["projects"]:
        if ("project", project["id"]) not in seen:
            selections.append(source_selection("project", {"id": project["id"]}, data["configuration"]))
    return selections


def catalog_identity(catalog, identifier: str | None) -> tuple[dict | None, bool]:
    profile = catalog.data["profiles"].get(identifier)
    if not profile:
        return None, False
    provider = catalog.data["providers"].get(profile["provider_id"])
    if not provider:
        return None, False
    model = next((item for item in provider["models"] if item.get("profile_id") == identifier), None)
    if model is None:
        return None, False
    identity = ModelIdentity(provider_id=provider["id"], protocol=provider["protocol"], api_format=provider["api_format"],
                             base_url=provider["base_url"], model_id=model["model_id"]).model_dump()
    return identity, provider["enabled"] is True and profile["enabled"] is True


def review_selection(selection: dict, catalog) -> dict:
    target_id = selection["profile_id"]
    if selection["source_scope"] == "global":
        target_id = next((item["id"] for item in catalog.profiles() if item.get("is_default") and item.get("enabled")), None)
    target_identity, enabled = catalog_identity(catalog, target_id)
    if selection["requires_confirmation"]:
        reason = "此前恢复的模型尚未确认，请重新选择本机模型"
    elif selection["source_identity"] is None:
        reason = "无法确认备份中的模型来源，请选择本机模型"
    elif target_identity is None:
        reason = "本机缺少对应模型，请配置并选择本机模型"
    elif target_identity != selection["source_identity"]:
        reason = "本机模型身份与备份不同，请核对供应商、地址和模型后重新选择"
    elif not enabled:
        reason = "对应本机模型已禁用，请启用并重新选择"
    else:
        reason = ""
    return {**selection, "requires_confirmation": bool(reason), "reason": reason, "target_identity": target_identity}


def restore_selection(store, scope: str, identifier: int, selection: dict) -> bool:
    pending = None
    selected_id = selection["profile_id"] if selection["source_scope"] != "global" else None
    if selection["requires_confirmation"]:
        pending = {key: selection[key] for key in ("profile_id", "source_scope", "source_identity", "reason")}
        selected_id = None
    store.update(scope, identifier, model_profile_id=selected_id, model_restore_pending=pending)
    return pending is not None
