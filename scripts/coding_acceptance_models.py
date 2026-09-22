"""真实产品评测的无凭据配置与本机模型绑定；不负责完成编码题。"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from coding_acceptance_schema import budget, fields, fingerprint

from private_agent_local.model_catalog import ModelParameters, endpoint_url, validate_id


def direct_config(data):
    fields(data, {"schema_version", "connection_mode", "endpoint", "profile_id", "model", "model_version",
                  "context_tokens", "parameters", "budget", "provider", "model_settings_directory", "credential_namespace"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 2 or data["connection_mode"] != "direct_provider":
        raise ValueError("直连评测必须显式使用配置 schema_version=2、direct_provider")
    parameters = data["parameters"]
    fields(parameters, {"reasoning_effort", "max_output_tokens", "auto_compact", *ModelParameters.model_fields})
    common = {k: v for k, v in data.items() if k not in {"provider", "model_settings_directory", "credential_namespace"}}
    common.update(schema_version=1, connection_mode="product_proxy",
                  parameters={k: parameters[k] for k in ("reasoning_effort", "max_output_tokens", "auto_compact")})
    product_config(common, identity_limits=(128, 200), max_context_tokens=10_000_000)
    ModelParameters.model_validate({k: parameters[k] for k in ModelParameters.model_fields}, strict=True)
    provider_config(data["provider"])
    directory = data["model_settings_directory"]
    if not isinstance(directory, str) or not 1 <= len(directory) <= 4096 or not Path(directory).is_absolute() or any(ord(c) < 32 for c in directory):
        raise ValueError("模型设置目录必须为明确的本机绝对路径")
    if not isinstance(data["credential_namespace"], str) or data["credential_namespace"] not in {"desktop", "candidate"}:
        raise ValueError("须明确选择客户端凭据命名空间")
    return {**data, "protocol": data["provider"]["protocol"], "max_total_tokens": data["budget"]["max_total_tokens"]}


def provider_config(provider):
    fields(provider, {"id", "protocol", "endpoint"})
    if not isinstance(provider["id"], str):
        raise ValueError("供应商标识无效")
    validate_id(provider["id"])
    if not isinstance(provider["protocol"], str) or provider["protocol"] not in {"openai", "claude", "ollama"}:
        raise ValueError("直连协议无效")
    if not isinstance(provider["endpoint"], str):
        raise ValueError("供应商端点无效")
    if endpoint_url(provider["endpoint"], provider["protocol"]) != provider["endpoint"]:
        raise ValueError("供应商端点必须规范化")


def product_config(data, *, identity_limits=(120, 120), max_context_tokens=1_000_000):
    fields(data, {"schema_version", "connection_mode", "endpoint", "profile_id", "model", "model_version",
                  "context_tokens", "parameters", "budget"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["connection_mode"] != "product_proxy":
        raise ValueError("产品连接配置版本或模式无效")
    if not isinstance(data["endpoint"], str) or not 1 <= len(data["endpoint"]) <= 2048 or any(char.isspace() for char in data["endpoint"]):
        raise ValueError("产品连接源站类型或格式无效")
    address = urlsplit(data["endpoint"])
    if (address.scheme != "https" or not address.hostname or address.username or address.password
            or address.query or address.fragment or address.path not in {"", "/"} or address.port == 0):
        raise ValueError("产品连接仅接受无凭据的 HTTPS 服务源站")
    model_limits(data, identity_limits=identity_limits, max_context_tokens=max_context_tokens)
    return {**data, "protocol": "service", "max_total_tokens": data["budget"]["max_total_tokens"]}


def model_limits(data, *, identity_limits=(120, 120), max_context_tokens=1_000_000):
    """共享生成参数与预算校验；账号来源仍由各入口分别校验。"""
    for key, limit in zip(("profile_id", "model"), identity_limits):
        if not isinstance(data[key], str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1," + str(limit) + "}", data[key]):
            raise ValueError("模型或 profile 标识无效")
    if data["model_version"] is not None and (not isinstance(data["model_version"], str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,120}", data["model_version"])):
        raise ValueError("模型版本应为标识或 null（未知）")
    if type(data["context_tokens"]) is not int or not 8192 <= data["context_tokens"] <= max_context_tokens:
        raise ValueError("上下文容量无效")
    parameters = data["parameters"]
    fields(parameters, {"reasoning_effort", "max_output_tokens", "auto_compact"})
    if parameters["reasoning_effort"] is not None and (not isinstance(parameters["reasoning_effort"], str)
            or parameters["reasoning_effort"] not in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}):
        raise ValueError("推理参数无效")
    if type(parameters["max_output_tokens"]) is not int or not 128 <= parameters["max_output_tokens"] <= 32768 or type(parameters["auto_compact"]) is not bool:
        raise ValueError("输出配额或压缩参数无效")
    budget(data["budget"], 2)


class ProductSession:
    def __init__(self, model):
        self.model_name, self.context_tokens = model["model"], model["context_tokens"]
        self.calls, self.errors = [], []
        self.model = model

    def configure(self, client):
        client.request("/model-evaluation/bind", "POST", {
            "model_settings_directory": self.model["model_settings_directory"],
            "credential_namespace": self.model["credential_namespace"],
            "profile_id": self.model["profile_id"],
            "expected": {key: self.model[key] for key in ("provider", "model", "context_tokens")},
            "parameters": {key: self.model["parameters"][key] for key in ModelParameters.model_fields},
        })

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def model_identity_fingerprint(description):
    # 新隔离库的记录时间不同；冻结仍覆盖全部模型、路由、参数和能力字段。
    profile = {key: value for key, value in description.get("profile", {}).items()
               if key not in {"created_at", "updated_at"}}
    return fingerprint({**description, "profile": profile})


def check_preflight(description, model, capabilities):
    errors = []
    profile = description.get("profile", {})
    if capabilities.get("coding_evaluation_contract_version") != "1.0":
        errors.append("runtime_evaluation_capability_missing")
    for key, expected in (("model_name", model["model"]), ("context_tokens", model["context_tokens"]), ("id", model.get("profile_id", "local-model"))):
        if profile.get(key) != expected:
            errors.append("model_identity_mismatch_" + key)
    if profile.get("native_tool_calls") is not True:
        errors.append("native_tool_calls_unconfirmed")
    if model.get("connection_mode") == "direct_provider":
        if description.get("route") != "direct_provider":
            errors.append("direct_provider_route_required")
        if capabilities.get("coding_direct_evaluation_contract_version") != "1.0":
            errors.append("direct_evaluation_capability_missing")
        if description.get("provider") != model["provider"]:
            errors.append("provider_identity_mismatch")
        if description.get("parameters") != {k: model["parameters"][k] for k in ModelParameters.model_fields}:
            errors.append("model_parameters_mismatch")
        if description.get("request_budget_protocol") != "direct-1.0":
            errors.append("provider_request_budget_capability_missing")
        if description.get("credential_state") != "ready":
            errors.append("model_credential_unavailable")
        if model["parameters"]["reasoning_effort"] and model["provider"]["protocol"] != "openai":
            errors.append("reasoning_effort_unsupported_by_adapter")
        cap = description.get("declared_max_output_tokens")
        if cap is not None and (type(cap) is not int or model["parameters"]["max_output_tokens"] > cap):
            errors.append("output_limit_exceeds_model_capacity")
    if model.get("connection_mode") in {"product_proxy", "direct_provider"}:
        if model["connection_mode"] == "product_proxy" and description.get("route") != "product_proxy":
            errors.append("product_proxy_route_required")
        if model["connection_mode"] == "product_proxy" and description.get("proxy_capabilities", {}).get("request_budget_protocol") != "1.0":
            errors.append("provider_request_budget_capability_missing")
        if model.get("model_version") is not None and description.get("model_version") != model["model_version"]:
            errors.append("model_version_mismatch")
        effort = model["parameters"]["reasoning_effort"]
        if effort and effort not in (profile.get("reasoning_efforts") or []):
            errors.append("reasoning_effort_unsupported")
    return errors
