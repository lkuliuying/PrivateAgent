"""把本机模型、工具与 SQLite 事件接入共享 AgentRuntime。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import uuid

from pydantic import ValidationError

from private_agent_core.contracts import (
    AgentEvent,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResult,
)
from private_agent_core.llm.contracts import ModelTextDelta
from private_agent_core.runtime import CancellationToken

from . import observer_steps, reflection
from .context import token_count
from .context_manager import LocalContext
from .instructions import InstructionError
from .model_errors import MODEL_CALL, CloudError
from .model_transport import MODEL_ACCOUNTING
from .progress import STOP_AT, observe


class LocalRunAdapter:
    def __init__(self, owner, run: dict, root):
        self.owner, self.run, self.root = owner, run, root
        self.model_error: CloudError | None = None
        self.terminal_payload: dict = {}
        self.last_usage_complete = False
        self.context = LocalContext(owner, run, root)
        owner.contexts[run["id"]] = self.context
        self.response_generation = run.get("generation", 0)
        self.pending_calls: set[str] = set()
        self.exposed_tool_names: frozenset[str] = frozenset()

    async def complete(self, request: ModelRequest, *, cancellation: CancellationToken) -> ModelResponse:
        return await self.complete_stream(request, cancellation=cancellation)

    async def complete_stream(self, request: ModelRequest, *, cancellation: CancellationToken, on_delta=None) -> ModelResponse:
        with observer_steps.call_scope(self.run, observer_steps.invocation_step(self.run)):
            return await self._complete_stream(request, cancellation=cancellation, on_delta=on_delta)

    async def _complete_stream(self, request: ModelRequest, *, cancellation: CancellationToken, on_delta=None) -> ModelResponse:
        while True:
            await self.owner.controls.boundary(self.run, model=True)
            generation = self.run.get("generation", 0)
            task = asyncio.create_task(self._complete_attempt(request, cancellation=cancellation, on_delta=on_delta, generation=generation))
            self.owner.controls.model_tasks[self.run["id"]] = task
            try:
                result = await task
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling() or self.run.get("cancel_requested_at"):
                    raise
                if generation == self.run.get("generation", 0):
                    raise
                continue
            finally:
                self.owner.controls.model_tasks.pop(self.run["id"], None)
            if generation != self.run.get("generation", 0):
                for key in ("input_tokens", "output_tokens", "cached_tokens"):
                    self.run[key] += getattr(result.usage, key) or 0
                self.owner.event(self.run, "model.response_discarded", generation=generation)
                continue
            self.response_generation = generation
            self.run["response_generation"] = generation
            self.run["response_attempt_id"] = self._completed_attempt_id
            self.run["pending_response"] = result.model_dump(mode="json")
            self.pending_calls = {call.id for call in result.tool_calls}
            self.owner.event(self.run, "model.response_confirmed", generation=generation)
            return result

    async def _complete_attempt(self, request: ModelRequest, *, cancellation: CancellationToken, on_delta=None, generation=0) -> ModelResponse:
        cancellation.raise_if_cancelled()
        try:
            request = await self.context.prepare(request)
            self.context.check_limits()
            self.exposed_tool_names = frozenset(tool.name for tool in request.tools)
        except CloudError as error:
            self.model_error = error
            raise
        except InstructionError as error:
            self.model_error = CloudError(422, str(error), code="instructions_unavailable")
            raise self.model_error from None
        except ValueError:
            self.model_error = CloudError(422, "上下文历史或配置无效，请检查当前会话", code="context_invalid")
            raise self.model_error from None
        attempt_id = str(uuid.uuid4())
        public_filters = {}
        callback_filter = self.owner.secret_filter.stream()
        safe_parts = []

        def finish_public_output():
            for identifier, stream_filter in public_filters.items():
                tail = stream_filter.finish()
                if tail:
                    pending.append({"message_id": identifier, "phase": messages[identifier], "delta": tail})

        def interrupted():
            finish_public_output()
            if public_filters:
                flush()
            self.run.update(usage_complete=False, cost_usd=None)
            self.context.cost_known = False
            self.context.tokens_known = False
            self.owner.event(self.run, "model.output.interrupted", attempt_id=attempt_id, generation=generation, usage_complete=False)

        try:
            self.context.rounds += 1
            self.owner.event(self.run, "model.requested", generation=generation, attempt_id=attempt_id)
            partial = []
            pending = []
            messages = {}
            size = 0
            partial_size = 0
            pending_size = 0
            message_stream = getattr(self.owner.cloud, "complete_stream_messages", None)
            profile = next((item for item in self.owner._profiles if item.get("id") == self.run["model_profile_id"]), {})
            rich_stream = message_stream is not None and profile.get("supports_streaming") is True

            def flush():
                nonlocal pending_size
                if generation != self.run.get("generation", 0):
                    pending.clear()
                    pending_size = 0
                    return
                if pending:
                    for item in pending:
                        self.owner.store.emit(self.run, "model.output.delta", {"attempt_id": attempt_id,
                            "generation": generation, **item}, lightweight=True)
                    pending.clear()
                    pending_size = 0

            async def publish_batches():
                while True:
                    await asyncio.sleep(0.1)
                    flush()

            publisher = asyncio.create_task(publish_batches())

            async def receive_message(value):
                nonlocal size, pending_size
                cancellation.raise_if_cancelled()
                if generation != self.run.get("generation", 0):
                    return
                if not isinstance(value, ModelTextDelta):
                    raise ValueError("公开消息增量格式无效")
                if self.owner.secret_filter.contains_known_secret(value.message_id):
                    raise CloudError(422, "模型公开标识包含疑似凭据，已停止接收", code="sensitive_model_metadata")
                delta = value.delta
                if not delta:
                    return
                identifier = f"{attempt_id}:{value.message_id}"
                first = identifier not in messages
                previous = messages.get(identifier)
                if previous is not None and previous != value.phase:
                    raise ValueError("公开消息阶段前后不一致")
                messages[identifier] = value.phase
                size += len(delta.encode("utf-8"))
                if size > 1024 * 1024:
                    raise ValueError("模型公开输出超出上限")
                # 协议完整性仍核对原文；公开增量按消息保留敏感前缀，避免跨块泄露。
                if identifier not in public_filters:
                    public_filters[identifier] = self.owner.secret_filter.stream()
                delta = public_filters[identifier].feed(delta)
                if not delta:
                    return
                if pending and pending[-1]["message_id"] == identifier and pending[-1]["phase"] == value.phase:
                    pending[-1]["delta"] += delta
                else:
                    pending.append({"message_id": identifier, "phase": value.phase, "delta": delta})
                pending_size += len(delta)
                if first or pending_size >= 4096:
                    flush()

            async def receive(delta):
                nonlocal partial_size
                cancellation.raise_if_cancelled()
                if generation != self.run.get("generation", 0):
                    return
                if not isinstance(delta, str):
                    raise ValueError("模型正文增量必须为字符串")
                partial_size += len(delta.encode("utf-8"))
                if partial_size > 1024 * 1024:
                    raise ValueError("模型正文输出超出上限")
                partial.append(delta)
                if not rich_stream:
                    await receive_message(ModelTextDelta("default", None, delta))
                safe_delta = callback_filter.feed(delta)
                if safe_delta:
                    safe_parts.append(safe_delta)
                    if on_delta is not None:
                        await on_delta(safe_delta)

            try:
                accounting = {"tracked": False, "call_id": attempt_id, "provider_requests": 0, "provider_retries": 0,
                              "missing_reason": None, "protocol": "direct"}
                accounting_scope = MODEL_ACCOUNTING.set(accounting)
                call_scope = MODEL_CALL.set(attempt_id if self.context.limits.max_total_tokens is not None else None)
                async with asyncio.timeout(max(0.001, self.context.remaining_seconds())):
                    stream = getattr(self.owner.cloud, "complete_stream", None)
                    if rich_stream:
                        raw = await message_stream(self.owner.token, self.run["model_profile_id"], request.model_dump(mode="json"),
                                                   on_delta=receive, on_message_delta=receive_message)
                    elif stream and profile.get("supports_streaming") is True:
                        raw = await stream(self.owner.token, self.run["model_profile_id"], request.model_dump(mode="json"), on_delta=receive)
                    else:
                        raw = await self.owner.cloud.complete(self.owner.token, self.run["model_profile_id"], request.model_dump(mode="json"))
            finally:
                MODEL_ACCOUNTING.reset(accounting_scope)
                MODEL_CALL.reset(call_scope)
                publisher.cancel()
                results = await asyncio.gather(publisher, return_exceptions=True)
                flush()
                if accounting["tracked"]:
                    self.owner.event(self.run, "model.transport", attempt_id=attempt_id,
                                     **{key: value for key, value in accounting.items() if key != "tracked"})
                if results and isinstance(results[0], Exception):
                    raise results[0]
            # 路由元数据只用于本机记录，不扩展共享模型响应契约。
            selected_profile_id = raw.pop("model_profile_id", None)
            transport = raw.pop("transport_metrics", None)
            if transport is not None and not accounting["tracked"]:
                self.owner.event(self.run, "model.transport", attempt_id=attempt_id, **transport)
            if selected_profile_id is not None and (not isinstance(selected_profile_id, str)
                    or not 1 <= len(selected_profile_id) <= 128
                    or (self.run["model_profile_id"] and self.run["model_profile_id"] != selected_profile_id)):
                raise ValueError("模型路由与当前运行不一致")
            result = ModelResponse.model_validate(raw)
            result.require_complete()
            if partial and "".join(partial) != result.text:
                raise ValueError("模型公开增量与最终响应不一致")
            if len(result.tool_calls) > 8:
                raise ValueError("模型工具请求超出限制")
            if not partial and result.text:
                # 非流式响应也复用公开正文通道，保留限长与取消检查，避免重复已收到的增量。
                await receive(result.text)
            if not messages and result.text:
                await receive_message(ModelTextDelta("default", result.phase, result.text))
            if any(self.owner.secret_filter.contains_known_secret(call.model_dump(mode="json")) for call in result.tool_calls):
                raise CloudError(422, "工具请求包含疑似凭据，未执行或保存该请求", code="sensitive_tool_arguments")
            if self.owner.secret_filter.contains_known_secret(result.model_dump(mode="json", exclude={"text", "tool_calls", "provider_state"})):
                raise CloudError(422, "模型响应标识包含疑似凭据，未保存该响应", code="sensitive_model_metadata")
            callback_tail = callback_filter.finish()
            if callback_tail:
                safe_parts.append(callback_tail)
                if on_delta is not None:
                    await on_delta(callback_tail)
            safe_text = "".join(safe_parts)
            safe_state = result.provider_state
            if safe_state is not None and self.owner.secret_filter.contains_public_provider_secret(safe_state.output_json):
                safe_state = None
            # 脱敏后的最终文本与公开流必须相同；原生续接若携带旧正文则停止复用。
            result = result.model_copy(update={"text": safe_text,
                "provider_state": safe_state if safe_text == result.text else None})
            flush()
        except (ValidationError, ValueError):
            interrupted()
            self.model_error = CloudError(502, "模型供应商响应格式无效", code="model_invalid_response")
            raise self.model_error from None
        except CloudError as error:
            interrupted()
            self.model_error = error
            raise
        except TimeoutError:
            interrupted()
            self.model_error = CloudError(422, "有效执行时长预算已耗尽", code="max_active_seconds")
            raise self.model_error from None
        except (OSError, sqlite3.Error):
            interrupted()
            raise
        except asyncio.CancelledError:
            interrupted()
            raise
        finally:
            # 取消、超时和断流也必须关闭过滤状态，未决敏感片段不能原样落库。
            finish_public_output()
            if public_filters:
                flush()
        usage = raw.get("usage") or {}
        # 每次请求都含系统提示；旧服务补出的全零 usage 不能充当真实计量。
        if token_count(usage.get("input_tokens")) == 0:
            usage = {}
        self.last_usage_complete = all(token_count(usage.get(key)) is not None for key in ("input_tokens", "output_tokens"))
        self.run["usage_complete"] = self.run.get("usage_complete", True) and self.last_usage_complete
        self.run["context_usage"] = {key: token_count(usage.get(key)) for key in ("input_tokens", "output_tokens", "cached_tokens")}
        used, cached = (token_count(usage.get(key)) for key in ("input_tokens", "cached_tokens"))
        totals = self.run.setdefault("cache_usage", {"input_tokens": 0, "cached_tokens": 0})
        if used and cached is not None and cached <= used:
            totals["input_tokens"] += used
            totals["cached_tokens"] += cached
        if selected_profile_id:
            self.run["model_profile_id"] = selected_profile_id
        self.run.update(provider=result.provider, model=result.model)
        self.context.observe_usage(result.usage, complete=self.last_usage_complete)
        phase = result.phase or ("commentary" if result.tool_calls else "final_answer")
        default_id = f"{attempt_id}:default"
        if len(messages) == 1 and default_id in messages and messages[default_id] is None:
            messages[default_id] = phase
        self.owner.event(self.run, "model.output.finished", attempt_id=attempt_id, generation=generation,
                         phase=phase, messages=[{"message_id": identifier, "phase": value} for identifier, value in messages.items()],
                         has_tool_calls=bool(result.tool_calls), usage_complete=self.last_usage_complete)
        self._completed_attempt_id = attempt_id
        return result

    async def execute(self, call: ToolCall, *, cancellation: CancellationToken) -> ToolResult:
        with observer_steps.call_scope(self.run, observer_steps.invocation_step(self.run, tool_call_id=call.id)):
            return await self._execute(call, cancellation=cancellation)

    async def _execute(self, call: ToolCall, *, cancellation: CancellationToken) -> ToolResult:
        cancellation.raise_if_cancelled()
        await self.owner.controls.boundary(self.run)
        if self.response_generation != self.run.get("generation", 0):
            self.owner.event(self.run, "tool.superseded", tool_call_id=call.id, name=call.name)
            return ToolResult(tool_call_id=call.id, name=call.name, success=False, error="用户约束已更新，旧工具未执行，请重新规划", error_code="steering_superseded")
        task = asyncio.create_task(self.owner.tool(self.run, self.root, call.model_dump(mode="json")))
        slots = self.owner.controls.tool_tasks.setdefault(self.run["id"], {})
        slots[call.id] = {"task": task, "name": call.name}
        try:
            output = await task
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling() or self.run.get("cancel_requested_at"):
                raise
            if not self.run.get("pause_requested") and self.response_generation == self.run.get("generation", 0):
                raise
            output = {"error": "运行约束已变化，当前调用已停止，已发生的副作用保留",
                      "error_code": "command_cancelled" if self.owner.registry[call.name].effect == "process" else "steering_superseded"}
        finally:
            slots.pop(call.id, None)
            if not slots:
                self.owner.controls.tool_tasks.pop(self.run["id"], None)
            self.owner.event(self.run, "tool.invocation_finished", tool_call_id=call.id, name=call.name)
        self.owner.event(self.run, "tool.result_recorded", tool_call_id=call.id, name=call.name)
        await self.owner.controls.boundary(self.run)
        if (self.response_generation != self.run.get("generation", 0)
                and (self.owner.registry[call.name].effect == "read" or call.name == "tool_search")):
            output = {"error": "用户约束已更新，旧读取结果未进入模型上下文，请重新查询", "error_code": "steering_superseded"}
        if output.get("error") is not None:
            return ToolResult(tool_call_id=call.id, name=call.name, success=False, error=output["error"],
                              error_code=output.get("error_code", "local_tool_rejected"),
                              output={key: value for key, value in output.items() if key not in {"error", "error_code"}})
        return ToolResult(tool_call_id=call.id, name=call.name, success=True, output=output)

    async def finalize_result(self, call, result):
        with observer_steps.call_scope(self.run, observer_steps.invocation_step(self.run, tool_call_id=call.id)):
            return await self._finalize_result(call, result)

    async def _finalize_result(self, call, result):
        """整个批次完成后按模型顺序复核代次，避免已完成的兄弟读取夹带旧结果。"""
        await self.owner.controls.boundary(self.run)
        if (call.name in self.owner.registry
                and (self.owner.registry[call.name].effect in {"read", "external"} or call.name == "tool_search")
                and self.response_generation != self.run.get("generation", 0)):
            result = ToolResult(tool_call_id=call.id, name=call.name, success=False,
                                error="用户约束已更新，旧读取结果未进入模型上下文，请重新查询", error_code="steering_superseded")
        if (self.run.get("recovery_contract_version") == "1.0"
                and self.response_generation != self.run.get("generation", 0)):
            return result
        # 并发的完成先后不影响停滞检测；只有相同调用的相同失败才累计。
        if not result.success:
            fingerprint = hashlib.sha256(json.dumps([call.name, call.arguments, result.error, result.error_code,
                result.output, self.run.get("workspace_version", 0)], sort_keys=True).encode()).hexdigest()
            self.context.failure_count = self.context.failure_count + 1 if fingerprint == self.context.failure_key else 1
            self.context.failure_key = fingerprint
            if self.context.failure_count == 3:
                result = result.model_copy(update={"output": {**(result.output or {}), "loop_warning": "相同失败已出现三次，请改变方案；再次无进展将停止"}})
        else:
            self.context.failure_key, self.context.failure_count = None, 0
            arguments = self.owner.registry[call.name].input_model.model_validate(call.arguments).model_dump(mode="json")
            progress, warning = observe(self.run, call.name, arguments, result.output or {})
            if progress is not None:
                with self.owner.store.transaction(run=self.run):
                    self.run["orchestration_progress"] = progress
                    kind = "progress.stalled" if progress["repeats"] >= STOP_AT else "progress.warning" if warning else "progress.observed"
                    self.owner.event(self.run, kind, tool_call_id=call.id, repeated_observations=progress["repeats"])
            if warning:
                result = result.model_copy(update={"output": {**(result.output or {}), "loop_warning": warning}})
        state, correction = reflection.observe(self.owner, self.run, call, result)
        if state is not None:
            with self.owner.store.transaction(run=self.run):
                self.run["reflection_state"] = state
                self.owner.event(self.run, "reflection.warning" if correction and correction["warning"] else "reflection.observed",
                                 category=(correction or {}).get("category"), attempts=(correction or {}).get("attempts", 0),
                                 entries=len(state["entries"]))
        if correction:
            result = result.model_copy(update={"output": {**(result.output or {}), "correction": correction}})
        return result

    async def record_context(self, message):
        await self.context.record(message)
        if message.role == "tool":
            self.pending_calls.discard(message.tool_call_id)
            if not self.pending_calls:
                self.run["pending_response"] = None

    async def emit(self, event: AgentEvent):
        self._emit_event(event)

    async def emit_with_steps(self, event: AgentEvent, steps):
        with self.owner.store.transaction(run=self.run):
            observer_steps.sync_steps(self.run, steps)
            previous_sequence = self.run["last_event_sequence"]
            self._emit_event(event)
            # 被过滤的核心工具事件也要落盘步骤快照；真实生命周期仍只发布一次。
            if (self.run["last_event_sequence"] == previous_sequence
                    and not event.type.value.startswith("run.")):
                self.owner.store.save_run_state(self.run)

    def _emit_event(self, event: AgentEvent):
        kind = event.type.value
        payload = {**event.payload, **({"step_id": event.step_id} if event.step_id else {})}
        if kind.removeprefix("run.") in {"completed", "failed", "cancelled", "timed_out", "limit_exceeded"}:
            # 终态与最终消息在本机宿主事务中一起提交，避免先显示完成后消息写入失败。
            self.terminal_payload = event.payload
            return
        if kind == "run.started":
            self.run["status"] = "running"
        if kind == "output.validation_started":
            self.run["verification_state"] = "started"
        if kind == "output.validation_failed" and event.payload.get("will_retry"):
            self.run["verification_retries"] = self.run.get("verification_retries", 0) + 1
        if kind == "run.started":
            self.owner.event(self.run, kind, **payload, completion_contract_version="1.0",
                             collaboration_mode=self.run.get("collaboration_mode", "default"),
                             completion_requirements=self.run.get("completion_requirements", []))
            return
        if kind == "model.completed":
            for key in ("input_tokens", "output_tokens", "cached_tokens"):
                self.run[key] += event.payload.get(key) or 0
            payload["usage_complete"] = self.last_usage_complete
            if not self.last_usage_complete:
                payload.update(input_tokens=None, output_tokens=None, cached_tokens=None, cost_usd=None)
            self.owner.event(self.run, kind, **payload)
            return
        if kind.startswith("tool."):
            # 工具生命周期由本机执行器在审批前后和副作用边界准确记录。
            name = event.payload.get("name")
            registered = name in self.exposed_tool_names and name in self.owner.registry and self.owner.registry[name].available(
                self.run["permission_mode"], self.run.get("execution_contract_version"))
            if not registered:
                if kind == "tool.requested":
                    self.run["tool_call_count"] += 1
                self.owner.event(self.run, kind, **payload)
            return
        self.owner.event(self.run, kind, **payload)

    async def latest_sequence(self, run_id: str) -> int:
        return self.run["last_event_sequence"]
