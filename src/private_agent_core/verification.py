"""输出校验器的公共协议，具体业务校验器由宿主提供。"""
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class OutputVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    passed: bool
    code: str = Field(pattern=r"^[a-z0-9_]{1,64}$")
    message: str = Field(min_length=1, max_length=2_000)
    correction: str | None = Field(default=None, max_length=4_000)


class OutputVerifier(Protocol):
    name: str
    output_schema: dict[str, Any] | None

    async def verify(self, output: str, *, attempt: int) -> OutputVerification: ...
