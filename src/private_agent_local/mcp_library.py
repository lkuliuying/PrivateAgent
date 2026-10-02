"""个人 MCP 服务与项目绑定；配置和迁移从不保存凭据正文。"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from . import files
from .model_errors import CloudError
from .public_http import public_url
from .store import encode, now

HEX = r"^[a-f0-9]{32}$"
RESERVED_HEADERS = frozenset({"authorization", "host", "cookie", "proxy-authorization", "proxy-connection",
                              "connection", "content-length", "transfer-encoding", "content-type", "accept",
                              "accept-encoding", "origin", "mcp-session-id", "mcp-protocol-version"})
RESERVED_ENV = frozenset({"PRIVATEAGENT_LOCAL_NONCE", "PA_MODEL_PROVIDER_SECRETS_JSON"})


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    transport: Literal["https", "stdio"]
    url: str = Field(default="", max_length=2048)
    command: str = Field(default="", max_length=4096)
    args: list[Annotated[str, StringConstraints(strip_whitespace=False)]] = Field(default_factory=list, max_length=32)
    oauth: bool = False
    auth_mode: Literal["none", "oauth", "bearer", "custom_headers"] = "none"
    oauth_persistence: Literal["persistent", "session"] = "persistent"
    header_names: list[str] = Field(default_factory=list, max_length=16)
    env_names: list[str] = Field(default_factory=list, max_length=32)
    trust_process: bool = False

    @model_validator(mode="after")
    def validate_transport(self):
        if self.oauth and self.auth_mode == "none":
            self.auth_mode = "oauth"
        if self.oauth and self.auth_mode != "oauth":
            raise ValueError("OAuth 与静态认证不能同时配置")
        self.oauth = self.auth_mode == "oauth"
        if self.transport == "https":
            public_url(self.url)
            if self.command or self.args or self.trust_process or self.env_names:
                raise ValueError("HTTPS 服务不能配置本机命令或环境变量")
            if bool(self.header_names) != (self.auth_mode == "custom_headers"):
                raise ValueError("仅自定义请求头认证需要填写请求头名称")
        else:
            executable = Path(self.command)
            if not self.trust_process or not executable.is_absolute() or not executable.is_file() or files.linked(executable):
                raise ValueError("stdio 需要确认进程信任并指定现有可执行文件的绝对路径")
            if self.auth_mode != "none" or self.url or self.header_names or any(len(value) > 2000 or "\0" in value for value in self.args):
                raise ValueError("stdio 参数无效；不能配置 HTTPS 认证或 URL")
            if executable.suffix.lower() in {".cmd", ".bat", ".ps1"}:
                raise ValueError("请直接选择 node、python 或服务可执行文件，不能使用 shell 包装脚本")
        lowered = [value.lower() for value in self.header_names]
        if len(set(lowered)) != len(lowered) or any(not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,80}", value)
                                                   or value.lower() in RESERVED_HEADERS for value in self.header_names):
            raise ValueError("请求头名称重复、无效或属于协议保留字段")
        upper = [value.upper() for value in self.env_names]
        if len(set(upper)) != len(upper) or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", value)
                                              or value.upper() in RESERVED_ENV or value.upper().startswith("PRIVATEAGENT_")
                                              or value.upper().startswith("PA_MCP_") for value in self.env_names):
            raise ValueError("环境变量名称重复、无效或属于执行器内部字段")
        return self


class PrepareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=HEX)
    service_id: str | None = Field(default=None, pattern=HEX)
    expected_version: str | None = Field(default=None, pattern=HEX)
    configuration: SourceInput
    replace_credentials: bool = False


class CommitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str | None = Field(default=None, max_length=300)


class BindInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_id: str = Field(pattern=HEX)


class VersionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: str = Field(pattern=HEX)


def required_fields(source):
    return (["bearer"] if source.get("auth_mode") == "bearer" else []) + ["header:" + name for name in source.get("header_names", [])] + ["env:" + name for name in source.get("env_names", [])]


def credential_values(source, raw):
    try:
        value = json.loads(raw) if isinstance(raw, str) else None
    except (ValueError, TypeError):
        value = None
    required = required_fields(source)
    if not isinstance(value, dict) or set(value) != set(required) or any(not isinstance(v, str) or not v or len(v) > 16384
                                                                      or any(c in v for c in "\r\n\0") for v in value.values()):
        raise CloudError(409, "所需凭据缺失或格式无效，请重新保存全部认证字段", code="mcp_credentials_required")
    if any(key.startswith("header:") or key == "bearer" for key in value):
        try:
            for key, item in value.items():
                if key.startswith("header:") or key == "bearer":
                    item.encode("ascii")
        except UnicodeEncodeError:
            raise ValueError("HTTP 认证值必须使用 ASCII 字符") from None
    return value


def create_schema(store):
    store.db.execute("CREATE TABLE IF NOT EXISTS mcp_services(id TEXT PRIMARY KEY, data TEXT NOT NULL)")
    store.db.execute("CREATE TABLE IF NOT EXISTS mcp_service_changes(id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL)")


def migrate_sources(store):
    """旧来源逐条迁移，保留项目选择；同 URL 不构成同一信任对象。"""
    create_schema(store)
    for project in store.list("project"):
        bindings = []
        changed = False
        for source in project.get("mcp_integrations", []):
            if source.get("service_id"):
                bindings.append(source)
                continue
            identifier = source["id"]
            if store.db.execute("SELECT 1 FROM mcp_services WHERE id=?", (identifier,)).fetchone():
                identifier = uuid.uuid5(uuid.NAMESPACE_OID, f"mcp:{project['id']}:{identifier}").hex
            config = {key: copy.deepcopy(source[key]) for key in SourceInput.model_fields if key in source}
            config.update(auth_mode="oauth" if source.get("oauth") else "none", oauth_persistence="session", header_names=[], env_names=[])
            service = {**config, "id": identifier, "version": uuid.uuid4().hex,
                       "credential_revision": uuid.uuid4().hex, "auth_revision": uuid.uuid4().hex, "created_at": now(), "updated_at": now()}
            store.db.execute("INSERT INTO mcp_services VALUES (?,?)", (identifier, encode(service)))
            bindings.append({key: copy.deepcopy(source.get(key)) for key in ("id", "version", "enabled", "tools", "catalog", "discovered_at")}
                            | {"service_id": identifier, "service_version": service["version"], "needs_validation": False})
            changed = True
        if changed:
            store.update("project", project["id"], mcp_integrations=bindings)


class McpLibrary:
    def __init__(self, owner):
        self.owner = owner
        self.store = owner.store
        self._locks = {}

    def lock(self, identifier):
        integrations = getattr(self.owner, "integrations", None)
        locks = integrations.locks if integrations is not None else self._locks
        return locks.setdefault(identifier, asyncio.Lock())

    @staticmethod
    def credential_keys(service):
        keys = []
        if required_fields(service):
            keys.append((service["id"], service["credential_revision"], "static"))
        if service.get("oauth") and service.get("oauth_persistence") != "session":
            keys.append((service["id"], service["auth_revision"], "oauth"))
        return keys

    def queue_credentials(self, service, *, static_only=False):
        # 与配置状态共用事务；只记录范围，不记录任何凭据值。
        for identifier, revision, slot in self.credential_keys(service):
            if static_only and slot != "static":
                continue
            key = f"cleanup.{identifier}.{revision}.{slot}"
            value = {"service_id": identifier, "revision": revision, "slot": slot}
            self.store.db.execute("INSERT OR IGNORE INTO mcp_service_changes VALUES (?,?,?)",
                                  (key, "credential_cleanup", encode(value)))

    def credential_references(self, identifier):
        references = set()
        row = self.store.db.execute("SELECT data FROM mcp_services WHERE id=?", (identifier,)).fetchone()
        if row:
            references.update(self.credential_keys(json.loads(row[0])))
        for (raw,) in self.store.db.execute("SELECT data FROM mcp_service_changes WHERE status='prepared' AND json_extract(data,'$.service_id')=?", (identifier,)):
            # OAuth 仅在活动配置建立连接，草稿不能延长已退出凭据的生命周期。
            references.update(key for key in self.credential_keys(json.loads(raw)["configuration"]) if key[2] == "static")
        return references

    def cleanup_pending(self):
        pending = []
        references = {}
        for identifier, raw in self.store.db.execute("SELECT id,data FROM mcp_service_changes WHERE status='credential_cleanup' ORDER BY id"):
            value = json.loads(raw)
            service_id = value["service_id"]
            if service_id not in references:
                references[service_id] = self.credential_references(service_id)
            if (service_id, value["revision"], value["slot"]) not in references[service_id]:
                pending.append({"id": identifier, **value})
        return pending

    async def _cleanup_service(self, identifier):
        from .mcp_credentials import McpCredentialError, get_broker
        broker = get_broker(self.owner)
        for item in self.cleanup_pending():
            if item["service_id"] != identifier:
                continue
            try:
                # HTTP 兼容进程不能证明系统凭据已被删除，必须保留恢复记录。
                if not broker.persistent:
                    if item["slot"] == "oauth":
                        await broker.delete(identifier, item["revision"], item["slot"])
                    raise McpCredentialError("persistent_credentials_unavailable")
                await broker.delete(identifier, item["revision"], item["slot"])
            except McpCredentialError:
                continue
            with self.store.transaction():
                self.store.db.execute("DELETE FROM mcp_service_changes WHERE id=? AND status='credential_cleanup'", (item["id"],))
        return any(item["service_id"] == identifier for item in self.cleanup_pending())

    async def cleanup(self):
        for identifier in sorted({item["service_id"] for item in self.cleanup_pending()}):
            async with self.lock(identifier):
                await self._cleanup_service(identifier)
        return {"credential_cleanup_pending": self.cleanup_pending()}

    def service(self, identifier):
        row = self.store.db.execute("SELECT data FROM mcp_services WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("个人 MCP 服务不存在")
        return json.loads(row[0])

    def uses(self, identifier):
        return [{"project_id": project["id"], "project_name": project.get("name", "项目"), "source_id": binding["id"]}
                for project in self.store.list("project") for binding in project.get("mcp_integrations", []) if binding.get("service_id") == identifier]

    def public(self, service):
        return {**service, "projects": self.uses(service["id"]), "required_fields": required_fields(service)}

    def services(self):
        return [self.public(json.loads(row[0])) for row in self.store.db.execute("SELECT data FROM mcp_services ORDER BY id")]

    def check_config(self, config):
        if self.owner.secret_filter.contains_secret(config):
            raise ValueError("配置包含疑似凭据，请使用独立认证字段；参数和 URL 不得携带秘密")

    def create(self, data):
        config = data.model_dump()
        self.check_config(config)
        if required_fields(config):
            raise ValueError("此服务需要系统凭据，请通过配置准备流程保存")
        if self.store.db.execute("SELECT count(*) FROM mcp_services").fetchone()[0] >= 128:
            raise ValueError("个人服务库最多保存 128 个 MCP 服务")
        service = {**config, "id": uuid.uuid4().hex, "version": uuid.uuid4().hex, "credential_revision": uuid.uuid4().hex,
                   "auth_revision": uuid.uuid4().hex, "created_at": now(), "updated_at": now()}
        with self.store.transaction():
            self.store.db.execute("INSERT INTO mcp_services VALUES (?,?)", (service["id"], encode(service)))
        return service

    def bindings(self, project_id):
        return copy.deepcopy(self.store.get("project", project_id).get("mcp_integrations", []))

    def source(self, project_id, identifier):
        binding = next((value for value in self.bindings(project_id) if value["id"] == identifier), None)
        if not binding:
            raise ValueError("MCP 项目绑定不存在")
        service = self.service(binding["service_id"])
        return {**service, **binding, "name": service["name"], "service_version": service["version"],
                "enabled": bool(binding["enabled"] and not binding.get("needs_validation") and binding["service_version"] == service["version"])}

    def sources(self, project_id):
        return [self.source(project_id, binding["id"]) for binding in self.bindings(project_id)]

    def save_binding(self, project_id, source):
        values = self.bindings(project_id)
        binding = {key: copy.deepcopy(source.get(key)) for key in ("id", "service_id", "version", "service_version", "enabled", "tools", "catalog", "discovered_at", "needs_validation")}
        index = next((i for i, value in enumerate(values) if value["id"] == binding["id"]), None)
        if index is None:
            if len(values) >= 32:
                raise ValueError("每个项目最多绑定 32 个 MCP 服务")
            values.append(binding)
        else:
            values[index] = binding
        self.store.update("project", project_id, mcp_integrations=values)

    def bind(self, project_id, identifier):
        if self.lock(identifier).locked():
            raise CloudError(409, "服务正在连接或修改，请稍后重试", code="mcp_service_busy")
        service = self.service(identifier)
        prior = next((value for value in self.bindings(project_id) if value["service_id"] == identifier), None)
        if prior:
            return self.source(project_id, prior["id"])
        binding = {"id": uuid.uuid4().hex, "service_id": identifier, "version": uuid.uuid4().hex,
                   "service_version": service["version"], "enabled": False, "tools": [], "catalog": None,
                   "discovered_at": None, "needs_validation": True}
        self.save_binding(project_id, binding)
        return self.source(project_id, binding["id"])

    def invalidate(self, identifier):
        for project in self.store.list("project"):
            values = project.get("mcp_integrations", [])
            changed = False
            for binding in values:
                if binding["service_id"] == identifier:
                    binding.update(enabled=False, needs_validation=True, version=uuid.uuid4().hex)
                    changed = True
            if changed:
                self.store.update("project", project["id"], mcp_integrations=values)

    def change(self, identifier):
        row = self.store.db.execute("SELECT status,data FROM mcp_service_changes WHERE id=?", (identifier,)).fetchone()
        if not row or row[0] == "credential_cleanup":
            raise KeyError("MCP 待保存配置不存在")
        return {**json.loads(row[1]), "status": row[0]}

    async def prepare(self, data):
        row = self.store.db.execute("SELECT data FROM mcp_service_changes WHERE id=?", (data.request_id,)).fetchone()
        identifier = json.loads(row[0])["service_id"] if row else data.service_id or uuid.uuid4().hex
        async with self.lock(identifier):
            return await self._prepare(data, identifier)

    async def _prepare(self, data, identifier):
        from .mcp_credentials import get_broker
        config = data.configuration.model_dump()
        self.check_config(config)
        fingerprint = hashlib.sha256(encode(data.model_dump()).encode()).hexdigest()
        if self.store.db.execute("SELECT 1 FROM mcp_service_changes WHERE id=?", (data.request_id,)).fetchone():
            change = self.change(data.request_id)
            if change["fingerprint"] != fingerprint or change["status"] == "discarded":
                raise CloudError(409, "本次保存标识已用于其他配置，请重新保存", code="mcp_change_conflict")
        else:
            previous = self.service(data.service_id) if data.service_id else None
            if previous and previous["version"] != data.expected_version or not previous and data.expected_version:
                raise CloudError(409, "个人服务已发生变化，请刷新后重试", code="mcp_config_changed")
            if not previous and self.store.db.execute("SELECT count(*) FROM mcp_services").fetchone()[0] >= 128:
                raise ValueError("个人服务库最多保存 128 个 MCP 服务")
            if self.store.db.execute("SELECT count(*) FROM mcp_service_changes WHERE status='prepared'").fetchone()[0] >= 32:
                raise ValueError("待保存 MCP 配置过多，请先完成或放弃已有配置")
            auth_keys = ("transport", "url", "command", "args", "auth_mode", "oauth_persistence", "header_names", "env_names")
            same_target = previous and all(previous.get(key) == config.get(key) for key in auth_keys)
            replace = bool(required_fields(config) and (data.replace_credentials or not same_target))
            service = {**config, "id": identifier, "version": uuid.uuid4().hex,
                       "credential_revision": previous["credential_revision"] if same_target and not replace else uuid.uuid4().hex,
                       "auth_revision": previous["auth_revision"] if same_target else uuid.uuid4().hex,
                       "created_at": previous["created_at"] if previous else now(), "updated_at": now()}
            change = {"id": data.request_id, "service_id": service["id"], "configuration": service,
                      "credential_revision": service["credential_revision"], "replace_credentials": replace,
                      "expected_version": data.expected_version, "fingerprint": fingerprint, "request": data.model_dump(), "created_at": now()}
            with self.store.transaction():
                self.store.db.execute("INSERT INTO mcp_service_changes VALUES (?,?,?)", (data.request_id, "prepared", encode(change)))
                self.queue_credentials(service, static_only=True)
            change["status"] = "prepared"
        binding = None
        if change["replace_credentials"] and change["status"] == "prepared":
            binding = await get_broker(self.owner).binding(change["service_id"], change["credential_revision"], "static")
        return {**change, "binding": binding, "required_fields": required_fields(change["configuration"])}

    async def commit(self, identifier, reference):
        async with self.lock(self.change(identifier)["service_id"]):
            return await self._commit(identifier, reference)

    async def _commit(self, identifier, reference):
        from .mcp_credentials import get_broker
        change = self.change(identifier)
        if change["status"] == "discarded":
            raise CloudError(409, "这次保存已放弃，请重新配置", code="mcp_change_discarded")
        service = change["configuration"]
        current = self.store.db.execute("SELECT data FROM mcp_services WHERE id=?", (service["id"],)).fetchone()
        if change["status"] == "completed":
            if not current or json.loads(current[0])["version"] != service["version"]:
                raise CloudError(409, "该配置已保存，但服务随后发生变化", code="mcp_config_changed")
            return {**self.public(service), "cleanup_pending": await self._cleanup_service(service["id"])}
        if (json.loads(current[0])["version"] if current else None) != change["expected_version"]:
            raise CloudError(409, "保存期间个人服务已发生变化，原配置保持不变", code="mcp_config_changed")
        if required_fields(service):
            broker = get_broker(self.owner)
            binding = await broker.binding(service["id"], service["credential_revision"], "static")
            expected = f"secret://os-keyring/mcp/{binding['identity']}/{service['id']}/{service['credential_revision']}/static"
            if change["replace_credentials"] and reference != expected:
                raise CloudError(409, "凭据引用与待保存配置不匹配", code="mcp_credentials_required")
            credential_values(service, await broker.get(service["id"], service["credential_revision"], "static"))
        # 凭据查询会让出执行权，提交前同时核对草稿状态和活动版本。
        with self.store.transaction():
            if self.change(identifier)["status"] != "prepared":
                raise CloudError(409, "这次保存已放弃或发生变化，请刷新", code="mcp_change_conflict")
            current = self.store.db.execute("SELECT data FROM mcp_services WHERE id=?", (service["id"],)).fetchone()
            if (json.loads(current[0])["version"] if current else None) != change["expected_version"]:
                raise CloudError(409, "保存期间个人服务已发生变化，原配置保持不变", code="mcp_config_changed")
            if current:
                self.queue_credentials(json.loads(current[0]))
            self.queue_credentials(service)
            self.store.db.execute("INSERT OR REPLACE INTO mcp_services VALUES (?,?)", (service["id"], encode(service)))
            self.invalidate(service["id"])
            self.store.db.execute("UPDATE mcp_service_changes SET status='completed' WHERE id=?", (identifier,))
        integrations = getattr(self.owner, "integrations", None)
        if integrations is not None:
            previous = json.loads(current[0]) if current else {}
            if previous.get("auth_revision") != service["auth_revision"]:
                integrations.tokens.pop(service["id"], None)
            if previous.get("credential_revision") != service["credential_revision"]:
                integrations.static_values.pop(service["id"], None)
        return {**self.public(service), "cleanup_pending": await self._cleanup_service(service["id"])}

    async def discard(self, identifier):
        async with self.lock(self.change(identifier)["service_id"]):
            change = self.change(identifier)
            if change["status"] == "completed":
                raise CloudError(409, "已生效配置不能作为草稿放弃", code="mcp_change_conflict")
            with self.store.transaction():
                self.queue_credentials(change["configuration"], static_only=True)
                self.store.db.execute("UPDATE mcp_service_changes SET status='discarded' WHERE id=?", (identifier,))
            return {"discarded": True, "cleanup_pending": await self._cleanup_service(change["service_id"])}

    async def delete(self, identifier, version):
        async with self.lock(identifier):
            return await self._delete(identifier, version)

    async def _delete(self, identifier, version):
        service = self.service(identifier)
        if service["version"] != version:
            raise CloudError(409, "个人服务已变化，请刷新", code="mcp_config_changed")
        uses = self.uses(identifier)
        if uses:
            raise CloudError(409, "请先解除这些项目的绑定：" + "、".join(item["project_name"] for item in uses), code="mcp_service_in_use")
        if self.store.db.execute("SELECT 1 FROM mcp_service_changes WHERE status='prepared' AND json_extract(data,'$.service_id')=?", (identifier,)).fetchone():
            raise CloudError(409, "请先完成或放弃此服务的待保存配置", code="mcp_change_pending")
        with self.store.transaction():
            self.queue_credentials(service)
            self.store.db.execute("DELETE FROM mcp_services WHERE id=?", (identifier,))
        integrations = getattr(self.owner, "integrations", None)
        if integrations is not None:
            integrations.tokens.pop(identifier, None)
            integrations.static_values.pop(identifier, None)
        return {"deleted": True, "cleanup_pending": await self._cleanup_service(identifier)}
