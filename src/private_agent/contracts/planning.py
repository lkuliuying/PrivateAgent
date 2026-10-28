"""本地任务计划的纯契约；计划进度不构成执行授权或验收证据。"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PlanStatus = Literal["pending", "in_progress", "completed", "blocked", "failed", "cancelled"]
TRANSITIONS = {
    "pending": {"in_progress", "cancelled"},
    "in_progress": {"completed", "blocked", "failed", "cancelled"},
    "blocked": {"in_progress", "failed", "cancelled"},
    "completed": set(), "failed": set(), "cancelled": set(),
}


class PlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    item_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,127}$")
    title: str = Field(min_length=1, max_length=512)
    status: PlanStatus = "pending"
    detail: str = Field(default="", max_length=1200)
    requirement_ids: list[str] = Field(default_factory=list, max_length=32)
    evidence_calls: list[str] = Field(default_factory=list, max_length=16)
    supersedes: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_references(self):
        for values in (self.requirement_ids, self.evidence_calls, self.supersedes):
            if len(set(values)) != len(values) or any(not value or len(value) > 128 for value in values):
                raise ValueError("计划引用必须是唯一的非空标识，最长 128 字符")
        return self


class PlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    expected_plan_version: int = Field(ge=0)
    goal_version: int = Field(ge=1)
    explanation: str = Field(default="", max_length=1200)
    items: list[PlanItem] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_items(self):
        if len(json.dumps(self.model_dump(), ensure_ascii=False).encode("utf-8")) > 16000:
            raise ValueError("计划超过 16000 字节，请保留简明步骤和必要引用")
        if len({item.item_key for item in self.items}) != len(self.items):
            raise ValueError("计划步骤标识不能重复")
        if sum(item.status == "in_progress" for item in self.items) > 1:
            raise ValueError("计划同时最多有一个进行中的步骤")
        earlier = {}
        for item in self.items:
            for key in item.supersedes:
                failed = earlier.get(key)
                if failed is None or failed.status != "failed":
                    raise ValueError("补救步骤只能关联排在前面的失败步骤")
                if not set(failed.requirement_ids).issubset(item.requirement_ids):
                    raise ValueError("补救步骤必须保留失败步骤的验收要求")
            earlier[item.item_key] = item
        return self


def validate_transition(previous: list[dict], items: list[PlanItem]) -> None:
    """保留既有步骤；撤销以 cancelled 表达，终态不能被重新打开或改名。"""
    incoming = {item.item_key: item for item in items}
    for old in previous:
        item = incoming.get(old["item_key"])
        if item is None:
            raise ValueError("不能删除已有计划步骤；请明确取消尚未结束的步骤")
        status = old["status"]
        if item.status != status and item.status not in TRANSITIONS[status]:
            raise ValueError(f"不允许计划状态转换：{status} -> {item.status}")
        if status in {"completed", "failed", "cancelled"} and (
            item.title != old["title"] or item.requirement_ids != old.get("requirement_ids", [])
            or item.supersedes != old.get("supersedes", [])
            or not set(old.get("evidence_calls", [])).issubset(item.evidence_calls)
        ):
            raise ValueError("已结束步骤的标题、关联要求和既有证据不可覆盖；请新增后续步骤")


class QuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=400)


class UserQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    question: str = Field(min_length=1, max_length=1000)
    options: list[QuestionOption] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_options(self):
        if len({option.label for option in self.options}) != len(self.options):
            raise ValueError("问题的选项不能重复")
        return self


class UserInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    questions: list[UserQuestion] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_questions(self):
        if len({question.id for question in self.questions}) != len(self.questions):
            raise ValueError("问题标识不能重复")
        return self
