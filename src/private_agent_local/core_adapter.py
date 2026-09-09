"""把本机模型、工具与 SQLite 事件接入共享 AgentRuntime。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid

from pydantic import ValidationError

from private_agent_core.contracts import (
    AgentEvent,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResult,
)
from private_agent_core.runtime import CancellationToken

from .cloud import CloudError
from .context import token_count
from .context_manager import LocalContext
from .instructions import InstructionError


class LocalRunAdapter:
    def __init__(self, owner, run: dict, root):
        self.owner, self.run, self.root = owner, run, root
        self.model_error: CloudError | None = None
        self.terminal_payload: dict = {}
        self.last_usage_complete = False
        self.context = LocalContext(owner, run, root)
        owner.contexts[run["id"]] = self.context
        self.response_generation = run.get("generation", 0)

    async def complete(self, request: ModelRequest, *, cancellation: CancellationToken) -> ModelResponse:
        return await self.complete_stream(request, cancellation=cancellation)

    async def complete_stream(self, request: ModelRequest, *, cancellation: CancellationToken, on_delta=None) -> ModelResponse:
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
            self.run["pending_response"] = result.model_dump(mode="json")
            self.owner.event(self.run, "model.response_confirmed", generation=generation)
            return result

    async def _complete_attempt(self, request: ModelRequest, *, cancellation: CancellationToken, on_delta=None, generation=0) -> ModelResponse:
        cancellation.raise_if_cancelled()
        try:
            request = await self.context.prepare(request)
            self.context.check_limits()
        except CloudError as error:
            self.model_error = error
            raise
        except InstructionError as error:
            self.model_error = CloudError(422, str(error), code="instructions_unavailable")
            raise self.model_error from None
        except ValueError:
            self.model_error = CloudError(422, "上下文历史或配置无效，请检查当前会话", code="context_invalid")
            raise self.model_error from None
        try:
            self.context.rounds += 1
            self.owner.event(self.run, "model.requested", generation=generation)
            attempt_id = str(uuid.uuid4())
            partial = []
            pending = []
            size = 0

            def interrupted():
                self.run.update(usage_complete=False, cost_usd=None)
                self.context.cost_known = False
                self.owner.event(self.run, "model.output.interrupted", attempt_id=attempt_id, usage_complete=False)

            def flush():
                if pending:
                    delta = "".join(pending)
                    pending.clear()
                    self.owner.store.emit(self.run, "model.output.delta", {"attempt_id": attempt_id, "delta": delta}, lightweight=True)

            async def publish_batches():
                while True:
                    await asyncio.sleep(0.1)
                    flush()

            publisher = asyncio.create_task(publish_batches())

            async def receive(delta):
                nonlocal size
                cancellation.raise_if_cancelled()
                if generation != self.run.get("generation", 0):
                    return
                size += len(delta.encode("utf-8"))
                if size > 1024 * 1024:
                    raise ValueError("模型公开输出超出上限")
                partial.append(delta)
                pending.append(delta)
                if len(partial) == 1 or sum(len(item) for item in pending) >= 4096:
                    flush()
                if on_delta is not None:
                    await on_delta(delta)

            try:
                async with asyncio.timeout(max(0.001, self.context.remaining_seconds())):
                    stream = getattr(self.owner.cloud, "complete_stream", None)
                    profile = next((item for item in self.owner._profiles if item.get("id") == self.run["model_profile_id"]), {})
                    if stream and profile.get("supports_streaming") is True:
                        raw = await stream(self.owner.token, self.run["model_profile_id"], request.model_dump(mode="json"), on_delta=receive)
                    else:
                        raw = await self.owner.cloud.complete(self.owner.token, self.run["model_profile_id"], request.model_dump(mode="json"))
            finally:
                publisher.cancel()
                results = await asyncio.gather(publisher, return_exceptions=True)
                flush()
                if results and isinstance(results[0], Exception):
                    raise results[0]
            # 路由元数据只用于本机记录，不扩展共享模型响应契约。
            selected_profile_id = raw.pop("model_profile_id", None)
            if selected_profile_id is not None and (not isinstance(selected_profile_id, str)
                    or not 1 <= len(selected_profile_id) <= 128
                    or (self.run["model_profile_id"] and self.run["model_profile_id"] != selected_profile_id)):
                raise ValueError("模型路由与当前运行不一致")
            result = ModelResponse.model_validate(raw)
            if partial and "".join(partial) != result.text:
                raise ValueError("模型公开增量与最终响应不一致")
            if len(result.tool_calls) > 8:
                raise ValueError("模型工具请求超出限制")
        except (ValidationError, ValueError):
            interrupted()
            self.model_error = CloudError(502, "服务器模型响应格式无效", code="model_invalid_response")
            raise self.model_error from None
        except CloudError as error:
            interrupted()
            self.model_error = error
            raise
        except TimeoutError:
            interrupted()
            self.model_error = CloudError(422, "有效执行时长预算已耗尽", code="max_active_seconds")
            raise self.model_error from None
        except asyncio.CancelledError:
            interrupted()
            raise
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
        self.context.observe_usage(result.usage)
        self.owner.event(self.run, "model.output.finished", attempt_id=attempt_id, has_tool_calls=bool(result.tool_calls), usage_complete=self.last_usage_complete)
        return result

    async def execute(self, call: ToolCall, *, cancellation: CancellationToken) -> ToolResult:
        cancellation.raise_if_cancelled()
        await self.owner.controls.boundary(self.run)
        if self.response_generation != self.run.get("generation", 0):
            self.owner.event(self.run, "tool.superseded", tool_call_id=call.id, name=call.name)
            return ToolResult(tool_call_id=call.id, name=call.name, success=False, error="用户约束已更新，旧工具未执行，请重新规划", error_code="steering_superseded")
        task = asyncio.create_task(self.owner.tool(self.run, self.root, call.model_dump(mode="json")))
        self.owner.controls.tool_tasks[self.run["id"]] = {"task": task, "name": call.name}
        try:
            output = await task
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling() or self.run.get("cancel_requested_at"):
                raise
            if not self.run.get("pause_requested"):
                raise
            output = {"error": "暂停已停止当前命令，已发生的副作用保留", "error_code": "command_cancelled"}
        finally:
            self.owner.controls.tool_tasks.pop(self.run["id"], None)
        # 只有相同参数、相同失败和相同结果反复出现才累计；成功读取不视为停滞。
        if output.get("error") is not None:
            fingerprint = hashlib.sha256(json.dumps([call.name, call.arguments, output, self.run.get("workspace_version", 0)], sort_keys=True).encode()).hexdigest()
            self.context.failure_count = self.context.failure_count + 1 if fingerprint == self.context.failure_key else 1
            self.context.failure_key = fingerprint
            if self.context.failure_count == 3:
                output = {**output, "loop_warning": "相同失败已出现三次，请改变方案；再次无进展将停止"}
        else:
            self.context.failure_key, self.context.failure_count = None, 0
        self.run["pending_response"] = None
        self.owner.event(self.run, "tool.result_recorded", tool_call_id=call.id, name=call.name)
        await self.owner.controls.boundary(self.run)
        if output.get("error") is not None:
            return ToolResult(tool_call_id=call.id, name=call.name, success=False, error=output["error"],
                              error_code=output.get("error_code", "local_tool_rejected"),
                              output={key: value for key, value in output.items() if key not in {"error", "error_code"}})
        return ToolResult(tool_call_id=call.id, name=call.name, success=True, output=output)

    async def emit(self, event: AgentEvent):
        kind = event.type.value
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
            self.owner.event(self.run, kind, **event.payload, completion_contract_version="1.0",
                             completion_requirements=self.run.get("completion_requirements", []))
            return
        if kind == "model.completed":
            for key in ("input_tokens", "output_tokens", "cached_tokens"):
                self.run[key] += event.payload.get(key) or 0
            payload = {**event.payload, "usage_complete": self.last_usage_complete}
            if not self.last_usage_complete:
                payload.update(input_tokens=None, output_tokens=None, cached_tokens=None, cost_usd=None)
            self.owner.event(self.run, kind, **payload)
            return
        if kind.startswith("tool."):
            # 工具生命周期由本机执行器在审批前后和副作用边界准确记录。
            from .runtime import TOOLS, WRITE_TOOLS
            name = event.payload.get("name")
            registered = name in TOOLS and not (self.run["permission_mode"] == "readonly" and name in WRITE_TOOLS)
            if not registered:
                if kind == "tool.requested":
                    self.run["tool_call_count"] += 1
                self.owner.event(self.run, kind, **event.payload)
            return
        self.owner.event(self.run, kind, **event.payload)

    async def latest_sequence(self, run_id: str) -> int:
        return self.run["last_event_sequence"]
