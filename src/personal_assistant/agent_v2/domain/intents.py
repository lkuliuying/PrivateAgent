"""ExecutionIntent 领域契约（专项计划 §7.4 / CT1-02）。

规则层先识别明确动作并冻结 required effects；可选的模型分类只能补充 tag，
不能降低规则层结论（``merge_model_tags`` 只增不减）。用户明确"仅解释、
仅预览、不执行"时，文件写入副作用要求被清除（F-008）。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .effects import EffectClass


class IntentTag(StrEnum):
    """P0 意图 tag（专项计划 §7.4 冻结集合）。"""

    ANSWER_ONLY = "answer.only"
    CODE_INSPECT = "code.inspect"
    FILE_PREVIEW = "file.preview"
    FILE_MUTATE = "file.mutate"
    COMMAND_RUN = "command.run"
    COMMAND_TEST = "command.test"
    NETWORK_READ = "network.read"
    NETWORK_WRITE = "network.write"
    DATABASE_READ = "database.read"
    EXTERNAL_MCP = "external.mcp"


# 规则层：tag → 完成任务所需的最小成功副作用集合。P0 只有 file.mutate
# 强制成功落盘；其余 tag 的"必须动过工具"语义由 CompletionContract 的
# minimum_evidence_count 表达（失败命令也是证据）。
_TAG_REQUIRED_EFFECTS: dict[IntentTag, frozenset[EffectClass]] = {
    IntentTag.FILE_MUTATE: frozenset({EffectClass.FILESYSTEM_WRITE}),
}


def required_effects_for_tags(tags: frozenset[IntentTag]) -> frozenset[EffectClass]:
    effects: set[EffectClass] = set()
    for tag in tags:
        effects |= _TAG_REQUIRED_EFFECTS.get(tag, frozenset())
    return frozenset(effects)


class ExecutionIntent(BaseModel):
    """一轮请求的可执行意图（不可变）。

    ``required_effects`` 在构造时由规则层从 tags 派生并冻结，外部不能
    直接注入更小的集合——这是"误判只会要求更多证据、绝不授予额外能力"
    的结构保证。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tags: frozenset[IntentTag]
    required_effects: frozenset[EffectClass]
    preview_only: bool = False
    rule_source: str = Field(default="heuristic.v0", max_length=64)
    model_added_tags: frozenset[IntentTag] = frozenset()

    @field_validator("tags")
    @classmethod
    def _non_empty_tags(cls, value: frozenset[IntentTag]) -> frozenset[IntentTag]:
        if not value:
            raise ValueError("ExecutionIntent.tags 不能为空（至少含 answer.only）")
        return value

    @classmethod
    def from_tags(
        cls,
        tags: frozenset[IntentTag],
        *,
        preview_only: bool = False,
    ) -> "ExecutionIntent":
        return cls(
            tags=frozenset(tags),
            required_effects=required_effects_for_tags(frozenset(tags)),
            preview_only=preview_only,
        )

    @classmethod
    def answer_only(cls) -> "ExecutionIntent":
        return cls.from_tags(frozenset({IntentTag.ANSWER_ONLY}))

    def merge_model_tags(self, extra_tags: frozenset[IntentTag]) -> "ExecutionIntent":
        """模型分类只能补充 tag；required effects 只增不减（§7.4）。"""
        added = frozenset(extra_tags) - self.tags
        merged = self.tags | added
        return ExecutionIntent(
            tags=merged,
            required_effects=required_effects_for_tags(merged)
            | self.required_effects,
            preview_only=self.preview_only,
            model_added_tags=added,
        )

    @property
    def requires_file_write(self) -> bool:
        return EffectClass.FILESYSTEM_WRITE in self.required_effects

    @property
    def is_executable(self) -> bool:
        return self.tags != {IntentTag.ANSWER_ONLY}
