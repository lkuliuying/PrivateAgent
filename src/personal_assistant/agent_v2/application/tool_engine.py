"""统一 Tool Lifecycle 引擎（专项计划 §6.2/CT-4/AD-T01/AD-T07）。

把 v0.9 ``ValidatedToolDispatcher`` 的单类编排拆分为显式端口：

    Router → Policy Gate → Approval → Execution Lease → Handler
      → Output Bounds → Result Verifier → Persistence

设计约束（计划书 §6.1/§6.2）：
- 生命周期的每一步产生低敏感、可关联的 :class:`ToolStageRecord`；
  任何异常不得直接转为 success=true；
- pre/post 内部钩子只读观察阶段上下文，返回值被忽略、不能授予权限
  （上下文为 frozen 模型，钩子异常按执行失败关闭）；
- 与 v0.9 dispatcher 的语义兼容由金标等价测试钉住
  （风险表"双实现漂移"缓解：adapter + golden tests；S7 完成单执行器收敛）。

本模块是纯应用层编排：不导入 FastAPI/SQLAlchemy/Provider SDK。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..domain.error_codes import ToolErrorCode
from .catalog import canonical_json

# ===========================================================================
# 阶段模型
# ===========================================================================


class LifecycleStage(StrEnum):
    """§6.2 生命周期阶段（顺序即枚举声明顺序）。"""

    ROUTE = "route"
    POLICY = "policy"
    APPROVAL = "approval"
    INPUT_VALIDATION = "input_validation"
    LEASE = "lease"
    EXECUTION = "execution"
    OUTPUT_VALIDATION = "output_validation"
    VERIFICATION = "verification"
    PERSISTENCE = "persistence"


class StageOutcome(StrEnum):
    OK = "ok"
    ERROR = "error"


class ToolStageRecord(BaseModel):
    """一步的低敏感状态记录（不含参数正文/输出正文/secret）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: LifecycleStage
    outcome: StageOutcome
    error_code: str | None = Field(default=None, max_length=64)


class ToolCallView(Protocol):
    """一次工具调用的最小视图。"""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """引擎终态（与 v0.9 ToolResult 字段语义对齐）。"""

    tool_call_id: str
    name: str
    success: bool
    output: Any = None
    error: str | None = None
    error_code: str | None = None
    approval_id: str | None = None
    stages: tuple[ToolStageRecord, ...] = ()

    def stage_codes(self) -> tuple[str, ...]:
        return tuple(f"{rec.stage.value}:{rec.outcome.value}" for rec in self.stages)


