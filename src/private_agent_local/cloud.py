"""The only network boundary of the local executor (no provider credentials)."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

import httpx

MODEL_ERROR_MESSAGES = {
    "not_configured": "当前账号未配置默认模型，请在模型配置中选择并启用模型",
    "invalid_configuration": "服务器模型配置无效，请检查模型服务地址和参数",
    "missing_api_key": "服务器模型未配置 API Key，请在模型配置中重新保存密钥",
    "unauthorized": "模型供应商认证失败，请检查 API Key 和模型访问权限",
    "model_not_found": "模型供应商未找到所选模型，请检查模型名称和服务地址",
    "unsupported_capability": "所选服务器模型不可用或不支持当前能力，请检查模型配置",
    "provider_rejected_request": "模型供应商拒绝请求，请检查模型能力、工具参数和推理强度配置",
    "rate_limited": "模型供应商请求限额已达到，请检查配额或稍后重试",
    "network_error": "服务器无法连接模型供应商，请检查模型服务地址和服务器网络",
    "provider_unavailable": "模型供应商暂不可用，请稍后重试",
    "timeout": "模型服务响应超时，请稍后重试",
    "invalid_response": "模型供应商响应格式无效，请检查模型接口兼容性",
    "provider_error": "服务器模型调用失败，请联系管理员检查模型服务状态",
}


class CloudError(Exception):
    def __init__(self, status: int, message: str, *, code: str = "cloud_unavailable"):
        super().__init__(message)
        self.status = status
        self.code = code


class Cloud:
    def __init__(self, origin: str, *, transport=None):
        url = urlsplit(origin)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.path not in {"", "/"} or url.query or url.fragment):
            raise ValueError("云端地址必须是不带路径和凭据的 HTTPS 源站")
        self.origin = origin.rstrip("/")
        self.client = httpx.AsyncClient(base_url=self.origin, timeout=190,
                                       follow_redirects=False, trust_env=False, transport=transport)

    async def request(self, method: str, path: str, token: str, payload=None):
        try:
            async with self.client.stream(method, path, headers={"Authorization": f"Bearer {token}"},
                                          json=payload, timeout=190 if payload else 15) as response:
                if response.status_code in {401, 403}:
                    raise CloudError(401, "服务器会话已失效，请重新登录", code="cloud_auth_required")
                if response.status_code == 404:
                    raise CloudError(503, "服务器尚未部署本机执行器所需的模型接口，请联系管理员升级服务器",
                                     code="cloud_interface_missing")
                if response.status_code != 200:
                    # 云端只传递固定错误码；不读取可能含凭据、提示词或代理页面的错误正文。
                    model_code = response.headers.get("X-Model-Error-Code", "")
                    if path == "/desktop/model/complete" and model_code in MODEL_ERROR_MESSAGES:
                        raise CloudError(response.status_code, MODEL_ERROR_MESSAGES[model_code],
                                         code=f"model_{model_code}")
                    status = response.status_code
                    messages = {
                        409: "服务器模型能力未启用，请联系管理员检查配置",
                        413: "模型上下文超过服务器限制，请缩小任务范围",
                        422: "所选模型或请求参数不可用，请检查模型配置和推理强度",
                        429: "服务器或模型服务请求过多，请稍后重试",
                        502: "服务器模型或代理服务请求失败（HTTP 502），请联系管理员检查模型服务和代理状态",
                        503: "服务器或模型服务暂不可用，请稍后重试",
                        504: "服务器模型响应超时，请稍后重试",
                    }
                    raise CloudError(status if status in messages else 502,
                                     messages.get(status, f"服务器请求失败（HTTP {status}）"))
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > 2 * 1024 * 1024:
                        raise CloudError(502, "服务器响应超过大小限制")
                    body.extend(chunk)
                return json.loads(body)
        except (httpx.HTTPError, ValueError):
            raise CloudError(502, "无法连接服务器或响应无效，请检查网络") from None

    async def identity(self, token: str) -> dict:
        identity = await self.request("GET", "/auth/me", token)
        if not isinstance(identity, dict) or not isinstance(identity.get("id"), (str, int)):
            raise CloudError(502, "服务器账号响应无效")
        return identity

    async def complete(self, token: str, profile: str | None, request: dict) -> dict:
        return await self.request("POST", "/desktop/model/complete", token,
                                  {"model_profile_id": profile, "request": request})

    async def close(self):
        await self.client.aclose()
