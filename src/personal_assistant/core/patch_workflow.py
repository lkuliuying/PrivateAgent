"""v0.5.0 B1：Patch 可信执行适配模块。

把 legacy ``apply_patch_to_workspace`` 包装为 versioned ``ToolSpec``
（契约见 ``agents/workflow_contracts.py``，B0 冻结）。本模块只服务 Agent
Runtime 的 versioned 路径；legacy 注册表与 ``routes_coding.py`` 继续使用
``code_tools`` 旧实现。

安全边界（威胁清单 docs/releases/v0.5.0/v0.5.0-b0-contracts-20260809.md §4.1）：

- 只允许授权项目根内相对路径；拒绝绝对路径、``..``、符号链接、目录联接与
  Windows 重解析点越界；
- 写入前重解析路径（TOCTOU 缓解）并复核磁盘旧 SHA；已有文件必须携带
  ``expected_old_sha256``，不匹配即拒绝（过期补丁/冲突）；
- 同目录临时文件 + ``os.replace`` 原子替换（替换路径本身，不跟随链接）；
- 写入后回读磁盘内容核对 new SHA，不一致失败关闭，不留下半写入状态。

所有失败一律抛 ``RuntimeError``/``PermissionError_``，由 dispatcher 转为
terminal failure；``non_idempotent`` 语义保证崩溃后的未知写入不被自动重放。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.runtime import CancellationToken
from ..agents.tools import (
    ToolSpec,
    VersionedToolRegistry,
)
from ..agents.workflow_contracts import WORKFLOW_CONTRACT_BY_NAME
from .code_tools import propose_patch
from .permissions import PermissionError_
from .projects import ProjectService, resolve_within

_PATCH_CONTRACT = WORKFLOW_CONTRACT_BY_NAME["apply_patch_to_workspace"]

# 拒绝写入的最终组件类型：符号链接 / 目录联接 / Windows 重解析点
_ISLINK = os.path.islink
_ISJUNCTION = getattr(os.path, "isjunction", lambda path: False)  # Python 3.12+


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_text_or_empty(path: Path, *, create: bool) -> str:
    """读取文件文本；create=True 且文件不存在时返回空串。"""
    if not path.exists():
        if create:
            return ""
        raise FileNotFoundError(f"文件不存在: {path.name}")
    if not path.is_file():
        raise ValueError(f"不是文件: {path.name}")
    size = path.stat().st_size
    if size > 5 * 1024 * 1024:
        raise ValueError(f"文件过大（{size} 字节，上限 5242880 字节）")
    return path.read_text(encoding="utf-8", errors="ignore")


def _reject_link_target(full: Path) -> None:
    """拒绝最终组件为符号链接/目录联接/重解析点的写入目标。

    父目录链中的链接指向根外时已被 ``resolve_within`` 的 resolve 语义拒绝
    （最终目标必须仍在根内）；此处再拒绝最终组件本身是链接的情况，保证
    ``os.replace`` 替换的是链接而不是其指向目标，行为可预测。
    """
    if _ISLINK(full) or _ISJUNCTION(full):
        raise PermissionError_("拒绝写入符号链接/目录联接/重解析点目标")


def _atomic_write(full: Path, content: str) -> int:
    """同目录临时文件 + 原子替换，返回写入字节数；失败时清理临时文件。"""
    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{full.name}.", suffix=".pa-tmp", dir=str(full.parent)
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, full)
        tmp_name = None
        return full.stat().st_size
    except OSError as exc:
        raise RuntimeError(f"写入失败: {exc}") from exc
    finally:
        if tmp_name is not None:
            with suppress(OSError):
                os.unlink(tmp_name)


def _write_and_verify(
    root: str,
    rel_path: str,
    new_content: str,
    *,
    expected_old_sha256: str | None,
    create: bool,
    preview: dict[str, Any],
) -> dict[str, Any]:
    """写入临界区（to_thread）：重解析 → 冲突校验 → 原子写 → 回读核对。"""
    full = resolve_within(root, rel_path)
    _reject_link_target(full)
    if create and not full.parent.exists():
        full.parent.mkdir(parents=True, exist_ok=True)
        # 父目录创建后重新校验仍在根内（TOCTOU：mkdir 可能经链接换址）
        full = resolve_within(root, rel_path)
    old = _read_text_or_empty(full, create=create)
    old_sha = _sha256_text(old)
    new_sha = _sha256_text(new_content)
    if old:
        if expected_old_sha256 is None:
            raise PermissionError_("已有文件必须携带 expected_old_sha256 才能应用补丁")
        if old_sha != expected_old_sha256:
            raise RuntimeError("文件内容已变化，拒绝应用过期补丁")
    elif expected_old_sha256 and expected_old_sha256 != _sha256_text(""):
        raise RuntimeError("新建文件必须携带 create=true 且 old_sha256 与空内容一致")
    size_bytes = _atomic_write(full, new_content)
    try:
        readback = full.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("写入后回读文件不是有效 UTF-8，失败关闭") from exc
    if _sha256_text(readback) != new_sha:
        raise RuntimeError("写入后回读 SHA 与声明不一致，失败关闭")
    return {
        "project_id": preview["project_id"],
        "rel_path": preview["rel_path"],
        "old_sha256": old_sha,
        "new_sha256": new_sha,
        "size_bytes": size_bytes,
        "diff": preview["diff"],
        "truncated": preview["truncated"],
        "verified": True,
    }


async def apply_patch_to_workspace_trusted(
    db: AsyncSession,
    project_id: int,
    rel_path: str,
    new_content: str,
    *,
    expected_old_sha256: str | None = None,
    create: bool = False,
) -> dict[str, Any]:
    """审批后把已预览内容原子写入授权项目文件，写入后回读核对 new SHA。"""
    preview = await propose_patch(db, project_id, rel_path, new_content, create=create)
    if preview["truncated"]:
        raise RuntimeError("预览被截断，不允许直接应用；请重新生成可完整审查的分块 Diff")
    project = await ProjectService(db).get(project_id)
    root = project.root_path
    return await asyncio.to_thread(
        _write_and_verify,
        root,
        rel_path,
        new_content,
        expected_old_sha256=expected_old_sha256,
        create=create,
        preview=preview,
    )


def build_patch_tool_registry(
    db: AsyncSession,
    *,
    legacy_registry=None,
) -> VersionedToolRegistry:
    """Build the versioned registry containing the audited patch tool."""
    from .tools import default_registry

    source = legacy_registry or default_registry
    legacy = source.get(_PATCH_CONTRACT.name)
    if legacy is None:
        raise RuntimeError(f"缺少内建工具：{_PATCH_CONTRACT.name}")
    if legacy.risk_level != _PATCH_CONTRACT.risk_level.value:
        raise RuntimeError(
            "工具风险等级与审核后的 Agent 契约不一致，拒绝迁移："
            f"{_PATCH_CONTRACT.name}"
        )
    registry = VersionedToolRegistry()
    registry.register(_build_patch_tool_spec(db))
    return registry


def _build_patch_tool_spec(db: AsyncSession) -> ToolSpec:
    async def execute(arguments: dict[str, Any], cancellation: CancellationToken) -> Any:
        if cancellation.is_cancelled:
            raise RuntimeError("工具执行已取消")
        return await apply_patch_to_workspace_trusted(
            db,
            arguments["project_id"],
            arguments["rel_path"],
            arguments["new_content"],
            expected_old_sha256=arguments.get("expected_old_sha256"),
            create=bool(arguments.get("create", False)),
        )

    return ToolSpec(
        name=_PATCH_CONTRACT.name,
        version=_PATCH_CONTRACT.version,
        description=_PATCH_CONTRACT.description,
        input_schema=_PATCH_CONTRACT.input_schema,
        output_schema=_PATCH_CONTRACT.output_schema,
        risk_level=_PATCH_CONTRACT.risk_level,
        required_capabilities=_PATCH_CONTRACT.required_capabilities,
        timeout_ms=_PATCH_CONTRACT.timeout_ms,
        max_input_bytes=_PATCH_CONTRACT.max_input_bytes,
        max_output_bytes=_PATCH_CONTRACT.max_output_bytes,
        idempotency=_PATCH_CONTRACT.idempotency,
        supports_cancellation=_PATCH_CONTRACT.supports_cancellation,
        redaction_policy=_PATCH_CONTRACT.redaction_policy,
        executor=execute,
    )
