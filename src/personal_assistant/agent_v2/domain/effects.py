"""Effect 与 Evidence 领域契约（专项计划 §7.6 / ADR-007）。

红线：
- Effect 是工具执行留下的规范化副作用事实；Evidence 是可信 verifier 对
  事实的确认。模型文本声明永远不是事实来源；
- 本模块是纯领域模型：禁止导入 FastAPI/SQLAlchemy/Provider SDK 与任何
  实现层（scripts/check_agent_v2_imports.py 强制）。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EffectClass(StrEnum):
    """规范化副作用类别（专项计划 §7.6 冻结集合）。"""

    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    FILESYSTEM_DELETE = "filesystem.delete"
    FILESYSTEM_RENAME = "filesystem.rename"
    PROCESS_SPAWN = "process.spawn"
    PROCESS_EXIT = "process.exit"
    NETWORK_REQUEST = "network.request"
    DATABASE_QUERY = "database.query"
    VERIFICATION_PASS = "verification.pass"


# 落盘类副作用：完成证据必须带 verified=True 的回读确认（ADR-007 §1-2）。
DISK_MUTATING_EFFECTS: frozenset[EffectClass] = frozenset(
    {
        EffectClass.FILESYSTEM_WRITE,
        EffectClass.FILESYSTEM_DELETE,
        EffectClass.FILESYSTEM_RENAME,
    }
)


class EffectRecord(BaseModel):
    """一条工具执行的副作用证据记录。

    由可信代码从 durable execution 事实投影而来（不是模型输出）：

    - ``status`` 取 durable execution 的终态
      （succeeded/failed/timed_out/cancelled/unknown）；
    - ``effects`` 是该工具按冻结契约表声明的副作用类别；未知/未分类工具为
      空集——仍可充当"执行过工具"的证据，但不满足任何 required effect；
    - ``verified`` 是磁盘回读等结果验证器的结论；写入类 effect 只有
      ``verified is True`` 才构成完成证据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=32)
    effects: tuple[EffectClass, ...] = ()
    verified: bool | None = None

    def is_terminal(self) -> bool:
        return self.status in {
            "succeeded",
            "failed",
            "timed_out",
            "cancelled",
        }

    def satisfies_effect(self, effect: EffectClass) -> bool:
        """本记录是否构成 ``effect`` 的成功完成证据（失败关闭）。"""
        if self.status != "succeeded":
            return False
        if effect not in self.effects:
            return False
        if self.verified is False:
            # 可信 verifier 显式判定未通过：任何 effect 都不采信。
            return False
        if effect in DISK_MUTATING_EFFECTS and self.verified is not True:
            # 落盘类副作用必须拿到显式回读确认，缺失即不采信。
            return False
        return True
