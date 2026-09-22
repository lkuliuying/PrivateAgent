"""独立评测 Agent 的最小产品配置交接；不返回或导出系统凭据。"""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import stat
from contextlib import closing
from pathlib import Path
from typing import Literal

from pydantic import Field

from .model_catalog import (
    Input,
    ModelParameters,
    ProfileInput,
    ProviderInput,
    validate_id,
)
from .model_credentials import read_model_credential
from .model_errors import CloudError


class EvaluationBinding(Input):
    model_settings_directory: str = Field(min_length=1, max_length=4096)
    credential_namespace: Literal["desktop", "candidate"]
    profile_id: str = Field(min_length=1, max_length=128)
    expected: dict
    parameters: ModelParameters


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def selected_configuration(root: str, scope: str, identifier: str):
    directory = Path(root)
    if not directory.is_absolute() or str(directory).startswith(("\\\\", "//")):
        raise ValueError("交接目录必须为本机绝对路径")
    path = directory / scope / "model-settings.sqlite3"
    for part in [*reversed(path.parents), path]:
        status = part.lstat()
        if stat.S_ISLNK(status.st_mode) or getattr(status, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("模型交接目录不能包含链接或重解析点")
    if path.stat().st_nlink != 1 or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("模型配置文件不是有界普通文件")
    # 只读连接不会运行 ModelCatalog 的初始化、迁移或恢复写入。
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        db.execute("PRAGMA query_only=ON")
        row = db.execute("SELECT data FROM model_catalog WHERE id=1").fetchone()
    if not row or len(row[0].encode()) > 4 * 1024 * 1024:
        raise ValueError("模型配置缺失或超过容量")
    data = json.loads(row[0])
    if type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("不支持的本机模型目录版本")
    try:
        profile = data["profiles"][identifier]
        provider = data["providers"][profile["provider_id"]]
        validate_id(provider["id"])
        if (set(provider) != {*ProviderInput.model_fields, "id"} - {"credential_reference"}
                or set(profile) != {*ProfileInput.model_fields, "id", "provider_id", "provider_name", "created_at", "updated_at"}):
            raise ValueError
        models = [m for m in provider["models"] if m["profile_id"] == identifier]
        value = ProviderInput.model_validate({k: v for k, v in provider.items() if k in ProviderInput.model_fields and k != "models"} | {
            "models": [{k: v for k, v in m.items() if k != "profile_id"} for m in models]})
        ProfileInput.model_validate({k: v for k, v in profile.items() if k in ProfileInput.model_fields})
        parameters = ModelParameters.model_validate(data["parameters"]).model_dump()
        if (len(models) != 1 or profile["id"] != identifier or not profile["enabled"] or not provider["enabled"]
                or models[0]["model_id"] != profile["model_name"] or profile["provider"] != provider["protocol"]
                or value.base_url != provider["base_url"]):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("选定模型配置缺失、禁用或不一致") from None
    return {"version": 1, "providers": {provider["id"]: {**provider, "models": models}},
            "profiles": {identifier: profile}, "parameters": parameters, "probes": {}}


async def bind_evaluation(service, token: str, data: EvaluationBinding):
    catalog = service.authorized(token)
    if getattr(service, "evaluation_binding", None):
        raise CloudError(409, "评测配置已冻结；请新建独立 Agent", code="evaluation_already_bound")
    snapshot = selected_configuration(data.model_settings_directory, catalog.scope, data.profile_id)
    previous = catalog.data
    catalog.data = copy.deepcopy(snapshot)
    try:
        selected, provider, _ = service.selection(token, data.profile_id)
        actual = {"provider": {"id": provider["id"], "protocol": provider["protocol"], "endpoint": provider["base_url"]},
                  "model": selected["model_name"], "context_tokens": selected["context_tokens"]}
        if actual != data.expected or snapshot["parameters"] != data.parameters.model_dump():
            raise CloudError(409, "客户端模型与评测冻结配置不一致", code="evaluation_configuration_mismatch")
        reference = catalog.reference(provider["id"])
        # 测试只能沿已有启动注入通道交付合成值；产品只查询这个账号、协议和端点的单个引用。
        secret = service.secrets.get(reference["reference"])
        if secret is None and provider["protocol"] != "ollama":
            secret = read_model_credential(reference["alias"], data.credential_namespace)
        if not secret and not selected["is_local"]:
            raise CloudError(409, "请先在客户端为选定测试供应商保存密钥", code="model_missing_api_key")
        if secret:
            service.set_secret(token, provider["id"], secret)
        catalog.save()
        service.evaluation_binding = {"source": data.model_settings_directory, "profile_id": data.profile_id,
                                      "sha256": fingerprint(snapshot)}
    except BaseException:
        catalog.data = previous
        raise
    return await service.describe(token, data.profile_id)


def verify_evaluation(service, token, profile):
    binding = getattr(service, "evaluation_binding", None)
    if not binding:
        return
    catalog = service.authorized(token)
    try:
        source = selected_configuration(binding["source"], catalog.scope, binding["profile_id"])
        if profile != binding["profile_id"] or fingerprint(source) != binding["sha256"] or fingerprint(catalog.data) != binding["sha256"]:
            raise ValueError
    except (OSError, sqlite3.Error, ValueError):
        raise CloudError(409, "评测期间模型配置已变化或不可读取，停止后续请求", code="evaluation_configuration_changed") from None
