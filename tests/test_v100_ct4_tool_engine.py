"""v1.0.0 CT-4 契约测试：统一 Lifecycle 引擎、安全并发与金标等价。

覆盖专项计划 §15 CT-4 退出条件：

- 所有工具类别走同一 lifecycle 路径，每步产生低敏感阶段记录（§6.2）；
- 与 v0.9 ``ValidatedToolDispatcher`` 的错误码/结果金标等价
  （风险表"双实现漂移"的 adapter + golden 缓解）；
- 故障注入矩阵：unknown/deny/input/approval/claim(cached|in_progress|
  unknown)/timeout/cancel/executor_error/output/verifier/persistence；
- 内部 pre/post 钩子只读观察：frozen 上下文不可改写、钩子异常不影响执行；
- AD-T07 只读并发调度器：资格门槛、副作用恒串行、有界并发、取消收敛、
  结果按原顺序 replay。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest

from personal_assistant.agent_v2.application.engine_adapter import (
    V09PolicyGateAdapter,
    V09ToolRouterAdapter,
)
from personal_assistant.agent_v2.application.read_only_scheduler import (
    ScheduledCall,
    plan_schedule,
    run_scheduled,
)
from personal_assistant.agent_v2.application.tool_engine import (
    LeaseClaim,
    LeaseClaimAction,
    LifecycleContext,
    LifecycleStage,
    LifecycleToolEngine,
    PolicyDecision,
    ToolDispatchCancelledError,
    VerificationResult,
)
from personal_assistant.agents import (
    CancellationToken,
    ToolCall,
    ToolCapability,
    ToolCapabilityPolicy,
    ToolIdempotency,
    ToolRedactionPolicy,
    ToolRiskLevel,
    ToolSpec,
    ValidatedToolDispatcher,
    VersionedToolRegistry,
)

# ===========================================================================
# 构造辅助
# ===========================================================================


async def _echo(arguments: dict[str, Any], cancellation: CancellationToken) -> dict:
    del cancellation
    return {"value": arguments["value"]}


def _v09_spec(
    *,
    executor: Callable[[dict[str, Any], CancellationToken], Awaitable[Any]] = _echo,
    risk_level: ToolRiskLevel = ToolRiskLevel.SAFE,
    idempotency: ToolIdempotency = ToolIdempotency.IDEMPOTENT,
    timeout_ms: int = 1_000,
    max_output_bytes: int = 1_024,
) -> ToolSpec:
    return ToolSpec(
        name="echo",
        version="1.0.0",
        description="Echo a value",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        risk_level=risk_level,
        required_capabilities=frozenset({ToolCapability.FILESYSTEM_READ}),
        timeout_ms=timeout_ms,
        max_output_bytes=max_output_bytes,
        idempotency=idempotency,
        supports_cancellation=True,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        executor=executor,
    )


@dataclass(frozen=True, slots=True)
class _Call:
    """引擎入参的最小调用视图。"""

    id: str
    name: str
    arguments: dict[str, Any]


def _engine(
    spec: ToolSpec,
    *,
    granted: frozenset[ToolCapability] | None = None,
    lease=None,
    verifier=None,
    hooks=(),
) -> LifecycleToolEngine:
    registry = VersionedToolRegistry()
    registry.register(spec)
    policy = ToolCapabilityPolicy(
        granted_capabilities=(
            granted if granted is not None else frozenset({ToolCapability.FILESYSTEM_READ})
        )
    )
    return LifecycleToolEngine(
        V09ToolRouterAdapter(registry),
        V09PolicyGateAdapter(policy),
        lease=lease,
        verifier=verifier,
        hooks=hooks,
    )


def _call(**overrides) -> _Call:
    payload = {"id": "call-1", "name": "echo", "arguments": {"value": "hi"}}
    payload.update(overrides)
    return _Call(**payload)


# ===========================================================================
# A. 金标等价：同一调用矩阵在 v0.9 dispatcher 与 v2 引擎上结论一致
# ===========================================================================


async def _run_both(spec: ToolSpec, call: _Call, *, granted=None):
    dispatcher = ValidatedToolDispatcher(
        (lambda r: (r.register(spec), r)[1])(VersionedToolRegistry()),
        policy=ToolCapabilityPolicy(
            granted_capabilities=(
                granted
                if granted is not None
                else frozenset({ToolCapability.FILESYSTEM_READ})
            )
        ),
    )
    legacy = await dispatcher.execute(
        ToolCall(id=call.id, name=call.name, arguments=dict(call.arguments)),
        cancellation=CancellationToken(),
    )
    engine_result = await _engine(spec, granted=granted).execute(
        call, cancellation=CancellationToken()
    )
    return legacy, engine_result


# §7.7 公开码统一：v0.9 dispatcher 保留既有码不变；v2 引擎的策略拒绝
# 统一为 tool_hidden_by_policy（其余码金标一致）。
_V2_UNIFIED_PUBLIC_CODES = {"permission_denied": "tool_hidden_by_policy"}


@pytest.mark.parametrize(
    ("call", "granted"),
    [
        (_call(), frozenset({ToolCapability.FILESYSTEM_READ})),  # 成功路径
        (_call(name="missing"), frozenset({ToolCapability.FILESYSTEM_READ})),
        (_call(), frozenset()),  # 默认拒绝
        (_call(arguments={"novalue": 1}), None),  # input schema invalid（缺必填）
        (_call(arguments={"value": 3}), None),  # 类型不符
    ],
)
async def test_golden_equivalence_with_legacy_dispatcher(call, granted):
    """金标等价：success/error_code 与 v0.9 一致（仅 §7.7 统一映射除外）。"""
    effective_granted = (
        granted
        if granted is not None
        else frozenset({ToolCapability.FILESYSTEM_READ})
    )
    spec = _v09_spec()
    legacy, engine_result = await _run_both(spec, call, granted=effective_granted)
    assert engine_result.success == legacy.success
    expected_code = _V2_UNIFIED_PUBLIC_CODES.get(
        legacy.error_code, legacy.error_code
    )
    assert engine_result.error_code == expected_code
    assert engine_result.output == legacy.output


async def test_golden_equivalence_redaction_and_secret_text():
    async def leak(arguments: dict[str, Any], cancellation: CancellationToken) -> dict:
        del arguments, cancellation
        return {"value": "token: abcsecret"}

    spec = _v09_spec(executor=leak)
    legacy, engine_result = await _run_both(spec, _call())
    assert legacy.output["value"].endswith("[REDACTED]")
    assert engine_result.output == legacy.output


# ===========================================================================
# B. 故障注入矩阵（引擎端口级）
# ===========================================================================


class _StaticRouter:
    def __init__(self, view=None):
        self._view = view

    def resolve(self, name):
        return self._view


class _FixedPolicy:
    def __init__(self, decision: PolicyDecision):
        self._decision = decision

    def decide(self, tool):
        return self._decision


class _StubView:
    name = "stub"
    version = "1.0.0"
    max_input_bytes = 64 * 1024
    max_output_bytes = 1024
    idempotent = True

    def validate_input(self, arguments):
        return None

    def validate_output(self, output):
        return None

    def redact_output(self, output):
        return output

    async def invoke_with_bounds(self, arguments, cancellation):
        raise NotImplementedError


class _StubCall:
    def __init__(self, arguments=None):
        self.id = "call-1"
        self.name = "stub"
        self.arguments = arguments or {}


class _FakeLease:
    def __init__(self, claim: LeaseClaim | None = None, *, fail_success=False):
        self.claim_value = claim
        self.fail_success = fail_success
        self.success_calls: list[tuple] = []
        self.failure_calls: list[dict] = []

    async def claim(self, tool, call, arguments, *, approval_id):
        if self.claim_value is None:
            raise RuntimeError("lease down")
        return self.claim_value

    async def complete_success(self, execution_id, *, claim_token, output, max_output_bytes):
        if self.fail_success:
            raise RuntimeError("db write failed")
        self.success_calls.append((execution_id, output))

    async def complete_failure(self, execution_id, *, claim_token, status, error_code, error_message):
        self.failure_calls.append(
            {"status": status, "error_code": error_code, "message": error_message}
        )


def _executing_claim() -> LeaseClaim:
    return LeaseClaim(
        action=LeaseClaimAction.EXECUTE,
        execution_id="exec-1",
        claim_token="token-1",
    )


def _ok_view(result: Any = {"ok": True}) -> _StubView:
    class _V(_StubView):
        async def invoke_with_bounds(self, arguments, cancellation):
            del arguments, cancellation
            return result

    return _V()


async def test_fault_matrix_injection():
    cases: list[tuple[str, LifecycleToolEngine, _StubCall, str]] = [
        (
            "unknown_tool",
            LifecycleToolEngine(_StaticRouter(None), _FixedPolicy(PolicyDecision.ALLOW)),
            _StubCall(),
            "unknown_tool",
        ),
        (
            "tool_hidden_by_policy",
            LifecycleToolEngine(
                _StaticRouter(_ok_view()), _FixedPolicy(PolicyDecision.DENY)
            ),
            _StubCall(),
            "tool_hidden_by_policy",
        ),
        (
            "approval_unavailable",
            LifecycleToolEngine(
                _StaticRouter(_ok_view()), _FixedPolicy(PolicyDecision.REQUIRE_APPROVAL)
            ),
            _StubCall(),
            "approval_unavailable",
        ),
        (
            "execution_claim_failed",
            LifecycleToolEngine(
                _StaticRouter(_ok_view()),
                _FixedPolicy(PolicyDecision.ALLOW),
                lease=_FakeLease(None),
            ),
            _StubCall(),
            "execution_claim_failed",
        ),
    ]
    for name, engine, call, expected in cases:
        outcome = await engine.execute(call, cancellation=CancellationToken())
        assert outcome.success is False, name
        assert outcome.error_code == expected, f"{name}: {outcome.error_code}"


async def test_lease_actions_cached_in_progress_unknown():
    cached = LifecycleToolEngine(
        _StaticRouter(_ok_view({"cached": 1})),
        _FixedPolicy(PolicyDecision.ALLOW),
        lease=_FakeLease(
            LeaseClaim(action=LeaseClaimAction.CACHED, cached_output={"cached": 1})
        ),
    ).execute(_StubCall(), cancellation=CancellationToken())
    cached_outcome = await cached
    assert cached_outcome.success and cached_outcome.output == {"cached": 1}

    for action, code in (
        (LeaseClaimAction.IN_PROGRESS, "execution_in_progress"),
        (LeaseClaimAction.UNKNOWN, "execution_state_unknown"),
    ):
        engine = LifecycleToolEngine(
            _StaticRouter(_ok_view()),
            _FixedPolicy(PolicyDecision.ALLOW),
            lease=_FakeLease(LeaseClaim(action=action, execution_id="e", claim_token="t")),
        )
        outcome = await engine.execute(_StubCall(), cancellation=CancellationToken())
        assert outcome.error_code == code


async def test_executor_error_persists_failure_and_redacts_secrets():
    class _BoomView(_StubView):
        async def invoke_with_bounds(self, arguments, cancellation):
            raise RuntimeError("password: topsecret")

    lease = _FakeLease(_executing_claim())
    engine = LifecycleToolEngine(
        _StaticRouter(_BoomView()), _FixedPolicy(PolicyDecision.ALLOW), lease=lease
    )
    outcome = await engine.execute(_StubCall(), cancellation=CancellationToken())
    assert outcome.error_code == "executor_error"
    assert "topsecret" not in (outcome.error or "")
    assert lease.failure_calls[0]["status"] == "failed"
    assert "topsecret" not in lease.failure_calls[0]["message"]


async def test_timeout_maps_to_timed_out_status():
    from personal_assistant.agents.tools import ToolDispatchCancelled as _  # noqa: F401

    class _SlowView(_StubView):
        async def invoke_with_bounds(self, arguments, cancellation):
            raise TimeoutError()

    lease = _FakeLease(_executing_claim())
    engine = LifecycleToolEngine(
        _StaticRouter(_SlowView()), _FixedPolicy(PolicyDecision.ALLOW), lease=lease
    )
    outcome = await engine.execute(_StubCall(), cancellation=CancellationToken())
    assert outcome.error_code == "timeout"
    assert lease.failure_calls[0]["status"] == "timed_out"


async def test_cancellation_persists_cancelled_and_short_circuits():
    class _CancelView(_StubView):
        async def invoke_with_bounds(self, arguments, cancellation):
            raise ToolDispatchCancelledError("工具执行已取消")

    lease = _FakeLease(_executing_claim())
    engine = LifecycleToolEngine(
        _StaticRouter(_CancelView()), _FixedPolicy(PolicyDecision.ALLOW), lease=lease
    )
    outcome = await engine.execute(_StubCall(), cancellation=CancellationToken())
    assert outcome.error_code == "cancelled"
    assert lease.failure_calls[0]["status"] == "cancelled"


async def test_verifier_failure_propagates_code_and_fails_execution():
    class _Verifier:
        def supports(self, tool_name):
            return True

        async def verify(self, tool_name, arguments, output):
            return VerificationResult(passed=False, code="disk_mismatch", message="回读不一致")

    lease = _FakeLease(_executing_claim())
    engine = LifecycleToolEngine(
        _StaticRouter(_ok_view()),
        _FixedPolicy(PolicyDecision.ALLOW),
        lease=lease,
        verifier=_Verifier(),
    )
    outcome = await engine.execute(_StubCall(), cancellation=CancellationToken())
    assert outcome.success is False
    assert outcome.error_code == "disk_mismatch"
    assert lease.failure_calls[0]["error_code"] == "disk_mismatch"


async def test_persistence_failure_never_reports_success():
    lease = _FakeLease(_executing_claim(), fail_success=True)
    engine = LifecycleToolEngine(
        _StaticRouter(_ok_view()), _FixedPolicy(PolicyDecision.ALLOW), lease=lease
    )
    outcome = await engine.execute(_StubCall(), cancellation=CancellationToken())
    assert outcome.success is False
    assert outcome.error_code == "execution_persistence_failed"


async def test_local_idempotent_cache_replays_same_output_without_lease():
    counter = {"n": 0}

    class _CountingView(_StubView):
        async def invoke_with_bounds(self, arguments, cancellation):
            counter["n"] += 1
            return {"n": counter["n"]}

    engine = LifecycleToolEngine(
        _StaticRouter(_CountingView()), _FixedPolicy(PolicyDecision.ALLOW)
    )
    first = await engine.execute(_StubCall(), cancellation=CancellationToken())
    second = await engine.execute(_StubCall(), cancellation=CancellationToken())
    assert first.success and second.success
    assert second.output == first.output == {"n": 1}


# ===========================================================================
# C. 阶段轨迹与内部钩子（§6.2：每步产生可关联状态）
# ===========================================================================


async def test_stage_trace_is_ordered_and_terminal_short_circuits():
    ok_engine = LifecycleToolEngine(
        _StaticRouter(_ok_view()), _FixedPolicy(PolicyDecision.ALLOW),
        lease=_FakeLease(_executing_claim()),
    )
    outcome = await ok_engine.execute(_StubCall(), cancellation=CancellationToken())
    assert outcome.stage_codes() == (
        "route:ok",
        "policy:ok",
        "input_validation:ok",
        "approval:ok",
        "lease:ok",
        "execution:ok",
        "output_validation:ok",
        "verification:ok",
        "persistence:ok",
    )
    denied = await LifecycleToolEngine(
        _StaticRouter(_ok_view()), _FixedPolicy(PolicyDecision.DENY)
    ).execute(_StubCall(), cancellation=CancellationToken())
    assert denied.stage_codes() == ("route:ok", "policy:error")


class _RecordingHook:
    def __init__(self):
        self.seen: list[LifecycleContext] = []

    def on_stage(self, context: LifecycleContext) -> None:
        self.seen.append(context)


async def test_hooks_observe_frozen_context_and_cannot_mutate_or_break_flow():
    hook = _RecordingHook()
    engine = LifecycleToolEngine(
        _StaticRouter(_ok_view()), _FixedPolicy(PolicyDecision.ALLOW), hooks=(hook,)
    )
    outcome = await engine.execute(_StubCall(), cancellation=CancellationToken())
    assert outcome.success is True
    # 钩子与阶段轨迹一一对应（§6.2：每步产生可关联状态）。
    assert [ctx.stage for ctx in hook.seen] == [
        LifecycleStage.ROUTE,
        LifecycleStage.POLICY,
        LifecycleStage.INPUT_VALIDATION,
        LifecycleStage.APPROVAL,
        LifecycleStage.LEASE,
        LifecycleStage.EXECUTION,
        LifecycleStage.OUTPUT_VALIDATION,
        LifecycleStage.VERIFICATION,
        LifecycleStage.PERSISTENCE,
    ]
    assert all(ctx.ok for ctx in hook.seen)
    for context in hook.seen:
        with pytest.raises(Exception):
            context.ok = False  # type: ignore[misc]


async def test_hook_exception_does_not_change_execution_semantics():
    class _BrokenHook:
        def on_stage(self, context: LifecycleContext) -> None:
            raise RuntimeError("hook boom")

    engine = LifecycleToolEngine(
        _StaticRouter(_ok_view()),
        _FixedPolicy(PolicyDecision.ALLOW),
        hooks=(_BrokenHook(),),
    )
    outcome = await engine.execute(_StubCall(), cancellation=CancellationToken())
    assert outcome.success is True


# ===========================================================================
# D. AD-T07 只读并发调度器
# ===========================================================================


def test_plan_schedule_matrix():
    good = ScheduledCall(call_id="a", parallel_eligible=True)
    bad = ScheduledCall(call_id="b", parallel_eligible=False)
    assert plan_schedule([good, good]) == (True, 2)
    assert plan_schedule([good, good, good], max_concurrency=2) == (True, 2)
    # 任一副作用/需审批调用 → 整轮串行（并发数恒为 1）。
    assert plan_schedule([good, bad]) == (False, 1)
    with pytest.raises(Exception):
        plan_schedule([])


async def test_scheduler_preserves_submission_order_despite_completion_order():
    async def execute_one(item: ScheduledCall) -> str:
        # 后提交的先完成。
        delay = 0.10 if item.call_id == "a" else 0.01
        await asyncio.sleep(delay)
        return item.call_id

    calls = [ScheduledCall("a", True), ScheduledCall("b", True)]
    results = await run_scheduled(calls, execute_one, max_concurrency=4)
    assert results == ["a", "b"]


async def test_side_effect_tool_forces_serial_concurrency_one():
    active = {"now": 0, "max": 0}

    async def execute_one(item: ScheduledCall) -> str:
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.02)
        active["now"] -= 1
        return item.call_id

    calls = [
        ScheduledCall("a", False),  # 副作用工具
        ScheduledCall("b", False),
        ScheduledCall("c", False),
    ]
    results = await run_scheduled(calls, execute_one)
    assert results == ["a", "b", "c"]
    assert active["max"] == 1  # 副作用工具并发数始终为 1


async def test_bounded_parallel_respects_concurrency_cap():
    active = {"now": 0, "peak": 0}

    async def execute_one(item: ScheduledCall) -> int:
        active["now"] += 1
        active["peak"] = max(active["peak"], active["now"])
        await asyncio.sleep(0.02)
        active["now"] -= 1
        return item.call_id

    calls = [ScheduledCall(str(i), True) for i in range(8)]
    await run_scheduled(calls, execute_one, max_concurrency=3)
    assert active["peak"] <= 3


async def test_cancellation_converges_all_subtasks():
    """外部取消父任务 → bounded task group 收敛全部子任务（§9.4）。"""
    started: set[str] = set()
    finished: set[str] = set()

    async def execute_one(item: ScheduledCall) -> str:
        started.add(item.call_id)
        await asyncio.sleep(1.0)
        finished.add(item.call_id)
        return item.call_id

    calls = [ScheduledCall("a", True), ScheduledCall("b", True)]
    loop = asyncio.get_running_loop()
    parent = asyncio.current_task()
    handle = loop.call_later(0.02, lambda: parent.cancel())  # type: ignore[union-attr]
    try:
        with pytest.raises(asyncio.CancelledError):
            await run_scheduled(calls, execute_one)
    finally:
        handle.cancel()
    assert started == {"a", "b"}  # 两个子任务都已启动
    assert finished == set()  # 全部被收敛，没有任何子任务跑满 1 秒


async def test_scheduler_replay_determinism():
    async def execute_one(item: ScheduledCall) -> str:
        await asyncio.sleep(0.005 if item.call_id == "b" else 0.001)
        return f"result-{item.call_id}"

    calls = [ScheduledCall(name, True) for name in ("x", "y", "z")]
    run_a = await run_scheduled(calls, execute_one)
    run_b = await run_scheduled(calls, execute_one)
    assert run_a == run_b == ["result-x", "result-y", "result-z"]
