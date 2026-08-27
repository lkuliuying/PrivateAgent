"""权限模式（v0.7.0 E0 §4.1/§4.2；v0.9.0 H0 §6 扩展）：能力映射、run 快照
组装与命令风险判定。

- ``readonly``：自动允许搜索/读取/只读 Git；写文件、命令、网络默认拒绝
  （写工具不注册，模型不可见）。
- ``confirm``：写操作（PatchSet 全部四类、项目命令）需人工审批。
- ``workspace``：项目内已配置 safe 命令 profile 自动允许；restricted 命令
  永不因模式切换自动获批（ToolCapabilityPolicy 的 RESTRICTED 分支同样拒绝）。
- ``full_access``（v0.9.0 H0 §6）：当前 OS 用户可访问的本机范围内常规文件/
  命令免逐次审批；不获得管理员权限、不绕过 OS/UAC，凭据/秘密/远程外发/
  系统级破坏动作仍有硬阻断。需要独立授予（full_access_grants）且在有效期内；
  能力位与 ``workspace`` 互相独立，不是别名。

快照契约（E0 §4.2；H0 §6.3 additive）：每次 run 保存 permission_mode /
capabilities / workspace{id, root_path_sha256} / command_profile_version /
patch_limits / remote_provider_data_policy / granted_full_access。快照只存
非秘密摘要（root_path_sha256 而非 root_path 原文）；历史 run 不因 profile
变化修改。
"""
from __future__ import annotations

from typing import Any, Mapping

from .coding_errors import PERMISSION_MODES

# 默认权限模式：最小权限（readonly 零写）。coding run 未显式指定时使用。
PERMISSION_MODE_DEFAULT = "readonly"

# 远程 Provider 数据策略：MVP 固定 no_send（模型 profile 的 secret 保持在
# 原生凭据边界；快照只存非秘密策略摘要，不存任何 Provider secret/token）。
REMOTE_PROVIDER_DATA_POLICY_DEFAULT = "no_send"

# 模式 → 工具能力集合（ToolCapability 枚举值字符串）。
# readonly 只授予只读能力；confirm/workspace/full_access 授予读写与进程执行，
# 写工具的最终放行由工具 risk（审批/拒绝）与注册表（readonly 不注册）把关；
# full_access 与 workspace 能力集合相同，差异在审批策略与硬阻断（H0 §6.2），
# 不在能力集本身——避免能力集差异造成提权假象。
_MODE_CAPABILITIES: Mapping[str, frozenset[str]] = {
    "readonly": frozenset({"filesystem.read"}),
    "confirm": frozenset(
        {"filesystem.read", "filesystem.write", "process.execute"}
    ),
    "workspace": frozenset(
        {"filesystem.read", "filesystem.write", "process.execute"}
    ),
    "full_access": frozenset(
        {"filesystem.read", "filesystem.write", "process.execute"}
    ),
}


def permission_mode_capabilities(mode: str) -> frozenset[str]:
    """按权限模式返回工具能力集合；非法模式抛 ValueError（契约 §4.1）。"""
    if mode not in PERMISSION_MODES:
        raise ValueError(
            f"permission_mode must be one of {sorted(PERMISSION_MODES)}"
        )
    return _MODE_CAPABILITIES[mode]


def build_permission_snapshot(
    *,
    permission_mode: str,
    workspace_id: int | None = None,
    workspace_root_sha256: str | None = None,
    command_profile_version: int | None = None,
    max_patchset_files: int,
    max_patchset_total_bytes: int,
    remote_provider_data_policy: str = REMOTE_PROVIDER_DATA_POLICY_DEFAULT,
    granted_full_access: bool = False,
) -> dict[str, Any]:
    """组装 run 权限快照（E0 §4.2 契约字段；只存非秘密摘要）。

    - capabilities 按模式映射（只读模式不出现写能力，快照可解释）；
    - workspace 只存 id 与 root_path_sha256，绝不包含 root_path 原文
      （错误响应与日志脱敏规则沿用 v0.6.0 交接契约 §4.1）；
    - patch_limits 来自 PatchSet 硬上限（E0 §5.1）；
    - remote_provider_data_policy 默认 no_send；
    - granted_full_access（v0.9.0 H0 §6.3）：仅当存在有效授予时为 True，
      执行器在每次工具调用前重新校验授予有效性。
    """
    workspace: dict[str, Any] | None = None
    if workspace_id is not None:
        workspace = {"id": workspace_id}
        if workspace_root_sha256:
            workspace["root_path_sha256"] = workspace_root_sha256
    snapshot: dict[str, Any] = {
        "permission_mode": permission_mode,
        "capabilities": sorted(permission_mode_capabilities(permission_mode)),
        "remote_provider_data_policy": remote_provider_data_policy,
        "patch_limits": {
            "max_files": max_patchset_files,
            "max_total_bytes": max_patchset_total_bytes,
        },
    }
    if workspace is not None:
        snapshot["workspace"] = workspace
    if command_profile_version is not None:
        snapshot["command_profile_version"] = command_profile_version
    # v0.9.0 H0 §6.3：full_access 授予事实入快照（旧客户端可忽略）
    if permission_mode == "full_access" or granted_full_access:
        snapshot["granted_full_access"] = granted_full_access
    return snapshot
