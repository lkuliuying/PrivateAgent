"""The only network boundary of the local executor (no provider credentials)."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

import httpx


class CloudError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


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
                    raise CloudError(401, "服务器会话已失效，请重新登录")
                if response.status_code == 404:
                    raise CloudError(503, "服务器尚未部署本机执行器所需的模型接口，请联系管理员升级服务器")
                if response.status_code != 200:
                    raise CloudError(502, f"服务器请求失败（HTTP {response.status_code}）")
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