class LifecycleContext(BaseModel):
    """传给内部钩子的只读快照（frozen——钩子不能改写任何决策输入）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_call_id: str
    tool_name: str
    stage: LifecycleStage
    ok: bool
    error_code: str | None = None


class LifecycleHook(Protocol):
    """pre/post 内部钩子（§15 CT-4）：只能观察，不能授权/改参。"""

    def on_stage(self, context: LifecycleContext) -> None: ...


def _record(stage: LifecycleStage, error_code: str | None) -> ToolStageRecord:
    if error_code is None:
        return ToolStageRecord(stage=stage, outcome=StageOutcome.OK)
    return ToolStageRecord(
        stage=stage, outcome=StageOutcome.ERROR, error_code=error_code
    )


# ===========================================================================
# 端口
# ===========================================================================


class EngineToolView(Protocol):
    """一个活跃工具版本的引擎视图（适配层从 v0.9 ToolSpec 投影）。"""

    name: str
    version: str
    max_input_bytes: int
    max_output_bytes: int
    idempotent: bool

    def validate_input(self, arguments: Mapping[str, Any]) -> str | None:
        """返回 schema 错误描述或 None。"""

    def validate_output(self, output: Any) -> str | None: ...
    def redact_output(self, output: Any) -> Any: ...

    async def invoke_with_bounds(
        self,
        arguments: dict[str, Any],
        cancellation: "EngineCancellationToken",
    ) -> Any:
        """在超时/取消边界内调用 handler；超时抛 TimeoutError，
        取消抛 ToolDispatchCancelledError。"""


class ToolDispatchCancelledError(RuntimeError):
    """取消先于结果发布（与 v0.9 ToolDispatchCancelled 对齐）。"""


class EngineCancellationToken(Protocol):
    @property
    def is_cancelled(self) -> bool: ...

    async def wait(self) -> Any: ...

    def raise_if_cancelled(self) -> None: ...


class ToolRouterPort(Protocol):
    def resolve(self, name: str) -> EngineToolView | None: ...


class PolicyDecision(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class PolicyGatePort(Protocol):
    def decide(self, tool: EngineToolView) -> PolicyDecision: ...


class ApprovalPort(Protocol):
    async def consume(
        self, tool: EngineToolView, call: ToolCallView, arguments: Mapping[str, Any]
    ) -> str | None: ...

    async def request(
        self, tool: EngineToolView, call: ToolCallView, arguments: Mapping[str, Any]
    ) -> str: ...


class LeaseClaimAction(StrEnum):
    EXECUTE = "execute"
    CACHED = "cached"
    IN_PROGRESS = "in_progress"
    UNKNOWN = "unknown"


class LeaseClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: LeaseClaimAction
    execution_id: str | None = None
    claim_token: str | None = None
    cached_output: Any = None


class ExecutionLeasePort(Protocol):
    async def claim(
        self,
        tool: EngineToolView,
        call: ToolCallView,
        arguments: Mapping[str, Any],
        *,
        approval_id: str | None,
    ) -> LeaseClaim: ...

    async def complete_success(
        self,
        execution_id: str,
        *,
        claim_token: str,
        output: Any,
        max_output_bytes: int,
    ) -> None: ...

    async def complete_failure(
        self,
        execution_id: str,
        *,
        claim_token: str,
        status: str,
        error_code: str,
        error_message: str,
    ) -> None: ...


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    code: str = Field(pattern=r"^[a-z0-9_]{1,64}$")
    message: str = Field(min_length=1, max_length=2_000)


class ResultVerifierPort(Protocol):
    def supports(self, tool_name: str) -> bool: ...

    async def verify(
        self, tool_name: str, arguments: Mapping[str, Any], output: Any
    ) -> VerificationResult: ...


_MAX_ERROR_CHARS = 2_000


def _redact_text(value: str) -> str:
    """与 v0.9 同口径的秘密文本脱敏 + 截断。"""
    import re

    patterns = (
        re.compile(r"(?i)(bearer\s+)[^\s,;]+"),
        re.compile(r"(?i)((?:api[_-]?key|password|secret|token)\s*[:=]\s*)[^\s,;]+"),
    )
    redacted = value
    for pattern in patterns:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted[:_MAX_ERROR_CHARS]


# ===========================================================================
# 引擎
# ===========================================================================


class LifecycleToolEngine:
    """所有工具类别走同一条生命周期路径；副作用工具并发数恒为 1
    （并发见 read_only_scheduler，仅 AD-T07 合格工具可并行）。"""

    def __init__(
        self,
        router: ToolRouterPort,
        policy: PolicyGatePort,
        *,
        approvals: ApprovalPort | None = None,
        lease: ExecutionLeasePort | None = None,
        verifier: ResultVerifierPort | None = None,
        hooks: tuple[LifecycleHook, ...] = (),
        local_cache_capacity: int = 128,
    ) -> None:
        self._router = router
        self._policy = policy
        self._approvals = approvals
        self._lease = lease
        self._verifier = verifier
        self._hooks = tuple(hooks)
        self._cache: dict[str, Any] = {}
        self._cache_order: list[str] = []
        if local_cache_capacity < 1:
            raise ValueError("local_cache_capacity must be >= 1")
        self._cache_capacity = local_cache_capacity

    # ---- 基础设施 -------------------------------------------------------

    def _notify(
        self,
        view: EngineToolView | None,
        call: ToolCallView,
        stage: LifecycleStage,
        ok: bool,
        error_code: str | None,
    ) -> None:
        if not self._hooks:
            return
        context = LifecycleContext(
            tool_call_id=call.id,
            tool_name=view.name if view is not None else call.name,
            stage=stage,
            ok=ok,
            error_code=error_code,
        )
        for hook in self._hooks:
            try:
                hook.on_stage(context)
            except Exception:  # noqa: BLE001 - 钩子异常不得改变执行语义
                continue

    @staticmethod
    def _json_clone(value: Any) -> Any:
        return json.loads(
            json.dumps(
                value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            )
        )

    def _remember(self, key: str, output: Any) -> None:
        self._cache[key] = deepcopy(output)
        self._cache_order.append(key)
        if len(self._cache_order) > self._cache_capacity:
            stale = self._cache_order.pop(0)
            self._cache.pop(stale, None)

    def _failure(
        self,
        call: ToolCallView,
        stages: list[ToolStageRecord],
        code: str,
        message: str,
        *,
        stage: LifecycleStage,
        approval_id: str | None = None,
    ) -> ExecutionOutcome:
        stages.append(_record(stage, code))
        self._notify(None, call, stage, False, code)
        return ExecutionOutcome(
            tool_call_id=call.id,
            name=call.name,
            success=False,
            error=_redact_text(message),
            error_code=code,
            approval_id=approval_id,
            stages=tuple(stages),
        )

    # ---- 主路径 ---------------------------------------------------------

    async def execute(
        self,
        call: ToolCallView,
        *,
        cancellation: EngineCancellationToken,
    ) -> ExecutionOutcome:
        stages: list[ToolStageRecord] = []

        def ok_stage(view_: EngineToolView | None, stage: LifecycleStage) -> None:
            stages.append(_record(stage, None))
            self._notify(view_, call, stage, True, None)

        # 1. Router
        view = self._router.resolve(call.name)
        if view is None:
            return self._failure(call, stages, "unknown_tool", "工具未注册",
                                 stage=LifecycleStage.ROUTE)
        ok_stage(view, LifecycleStage.ROUTE)

        # 2. Policy Gate
        decision = self._policy.decide(view)
        if decision == PolicyDecision.DENY:
            return self._failure(
                call,
                stages,
                ToolErrorCode.TOOL_HIDDEN_BY_POLICY,
                "工具能力未获授权",
                stage=LifecycleStage.POLICY,
            )
        ok_stage(view, LifecycleStage.POLICY)

        # 3. Input validation（先于审批消费，避免无效参数烧审批 token）
        try:
            canonical_arguments = self._json_clone(call.arguments)
            input_size = len(
                json.dumps(
                    canonical_arguments,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        except (TypeError, ValueError, RecursionError):
            return self._failure(call, stages, "input_not_json", "工具参数必须是有效 JSON",
                                 stage=LifecycleStage.INPUT_VALIDATION)
        if input_size > view.max_input_bytes:
            return self._failure(call, stages, "input_too_large", "工具参数超过大小上限",
                                 stage=LifecycleStage.INPUT_VALIDATION)
        input_error = view.validate_input(canonical_arguments)
        if input_error is not None:
            return self._failure(call, stages, "input_schema_invalid",
                                 _redact_text(input_error),
                                 stage=LifecycleStage.INPUT_VALIDATION)
        ok_stage(view, LifecycleStage.INPUT_VALIDATION)

        # 4. Approval
        consumed_approval_id: str | None = None
        if decision == PolicyDecision.REQUIRE_APPROVAL and self._approvals is not None:
            try:
                consumed = await self._approvals.consume(view, call, canonical_arguments)
                if consumed is not None:
                    if not isinstance(consumed, str) or not 1 <= len(consumed) <= 36:
                        raise ValueError("approval consumer returned an invalid id")
                    consumed_approval_id = consumed
                    decision = PolicyDecision.ALLOW
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                return self._failure(call, stages, "approval_consume_failed",
                                     str(exc) or type(exc).__name__,
                                     stage=LifecycleStage.APPROVAL)
        if decision == PolicyDecision.REQUIRE_APPROVAL:
            if self._approvals is None:
                return self._failure(call, stages, "approval_unavailable",
                                     "工具需要审批，但当前运行未配置安全审批通道",
                                     stage=LifecycleStage.APPROVAL)
            try:
                approval_id = await self._approvals.request(
                    view, call, canonical_arguments
                )
                if not isinstance(approval_id, str) or not 1 <= len(approval_id) <= 36:
                    raise ValueError("approval requester returned an invalid id")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                return self._failure(call, stages, "approval_persistence_failed",
                                     str(exc) or type(exc).__name__,
                                     stage=LifecycleStage.APPROVAL)
            return self._failure(call, stages, "approval_required", "工具需要用户审批",
                                 stage=LifecycleStage.APPROVAL,
                                 approval_id=approval_id)
        ok_stage(view, LifecycleStage.APPROVAL)

        # 5. Execution lease
        claim: LeaseClaim | None = None
        if self._lease is not None:
            try:
                claim = await self._lease.claim(
                    view, call, canonical_arguments,
                    approval_id=consumed_approval_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                return self._failure(call, stages, "execution_claim_failed",
                                     str(exc) or type(exc).__name__,
                                     stage=LifecycleStage.LEASE)
            if claim.action == LeaseClaimAction.CACHED:
                ok_stage(view, LifecycleStage.LEASE)
                return ExecutionOutcome(
                    tool_call_id=call.id, name=call.name, success=True,
                    output=deepcopy(claim.cached_output), stages=tuple(stages),
                )
            if claim.action == LeaseClaimAction.IN_PROGRESS:
                return self._failure(call, stages, "execution_in_progress",
                                     "工具调用已有活动执行租约",
                                     stage=LifecycleStage.LEASE)
            if claim.action == LeaseClaimAction.UNKNOWN:
                return self._failure(call, stages, "execution_state_unknown",
                                     "工具执行状态不确定，已拒绝自动重试",
                                     stage=LifecycleStage.LEASE)
            if claim.action != LeaseClaimAction.EXECUTE or not claim.claim_token:
                return self._failure(call, stages, "execution_claim_invalid",
                                     "工具执行仓储返回了无效 claim",
                                     stage=LifecycleStage.LEASE)
        cache_key: str | None = None
        if self._lease is None and view.idempotent:
            digest = hashlib.sha256(
                canonical_json(dict(canonical_arguments)).encode("utf-8")
            ).hexdigest()
            cache_key = f"{view.name}@{view.version}:{digest}"
            if cache_key in self._cache:
                stages.append(_record(LifecycleStage.LEASE, None))
                return ExecutionOutcome(
                    tool_call_id=call.id, name=call.name, success=True,
                    output=deepcopy(self._cache[cache_key]), stages=tuple(stages),
                )
        ok_stage(view, LifecycleStage.LEASE)

        # 6. Execution（超时/取消边界）
        try:
            raw_output = await view.invoke_with_bounds(canonical_arguments, cancellation)
        except ToolDispatchCancelledError as exc:
            await self._persist_cancelled(claim, message=str(exc) or "工具执行已取消")
            stages.append(_record(LifecycleStage.EXECUTION, "cancelled"))
            return ExecutionOutcome(
                tool_call_id=call.id, name=call.name, success=False,
                error=_redact_text(str(exc) or "工具执行已取消"),
                error_code="cancelled", stages=tuple(stages),
            )
        except asyncio.CancelledError:
            await self._persist_cancelled(claim)
            raise
        except TimeoutError as exc:
            return await self._terminal_failure(
                call, stages, claim, stage=LifecycleStage.EXECUTION,
                code="timeout", status="timed_out",
                message=str(exc) or "工具执行超时",
            )
        except Exception as exc:  # noqa: BLE001
            return await self._terminal_failure(
                call, stages, claim, stage=LifecycleStage.EXECUTION,
                code="executor_error", status="failed",
                message=str(exc) or type(exc).__name__,
            )
        ok_stage(view, LifecycleStage.EXECUTION)

        # 7. Output bounds
        try:
            canonical_output = self._json_clone(raw_output)
        except (TypeError, ValueError, RecursionError):
            return await self._terminal_failure(
                call, stages, claim, stage=LifecycleStage.OUTPUT_VALIDATION,
                code="output_not_json", status="failed",
                message="工具输出必须是有效 JSON",
            )
        output_error = view.validate_output(canonical_output)
        if output_error is not None:
            return await self._terminal_failure(
                call, stages, claim, stage=LifecycleStage.OUTPUT_VALIDATION,
                code="output_schema_invalid", status="failed",
                message=output_error,
            )
        safe_output = view.redact_output(canonical_output)
        try:
            serialized = json.dumps(
                safe_output, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError):
            return await self._terminal_failure(
                call, stages, claim, stage=LifecycleStage.OUTPUT_VALIDATION,
                code="output_not_json", status="failed",
                message="工具输出必须是有效 JSON",
            )
        if len(serialized) > view.max_output_bytes:
            return await self._terminal_failure(
                call, stages, claim, stage=LifecycleStage.OUTPUT_VALIDATION,
                code="output_too_large", status="failed",
                message="工具输出超过大小上限",
            )
        safe_output = json.loads(serialized)
        ok_stage(view, LifecycleStage.OUTPUT_VALIDATION)

        # 8. Result verification（可信代码固定注入）
        if self._verifier is not None and self._verifier.supports(call.name):
            try:
                verification = await self._verifier.verify(
                    call.name, canonical_arguments, safe_output
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                verification = VerificationResult(
                    passed=False, code="verifier_error",
                    message=(
                        f"结果验证器异常: {type(exc).__name__}"
                        if str(exc) else type(exc).__name__
                    )[:2_000],
                )
            if not verification.passed:
                return await self._terminal_failure(
                    call, stages, claim, stage=LifecycleStage.VERIFICATION,
                    code=verification.code or "result_verification_failed",
                    status="failed", message=verification.message,
                )
        ok_stage(view, LifecycleStage.VERIFICATION)

        # 9. Persistence
        if claim is not None and self._lease is not None:
            try:
                await self._lease.complete_success(
                    claim.execution_id or "",
                    claim_token=claim.claim_token or "",
                    output=safe_output,
                    max_output_bytes=view.max_output_bytes,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                stages.append(_record(LifecycleStage.PERSISTENCE, "execution_persistence_failed"))
                self._notify(view, call, LifecycleStage.PERSISTENCE, False,
                             "execution_persistence_failed")
                return ExecutionOutcome(
                    tool_call_id=call.id, name=call.name, success=False,
                    error=_redact_text(str(exc) or type(exc).__name__),
                    error_code="execution_persistence_failed",
                    stages=tuple(stages),
                )
        elif cache_key is not None:
            self._remember(cache_key, safe_output)
        ok_stage(view, LifecycleStage.PERSISTENCE)
        return ExecutionOutcome(
            tool_call_id=call.id, name=call.name, success=True,
            output=deepcopy(safe_output), stages=tuple(stages),
        )

    # ---- 终态辅助 -------------------------------------------------------

    async def _terminal_failure(
        self,
        call: ToolCallView,
        stages: list[ToolStageRecord],
        claim: LeaseClaim | None,
        *,
        stage: LifecycleStage,
        code: str,
        status: str,
        message: str,
    ) -> ExecutionOutcome:
        if claim is not None and self._lease is not None:
            try:
                await self._lease.complete_failure(
                    claim.execution_id or "",
                    claim_token=claim.claim_token or "",
                    status=status,
                    error_code=code,
                    error_message=_redact_text(message),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                stages.append(_record(LifecycleStage.PERSISTENCE, "execution_persistence_failed"))
                return ExecutionOutcome(
                    tool_call_id=call.id, name=call.name, success=False,
                    error=_redact_text(str(exc) or type(exc).__name__),
                    error_code="execution_persistence_failed",
                    stages=tuple(stages),
                )
        return self._failure(call, stages, code, message, stage=stage)

    async def _persist_cancelled(
        self, claim: LeaseClaim | None, *, message: str = "工具执行已取消"
    ) -> None:
        if claim is None or self._lease is None:
            return
        with suppress(Exception):
            await asyncio.shield(
                self._lease.complete_failure(
                    claim.execution_id or "",
                    claim_token=claim.claim_token or "",
                    status="cancelled",
                    error_code="cancelled",
                    error_message=message,
                )
            )
