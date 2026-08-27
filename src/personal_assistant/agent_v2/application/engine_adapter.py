"""v0.9 dispatcher 资产 → LifecycleToolEngine 端口适配层（CT-4）。

风险表"ToolSpec v2 与 v0.9 双实现漂移"的缓解措施：适配层直接复用 v0.9 的
边界执行（``ValidatedToolDispatcher._execute_with_bounds``）、schema 编译与
脱敏实现，不复制第二套语义；等价性由金标测试钉住，S7 收敛为单执行器。

本模块位于组合边缘：允许导入 v0.9 ``personal_assistant.agents``。
"""

from __future__ import annotations

from typing import Any, Mapping

from .tool_engine import ApprovalPort as ApprovalPortProtocol
from .tool_engine import (
    ExecutionLeasePort,
    LeaseClaim,
    LeaseClaimAction,
    PolicyDecision,
    PolicyGatePort,
    ResultVerifierPort,
    ToolDispatchCancelledError,
    ToolRouterPort,
)


class V09ToolRouterAdapter(ToolRouterPort):
    """把 ``VersionedToolRegistry`` 投影为 Router + EngineToolView。"""

    def __init__(self, registry) -> None:
        # registry: personal_assistant.agents.tools.VersionedToolRegistry
        self._registry = registry

    def resolve(self, name: str):
        spec = self._registry.get(name)
        return V09ToolView(spec) if spec is not None else None


class V09ToolView:
    """EngineToolView 的 v0.9 ToolSpec 投影（复用原校验/脱敏实现）。"""

    __slots__ = ("_spec",)

    def __init__(self, spec) -> None:
        self._spec = spec

    @property
    def spec(self):
        return self._spec

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def version(self) -> str:
        return self._spec.version

    @property
    def max_input_bytes(self) -> int:
        return int(self._spec.max_input_bytes)

    @property
    def max_output_bytes(self) -> int:
        return int(self._spec.max_output_bytes)

    @property
    def idempotent(self) -> bool:
        from ...agents.tools import ToolIdempotency

        return self._spec.idempotency == ToolIdempotency.IDEMPOTENT

    def validate_input(self, arguments: Mapping[str, Any]) -> str | None:
        from ...agents.tools import _validation_error

        error = next(self._spec._input_validator.iter_errors(dict(arguments)), None)
        return None if error is None else _validation_error("工具参数", error)

    def validate_output(self, output: Any) -> str | None:
        from ...agents.tools import _validation_error

        error = next(self._spec._output_validator.iter_errors(output), None)
        return None if error is None else _validation_error("工具输出", error)

    def redact_output(self, output: Any):
        from ...agents.tools import ToolRedactionPolicy, _redact_value

        if self._spec.redaction_policy == ToolRedactionPolicy.SENSITIVE_KEYS:
            return _redact_value(output, self._spec.sensitive_keys)
        return output

    async def invoke_with_bounds(
        self,
        arguments: dict[str, Any],
        cancellation,
    ) -> Any:
        """复用 v0.9 边界执行实现；取消映射为引擎异常类型。"""
        from ...agents.tools import ToolDispatchCancelled, ValidatedToolDispatcher

        try:
            return await ValidatedToolDispatcher._execute_with_bounds(
                self._spec, dict(arguments), cancellation
            )
        except ToolDispatchCancelled as exc:
            raise ToolDispatchCancelledError(str(exc)) from exc


class V09PolicyGateAdapter(PolicyGatePort):
    def __init__(self, policy) -> None:
        # policy: personal_assistant.agents.tools.ToolCapabilityPolicy
        self._policy = policy

    def decide(self, tool: V09ToolView) -> PolicyDecision:

        decision = self._policy.evaluate(tool.spec)
        return PolicyDecision(decision.value)


class V09ApprovalAdapter(ApprovalPortProtocol):
    """包装 v0.9 审批 requester/consumer；调用前转换为 v0.9 ToolCall。"""

    def __init__(self, requester=None, consumer=None) -> None:
        self._requester = requester
        self._consumer = consumer

    @staticmethod
    def _as_v09_call(call):
        from ...agents.contracts import ToolCall

        if isinstance(call, ToolCall):
            return call
        return ToolCall(
            id=getattr(call, "id", ""),
            name=getattr(call, "name", ""),
            arguments=dict(getattr(call, "arguments", {}) or {}),
        )

    async def consume(self, tool, call, arguments) -> str | None:
        if self._consumer is None:
            return None
        return await self._consumer.consume(
            tool.spec, self._as_v09_call(call), dict(arguments)
        )

    async def request(self, tool, call, arguments) -> str:
        assert self._requester is not None
        return await self._requester.request(
            tool.spec, self._as_v09_call(call), dict(arguments)
        )


class V09LeaseAdapter(ExecutionLeasePort):
    """包装 durable ``ToolExecutionRepository``（claim/success/failure 同签名）。"""

    def __init__(self, store) -> None:
        # store: personal_assistant.agents.executions.ToolExecutionRepository
        self._store = store

    async def claim(
        self, tool, call, arguments, *, approval_id: str | None
    ) -> LeaseClaim:
        from ...agents.executions import ToolExecutionClaimAction

        view = await self._store.claim(
            spec=tool.spec,
            call=self._as_v09_call(call),
            arguments=dict(arguments),
            approval_id=approval_id,
        )
        action = ToolExecutionClaimAction(view.action)
        mapped = {
            ToolExecutionClaimAction.EXECUTE: LeaseClaimAction.EXECUTE,
            ToolExecutionClaimAction.CACHED: LeaseClaimAction.CACHED,
            ToolExecutionClaimAction.IN_PROGRESS: LeaseClaimAction.IN_PROGRESS,
            ToolExecutionClaimAction.UNKNOWN: LeaseClaimAction.UNKNOWN,
        }[action]
        return LeaseClaim(
            action=mapped,
            execution_id=view.execution_id,
            claim_token=view.claim_token,
            cached_output=view.output,
        )

    @staticmethod
    def _as_v09_call(call):
        from ...agents.contracts import ToolCall

        if isinstance(call, ToolCall):
            return call
        return ToolCall(
            id=getattr(call, "id", ""),
            name=getattr(call, "name", ""),
            arguments=dict(getattr(call, "arguments", {}) or {}),
        )

    async def complete_success(
        self, execution_id: str, *, claim_token: str, output: Any, max_output_bytes: int
    ) -> None:
        await self._store.complete_success(
            execution_id,
            claim_token=claim_token,
            output=output,
            max_output_bytes=max_output_bytes,
        )
        return None

    async def complete_failure(
        self,
        execution_id: str,
        *,
        claim_token: str,
        status: str,
        error_code: str,
        error_message: str,
    ) -> None:
        await self._store.complete_failure(
            execution_id,
            claim_token=claim_token,
            status=status,
            error_code=error_code,
            error_message=error_message,
        )
        return None


class ResultVerifierAdapter(ResultVerifierPort):
    """ResultVerification（dataclass）→ VerificationResult（frozen 模型）。"""

    def __init__(self, verifier) -> None:
        self._verifier = verifier

    def supports(self, tool_name: str) -> bool:
        return bool(self._verifier.supports(tool_name))

    async def verify(self, tool_name: str, arguments, output):
        verification = await self._verifier.verify(tool_name, arguments, output)
        from .tool_engine import VerificationResult

        return VerificationResult(
            passed=bool(verification.passed),
            code=str(verification.code),
            message=str(verification.message)[:2_000],
        )

