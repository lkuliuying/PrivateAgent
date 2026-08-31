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

class ModelConfig(BaseModel):
    """模型设置与服务器账号身份独立，不接受服务器地址或本机账号模式。"""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    inference_mode: Literal["auto", "service", "local"] = "auto"
    model_protocol: Literal["ollama", "openai"] = "ollama"
    model_endpoint: str = "http://127.0.0.1:11434"
    model_name: str = Field(default="", max_length=200)
    context_tokens: int | None = Field(default=8192, gt=0, le=1_000_000_000, strict=True)

    @model_validator(mode="after")
    def validate_endpoint(self):
        url = urlsplit(self.model_endpoint)
        if (url.scheme not in {"http", "https"} or url.hostname not in {"127.0.0.1", "localhost", "::1"}
                or url.username or url.password or url.query or url.fragment):
            raise ValueError("本机模型仅允许回环地址，且不能包含凭据、查询参数或片段")
        if url.port == 0:
            raise ValueError("本机模型端口无效")
        if self.model_protocol == "ollama" and url.path not in {"", "/"}:
            raise ValueError("Ollama 地址不能包含 API 路径")
        self.model_endpoint = self.model_endpoint.rstrip("/")
        return self
