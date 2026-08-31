"""连接配置不包含凭据，也不决定项目记录的数据所有者。"""
from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


def service_origin(value: str) -> str:
    url = urlsplit(value)
    loopback = url.hostname in {"127.0.0.1", "localhost", "::1"}
    if (url.scheme not in {"http", "https"} or (url.scheme == "http" and not loopback)
            or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}):
        raise ValueError("服务地址必须是 HTTPS 源站；仅本机回环地址允许 HTTP")
    return value.rstrip("/")


class ConnectionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mode: Literal["local", "cloud", "self_hosted"] = "local"
    server_origin: str = ""
    inference_mode: Literal["service", "local"] = "service"
    model_protocol: Literal["ollama", "openai"] = "ollama"
    model_endpoint: str = "http://127.0.0.1:11434"
    model_name: str = Field(default="", max_length=200)
    context_tokens: int | None = Field(default=8192, ge=1, le=1_000_000_000)

    @model_validator(mode="after")
    def validate_addresses(self):
        if self.mode != "local":
            self.server_origin = service_origin(self.server_origin)
        url = urlsplit(self.model_endpoint)
        if (url.scheme not in {"http", "https"} or url.hostname not in {"127.0.0.1", "localhost", "::1"}
                or url.username or url.password or url.query or url.fragment):
            raise ValueError("本地模型必须使用不含凭据的回环地址，不允许转发到远程服务")
        if self.model_protocol == "ollama" and url.path not in {"", "/"}:
            raise ValueError("Ollama 地址必须为源站，不包含 /api 路径")
        return self
