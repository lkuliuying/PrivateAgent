"""Bounded, evidence-based output verification for AgentRuntime."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, ClassVar, Protocol

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from .contracts import ModelOutputFormat


class OutputVerification(BaseModel):
    """One verifier decision; text is bounded before it enters events/prompts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    code: str = Field(pattern=r"^[a-z0-9_]{1,64}$")
    message: str = Field(min_length=1, max_length=2_000)
    correction: str | None = Field(default=None, max_length=4_000)


class OutputVerifier(Protocol):
    name: str
    output_schema: dict[str, Any] | None

    async def verify(self, output: str, *, attempt: int) -> OutputVerification: ...


class NonEmptyOutputVerifier:
    name = "non_empty"
    output_schema = None

    async def verify(self, output: str, *, attempt: int) -> OutputVerification:
        del attempt
        if output.strip():
            return OutputVerification(
                passed=True,
                code="ok",
                message="Output is non-empty.",
            )
        return OutputVerification(
            passed=False,
            code="empty_output",
            message="The model returned an empty output.",
            correction="Return a concrete final answer instead of an empty response.",
        )


class JsonSchemaOutputVerifier:
    """Require the model output to be JSON accepted by a fixed Draft 2020-12 schema."""

    name = "json_schema"

    def __init__(self, schema: dict[str, Any]) -> None:
        if not isinstance(schema, dict):
            raise TypeError("JSON output schema must be an object")
        try:
            copied = json.loads(
                json.dumps(
                    schema,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("JSON output schema must be serializable") from exc
        try:
            output_format = ModelOutputFormat(json_schema=copied)
        except ValueError as exc:
            raise ValueError("JSON output schema is invalid or unsafe") from exc
        self.output_schema = output_format.json_schema
        self._validator = Draft202012Validator(copied)

    async def verify(self, output: str, *, attempt: int) -> OutputVerification:
        del attempt
        try:
            value = json.loads(output)
        except json.JSONDecodeError as exc:
            return OutputVerification(
                passed=False,
                code="invalid_json",
                message=(
                    f"Output is not valid JSON at line {exc.lineno}, column {exc.colno}."
                ),
                correction=(
                    "Return only one valid JSON value. Do not wrap it in Markdown fences "
                    "or add explanatory text."
                ),
            )
        error = next(self._validator.iter_errors(value), None)
        if error is None:
            return OutputVerification(
                passed=True,
                code="ok",
                message="Output matches the required JSON Schema.",
            )
        path = "$" + "".join(
            f"[{item}]" if isinstance(item, int) else f".{item}"
            for item in error.absolute_path
        )
        rule = str(error.validator or "schema")[:64]
        message = f"JSON Schema validation failed at {path} (rule: {rule})."
        return OutputVerification(
            passed=False,
            code="json_schema_mismatch",
            message=message[:2_000],
            correction=(
                "Return only JSON that matches the required schema. Correct the field at "
                f"{path} and preserve already valid fields."
            )[:4_000],
        )


class RagCitationSource(BaseModel):
    """One trusted retrieval result available to citation verification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: int = Field(gt=0)
    index_version_id: str | None = Field(default=None, min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=1_000_000, repr=False)
    doc_name: str | None = Field(default=None, min_length=1, max_length=512)
    ordinal: int | None = Field(default=None, ge=0)
    heading: str | None = Field(default=None, max_length=512)
    score: float | None = None
    fusion_score: float | None = None
    bm25_score: float | None = None
    rerank_score: float | None = None
    matched_via: tuple[str, ...] = Field(default=(), max_length=10)
    matched_keywords: tuple[str, ...] = Field(default=(), max_length=20)


class RagCitationOutputVerifier:
    """Validate citation identity and verbatim support against retrieved chunks.

    This deliberately verifies traceability, not the truth of every natural-language
    inference in ``answer``.
    """

    name = "rag_citations"
    _schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "minLength": 1, "maxLength": 100_000},
            "citations": {
                "type": "array",
                "maxItems": 32,
                "items": {
                    "type": "object",
                    "properties": {
                        "chunk_id": {"type": "integer", "minimum": 1},
                        "index_version_id": {
                            "type": ["string", "null"],
                            "minLength": 1,
                            "maxLength": 64,
                        },
                        "quote": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 2_000,
                        },
                    },
                    "required": ["chunk_id", "index_version_id", "quote"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["answer", "citations"],
        "additionalProperties": False,
    }
    output_schema: ClassVar[dict[str, Any]] = _schema

    def __init__(
        self,
        sources: list[RagCitationSource] | tuple[RagCitationSource, ...],
    ) -> None:
        if len(sources) > 128:
            raise ValueError("RAG citation verifier accepts at most 128 sources")
        if sum(len(source.content) for source in sources) > 2 * 1024 * 1024:
            raise ValueError("RAG citation verifier source content exceeds 2 MiB")
        indexed: dict[tuple[str | None, int], RagCitationSource] = {}
        for source in sources:
            key = (source.index_version_id, source.chunk_id)
            if key in indexed:
                raise ValueError("RAG citation verifier sources must be unique")
            indexed[key] = source
        self._sources = indexed
        self._validator = Draft202012Validator(self._schema)

    async def verify(self, output: str, *, attempt: int) -> OutputVerification:
        del attempt
        try:
            value = json.loads(output)
        except json.JSONDecodeError as exc:
            return OutputVerification(
                passed=False,
                code="invalid_json",
                message=(
                    f"Citation output is not valid JSON at line {exc.lineno}, "
                    f"column {exc.colno}."
                ),
                correction=(
                    "Return only the required answer/citations JSON object without "
                    "Markdown fences or explanatory text."
                ),
            )
        error = next(self._validator.iter_errors(value), None)
        if error is not None:
            path = "$" + "".join(
                f"[{item}]" if isinstance(item, int) else f".{item}"
                for item in error.absolute_path
            )
            rule = str(error.validator or "schema")[:64]
            return OutputVerification(
                passed=False,
                code="citation_schema_mismatch",
                message=f"Citation schema failed at {path} (rule: {rule})."[:2_000],
                correction=(
                    "Return an answer string and citations array. Each citation needs "
                    "chunk_id, index_version_id, and an exact quote."
                ),
            )

        citations = value["citations"]
        if self._sources and not citations:
            return OutputVerification(
                passed=False,
                code="missing_citations",
                message="Retrieved evidence exists but the answer has no citations.",
                correction="Cite at least one retrieved chunk with an exact quote.",
            )

        seen: set[tuple[str | None, int]] = set()
        for citation in citations:
            key = (citation["index_version_id"], citation["chunk_id"])
            if key in seen:
                return OutputVerification(
                    passed=False,
                    code="duplicate_citation",
                    message="The citation list contains a duplicate source identity.",
                    correction="Include each source identity at most once.",
                )
            seen.add(key)
            source = self._sources.get(key)
            if source is None:
                return OutputVerification(
                    passed=False,
                    code="unknown_citation",
                    message="A citation does not match any retrieved source identity.",
                    correction=(
                        "Use only chunk_id/index_version_id pairs supplied by retrieval."
                    ),
                )
            quote = citation["quote"]
            if quote != quote.strip() or quote not in source.content:
                return OutputVerification(
                    passed=False,
                    code="unsupported_quote",
                    message="A citation quote is not an exact substring of its source.",
                    correction=(
                        "Copy a bounded verbatim quote from the cited chunk without "
                        "adding or removing characters."
                    ),
                )
        return OutputVerification(
            passed=True,
            code="ok",
            message="Every citation identity and quote matches retrieved evidence.",
        )


RagCitationSourceLoader = Callable[
    [], Awaitable[Sequence[RagCitationSource]]
]


class ReloadingRagCitationOutputVerifier:
    """Reload trusted, durable retrieval evidence before each verification."""

    name = "rag_citations"
    output_schema: ClassVar[dict[str, Any]] = RagCitationOutputVerifier.output_schema

    def __init__(self, source_loader: RagCitationSourceLoader) -> None:
        if not callable(source_loader):
            raise TypeError("RAG citation source loader must be callable")
        self._source_loader = source_loader

    async def verify(self, output: str, *, attempt: int) -> OutputVerification:
        try:
            sources = tuple(await self._source_loader())
            verifier = RagCitationOutputVerifier(sources)
        except Exception:
            return OutputVerification(
                passed=False,
                code="citation_evidence_unavailable",
                message="Trusted RAG citation evidence could not be loaded.",
                correction=(
                    "Do not invent citations. Retry only after the trusted retrieval "
                    "evidence is available."
                ),
            )
        return await verifier.verify(output, attempt=attempt)


class CompositeOutputVerifier:
    """Run independent real validators in order and stop on the first failure."""

    name = "composite"

    def __init__(self, verifiers: list[OutputVerifier] | tuple[OutputVerifier, ...]) -> None:
        if not verifiers:
            raise ValueError("Composite verifier requires at least one verifier")
        self._verifiers = tuple(verifiers)
        schemas = [
            verifier.output_schema
            for verifier in self._verifiers
            if verifier.output_schema is not None
        ]
        self.output_schema = (
            schemas[0]
            if schemas and all(schema == schemas[0] for schema in schemas[1:])
            else None
        )

    async def verify(self, output: str, *, attempt: int) -> OutputVerification:
        for verifier in self._verifiers:
            result = await verifier.verify(output, attempt=attempt)
            if not result.passed:
                return result.model_copy(
                    update={
                        "message": f"{verifier.name}: {result.message}"[:2_000]
                    }
                )
        return OutputVerification(
            passed=True,
            code="ok",
            message="All configured output verifiers passed.",
        )


# ============ v0.5.0 B5：多步骤工作流完成条件 ============


class WorkflowCompletionFacts(BaseModel):
    """Durable tool execution facts evaluated by the completion verifier."""

    model_config = ConfigDict(extra="forbid")

    executions: list[dict[str, Any]] = Field(default_factory=list, max_length=256)
    # E3（E0 §7）：PatchSet 未决事实（{id, status} 摘要）
    patch_sets: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    # E3：最终 Git Diff 是否为空（None = 非 git 目录，不可判定）
    git_diff_empty: bool | None = None


WorkflowCompletionFactLoader = Callable[[], Awaitable[WorkflowCompletionFacts]]


class WorkflowCompletionOutputVerifier:
    """v0.5.0 B5：多步骤工作流的可信完成条件验证。

    完成条件由可信调用方（run 创建方）固定注入，模型不能通过自由填写
    "完成"宣称完成。验证基于 durable executions 事实：

    - ``must_succeed_tools``：这些工具必须存在 succeeded 执行；
    - ``max_failed_tools``：允许的失败工具数上限（默认 0）；
    - ``require_verified``：存在 ``verified`` 字段的工具必须为 True；
    - ``must_pass_command_profiles``（E3/E0 §7）：这些命令 profile 必须
      存在 succeeded 且 ``profile`` 匹配的执行（命令输出事实）；
    - ``no_pending_patchsets``（E3/E0 §7）：run 不得存在未决（previewed）
      PatchSet；
    - ``final_git_diff``（E3/E0 §7）：any/nonempty/empty——最终 Git Diff
      判定基于 workspace 当前 dirty 状态；非 git 目录时 nonempty/empty
      不可判定即失败关闭。

    条件未满足 → run 以 output_validation_failed 失败关闭，不进入 completed。
    """

    name = "workflow_completion"
    output_schema: ClassVar[dict[str, Any] | None] = None

    def __init__(
        self,
        fact_loader: WorkflowCompletionFactLoader,
        *,
        must_succeed_tools: tuple[str, ...] = (),
        max_failed_tools: int = 0,
        require_verified: bool = False,
        must_pass_command_profiles: tuple[str, ...] = (),
        no_pending_patchsets: bool = False,
        final_git_diff: str = "any",
    ) -> None:
        if not callable(fact_loader):
            raise TypeError("workflow completion fact loader must be callable")
        if max_failed_tools < 0:
            raise ValueError("max_failed_tools must be non-negative")
        if final_git_diff not in {"any", "nonempty", "empty"}:
            raise ValueError("final_git_diff must be any|nonempty|empty")
        self._loader = fact_loader
        self._must_succeed = tuple(must_succeed_tools)
        self._max_failed = int(max_failed_tools)
        self._require_verified = bool(require_verified)
        self._must_pass_profiles = tuple(must_pass_command_profiles)
        self._no_pending_patchsets = bool(no_pending_patchsets)
        self._final_git_diff = final_git_diff

    async def verify(self, output: str, *, attempt: int) -> OutputVerification:
        del output, attempt
        try:
            facts = await self._loader()
        except Exception:  # noqa: BLE001
            return OutputVerification(
                passed=False,
                code="completion_evidence_unavailable",
                message="多步骤工作流完成条件证据不可用。",
                correction="确认执行事实持久化后重试，不要宣称已完成。",
            )
        by_tool: dict[str, list[dict[str, Any]]] = {}
        for execution in facts.executions:
            name = str(execution.get("tool_name") or "")
            by_tool.setdefault(name, []).append(execution)

        unmet: list[str] = []
        for tool_name in self._must_succeed:
            records = by_tool.get(tool_name, [])
            if not any(record.get("status") == "succeeded" for record in records):
                unmet.append(f"{tool_name} 无 succeeded 执行")
        failed_count = sum(
            1
            for records in by_tool.values()
            for record in records
            if record.get("status") in {"failed", "timed_out", "cancelled"}
        )
        if failed_count > self._max_failed:
            unmet.append(f"失败工具数 {failed_count} 超过上限 {self._max_failed}")
        if self._require_verified:
            # 只有 succeeded 且显式声明 verified=False 的工具被拒绝（缺失该
            # 字段的工具无回读验证语义，不检查）；失败工具由 max_failed 覆盖。
            unverified = [
                f"{record.get('tool_name')}({record.get('status')})"
                for records in by_tool.values()
                for record in records
                if record.get("status") == "succeeded"
                and record.get("verified") is False
            ]
            if unverified:
                unmet.append("存在未通过回读验证的工具：" + ", ".join(unverified[:5]))
        # E3（E0 §7）：必须通过的命令 profile（命令输出事实，不信任模型文本）
        for profile_name in self._must_pass_profiles:
            passed = any(
                record.get("status") == "succeeded"
                and record.get("profile") == profile_name
                for record in facts.executions
            )
            if not passed:
                unmet.append(f"命令 profile {profile_name} 无 succeeded 执行")
        # E3（E0 §7）：不得存在未决 PatchSet（previewed = 已预览未应用/未决）
        if self._no_pending_patchsets:
            pending = [
                str(item.get("status"))
                for item in facts.patch_sets
                if item.get("status") == "previewed"
            ]
            if pending:
                unmet.append(f"存在 {len(pending)} 个未决 PatchSet（预览未应用）")
        # E3（E0 §7）：最终 Git Diff 要求（nonempty/empty；非 git 不可判定）
        if self._final_git_diff != "any":
            if facts.git_diff_empty is None:
                unmet.append("无法判定最终 Git Diff（非 git 目录）")
            elif self._final_git_diff == "nonempty" and facts.git_diff_empty:
                unmet.append("最终 Git Diff 为空，但条件要求非空")
            elif self._final_git_diff == "empty" and not facts.git_diff_empty:
                unmet.append("最终 Git Diff 非空，但条件要求为空")
        if unmet:
            return OutputVerification(
                passed=False,
                code="completion_not_met",
                message="工作流完成条件未满足：" + "；".join(unmet)[:2_000],
                correction="继续执行未完成步骤或修正失败工具后重试。",
            )
        return OutputVerification(
            passed=True,
            code="ok",
            message="工作流完成条件已满足（工具执行事实核对通过）。",
        )
