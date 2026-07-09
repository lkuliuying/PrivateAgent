"""第八阶段 M7：扩展注册表。

把 command action / capture source / provider / diagnostic check / maintenance check /
notification target 抽象为可注册描述符，统一声明 id / title / kind / risk_level /
permissions / input_schema / output_summary / ui_entry / enabled。

注册项只存元数据；执行逻辑仍由各自服务承担（注册表不绕过审批状态机）。
diagnostic_check / maintenance_check 可附带 runner，由 DiagnosticsService /
IntegrityService 在运行时遍历调用，使新增检查自动出现在诊断中心、诊断包与体检中。

持久化：用户可配置的 enabled 覆盖存于 extension_registry_items 表；内存描述符为权威来源。
内置体检 / 诊断检查标记 configurable=False（始终运行，避免漏检）；command action 等
可由用户启用/禁用，但启用/禁用不得绕过现有审批状态机（命令执行仍走原审批路由）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ExtensionRegistryItem


class ExtensionKind:
    COMMAND = "command"
    CAPTURE_SOURCE = "capture_source"
    PROVIDER = "provider"
    DIAGNOSTIC_CHECK = "diagnostic_check"
    MAINTENANCE_CHECK = "maintenance_check"
    NOTIFICATION_TARGET = "notification_target"


ALL_KINDS = (
    ExtensionKind.COMMAND,
    ExtensionKind.CAPTURE_SOURCE,
    ExtensionKind.PROVIDER,
    ExtensionKind.DIAGNOSTIC_CHECK,
    ExtensionKind.MAINTENANCE_CHECK,
    ExtensionKind.NOTIFICATION_TARGET,
)

# runner 签名因 kind 而异：
# - maintenance_check: Callable[[IntegrityService], Awaitable[list[dict]]]
# - diagnostic_check:  Callable[[AsyncSession], Awaitable[dict]]
# 注册表不约束签名，由消费方按 kind 传参。
Runner = Callable[..., Awaitable[Any]]


@dataclass
class ExtensionDescriptor:
    id: str
    title: str
    kind: str
    description: str = ""
    risk_level: str = "safe"  # safe | confirm | restricted
    # permissions 必须显式声明（可为空列表）；None 视为「缺权限声明」，注册失败。
    permissions: list[str] | None = None
    input_schema: dict | None = None
    output_summary: str | None = None
    ui_entry: dict | None = None  # {panel, action_label, icon?}
    enabled_by_default: bool = True
    configurable: bool = True
    runner: Runner | None = None

    def to_dict(self, enabled: bool | None = None) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "description": self.description,
            "risk_level": self.risk_level,
            "permissions": list(self.permissions or []),
            "input_schema": self.input_schema,
            "output_summary": self.output_summary,
            "ui_entry": self.ui_entry,
            "enabled": self.enabled_by_default if enabled is None else enabled,
            "configurable": self.configurable,
        }


class ExtensionRegistry:
    """内存扩展注册表（描述符为权威来源）+ 持久化 enabled 覆盖。"""

    def __init__(self) -> None:
        self._items: dict[str, ExtensionDescriptor] = {}

    def register(self, desc: ExtensionDescriptor) -> None:
        if not desc.id:
            raise ValueError("扩展 id 不能为空")
        if desc.kind not in ALL_KINDS:
            raise ValueError(f"未知扩展 kind: {desc.kind}")
        if desc.risk_level not in ("safe", "confirm", "restricted"):
            raise ValueError(f"非法 risk_level: {desc.risk_level}")
        if desc.permissions is None:
            raise ValueError(f"扩展 {desc.id} 缺权限声明（permissions 必须为列表，可为空）")
        if desc.id in self._items:
            raise ValueError(f"扩展 id 重复: {desc.id}")
        self._items[desc.id] = desc

    def unregister(self, ext_id: str) -> None:
        """从内存注册表移除（主要用于测试清理）。不清理持久化覆盖行。"""
        self._items.pop(ext_id, None)

    def get(self, ext_id: str) -> ExtensionDescriptor | None:
        return self._items.get(ext_id)

    def list(self, *, kind: str | None = None) -> list[ExtensionDescriptor]:
        items = list(self._items.values())
        if kind:
            items = [d for d in items if d.kind == kind]
        return items

    async def list_with_state(
        self, db: AsyncSession, *, kind: str | None = None
    ) -> list[dict]:
        """合并内存描述符与持久化 enabled 覆盖，返回可序列化列表。"""
        rows = {
            r.ext_id: r
            for r in (
                await db.execute(select(ExtensionRegistryItem))
            ).scalars().all()
        }
        out: list[dict] = []
        for d in self.list(kind=kind):
            row = rows.get(d.id)
            enabled = row.enabled if row is not None else d.enabled_by_default
            out.append(d.to_dict(enabled=enabled))
        return out

    async def set_enabled(
        self, db: AsyncSession, ext_id: str, enabled: bool
    ) -> dict:
        desc = self.get(ext_id)
        if desc is None:
            raise KeyError(ext_id)
        if not desc.configurable:
            raise PermissionError(f"扩展 {ext_id} 不可配置")
        row = await db.get(ExtensionRegistryItem, ext_id)
        if row is None:
            row = ExtensionRegistryItem(
                ext_id=ext_id,
                kind=desc.kind,
                title=desc.title,
                risk_level=desc.risk_level,
                enabled=enabled,
            )
            db.add(row)
        else:
            row.enabled = enabled
            row.kind = desc.kind
            row.title = desc.title
            row.risk_level = desc.risk_level
        await db.commit()
        return desc.to_dict(enabled=enabled)

    async def is_enabled(self, db: AsyncSession, ext_id: str) -> bool:
        desc = self.get(ext_id)
        if desc is None:
            return False
        row = await db.get(ExtensionRegistryItem, ext_id)
        return row.enabled if row is not None else desc.enabled_by_default


extension_registry = ExtensionRegistry()


def register_builtin_extensions() -> None:
    """注册内置 command action / capture source / provider / notification target。

    diagnostic_check / maintenance_check 由各自服务模块注册（附带 runner）。
    幂等：已存在的 id 跳过。
    """
    # ---- command actions（命令面板可执行动作；执行仍走原审批路由，不在此绕过）----
    commands = [
        ("cmd.new_reminder", "新建提醒", "confirm", ["write:reminders"],
         {"panel": "reminders", "action_label": "新建提醒"}),
        ("cmd.new_inbox", "新建收件箱", "safe", ["write:inbox"],
         {"panel": "inbox", "action_label": "新建收件箱"}),
        ("cmd.generate_briefing", "生成今日简报", "safe", ["read:today", "write:briefings"],
         {"panel": "today", "action_label": "生成今日简报"}),
        ("cmd.run_health_check", "运行健康检查", "safe", ["read:health"],
         {"panel": "diagnostics", "action_label": "运行健康检查"}),
        ("cmd.export_diagnostics", "导出诊断包", "safe", ["read:diagnostics"],
         {"panel": "diagnostics", "action_label": "导出诊断包"}),
        ("cmd.integrity_check", "数据完整性体检", "safe", ["read:integrity"],
         {"panel": "diagnostics", "action_label": "数据完整性体检"}),
    ]
    for cid, title, risk, perms, ui in commands:
        if extension_registry.get(cid) is None:
            extension_registry.register(
                ExtensionDescriptor(
                    id=cid, title=title, kind=ExtensionKind.COMMAND,
                    description=title, risk_level=risk, permissions=perms,
                    output_summary="触发对应 API 路由", ui_entry=ui,
                )
            )

    # ---- capture sources（对应 capture_source_enum）----
    capture_sources = [
        ("capture.manual", "手动输入"),
        ("capture.clipboard", "剪贴板"),
        ("capture.chat_message", "聊天消息"),
        ("capture.document_extraction", "文档抽取"),
        ("capture.file", "文件"),
        ("capture.web", "网页"),
    ]
    for cid, title in capture_sources:
        if extension_registry.get(cid) is None:
            extension_registry.register(
                ExtensionDescriptor(
                    id=cid, title=title, kind=ExtensionKind.CAPTURE_SOURCE,
                    description=f"捕获来源：{title}", risk_level="safe",
                    permissions=[], configurable=False,
                )
            )

    # ---- providers ----
    providers = [
        ("provider.ollama", "Ollama（本地）", "safe", []),
        ("provider.openai", "OpenAI 兼容（远程）", "confirm", ["remote_send"]),
        ("provider.claude", "Claude（远程）", "confirm", ["remote_send"]),
    ]
    for cid, title, risk, perms in providers:
        if extension_registry.get(cid) is None:
            extension_registry.register(
                ExtensionDescriptor(
                    id=cid, title=title, kind=ExtensionKind.PROVIDER,
                    description=title, risk_level=risk, permissions=perms,
                    output_summary="LLM / 嵌入调用", configurable=False,
                )
            )

    # ---- notification targets ----
    targets = [
        ("notify.toast", "应用内 toast", "safe"),
        ("notify.desktop", "桌面通知", "safe"),
    ]
    for cid, title, risk in targets:
        if extension_registry.get(cid) is None:
            extension_registry.register(
                ExtensionDescriptor(
                    id=cid, title=title, kind=ExtensionKind.NOTIFICATION_TARGET,
                    description=title, risk_level=risk, permissions=[],
                    configurable=False,
                )
            )


register_builtin_extensions()
