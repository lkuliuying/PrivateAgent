"""模型选择只引用本机已有配置，项目和会话不能覆盖地址、密钥或权限。"""
from typing import Literal

from fastapi import Depends, Query
from pydantic import Field

from .model_catalog import Input
from .model_errors import CloudError


class ModelPreference(Input):
    scope: Literal["global", "project", "session"]
    project_id: int | None = Field(default=None, gt=0)
    session_id: int | None = Field(default=None, gt=0)
    profile_id: str | None = Field(default=None, max_length=128)


class ModelRestoreConfirmationRequired(ValueError):
    """待确认的恢复来源不能被显式任务参数或默认模型绕过。"""

    code = "model_restore_confirmation_required"

    def __init__(self):
        super().__init__("恢复的模型选择待确认，请在当前项目或会话中选择模型；任务尚未创建")


def records(store, project_id, session_id):
    session = store.get("session", session_id) if session_id else None
    if session and session["project_id"] != project_id:
        raise ValueError("会话不属于当前项目")
    project = store.get("project", project_id) if project_id else None
    return project, session


def local_override(project, session):
    for scope, item in (("session", session), ("project", project)):
        if item and (item.get("model_restore_pending") is not None or item.get("model_profile_id")):
            return scope, item
    return "global", {}


def require_model_restore_confirmed(store, project_id, session_id):
    _, item = local_override(*records(store, project_id, session_id))
    if item.get("model_restore_pending") is not None:
        raise ModelRestoreConfirmationRequired()


def resolve(store, profiles, project_id=None, session_id=None):
    project, session = records(store, project_id, session_id)
    default = next((item["id"] for item in profiles if item.get("is_default") and item.get("enabled", True)), None)
    overrides = {"global": default, "project": (project or {}).get("model_profile_id"), "session": (session or {}).get("model_profile_id")}
    source, item = local_override(project, session)
    pending = item.get("model_restore_pending")
    requires_confirmation = pending is not None
    selected = None if requires_confirmation else overrides[source]
    available = not requires_confirmation and any(item["id"] == selected and item.get("enabled", True) for item in profiles)
    details = pending if isinstance(pending, dict) else {}
    return {"profile_id": selected, "source": source, "overrides": overrides, "available": available,
            "requires_confirmation": requires_confirmation,
            "confirmation_reason": details.get("reason", "恢复的模型来源待确认") if requires_confirmation else None,
            "restore_source": {key: details.get(key) for key in ("profile_id", "source_scope", "source_identity")} if requires_confirmation else None}


def install_model_preference_routes(app, models, local):
    @app.get("/model-preferences")
    async def get_preference(project_id: int | None = Query(default=None, gt=0), session_id: int | None = Query(default=None, gt=0), runtime=Depends(local)):
        return resolve(runtime.store, await models.profiles(runtime.token), project_id, session_id)

    @app.put("/model-preferences")
    async def set_preference(value: ModelPreference, runtime=Depends(local)):
        records(runtime.store, value.project_id, value.session_id)
        catalog = models.authorized(runtime.token)
        if value.profile_id and not any(item["id"] == value.profile_id for item in catalog.profiles(enabled_only=True)):
            raise CloudError(409, "所选模型已删除或禁用，请刷新模型配置", code="model_preference_unavailable")
        if value.scope == "global":
            if not value.profile_id:
                raise ValueError("全局默认模型不能为空")
            catalog.set_default(value.profile_id)
        else:
            identifier = value.project_id if value.scope == "project" else value.session_id
            if not identifier:
                raise ValueError("请先选择要设置的项目或会话")
            runtime.store.update(value.scope, identifier, model_profile_id=value.profile_id, model_restore_pending=None)
        runtime._profiles_at = 0
        return resolve(runtime.store, catalog.profiles(enabled_only=True), value.project_id, value.session_id)
