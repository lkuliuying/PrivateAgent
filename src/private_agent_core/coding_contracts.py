"""Coding 跨阶段 v1 纯契约的唯一类型源；业务接入由后续阶段完成。"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=128)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class CodingContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContentRef(CodingContract):
    """只接受内容寻址标识，不允许模型提供任意文件路径。"""
    sha256: Digest
    bytes: int = Field(ge=0)


class Requirement(CodingContract):
    requirement_id: Identifier
    description: str = Field(min_length=1, max_length=4000)
    required: bool = True



class VerificationResult(CodingContract):
    requirement_id: Identifier
    status: Literal["passed", "failed", "blocked", "unverified"]
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=128)


class RunOutcome(CodingContract):
    schema_version: Literal["1.0"] = "1.0"
    run_id: Identifier
    goal_outcome: Literal["answered", "verified", "unmet", "blocked", "unknown"]
    requirements: list[Requirement] = Field(default_factory=list, max_length=128)
    verification_results: list[VerificationResult] = Field(default_factory=list, max_length=128)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=256)
    unverified_items: list[str] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def validate_evidence(self):
        keys = [item.requirement_id for item in self.requirements]
        results = {item.requirement_id: item for item in self.verification_results}
        if len(keys) != len(set(keys)) or len(results) != len(self.verification_results):
            raise ValueError("要求与验证结果的标识必须唯一")
        if not set(results).issubset(keys):
            raise ValueError("验证结果必须关联当前要求")
        for item in self.verification_results:
            if not set(item.evidence_ids).issubset(self.evidence_ids):
                raise ValueError("验证证据必须在运行证据索引内")
            if item.status == "passed" and not item.evidence_ids:
                raise ValueError("通过的验证必须关联证据")
        if self.goal_outcome == "verified":
            required = [item.requirement_id for item in self.requirements if item.required]
            if not required or self.unverified_items or any(
                key not in results or results[key].status != "passed" for key in required
            ) or any(item.status == "failed" for item in self.verification_results):
                raise ValueError("已验证完成必须具有全部必要要求的通过证据，且无失败或未验证项")
        return self


class ExecutionResult(CodingContract):
    schema_version: Literal["1.0"] = "1.0"
    execution_id: Identifier
    operation_id: Identifier
    outcome: Literal["exited", "timed_out", "cancelled", "failed", "unknown"]
    exit_code: int | None = None
    output_ref: ContentRef | None = None

    @model_validator(mode="after")
    def validate_exit(self):
        if self.outcome == "exited" and self.exit_code is None:
            raise ValueError("正常退出必须记录真实退出码，包括非零退出码")
        if self.outcome == "unknown" and self.exit_code is not None:
            raise ValueError("未知结果不能推定退出码")
        return self


class EventEnvelope(CodingContract):
    schema_version: Literal["1.0"] = "1.0"
    run_id: Identifier
    sequence: int = Field(ge=1, le=9007199254740991)
    type: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,127}$")
    # 开放事件名用于后续兼容；具体事件载荷仍按对应类型验证。
    payload: dict = Field(default_factory=dict)


class ToolCapability(CodingContract):
    name: Identifier
    version: Identifier


class CapabilitySnapshot(CodingContract):
    protocol_version: Literal["1.0"] = "1.0"
    tools: list[ToolCapability] = Field(default_factory=list, max_length=128)
    execution: bool = False
    stdin: bool = False
    pty: bool = False
    model_streaming: bool = False
    output_streaming: bool = False
    recovery: bool = False

    @model_validator(mode="after")
    def validate_capabilities(self):
        if len({item.name for item in self.tools}) != len(self.tools):
            raise ValueError("工具能力名称不能重复")
        if (self.stdin or self.pty or self.output_streaming) and not self.execution:
            raise ValueError("终端能力依赖实际可用的执行能力")
        return self


class ContextItem(CodingContract):
    item_id: Identifier
    session_id: int = Field(ge=1)
    run_id: Identifier
    ordinal: int = Field(ge=1, le=9007199254740991)
    role: Literal["system", "user", "assistant", "tool"]
    kind: Literal["message", "instruction", "tool_call", "tool_result", "summary"]
    content_ref: ContentRef
    source: Literal["user", "project_instruction", "model", "tool", "summary", "legacy"]
    created_at: datetime
    tool_call_id: Identifier | None = None
    summary_of: list[Identifier] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def validate_source(self):
        if self.created_at.utcoffset() is None:
            raise ValueError("上下文时间必须包含时区")
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("工具上下文必须关联调用标识")
        if self.source == "summary" and not self.summary_of:
            raise ValueError("摘要必须保留来源条目标识")
        if self.source != "summary" and self.summary_of:
            raise ValueError("非摘要条目不能携带摘要来源列表")
        if (self.source == "summary") != (self.kind == "summary"):
            raise ValueError("摘要来源与条目种类必须一致")
        return self


class WorkspaceIdentity(CodingContract):
    project_id: int = Field(ge=1)
    workspace_id: int = Field(ge=1)
    root_path: str = Field(min_length=1, max_length=2048)
    canonical_path: str = Field(min_length=1, max_length=2048)
    git_available: bool
    initial_head: str | None = Field(default=None, pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    initial_dirty: bool | None = None

    @model_validator(mode="after")
    def validate_git(self):
        if not self.git_available and (self.initial_head is not None or self.initial_dirty is not None):
            raise ValueError("Git 不可用时不能编造初始状态")
        return self


CONTRACTS = (RunOutcome, ExecutionResult, EventEnvelope, CapabilitySnapshot, ContextItem, WorkspaceIdentity)
