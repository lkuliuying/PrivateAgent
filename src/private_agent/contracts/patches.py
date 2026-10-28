"""本机结构化补丁的纯契约与文本变换；不依赖服务端仓储。"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_PATCH_BYTES = 4 * 1024 * 1024
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10)}


def relative_path(value: str) -> str:
    if (not value or len(value) > 1024 or any(c in value for c in '\\:*?"<>|')
            or re.search(r"[\x00-\x1f\x7f]", value)):
        raise ValueError("路径必须是规范的项目相对路径")
    if any(part in {"", ".", ".."} or part.endswith((".", " "))
           or part.split(".")[0].upper() in RESERVED for part in value.split("/")):
        raise ValueError("路径包含越界、空段或 Windows 别名")
    return value


class PatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LineEdit(PatchInput):
    start_line: int = Field(ge=1)
    delete_count: int = Field(ge=0)
    text: str = Field(max_length=1024 * 1024)


class PatchOperation(PatchInput):
    operation: Literal["create", "update", "delete", "move", "mkdir"]
    rel_path: str
    new_rel_path: str | None = None
    snapshot_id: str | None = Field(default=None, min_length=1, max_length=128)
    content: str | None = Field(default=None, max_length=1024 * 1024)
    edits: list[LineEdit] = Field(default_factory=list, max_length=128)

    @field_validator("rel_path", "new_rel_path")
    @classmethod
    def validate_path(cls, value):
        return relative_path(value) if value is not None else value

    @model_validator(mode="after")
    def validate_shape(self):
        if (self.operation in {"update", "delete", "move"}) != (self.snapshot_id is not None):
            raise ValueError("修改、删除、移动必须引用本任务的读取版本；新增不能指定旧版本")
        if (self.operation == "move") != (self.new_rel_path is not None):
            raise ValueError("仅移动操作必须提供目标路径")
        if self.operation == "create" and (self.content is None or self.edits):
            raise ValueError("新增文件必须提供完整内容")
        if self.operation == "update" and ((self.content is not None) == bool(self.edits)):
            raise ValueError("修改文件须提供完整内容或局部行补丁之一")
        if self.operation not in {"create", "update"} and (self.content is not None or self.edits):
            raise ValueError("该操作不接受文本内容")
        return self


class PatchProposal(PatchInput):
    operations: list[PatchOperation] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_paths(self):
        paths = [(p, op.operation) for op in self.operations for p in (op.rel_path, op.new_rel_path) if p]
        seen = {}
        for path, kind in paths:
            key = path.casefold()
            if key in seen:
                raise ValueError("补丁包含重复路径、大小写别名或移动循环")
            seen[key] = kind
        for path, kind in seen.items():
            if kind != "mkdir" and any(other.startswith(path + "/") for other in seen):
                raise ValueError("文件操作不能同时作为其他操作的祖先目录")
        if len(self.model_dump_json().encode("utf-8")) > MAX_PATCH_BYTES:
            raise ValueError("补丁请求超过 4 MiB 上限")
        return self


class PatchApply(PatchInput):
    patch_set_id: str = Field(min_length=1, max_length=128)
    preview_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    require_approval: bool = False


def updated_bytes(before: bytes, operation: PatchOperation) -> bytes:
    """保留原始 BOM 和未编辑行；插入文本使用原文件换行风格。"""
    bom = before.startswith(b"\xef\xbb\xbf")
    text = before.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"

    def normalize(value):
        if "\x00" in value:
            raise ValueError("补丁不能写入二进制内容")
        return value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)

    if operation.content is not None:
        result = normalize(operation.content)
    else:
        lines = text.splitlines(keepends=True)
        end = -1
        for edit in sorted(operation.edits, key=lambda item: item.start_line):
            start = edit.start_line - 1
            if start <= end or start > len(lines) or start + edit.delete_count > len(lines):
                raise ValueError("行补丁越界、重复或重叠")
            end = start + max(1, edit.delete_count) - 1
        for edit in sorted(operation.edits, key=lambda item: item.start_line, reverse=True):
            start = edit.start_line - 1
            lines[start:start + edit.delete_count] = [normalize(edit.text)]
        result = "".join(lines)
    data = (b"\xef\xbb\xbf" if bom else b"") + result.encode("utf-8")
    if len(data) > 1024 * 1024:
        raise ValueError("补丁结果超过单文件 1 MiB 上限")
    return data
