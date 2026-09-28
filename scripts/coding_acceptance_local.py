"""个人学习联调的本机模型配置与显式内存凭据；不启动账号服务。"""
from __future__ import annotations

import copy
import getpass
import hashlib
import sys
import warnings
from pathlib import Path

from coding_acceptance_models import ProductSession, model_limits, provider_config
from coding_acceptance_schema import fields, fingerprint

from private_agent_local.identity import LOCAL_AUTHORITY, LOCAL_OWNER_ID
from private_agent_local.model_catalog import (
    FORMATS,
    ModelCatalog,
    ModelParameters,
    ProviderInput,
    profile_id,
)

ACCOUNT_MODE = "isolated_local_test"


def local_config(data):
    fields(data, {"schema_version", "connection_mode", "account_mode", "provider", "model", "model_version",
                  "context_tokens", "supports_streaming", "parameters", "budget", "tasks"})
    if (type(data["schema_version"]) is not int or data["schema_version"] != 3
            or data["connection_mode"] != "direct_provider" or data["account_mode"] != ACCOUNT_MODE):
        raise ValueError("本机联调须显式使用 schema 3、direct_provider 和 isolated_local_test")
    provider_config(data["provider"])
    if data["provider"]["protocol"] not in {"openai", "claude"}:
        raise ValueError("本入口用于云 API，仅支持 OpenAI Chat Completions 或 Claude Messages 协议")
    if not isinstance(data["model"], str):
        raise ValueError("模型标识无效")
    identifier = profile_id(data["provider"]["id"], data["model"])
    parameters = data["parameters"]
    fields(parameters, {"reasoning_effort", "max_output_tokens", "auto_compact", *ModelParameters.model_fields})
    model_limits({**data, "profile_id": identifier,
                  "parameters": {k: parameters[k] for k in ("reasoning_effort", "max_output_tokens", "auto_compact")}},
                 identity_limits=(128, 200), max_context_tokens=10_000_000)
    ModelParameters.model_validate({k: parameters[k] for k in ModelParameters.model_fields}, strict=True)
    if parameters["llm_context_length"] > data["context_tokens"]:
        raise ValueError("使用的上下文长度不能超过声明的模型容量")
    if type(data["supports_streaming"]) is not bool:
        raise ValueError("须明确声明流式响应支持情况")
    if (not isinstance(data["tasks"], list) or not 1 <= len(data["tasks"]) <= 3
            or any(not isinstance(item, str) for item in data["tasks"])
            or len(set(data["tasks"])) != len(data["tasks"])):
        raise ValueError("本机联调须在配置中固定 1～3 个不重复的公开任务")
    if data["budget"]["cost_usd"] is not None or data["budget"]["total_cost_usd"] is not None:
        raise ValueError("本入口尚无模型价格配置；费用须为 null，请在供应商侧设置费用上限")
    return {**copy.deepcopy(data), "profile_id": identifier, "protocol": data["provider"]["protocol"],
            "max_total_tokens": data["budget"]["max_total_tokens"]}


def validate_secret(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 16384 or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("API Key 为空、过长或包含空白/控制字符；未保存输入")
    return value


def secret_input():
    if not sys.stdin.isatty():
        raise ValueError("API Key 只能在本机交互终端隐藏输入，不接受配置、命令行或环境变量")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return validate_secret(getpass.getpass("本次云 API Key（隐藏输入，仅本次进程使用）："))
    except (getpass.GetPassWarning, EOFError):
        raise ValueError("终端无法安全隐藏输入，已停止；请使用本机 PowerShell 交互终端") from None


class LocalSession(ProductSession):
    """本机模型快照和短期内存密钥；生成请求交给配置指定的供应商。"""

    def __init__(self, model, directory: Path, secret: str):
        self._secret = validate_secret(secret)
        self._closed = False
        self.origin = LOCAL_AUTHORITY
        root = directory / "local-model-settings"
        scope = hashlib.sha256(f"{LOCAL_AUTHORITY}\0{LOCAL_OWNER_ID}".encode()).hexdigest()
        try:
            catalog = ModelCatalog(root / scope / "model-settings.sqlite3", scope)
            try:
                provider = model["provider"]
                catalog.upsert(provider["id"], ProviderInput.model_validate({
                    "name": "本次隔离联调", "protocol": provider["protocol"], "base_url": provider["endpoint"],
                    "api_format": FORMATS[provider["protocol"]],
                    "models": [{"model_id": model["model"], "context_tokens": model["context_tokens"],
                                "metadata_source": "user_override"}]}))
                catalog.data["parameters"] = {k: model["parameters"][k] for k in ModelParameters.model_fields}
                catalog.data["profiles"][model["profile_id"]]["supports_streaming"] = model["supports_streaming"]
                catalog.save()
                self._reference = catalog.reference(provider["id"])["reference"]
                self._snapshot_sha256 = fingerprint(catalog.data)
            finally:
                catalog.close()
            super().__init__({**copy.deepcopy(model), "endpoint": LOCAL_AUTHORITY, "model_settings_directory": str(root),
                              "credential_namespace": "candidate"})
        except BaseException:
            self.close()
            raise

    def runtime_credentials(self):
        if self._closed or not self._secret:
            raise ValueError("本机联调凭据已释放")
        return {self._reference: self._secret}

    def identity(self):
        return {"account_mode": ACCOUNT_MODE, "origin": self.origin, "local_owner": LOCAL_OWNER_ID, "account_service_started": False,
                "real_server_account_verified": False, "account_service_model_routes": False,
                "model_settings_directory": self.model["model_settings_directory"],
                "settings_sha256": self._snapshot_sha256, "model_capabilities_source": "user_declared",
                "credential_source": "interactive_memory_only", "system_credentials_access": "disabled"}

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._secret = ""
