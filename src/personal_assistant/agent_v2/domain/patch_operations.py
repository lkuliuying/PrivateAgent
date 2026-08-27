"""PatchOperation 领域契约（专项计划 §10.2/§10.3/CT-5）。

统一内部表示：单文件 Patch 与多文件 PatchSet 都投影为 ``PatchOperation``
序列；原始自由文本 patch 不是 durable fact（AD-T04：Qwen 默认输出严格
结构化 JSON，native apply-patch adapter 仅在模型 probe 证明稳定后开放）。

Windows 路径安全规则（§10.3，叠加 v0.9 ``resolve_within`` 的越界/链接
逃逸防护——本模块在 schema 层先行拒绝）：

- 拒绝绝对路径、盘符、UNC/设备路径（``\\\\``、``\\\\.\\``、``\\\\?\\``）；
- 拒绝任何段中的 ADS 冒号；
- 拒绝保留设备名段（CON/PRN/AUX/NUL/COM1-9/LPT1-9，含带扩展名变体）；
- 拒绝段尾的 ``.`` 或空格（Win32 会静默剥离，造成路径混淆）；
- 拒绝控制字符与反斜杠分隔（统一 POSIX 分隔）。
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .effects import EffectClass


class PatchOperationKind(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RENAME = "rename"


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


class PatchPathError(ValueError):
    """rel_path 违反 Windows 安全规则；``reason`` 为公开低敏感原因。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def validate_workspace_rel_path(rel_path: str) -> str:
    """schema 层路径校验；返回规范化（POSIX 分隔）路径。"""
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise PatchPathError("rel_path 不能为空")
    if rel_path != rel_path.strip():
        # 首尾空白本身即混淆向量（Win32 剥离语义），整体拒绝；
        # 段内/中间空格保持合法。
        raise PatchPathError("rel_path 不能以空白开头或结尾")
    path = rel_path.replace("\\", "/")
    if len(path) > 2048:
        raise PatchPathError("rel_path 过长（上限 2048）")
    if _CONTROL_CHARS_RE.search(path):
        raise PatchPathError("rel_path 含控制字符")
    if path.startswith("/"):
        raise PatchPathError("rel_path 必须是项目内相对路径")
    if re.match(r"^[a-zA-Z]:", path):
        raise PatchPathError("rel_path 不能包含盘符")
    if "\\\\" in rel_path or rel_path.startswith("\\\\"):
        raise PatchPathError("rel_path 不能是 UNC/设备路径")
    segments = [segment for segment in path.split("/")]
    if any(segment == "" for segment in segments):
        raise PatchPathError("rel_path 含空段（重复分隔符）")
    for segment in segments:
        if segment in {".", ".."}:
            raise PatchPathError("rel_path 不允许 . / .. 段")
        if ":" in segment:
            raise PatchPathError("rel_path 不允许 NTFS 备用数据流（冒号）")
        # Win32 语义：保留设备名即使带任意扩展名也等价保留（CON.txt → CON）。
        if segment.split(".")[0].upper() in _RESERVED_NAMES:
            raise PatchPathError(f"rel_path 含 Windows 保留设备名：{segment}")
        if segment.endswith(".") or segment.endswith(" "):
            raise PatchPathError("rel_path 段不能以点或空格结尾（Win32 剥离语义）")
    return path


class PatchOperation(BaseModel):
    """一个文件的规范化补丁操作（不可变）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: PatchOperationKind
    rel_path: str
    new_rel_path: str | None = None
    before_sha256: str | None = Field(default=None, pattern=_SHA256_RE.pattern)
    after_sha256: str | None = Field(default=None, pattern=_SHA256_RE.pattern)
    encoding: str = Field(default="utf-8", max_length=32)
    line_ending: str = Field(default="lf", pattern=r"^(lf|crlf|native)$")

    @field_validator("rel_path")
    @classmethod
    def _validate_rel(cls, value: str) -> str:
        return validate_workspace_rel_path(value)

    @field_validator("new_rel_path")
    @classmethod
    def _validate_new_rel(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_workspace_rel_path(value)

    @model_validator(mode="after")
    def _validate_shape(self) -> "PatchOperation":
        if self.operation == PatchOperationKind.RENAME:
            if self.new_rel_path is None:
                raise ValueError("rename 操作必须提供 new_rel_path")
            if self.new_rel_path.casefold() == self.rel_path.casefold():
                raise ValueError(
                    "rename 的目标路径与原路径相同（大小写不敏感比较）"
                )
            if self.before_sha256 is None:
                raise ValueError("rename 必须携带 before_sha256（TOCTOU 校验）")
        else:
            if self.new_rel_path is not None:
                raise ValueError(f"{self.operation.value} 操作不允许 new_rel_path")
        if self.operation in (
            PatchOperationKind.UPDATE,
            PatchOperationKind.DELETE,
            PatchOperationKind.RENAME,
        ) and self.before_sha256 is None:
            raise ValueError(
                f"{self.operation.value} 必须携带 before_sha256（防覆盖用户改动）"
            )
        if self.operation == PatchOperationKind.CREATE and (
            self.before_sha256 is not None
        ):
            raise ValueError("create 是新建操作，不允许 before_sha256")
        if self.operation in (
            PatchOperationKind.CREATE,
            PatchOperationKind.UPDATE,
        ) and self.after_sha256 is None:
            raise ValueError(f"{self.operation.value} 必须携带 after_sha256")
        return self

    @property
    def effects(self) -> tuple[EffectClass, ...]:
        mapping = {
            PatchOperationKind.CREATE: (
                EffectClass.FILESYSTEM_WRITE,
                EffectClass.FILESYSTEM_READ,
            ),
            PatchOperationKind.UPDATE: (
                EffectClass.FILESYSTEM_WRITE,
                EffectClass.FILESYSTEM_READ,
            ),
            PatchOperationKind.DELETE: (
                EffectClass.FILESYSTEM_DELETE,
                EffectClass.FILESYSTEM_READ,
            ),
            PatchOperationKind.RENAME: (
                EffectClass.FILESYSTEM_RENAME,
                EffectClass.FILESYSTEM_READ,
            ),
        }
        return mapping[self.operation]


def canonical_operations_hash(operations: list["PatchOperation"]) -> str:
    """审批绑定的规范化 operations hash（§10.2：审批绑定 hash，非自由文本）。"""
    payload = json.dumps(
        [op.model_dump(mode="json") for op in sorted(
            operations, key=lambda item: (item.rel_path, item.operation.value)
        )],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def find_case_collisions(rel_paths: list[str]) -> list[tuple[str, str]]:
    """同一批操作内的大小写不敏感碰撞（Windows 大小写不敏感文件系统上
    两个不同写法指向同一文件）。返回有序对列表。"""
    seen: dict[str, str] = {}
    collisions: list[tuple[str, str]] = []
    for raw in sorted(set(rel_paths)):
        normalized = validate_workspace_rel_path(raw).casefold()
        if normalized in seen:
            collisions.append((seen[normalized], raw))
        else:
            seen[normalized] = raw
    return collisions
