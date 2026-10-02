"""模型配置的准备、凭据就绪与提交日志；未完成操作不替换活动配置。"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends
from pydantic import Field, SecretStr

from .model_catalog import Input, ModelParameters, ProviderInput, validate_id
from .model_errors import CloudError
from .store import encode, now


class PrepareSave(Input):
    operation_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    provider_id: str = Field(min_length=1, max_length=64)
    configuration: ProviderInput
    parameters: ModelParameters | None = None
    credential_action: Literal["keep", "replace"] = "keep"


class PreparedSecret(Input):
    alias: str = Field(pattern=r"^[a-f0-9]{64}$")
    secret: SecretStr = Field(min_length=1, max_length=16_384)


class CleanupCredentials(Input):
    aliases: list[str] = Field(min_length=1, max_length=64)


def create_schema(db):
    db.execute("CREATE TABLE IF NOT EXISTS model_retired_credentials(alias TEXT PRIMARY KEY, cleared INTEGER NOT NULL DEFAULT 0)")
    db.execute("CREATE TABLE IF NOT EXISTS model_save_operations(id TEXT PRIMARY KEY, provider_id TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL)")


class ModelSaves:
    def __init__(self, models, token):
        self.models, self.token = models, token
        self.catalog = models.authorized(token)
        create_schema(self.catalog.db)

    def fingerprint(self, provider_id, parameters):
        current = {"provider": self.catalog.data["providers"].get(provider_id),
                   "profiles": {key: item for key, item in self.catalog.data["profiles"].items() if item["provider_id"] == provider_id}}
        if parameters is not None:
            current["parameters"] = self.catalog.data["parameters"]
        return hashlib.sha256(encode(current).encode()).hexdigest()

    def raw(self, identifier):
        row = self.catalog.db.execute("SELECT status,data,updated_at FROM model_save_operations WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError(identifier)
        return {**json.loads(row[1]), "id": identifier, "status": row[0], "updated_at": row[2]}

    def output(self, operation):
        reference = "secret://os-keyring/model-provider/" + operation["credential_alias"]
        config = operation["configuration"]
        required = operation["credential_action"] == "replace" or (config["enabled"] and config["protocol"] != "ollama"
                    and urlsplit(config["base_url"]).hostname not in {"localhost", "127.0.0.1", "::1"})
        return {**{key: operation[key] for key in ("id", "provider_id", "configuration", "parameters", "credential_action", "credential_alias", "status", "updated_at")},
                "credential_ready": not required or bool(self.models.secrets.get(reference)),
                "active_configuration_unchanged": operation["status"] != "completed"}

    def list(self):
        return [self.output(self.raw(row[0])) for row in self.catalog.db.execute("SELECT id FROM model_save_operations WHERE status IN ('prepared','credential_ready') ORDER BY updated_at DESC")]

    def prepare(self, value: PrepareSave):
        validate_id(value.provider_id)
        if value.configuration.credential_reference:
            raise ValueError("凭据引用由本机管理，不能从配置文件指定")
        if value.parameters is not None and value.configuration.protocol != "ollama":
            raise ValueError("仅本机 Ollama 配置包含本地模型参数")
        if value.configuration.protocol == "ollama" and value.credential_action == "replace":
            raise ValueError("本机 Ollama 不需要保存供应商密钥")
        existing = self.catalog.db.execute("SELECT id FROM model_save_operations WHERE id=?", (value.operation_id,)).fetchone()
        submitted = value.model_dump(exclude={"operation_id"})
        if existing:
            previous = self.raw(value.operation_id)
            if any(previous[key] != submitted[key] for key in submitted):
                raise CloudError(409, "同一保存标识对应的配置已改变，请重新保存", code="model_save_conflict")
            if previous["status"] == "discarded":
                raise CloudError(409, "这次保存已放弃，请重新保存配置", code="model_save_discarded")
            if previous["status"] == "completed":
                return self.commit(value.operation_id)
            return self.output(previous)
        if self.catalog.db.execute("SELECT count(*) FROM model_save_operations WHERE status IN ('prepared','credential_ready')").fetchone()[0] >= 64:
            raise ValueError("未完成的配置保存过多，请先处理或放弃已有记录")
        candidate = copy.copy(self.catalog)
        candidate.data = copy.deepcopy(self.catalog.data)
        provider = candidate.upsert(value.provider_id, value.configuration, persist=False)
        if value.credential_action == "replace":
            provider["credential_version"] = value.operation_id
        reference = candidate.reference(value.provider_id)
        previous_alias = self.catalog.reference(value.provider_id)["alias"] if value.provider_id in self.catalog.data["providers"] else None
        operation = {**submitted, "credential_alias": reference["alias"], "credential_version": provider.get("credential_version"),
                     "previous_alias": previous_alias, "base_fingerprint": self.fingerprint(value.provider_id, value.parameters)}
        with self.catalog.db:
            self.catalog.db.execute("INSERT INTO model_save_operations VALUES (?,?,?,?,?)", (value.operation_id, value.provider_id, "prepared", encode(operation), now()))
        return self.output(self.raw(value.operation_id))

    def credential(self, identifier, value: PreparedSecret):
        operation = self.raw(identifier)
        if operation["status"] not in {"prepared", "credential_ready"} or operation["configuration"]["protocol"] == "ollama":
            raise CloudError(409, "这次保存不接受待提交凭据", code="model_save_conflict")
        if value.alias != operation["credential_alias"]:
            raise ValueError("凭据与待保存的供应商配置不匹配")
        secret = value.secret.get_secret_value().strip()
        if not secret or any(char in secret for char in "\r\n\0"):
            raise ValueError("模型密钥为空或含无效字符")
        self.models.secrets["secret://os-keyring/model-provider/" + value.alias] = secret
        with self.catalog.db:
            self.catalog.db.execute("UPDATE model_save_operations SET status='credential_ready',updated_at=? WHERE id=?", (now(), identifier))
        return self.output(self.raw(identifier))

    def commit(self, identifier):
        operation = self.raw(identifier)
        if operation["status"] == "completed":
            active = self.catalog.data["providers"].get(operation["provider_id"], {})
            if active.get("last_save_operation") != identifier:
                raise CloudError(409, "这次保存已完成，但活动配置随后已改变，请重新核对", code="model_save_conflict")
            return self.output(operation)
        if operation["status"] == "discarded":
            raise CloudError(409, "这次保存已放弃", code="model_save_discarded")
        if operation["base_fingerprint"] != self.fingerprint(operation["provider_id"], operation["parameters"]):
            raise CloudError(409, "活动配置已发生变化，待保存内容仍保留，请核对后重新保存", code="model_save_conflict")
        if not self.output(operation)["credential_ready"]:
            raise CloudError(409, "配置草案已保存，密钥尚未就绪；原配置仍在使用，请先保存密钥或恢复已保存凭据", code="model_save_credential_required")
        previous, committed = copy.deepcopy(self.catalog.data), self.catalog._committed
        try:
            with self.catalog.db:
                provider = self.catalog.upsert(operation["provider_id"], ProviderInput.model_validate(operation["configuration"]), persist=False)
                if operation["credential_version"]:
                    provider["credential_version"] = operation["credential_version"]
                else:
                    provider.pop("credential_version", None)
                provider["last_save_operation"] = identifier
                if operation["parameters"] is not None:
                    self.catalog.data["parameters"] = operation["parameters"]
                self.catalog.save(commit=False)
                self.catalog.db.execute("UPDATE model_save_operations SET status='completed',updated_at=? WHERE id=?", (now(), identifier))
        except BaseException:
            # 数据库提交失败时连同内存配置一起恢复，不能提前宣称新配置已启用。
            self.catalog.data, self.catalog._committed = previous, committed
            raise
        return self.output(self.raw(identifier))

    def discard(self, identifier):
        operation = self.raw(identifier)
        if operation["status"] == "completed":
            raise CloudError(409, "已启用的配置不能作为草案放弃，请在模型设置中修改", code="model_save_conflict")
        with self.catalog.db:
            self.catalog.db.execute("UPDATE model_save_operations SET status='discarded',updated_at=? WHERE id=?", (now(), identifier))
        return {"discarded": True}

    def unused_aliases(self):
        used = {self.catalog.reference(identifier)["alias"] for identifier in self.catalog.data["providers"]}
        pending = {row[0] for row in self.catalog.db.execute("SELECT id FROM model_save_operations WHERE status IN ('prepared','credential_ready')")}
        for identifier in pending:
            operation = self.raw(identifier)
            used.add(operation["credential_alias"])
        known = set()
        for (raw,) in self.catalog.db.execute("SELECT data FROM model_save_operations"):
            operation = json.loads(raw)
            known.update(alias for alias in (operation["credential_alias"], operation["previous_alias"]) if alias)
        cleared = {row[0] for row in self.catalog.db.execute("SELECT alias FROM model_retired_credentials WHERE cleared=1")}
        return sorted(known - used - cleared)

    def reserve_cleanup(self, aliases):
        if len(set(aliases)) != len(aliases) or not set(aliases) <= set(self.unused_aliases()):
            raise CloudError(409, "凭据引用已变化，请重新预览清理范围", code="credential_cleanup_conflict")
        with self.catalog.db:
            self.catalog.db.executemany("INSERT OR IGNORE INTO model_retired_credentials(alias) VALUES (?)", ((alias,) for alias in aliases))
        return {"aliases": aliases}

    def confirm_cleanup(self, alias):
        if not self.catalog.db.execute("SELECT 1 FROM model_retired_credentials WHERE alias=?", (alias,)).fetchone():
            raise ValueError("凭据清理尚未预览和确认")
        with self.catalog.db:
            self.catalog.db.execute("UPDATE model_retired_credentials SET cleared=1 WHERE alias=?", (alias,))
        self.models.secrets.pop("secret://os-keyring/model-provider/" + alias, None)
        return {"cleared": True}


def install_model_save_routes(app, models, local):
    def service(runtime):
        if not hasattr(models, "authorized"):
            raise CloudError(409, "当前执行器不支持配置恢复，请升级客户端", code="model_save_unavailable")
        return ModelSaves(models, runtime.token)

    @app.get("/model-save-operations")
    async def pending(runtime=Depends(local)):
        return service(runtime).list()

    @app.post("/model-save-operations")
    async def prepare(value: PrepareSave, runtime=Depends(local)):
        return service(runtime).prepare(value)

    @app.put("/model-save-operations/{identifier}/credential")
    async def credential(identifier: str, value: PreparedSecret, runtime=Depends(local)):
        return service(runtime).credential(identifier, value)

    @app.post("/model-save-operations/{identifier}/commit")
    async def commit(identifier: str, runtime=Depends(local)):
        await models.cancel_probes()
        return service(runtime).commit(identifier)

    @app.delete("/model-save-operations/{identifier}")
    async def discard(identifier: str, runtime=Depends(local)):
        return service(runtime).discard(identifier)

    @app.get("/model-save-operations/credentials/unused")
    async def unused(runtime=Depends(local)):
        return {"aliases": service(runtime).unused_aliases()}

    @app.post("/model-save-operations/credentials/cleanup")
    async def reserve_cleanup(value: CleanupCredentials, runtime=Depends(local)):
        return service(runtime).reserve_cleanup(value.aliases)

    @app.post("/model-save-operations/credentials/{alias}/cleared")
    async def confirm_cleanup(alias: str, runtime=Depends(local)):
        return service(runtime).confirm_cleanup(alias)
