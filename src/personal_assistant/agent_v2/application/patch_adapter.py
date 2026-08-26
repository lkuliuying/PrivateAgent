"""单文件 Patch / PatchSet → PatchOperation 统一适配（专项计划 §10.1/CT-5）。

单一表示：两类补丁工具的预览/应用输出都投影为 ``PatchOperation`` 序列，
供完成证据（filesystem.write/delete/rename effect）与审批 hash 复用；
不复制第二套落盘语义（v0.9 handler 仍是唯一执行器）。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..domain.patch_operations import (
    PatchOperation,
    PatchOperationKind,
    canonical_operations_hash,
)


def operation_from_single_file(output: Mapping[str, Any]) -> PatchOperation:
    """从 v0.9 单文件 diff 工具输出投影（propose/apply 共用 schema）。"""
    rel_path = str(output.get("rel_path") or "")
    creates = bool(output.get("creates_file"))
    return PatchOperation(
        operation=PatchOperationKind.CREATE if creates else PatchOperationKind.UPDATE,
        rel_path=rel_path,
        before_sha256=(
            None if creates else _optional_sha(output.get("old_sha256"))
        ),
        after_sha256=_optional_sha(output.get("new_sha256")),
    )


def operations_from_patchset(
    files: Sequence[Mapping[str, Any]],
) -> tuple[PatchOperation, ...]:
    """从 PatchSet 文件记录列表投影（含 delete/rename 变体）。

    文件记录字段与 v0.9 ``CodingPatchSetFile`` 对齐：
    {rel_path, operation?, new_rel_path?, old_sha256?, new_sha256?}。
    """
    operations: list[PatchOperation] = []
    for record in files:
        raw_kind = str(record.get("operation") or "update").strip().lower()
        kind = PatchOperationKind(raw_kind)
        old_sha = _optional_sha(record.get("old_sha256"))
        new_sha = _optional_sha(record.get("new_sha256"))
        if kind == PatchOperationKind.DELETE:
            # delete 记录只有旧内容事实；after 置空由回读"目标不存在"验证。
            new_sha = None
        operations.append(
            PatchOperation(
                operation=kind,
                rel_path=str(record.get("rel_path") or ""),
                new_rel_path=record.get("new_rel_path"),
                before_sha256=old_sha
                if kind != PatchOperationKind.CREATE
                else None,
                after_sha256=new_sha,
            )
        )
    return tuple(operations)


def patchset_operations_hash(files: Sequence[Mapping[str, Any]]) -> str:
    """审批绑定的规范化 operations hash（§10.2）。"""
    return canonical_operations_hash(list(operations_from_patchset(files)))


def _optional_sha(value: Any) -> str | None:
    if value is None or not isinstance(value, str):
        return None
    return value.lower() if value else None
