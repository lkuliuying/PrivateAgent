"""把本机模型、工具与 SQLite 事件接入共享 AgentRuntime。"""
from __future__ import annotations

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


class LocalRunAdapter:
    def __init__(self, owner, run: dict, root):
        self.owner, self.run, self.root = owner, run, root
        self.rounds = 0
        self.model_error: CloudError | None = None
        self.terminal_payload: dict = {}

    async def complete(self, request: ModelRequest, *, cancellation: CancellationToken) -> ModelResponse:
        cancellation.raise_if_cancelled()
        self.rounds += 1
        if self.rounds > 24 or len(request.messages) > 90 or len(request.model_dump_json().encode()) > 1_500_000:
            self.model_error = CloudError(422, "本机上下文或模型轮次达到上限，请缩小任务范围", code="context_limit")
            raise self.model_error
        try:
            raw = await self.owner.cloud.complete(self.owner.token, self.run["model_profile_id"], request.model_dump(mode="json"))
            # 路由元数据只用于本机记录，不扩展共享模型响应契约。
            selected_profile_id = raw.pop("model_profile_id", None)
            if selected_profile_id is not None and (not isinstance(selected_profile_id, str)
                    or not 1 <= len(selected_profile_id) <= 128
                    or (self.run["model_profile_id"] and self.run["model_profile_id"] != selected_profile_id)):
                raise ValueError("模型路由与当前运行不一致")
            result = ModelResponse.model_validate(raw)
            if len(result.tool_calls) > 8:
                raise ValueError("模型工具请求超出限制")
        except (ValidationError, ValueError):
            self.model_error = CloudError(502, "服务器模型响应格式无效", code="model_invalid_response")
            raise self.model_error from None
        except CloudError as error:
            self.model_error = error
            raise
        usage = raw.get("usage") or {}
        # 每次请求都含系统提示；旧服务补出的全零 usage 不能充当真实计量。
        if token_count(usage.get("input_tokens")) == 0:
            usage = {}
        self.run["context_usage"] = {key: token_count(usage.get(key)) for key in ("input_tokens", "output_tokens", "cached_tokens")}
        used, cached = (token_count(usage.get(key)) for key in ("input_tokens", "cached_tokens"))
        totals = self.run.setdefault("cache_usage", {"input_tokens": 0, "cached_tokens": 0})
        if used and cached is not None and cached <= used:
            totals["input_tokens"] += used
            totals["cached_tokens"] += cached
        if selected_profile_id:
            self.run["model_profile_id"] = selected_profile_id
        self.run.update(provider=result.provider, model=result.model)
        return result

    async def execute(self, call: ToolCall, *, cancellation: CancellationToken) -> ToolResult:
        cancellation.raise_if_cancelled()
        output = await self.owner.tool(self.run, self.root, call.model_dump(mode="json"))
        if "error" in output:
            return ToolResult(tool_call_id=call.id, name=call.name, success=False, error=output["error"], error_code="local_tool_rejected")
        return ToolResult(tool_call_id=call.id, name=call.name, success=True, output=output)

    async def emit(self, event: AgentEvent):
        kind = event.type.value
        if kind.removeprefix("run.") in {"completed", "failed", "cancelled", "timed_out", "limit_exceeded"}:
            # 终态与最终消息在本机宿主事务中一起提交，避免先显示完成后消息写入失败。
            self.terminal_payload = event.payload
            return
        if kind == "run.started":
            self.run["status"] = "running"
        if kind == "model.completed":
            for key in ("input_tokens", "output_tokens", "cached_tokens"):
                self.run[key] += event.payload.get(key) or 0
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
