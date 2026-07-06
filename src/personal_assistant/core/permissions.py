"""权限与风险等级。

风险分级（docs/phase2-requirements.md §4.1）：
  safe       只读、低风险，无需审批。
  confirm    读取本地文件、消耗资源，需审批。
  restricted 有潜在破坏性（写/删/执行），第二阶段不开放。

路径校验：工具只能访问用户显式授权过的路径（trusted_paths），
resolve 后必须等于某授权文件或位于某授权目录之下，防止 ``../`` 越界。
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path


class RiskLevel(str, Enum):
    SAFE = "safe"
    CONFIRM = "confirm"
    RESTRICTED = "restricted"


class PermissionError_(RuntimeError):
    """路径未授权或越界。"""


def is_trusted_path(path: str, trusted: list[str]) -> bool:
    """路径是否在授权范围内。

    将目标路径与每个授权路径都 resolve 后比较：相等（授权文件本身），
    或目标位于某授权目录之下。resolve 会规范化 ``..`` / 符号链接，防越界。
    """
    try:
        target = Path(path).resolve()
    except (OSError, ValueError):
        return False
    for t in trusted:
        try:
            tp = Path(t).resolve()
        except (OSError, ValueError):
            continue
        if target == tp:
            return True
        # 目录授权：target 位于 tp 之下
        try:
            target.relative_to(tp)
            return True
        except ValueError:
            continue
    return False


def assert_trusted(path: str, trusted: list[str]) -> None:
    """断言路径已授权，否则抛 PermissionError_。"""
    if not is_trusted_path(path, trusted):
        raise PermissionError_(f"路径未授权或越界: {path}")
