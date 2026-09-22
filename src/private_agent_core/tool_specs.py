"""共享工具契约；模型展示与执行策略使用同一份受信元数据。"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel

from .contracts import ModelToolDefinition


class ToolFailure(ValueError):
    """可安全返回模型的稳定错误；不得携带原始输入或秘密。"""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def model_schema(model: type[BaseModel]) -> dict:
    """保持现有严格模型协议；默认值由执行器解析而非模型猜测。"""
    def prepare(value):
        if isinstance(value, dict):
            value.pop("title", None)
            value.pop("default", None)
            if "properties" in value:
                value["required"] = list(value["properties"])
            for child in value.values():
                prepare(child)
        elif isinstance(value, list):
            for child in value:
                prepare(child)
    schema = model.model_json_schema()
    prepare(schema)
    return schema


def object_output(**fields: str) -> dict:
    return {"type": "object", "properties": {name: {"type": kind} for name, kind in fields.items()},
            "required": list(fields), "additionalProperties": True}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    input_model: type[BaseModel]
    description: str
    version: str = "1"
    effect: Literal["read", "write", "process", "control", "external"] = "read"
    approval: Literal["auto", "policy", "always"] = "auto"
    capabilities: tuple[str, ...] = ("file.read",)
    parallel_safe: bool = False
    idempotent: bool = True
    supports_cancellation: bool = False
    execution_protocol: bool = False
    legacy_only: bool = False
    display_model: type[BaseModel] | None = None
    output_schema: Mapping[str, Any] = field(default_factory=object_output)
    max_output_bytes: int = 4 * 1024 * 1024

    def __post_init__(self):
        if self.parallel_safe and (
            self.effect != "read" or self.approval != "auto" or not self.idempotent
        ):
            raise ValueError("只有自动授权、幂等的只读工具可以声明并行")
        if self.effect in {"write", "process", "external"} and self.approval == "auto":
            raise ValueError("存在副作用的工具必须声明执行策略或审批")
        Draft202012Validator.check_schema(self.output_schema)
        self.definition()

    @property
    def blocked_in_readonly(self) -> bool:
        return self.effect in {"write", "process"}

    def available(self, permission_mode: str, execution_version: str | None) -> bool:
        return not (
            permission_mode == "readonly" and self.blocked_in_readonly
            or self.execution_protocol and execution_version != "1.0"
            or self.legacy_only and execution_version == "1.0"
        )

    def definition(self) -> ModelToolDefinition:
        return ModelToolDefinition(name=self.name, description=self.description,
                                   input_schema=model_schema(self.display_model or self.input_model))

    def validate_output(self, output: Any) -> dict:
        try:
            size = len(json.dumps(output, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        except (TypeError, ValueError, RecursionError) as error:
            raise ToolFailure("invalid_tool_output", "工具结果不符合 JSON 契约，未作为成功结果使用") from error
        if size > self.max_output_bytes:
            raise ToolFailure("tool_output_too_large", "工具结果超过大小上限，请缩小查询或分页读取")
        if not Draft202012Validator(self.output_schema).is_valid(output):
            raise ToolFailure("invalid_tool_output", "工具结果不符合声明结构，未作为成功结果使用")
        return output

    def public(self) -> dict:
        return {"name": self.name, "version": self.version, "effect": self.effect,
                "approval": self.approval, "capabilities": list(self.capabilities),
                "parallel_safe": self.parallel_safe, "idempotent": self.idempotent,
                "supports_cancellation": self.supports_cancellation,
                "input_schema": self.definition().input_schema, "output_schema": dict(self.output_schema)}


class ToolRegistry:
    def __init__(self, specs: Iterable[ToolSpec] = ()):
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError("工具名称重复：" + spec.name)
        self._specs[spec.name] = spec

    def __getitem__(self, name: str) -> ToolSpec:
        return self._specs[name]

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def __iter__(self):
        return iter(self._specs.values())

    def visible(self, permission_mode: str, execution_version: str | None) -> tuple[ToolSpec, ...]:
        return tuple(spec for spec in self if spec.available(permission_mode, execution_version))
