"""本机请求边界的历史组装、预算和事务压缩。"""
from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid

from private_agent_core.context import (
    ContextLimits,
    configuration_version,
    request_budget,
)
from private_agent_core.contracts import ModelMessage, ModelRequest

from .cloud import CloudError
from .instructions import InstructionError, instruction_message, public_sources


class LocalContext:
    def __init__(self, owner, run, root):
        self.owner, self.run, self.root = owner, run, root
        self.history = owner.store.context
        self.limits = ContextLimits.model_validate(run.get("context_limits", {}))
        self.started = time.monotonic()
        self.message_count = 0
        self.calibration = 1.0
        self.version: str | None = None
        self.scope = "."
        self.sources: dict[str, list[dict]] = {}
        self.pending_scopes: list[str] = []
        self.delivered_rules: set[tuple[str, str]] = set()
        self.rounds = 0
        self.cost = 0.0
        self.cost_known = True
        self.failure_key = None
        self.failure_count = 0
        self.auto_compaction_failed = False

    def remaining_seconds(self) -> float:
        return self.limits.max_active_seconds - (time.monotonic() - self.started - self.run.get("approval_wait_seconds", 0))

    def budget_snapshot(self) -> dict:
        return {"model_requests": self.rounds, "max_model_requests": self.limits.max_model_requests,
                "tool_calls": self.run["tool_call_count"], "max_tool_calls": self.limits.max_tool_calls,
                "active_seconds": round(self.limits.max_active_seconds - self.remaining_seconds(), 3),
                "approval_wait_seconds": self.run.get("approval_wait_seconds", 0),
                "max_active_seconds": self.limits.max_active_seconds, "cost_usd": self.cost if self.cost_known else None,
                "max_cost_usd": self.limits.max_cost_usd}

    def check_limits(self):
        reason = None
        if self.rounds >= self.limits.max_model_requests:
            reason = "max_model_requests"
        elif self.remaining_seconds() <= 0:
            reason = "max_active_seconds"
        elif self.limits.max_cost_usd is not None and self.cost >= self.limits.max_cost_usd:
            reason = "max_cost_usd"
        elif self.failure_count >= 4:
            reason = "no_progress"
        self.run["loop_budget"] = self.budget_snapshot()
        if reason:
            raise CloudError(422, f"任务达到执行预算：{reason}", code=reason)

    async def record(self, message: ModelMessage):
        self.message_count += 1
        source = "tool" if message.role in {"tool", "user"} else "model"
        execution = next((item for item in reversed(self.run["executions"]) if item["tool_call_id"] == message.tool_call_id and item["tool_name"] == message.name
                          and item.get("source_sequence")), None) if message.role == "tool" else None
        self.history.append(self.run["session_id"], self.run["id"], message,
                            key=f"{self.run['id']}:core:{self.message_count}", source=source, execution=execution)

    def instructions(self, target: str, *, before_write: bool = False):
        project = self.owner.store.get("project", self.run["project_id"])
        trusted = project.get("trust_instructions") is True
        rules = self.owner.instructions.load(self.root, target, trusted=trusted)
        public = public_sources(rules)
        old = self.sources.get(target)
        known = {item["path"]: item for sources in self.sources.values() for item in sources}
        self.sources[target] = public
        self.scope = target
        self.run["instruction_sources"] = public
        self.run["instruction_scope"] = target
        applicable = {path for path, item in known.items() if item["scope"] == "." or target == item["scope"] or target.startswith(item["scope"] + "/")}
        changed = (old is not None and old != public) or bool(applicable - {item["path"] for item in public}) or any(
            item["path"] in known and known[item["path"]] != item for item in public)
        if changed:
            self.owner.event(self.run, "context.instructions_changed", sources=public, target=target)
            self.run["instructions_invalidated"] = True
        if before_write and self.run.get("instructions_invalidated"):
            raise InstructionError("活动任务中的规则或信任状态已变化；本轮写入停止，请确认规则后重新发起任务")
        unseen = any(rule.trusted and (rule.path, rule.sha256) not in self.delivered_rules for rule in rules)
        return rules, unseen

    async def prepare(self, request: ModelRequest) -> ModelRequest:
        self.check_limits()
        if self.owner.root(self.run["project_id"], self.run["workspace_id"]) != self.root:
            raise CloudError(422, "项目位置已变化", code="permission_blocked")
        self.owner.require_grant(self.run)
        await self.owner.cloud.identity(self.owner.token)
        profiles = await self.owner.cloud.profiles(self.owner.token)
        self.owner._profiles, self.owner._profiles_at = profiles, time.monotonic()
        profile = next((p for p in profiles if p.get("id") == self.run["model_profile_id"]), None) if self.run["model_profile_id"] else next((p for p in profiles if p.get("is_default")), None)
        if not profile or profile.get("enabled") is False:
            raise CloudError(422, "当前模型不可用，请刷新模型配置", code="model_not_configured")
        self.run["model_profile_id"] = profile["id"]
        version = configuration_version(profile)
        if version != self.version:
            self.calibration = 1.0
            self.run.pop("context_usage", None)
            self.version = version
        target = self.scope
        self.instructions(".")
        system = [message for message in request.messages if message.role == "system"]
        delivered = []
        for scope in self.pending_scopes or [target]:
            rules, _ = self.instructions(scope)
            text = instruction_message(rules)
            if text:
                system.append(ModelMessage(role="system", content=f"以下规则仅用于目标 {scope} 的适用子树：\n{text}"))
            delivered.extend(rules)
        self.delivered_rules.update((rule.path, rule.sha256) for rule in delivered if rule.trusted)

        def assemble(checkpoint=None):
            return request.model_copy(update={"messages": tuple([*system, *self.history.messages(self.run["session_id"], compacted=checkpoint)]),
                                               "max_output_tokens": self.limits.reserved_output_tokens})

        prepared = assemble()
        budget = request_budget(prepared, profile.get("context_tokens"), self.limits.reserved_output_tokens, calibration=self.calibration)
        pending = self.history.pending(self.run["session_id"])
        if not budget["should_compact"]:
            self.auto_compaction_failed = False
        if pending or (self.limits.auto_compact and budget["should_compact"] and not self.auto_compaction_failed):
            checkpoint = pending or self.history.begin(self.run["session_id"], "auto:" + uuid.uuid4().hex)
            checkpoint["state"] = "compacting"
            self.history.save_checkpoint(self.run["session_id"], checkpoint)
            self.run["compaction_state"] = "compacting"
            self.owner.event(self.run, "context.compaction_started", checkpoint_id=checkpoint["id"])
            try:
                # 在安全模型边界让出取消机会，生成与提交之间不允许副作用穿插。
                await asyncio.sleep(0)
                candidate = self.history.compact(self.run["session_id"], checkpoint)
                candidate_request = assemble(candidate)
                candidate_budget = request_budget(candidate_request, profile.get("context_tokens"), self.limits.reserved_output_tokens, calibration=self.calibration)
                if candidate_budget["exceeded"] or (not pending and candidate_budget["estimated_input_tokens"] >= budget["estimated_input_tokens"]):
                    raise ValueError("压缩后必需上下文仍超限或没有减少，请缩小任务范围或选择更大窗口")
                with self.owner.store.transaction():
                    self.history.save_checkpoint(self.run["session_id"], candidate)
                    self.run.update(compaction_state="idle", last_compacted_at=candidate["completed_at"], compaction_error=None)
                    self.owner.event(self.run, "context.compaction_completed", checkpoint_id=checkpoint["id"], source_count=len(candidate["summary"]["source_item_ids"]))
                prepared, budget = candidate_request, candidate_budget
            except asyncio.CancelledError:
                checkpoint.update(state="failed", error="压缩已取消，原历史保留")
                self.history.save_checkpoint(self.run["session_id"], checkpoint)
                self.run.update(compaction_state="failed", compaction_error=checkpoint["error"])
                raise
            except (ValueError, OSError, sqlite3.Error) as error:
                self.auto_compaction_failed = True
                checkpoint.update(state="failed", error=str(error) if isinstance(error, ValueError) else "压缩写入失败，原历史保留")
                self.history.save_checkpoint(self.run["session_id"], checkpoint)
                self.run.update(compaction_state="failed", compaction_error=checkpoint["error"])
                self.owner.event(self.run, "context.compaction_failed", checkpoint_id=checkpoint["id"], error=checkpoint["error"])
                if budget["exceeded"]:
                    raise CloudError(422, checkpoint["error"], code="context_limit") from None
        self.run["context_budget"] = {**budget, "model_config_version": version}
        self.owner.event(self.run, "context.prepared", **self.run["context_budget"], instruction_sources=self.run["instruction_sources"])
        if budget["exceeded"]:
            raise CloudError(422, "必需上下文超出模型输入预算；原历史已保留，请缩小范围或选择更大窗口", code="context_limit")
        return prepared

    def observe_usage(self, usage):
        estimate = self.run.get("context_budget", {}).get("estimated_input_tokens", 0)
        if estimate and usage.input_tokens > estimate:
            self.calibration *= usage.input_tokens / estimate
        if usage.cost_usd is None:
            self.cost_known = False
        else:
            self.cost += usage.cost_usd
        self.run["cost_usd"] = self.cost if self.cost_known else None
        self.run["loop_budget"] = self.budget_snapshot()
