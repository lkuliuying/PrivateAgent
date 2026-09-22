"""按账号保存本机模型配置；数据库不保存模型密钥。"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from private_agent_core.llm.url_policy import validate_remote_base_url

Protocol = Literal["ollama", "openai", "claude"]
FORMATS = {"ollama": "ollama_chat", "openai": "chat_completions", "claude": "anthropic_messages"}


def valid_format(protocol: str, api_format: str) -> bool:
    return protocol in FORMATS and (api_format == FORMATS[protocol] or protocol == "openai" and api_format == "responses")


def validate_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
        raise ValueError("供应商标识格式无效")
    return value


def endpoint_url(value: str, protocol: Protocol) -> str:
    local = urlsplit(value).hostname in {"localhost", "127.0.0.1", "::1"}
    if protocol == "ollama" and not local:
        raise ValueError("Ollama 地址必须指向本机回环服务")
    return validate_remote_base_url(value, allow_http=local and protocol != "claude",
                                    allow_private_network=local and protocol != "claude")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)


class ProviderModel(Input):
    model_id: str = Field(min_length=1, max_length=200)
    context_tokens: int | None = Field(default=None, ge=1, le=10_000_000)
    max_output_tokens: int | None = Field(default=None, ge=1, le=10_000_000)
    metadata_source: Literal["provider_api", "local_model", "official_catalog", "user_override", "unknown"] = "unknown"


class ProviderInput(Input):
    name: str = Field(min_length=1, max_length=200)
    protocol: Protocol
    base_url: str = Field(min_length=1, max_length=500)
    api_format: Literal["ollama_chat", "chat_completions", "responses", "anthropic_messages"]
    credential_reference: str | None = Field(default=None, max_length=300)
    enabled: bool = True
    is_builtin: bool = False
    models: list[ProviderModel] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_provider(self):
        self.base_url = endpoint_url(self.base_url, self.protocol)
        if not valid_format(self.protocol, self.api_format):
            raise ValueError("供应商协议与接口格式不一致")
        if len({item.model_id for item in self.models}) != len(self.models):
            raise ValueError("供应商中存在重复模型")
        return self


class DiscoveryInput(Input):
    provider_id: str | None = Field(default=None, max_length=64)
    protocol: Protocol
    base_url: str = Field(min_length=1, max_length=500)
    credential_reference: str | None = Field(default=None, max_length=300)
    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=16_384)


class SecretInput(Input):
    secret: SecretStr = Field(min_length=1, max_length=16_384)


class ModelParameters(Input):
    llm_temperature: float = Field(default=0.7, ge=0, le=1, allow_inf_nan=False)
    llm_context_length: int = Field(default=8192, ge=512, le=10_000_000)
    kb_enabled_by_default: bool = False


class ProfileInput(Input):
    provider: Protocol
    display_name: str = Field(min_length=1, max_length=200)
    model_name: str | None = Field(default=None, max_length=200)
    is_local: bool = False
    native_tool_calls: bool = True
    supports_streaming: bool = True
    supports_structured_output: bool = False
    supports_vision: bool = False
    context_tokens: int | None = Field(default=None, ge=1, le=10_000_000)
    reasoning_efforts: list[str] | None = Field(default=None, max_length=16)
    usage_reporting: bool = True
    enabled: bool = True
    is_default: bool = False


def profile_id(provider_id: str, model_id: str) -> str:
    safe_model = re.sub(r"[^A-Za-z0-9._-]+", "-", model_id).strip("-.") or "model"
    digest = hashlib.sha256(model_id.encode()).hexdigest()[:10]
    return f"{f'{provider_id}--{safe_model}'[:116]}--{digest}"


class ModelCatalog:
    def __init__(self, path: Path, scope: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.scope = scope
        self.db = sqlite3.connect(path, timeout=5)
        try:
            self.db.execute("CREATE TABLE IF NOT EXISTS model_catalog (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
            row = self.db.execute("SELECT data FROM model_catalog WHERE id=1").fetchone()
            self.data = json.loads(row[0]) if row else {"version": 1, "providers": {}, "profiles": {}, "probes": {}, "parameters": {}}
            self._committed = json.dumps(self.data, ensure_ascii=False)
            if self.data.get("version") != 1:
                raise ValueError("本机模型配置版本不兼容，请升级客户端")
            for snapshot in self.data["probes"].values():
                if snapshot.get("status") == "running":
                    snapshot.update(status="failed", error_code="probe_interrupted")
            self.save()
        except BaseException:
            self.db.close()
            raise

    def save(self):
        try:
            encoded = json.dumps(self.data, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode()) > 4 * 1024 * 1024:
                raise ValueError("本机模型配置超过容量限制")
            with self.db:
                self.db.execute("INSERT INTO model_catalog VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (encoded,))
        except (sqlite3.Error, ValueError, TypeError):
            # 磁盘写入失败后回到已提交快照，内存不能假装配置已生效。
            self.data = json.loads(self._committed)
            raise
        self._committed = encoded

    def close(self):
        self.db.close()

    def provider(self, provider_id: str) -> dict:
        return self.data["providers"][validate_id(provider_id)]

    def reference(self, provider_id: str) -> dict:
        provider = self.provider(provider_id)
        # 地址也参与隔离，修改端点不会把旧供应商密钥交给新主机。
        alias = hashlib.sha256(f"{self.scope}\0{provider_id}\0{provider['protocol']}\0{provider['base_url']}".encode()).hexdigest()
        return {"alias": alias, "reference": f"secret://os-keyring/model-provider/{alias}"}

    def profiles(self, enabled_only=False) -> list[dict]:
        return [dict(item) for item in self.data["profiles"].values() if not enabled_only or item["enabled"]]

    def reconcile_default(self, preferred: str | None = None):
        enabled = [p for p in self.data["profiles"].values() if p["enabled"]]
        selected = next((p for p in enabled if p["id"] == preferred), None)
        selected = selected or next((p for p in enabled if p["is_default"]), None) or next(iter(enabled), None)
        for profile in self.data["profiles"].values():
            profile["is_default"] = bool(selected and profile["id"] == selected["id"])

    def upsert(self, provider_id: str, value: ProviderInput) -> dict:
        validate_id(provider_id)
        if provider_id not in self.data["providers"] and len(self.data["providers"]) >= 64:
            raise ValueError("供应商数量已达到上限")
        previous = self.data["providers"].get(provider_id)
        provider = {**value.model_dump(exclude={"credential_reference"}), "id": provider_id}
        profiles = self.data["profiles"]
        original = {key: dict(p) for key, p in profiles.items() if p["provider_id"] == provider_id}
        if len(profiles) - len(original) + len(value.models) > 2048:
            raise ValueError("模型数量已达到上限")
        timestamp = datetime.now(timezone.utc).isoformat()
        keep = set()
        for model in provider["models"]:
            identifier = profile_id(provider_id, model["model_id"])
            model["profile_id"] = identifier
            keep.add(identifier)
            old = original.get(identifier, {})
            profiles[identifier] = {
                "id": identifier, "provider": value.protocol, "provider_id": provider_id,
                "provider_name": value.name, "display_name": old.get("display_name", model["model_id"]),
                "model_name": model["model_id"], "is_local": urlsplit(value.base_url).hostname in {"localhost", "127.0.0.1", "::1"},
                "is_default": old.get("is_default", False), "enabled": value.enabled,
                "native_tool_calls": old.get("native_tool_calls", True), "supports_streaming": old.get("supports_streaming", True),
                "supports_structured_output": old.get("supports_structured_output", False), "supports_vision": old.get("supports_vision", False),
                "context_tokens": model["context_tokens"], "reasoning_efforts": old.get("reasoning_efforts", ["low", "medium", "high", "max"] if value.protocol != "ollama" else []),
                "usage_reporting": old.get("usage_reporting", value.protocol != "ollama"),
                "created_at": old.get("created_at", timestamp), "updated_at": timestamp,
            }
        for identifier in original:
            if identifier not in keep:
                profiles.pop(identifier)
        if previous != provider:
            for identifier in original:
                self.data["probes"].pop(identifier, None)
        self.data["providers"][provider_id] = provider
        self.reconcile_default()
        self.save()
        return provider

    def delete(self, provider_id: str):
        self.provider(provider_id)
        del self.data["providers"][provider_id]
        for identifier, profile in list(self.data["profiles"].items()):
            if profile["provider_id"] == provider_id:
                del self.data["profiles"][identifier]
                self.data["probes"].pop(identifier, None)
        self.reconcile_default()
        self.save()

    def update_profile(self, identifier: str, value: ProfileInput) -> dict:
        profile = self.data["profiles"][identifier]
        provider = self.provider(profile["provider_id"])
        if value.provider != provider["protocol"] or value.model_name != profile["model_name"] or value.is_local != profile["is_local"]:
            raise ValueError("请通过供应商设置修改模型名称、协议或地址")
        if value.enabled and not provider["enabled"]:
            raise ValueError("请先启用供应商")
        profile.update(value.model_dump())
        for model in provider["models"]:
            if model["profile_id"] == identifier:
                model["context_tokens"] = value.context_tokens
        self.data["probes"].pop(identifier, None)
        self.reconcile_default(identifier if value.is_default else None)
        self.save()
        return dict(profile)

    def set_default(self, identifier: str) -> dict:
        profile = self.data["profiles"][identifier]
        if not profile["enabled"]:
            raise ValueError("不能选择已禁用的模型")
        self.reconcile_default(identifier)
        self.save()
        return dict(profile)
