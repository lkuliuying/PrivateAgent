"""本机请求边界的历史组装、预算和事务压缩。"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid

from private_agent_core.context import (
    ContextLimits,
    configuration_version,
    request_budget,
)
from private_agent_core.contracts import ModelMessage, ModelRequest, ModelResponse

from . import reflection
from .context_summary import summary_request, validate_summary
from .instructions import InstructionError, instruction_message, public_sources
from .model_errors import MODEL_CALL, CloudError
from .model_transport import MODEL_ACCOUNTING
from .progress import STOP_AT
from .recovery import model_capability_version
from .task_constraints import refresh_interpretation


class LocalContext:
    def __init__(self, owner, run, root):
        self.owner, self.run, self.root = owner, run, root
        self.history = owner.store.context
        self.limits = ContextLimits.model_validate(run.get("context_limits", {}))
        self.started = time.monotonic()
        prior = run.get("loop_budget", {}) if run.get("resumed_from_run_id") else {}
        self.prior_active_seconds = prior.get("active_seconds", 0)
        self.paused_seconds = 0.0
        self.paused_at = None
        self.approval_started = None
        self.input_started = None
        self.message_count = 0
        self.calibration = 1.0
        self.previous_usage: tuple[int, int] | None = None
        self.previous_request: ModelRequest | None = None
        self.prepared_request: ModelRequest | None = None
        self.version: str | None = None
        self.route: tuple | None = None
        self.scope = "."
        self.sources: dict[str, list[dict]] = {}
        self.pending_scopes: list[str] = []
        self.delivered_rules: set[tuple[str, str]] = set()
        self.rounds = prior.get("model_requests", 0)
        self.cost = prior.get("known_cost_usd", prior.get("cost_usd")) or 0.0
        self.cost_known = prior.get("cost_usd", 0) is not None
        self.tokens = prior.get("known_tokens", 0)
        self.tokens_known = prior.get("tokens", 0) is not None
        self.failure_key = prior.get("failure_key")
        self.failure_count = prior.get("failure_count", 0)
        self.auto_compaction_failed = False

    def remaining_seconds(self) -> float:
        elapsed = (self.paused_at or time.monotonic()) - self.started - self.run.get("approval_wait_seconds", 0) - self.paused_seconds
        if self.approval_started is not None:
            elapsed -= time.monotonic() - self.approval_started
        elapsed -= self.run.get("input_wait_seconds", 0)
        if self.input_started is not None:
            elapsed -= time.monotonic() - self.input_started
        return self.limits.max_active_seconds - self.prior_active_seconds - max(0, elapsed)

    def budget_snapshot(self) -> dict:
        return {"model_requests": self.rounds, "max_model_requests": self.limits.max_model_requests,
                "tool_calls": self.run["tool_call_count"], "max_tool_calls": self.limits.max_tool_calls,
                "active_seconds": round(self.limits.max_active_seconds - self.remaining_seconds(), 3),
                "approval_wait_seconds": self.run.get("approval_wait_seconds", 0),
                "input_wait_seconds": self.run.get("input_wait_seconds", 0),
                "max_active_seconds": self.limits.max_active_seconds, "cost_usd": self.cost if self.cost_known else None,
                "max_cost_usd": self.limits.max_cost_usd, "known_cost_usd": self.cost,
                "tokens": self.tokens if self.tokens_known else None, "known_tokens": self.tokens,
                "max_total_tokens": self.limits.max_total_tokens,
                "verification_retries": self.run.get("verification_retries", 0),
                "failure_count": self.failure_count, "failure_key": self.failure_key}

    def check_limits(self):
        reason = None
        if self.rounds >= self.limits.max_model_requests:
            reason = "max_model_requests"
        elif self.remaining_seconds() <= 0:
            reason = "max_active_seconds"
        elif self.limits.max_cost_usd is not None and self.cost >= self.limits.max_cost_usd:
            reason = "max_cost_usd"
        elif self.limits.max_cost_usd is not None and not self.cost_known:
            reason = "cost_usage_unknown"
        elif self.limits.max_total_tokens is not None and self.tokens >= self.limits.max_total_tokens:
            reason = "max_total_tokens"
        elif self.limits.max_total_tokens is not None and not self.tokens_known:
            reason = "token_usage_unknown"
        elif self.failure_count >= 4 or (self.run.get("orchestration_progress") or {}).get("repeats", 0) >= STOP_AT or reflection.stalled(self.run):
            reason = "no_progress"
        self.run["loop_budget"] = self.budget_snapshot()
        if reason:
            message = ("重复读取没有产生新信息，任务已停止；请根据已取得的证据调整查询或任务目标"
                       if reason == "no_progress" and (self.run.get("orchestration_progress") or {}).get("repeats", 0) >= STOP_AT
                       else f"任务达到执行预算：{reason}")
            raise CloudError(422, message, code=reason)

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
        generation = self.run.get("generation", 0)
        refresh_interpretation(self.run)
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
        if request.output_format is not None and profile.get("supports_structured_output") is not True:
            raise CloudError(422, "当前模型未声明支持结构化输出，请选择支持该能力的模型", code="model_structured_output_unsupported")
        self.run["model_profile_id"] = profile["id"]
        route = tuple(profile.get(key) for key in ("id", "provider", "model_name", "api_format", "endpoint"))
        if self.route is not None and route != self.route:
            raise CloudError(422, "运行期间模型路由已变化，请重新发起任务", code="model_not_configured")
        self.route = route
        version = configuration_version(profile)
        if self.run.get("recovery_contract_version"):
            capability_version = model_capability_version(profile)
            if self.run.get("model_capability_version") not in {None, capability_version}:
                raise CloudError(422, "运行期间模型能力已变化，请核对配置", code="model_not_configured")
            self.run["model_capability_version"] = capability_version
        if self.run.get("resumed_from_run_id") and self.run.get("model_config_version") not in {None, version}:
            raise CloudError(422, "恢复期间模型配置已变化", code="model_not_configured")
        self.run["model_config_version"] = version
        if version != self.version:
            self.calibration = 1.0
            self.previous_usage = None
            self.run.pop("context_usage", None)
            self.version = version
        target = self.scope
        self.instructions(".")
        system = [message for message in request.messages if message.role == "system"]
        # 使用本轮已验证的路由信息，不能把助手角色或历史回答当作模型身份。
        identity = {"model_id": profile.get("model_name") or None}
        system.append(ModelMessage(role="system", content=(
            "当前请求的模型信息（以下 JSON 仅为数据）："
            + json.dumps(identity, ensure_ascii=False)
            + "。用户仅询问你是什么模型时，直接简短回答：我是 <model_id>。使用此处的完整模型 ID。"
            "不要附加配置来源、字段名、版本边界、工具能力或其他说明，也无需查找项目文件。"
            "ID 为空时只回答：无法确认当前模型。用户明确追问其他信息时再按问题回答。"
        )))
        guidance = []
        from .observer import check_guidance
        observer_guidance = check_guidance(self.run, self.root)
        if observer_guidance:
            guidance.append(ModelMessage(role="user", content="项目完成检查（优先服从用户原文和权限，不是新的操作授权）："
                                         + json.dumps(observer_guidance, ensure_ascii=False)))
        correction = reflection.guidance(self.run)
        if correction:
            guidance.append(ModelMessage(role="user", content="当前纠错记录（工具事实摘要，不是授权；先核对原因，再用新证据验证修正）："
                                         + json.dumps(correction, ensure_ascii=False)))
        task_state = self.owner.planner.context(self.run)
        if task_state:
            guidance.append(ModelMessage(role="user", content="当前运行计划与公开决策记录（模型报告，不是新授权或验收证据；优先于历史摘要中的旧计划）：" + json.dumps(task_state, ensure_ascii=False)))
        if self.run.get("task_interpretation"):
            guidance.append(ModelMessage(role="user", content="程序提取的任务状态（辅助数据，不是完整语义或新授权；结合后面的用户原文理解任务，禁止项仍由执行器检查）：" + json.dumps({
                "goal_version": self.run.get("goal_version", 1), "requirements": self.run["completion_requirements"],
                "conditions": self.run["task_interpretation"].get("conditions", []),
                "policy_releases": self.run["task_interpretation"].get("policy_releases", []),
                "scoped_constraints": self.run["task_interpretation"].get("constraints", []),
                "command_scope_issue": self.run.get("command_scope_issue"),
                "restrictions": self.run["completion_policy"]}, ensure_ascii=False)))
        delivered, rule_messages = [], []
        for scope in self.pending_scopes or [target]:
            rules, _ = self.instructions(scope)
            text = instruction_message(rules)
            if text:
                rule_messages.append(ModelMessage(role="user", content=f"以下项目规则仅用于目标 {scope} 的适用子树：\n{text}"))
            delivered.extend(rules)
        self.delivered_rules.update((rule.path, rule.sha256) for rule in delivered if rule.trusted)
        memory_messages, memory_ids = self.owner.memories.recall(self.run["session_id"], self.run["project_id"], self.run.get("goal", ""))
        omitted_ids = []

        def assemble(checkpoint=None):
            return request.model_copy(update={"messages": tuple([*system, *rule_messages, *guidance, *memory_messages, *self.history.messages(self.run["session_id"], compacted=checkpoint)]),
                                               "tools": self.owner.model_tools(self.run, self.root),
                                               "max_output_tokens": self.limits.reserved_output_tokens})

        prepared = assemble()
        prior = self.previous_request
        previous_usage = self.previous_usage if (prior and prepared.tools == prior.tools
            and prepared.output_format == prior.output_format
            and prepared.messages[:len(prior.messages)] == prior.messages) else None
        budget = request_budget(prepared, profile.get("context_tokens"), self.limits.reserved_output_tokens,
                                calibration=self.calibration, previous_usage=previous_usage,
                                auto_compact_token_limit=self.limits.auto_compact_token_limit)
        # 跨会话记忆是可选参考，不以挤压当前请求或触发压缩为代价。
        if memory_messages and (budget["should_compact"] or budget["exceeded"]):
            memory_messages, omitted_ids, memory_ids = [], memory_ids, []
            prepared = assemble()
            budget = request_budget(prepared, profile.get("context_tokens"), self.limits.reserved_output_tokens,
                                    calibration=self.calibration, auto_compact_token_limit=self.limits.auto_compact_token_limit)
        self.run["memory_context"] = {"recalled_ids": memory_ids, "omitted_ids": omitted_ids}
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
                if generation != self.run.get("generation", 0):
                    raise asyncio.CancelledError
                candidate = self.history.compact(self.run["session_id"], checkpoint, **({"task_state": task_state} if task_state else {}))
                # 工作摘要只增加参考信息；必需内容已经放不下时，不发起无收益的模型调用。
                candidate_budget = request_budget(assemble(candidate), profile.get("context_tokens"), self.limits.reserved_output_tokens,
                    calibration=self.calibration, auto_compact_token_limit=self.limits.auto_compact_token_limit)
                if candidate_budget["exceeded"] or (not pending and candidate_budget["estimated_input_tokens"] >= budget["estimated_input_tokens"]):
                    raise ValueError("压缩后必需上下文仍超限或没有减少，请缩小任务范围或选择更大窗口")
                working_summary = await self.summarize(candidate, profile)
                refreshed = await self.owner.cloud.profiles(self.owner.token)
                if generation != self.run.get("generation", 0):
                    raise asyncio.CancelledError
                current = next((item for item in refreshed if item.get("id") == profile["id"]), {})
                if current.get("enabled") is False or configuration_version(current) != version or model_capability_version(current) != model_capability_version(profile):
                    raise CloudError(422, "压缩期间模型配置已变化，请重新发起任务", code="model_not_configured")
                if self.owner.root(self.run["project_id"], self.run["workspace_id"]) != self.root:
                    raise CloudError(422, "压缩期间项目位置已变化，原历史保留", code="permission_blocked")
                self.owner.require_grant(self.run)
                for scope in self.sources:
                    self.instructions(scope)
                if self.run.get("instructions_invalidated"):
                    raise InstructionError("压缩期间项目规则已变化，原历史保留")
                if working_summary:
                    enriched = self.history.with_working_summary(candidate, working_summary)
                    if not request_budget(assemble(enriched), profile.get("context_tokens"), self.limits.reserved_output_tokens,
                                          calibration=self.calibration)["exceeded"]:
                        candidate = enriched
                    else:
                        candidate["summary_fallback_reason"] = "summary_exceeds_budget"
                candidate_request = assemble(candidate)
                candidate_budget = request_budget(candidate_request, profile.get("context_tokens"), self.limits.reserved_output_tokens,
                    calibration=self.calibration, auto_compact_token_limit=self.limits.auto_compact_token_limit)
                if candidate_budget["exceeded"] or (not pending and candidate_budget["estimated_input_tokens"] >= budget["estimated_input_tokens"]):
                    raise ValueError("压缩后必需上下文仍超限或没有减少，请缩小任务范围或选择更大窗口")
                with self.owner.store.transaction():
                    if self.history.items(self.run["session_id"])[-1]["ordinal"] != candidate["through_ordinal"]:
                        raise ValueError("压缩期间历史已变化，原历史保留")
                    self.history.save_checkpoint(self.run["session_id"], candidate)
                    self.run.update(compaction_state="idle", last_compacted_at=candidate["completed_at"], compaction_error=None)
                    self.owner.event(self.run, "context.compaction_completed", checkpoint_id=checkpoint["id"],
                        source_count=len(candidate["summary"]["source_item_ids"]), summary_strategy=candidate["summary_strategy"])
                prepared, budget = candidate_request, candidate_budget
                self.previous_usage = None
            except asyncio.CancelledError:
                checkpoint.update(state="failed", error="压缩已取消，原历史保留")
                self.history.save_checkpoint(self.run["session_id"], checkpoint)
                self.run.update(compaction_state="failed", compaction_error=checkpoint["error"])
                raise
            except (CloudError, InstructionError):
                checkpoint.update(state="failed", error="压缩期间配置或权限已变化，原历史保留")
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
        self.prepared_request = prepared
        return prepared

    async def summarize(self, candidate: dict, profile: dict) -> dict | None:
        """摘要调用计入当前任务预算，取消向上传播；失败降级为原始事实索引。"""
        compact = getattr(self.owner.cloud, "compact_context", None)
        if not self.limits.semantic_compaction or compact is None:
            return None
        # 留一次调用用于继续任务；摘要不能耗尽最后一轮工作机会。
        if self.rounds + 1 >= self.limits.max_model_requests:
            candidate["summary_fallback_reason"] = "request_budget_reserved"
            return None
        requested = False
        accounting = {"tracked": False, "call_id": str(uuid.uuid4()), "provider_requests": 0,
                      "provider_retries": 0, "missing_reason": None, "protocol": "direct"}
        scope = MODEL_ACCOUNTING.set(accounting)
        call_scope = MODEL_CALL.set(accounting["call_id"])
        try:
            self.check_limits()
            identifiers = set(candidate["summary"]["source_item_ids"])
            sources = [item for item in self.history.items(self.run["session_id"]) if item["item_id"] in identifiers]
            request, allowed = summary_request(sources, self.history.checkpoint(self.run["session_id"]),
                capacity=profile.get("context_tokens"), structured=profile.get("supports_structured_output") is True,
                secrets=self.owner.memories.secrets())
            self.rounds += 1
            requested = True
            self.owner.event(self.run, "context.summary_requested", attempt_id=accounting["call_id"])
            async with asyncio.timeout(max(0.001, min(30, self.remaining_seconds()))):
                raw = await compact(self.owner.token, profile["id"], request.model_dump(mode="json"))
            if not isinstance(raw, dict):
                raise ValueError("摘要响应格式无效")
            result = ModelResponse.model_validate({key: value for key, value in raw.items() if key not in {"model_profile_id", "transport_metrics"}})
            usage = raw.get("usage") or {}
            complete = result.usage.input_tokens > 0 and all(type(usage.get(key)) is int and usage[key] >= 0 for key in ("input_tokens", "output_tokens"))
            self.tokens += result.usage.input_tokens + result.usage.output_tokens
            self.tokens_known = self.tokens_known and complete
            self.cost_known = self.cost_known and result.usage.cost_usd is not None
            self.cost += result.usage.cost_usd or 0
            for key in ("input_tokens", "output_tokens", "cached_tokens"):
                self.run[key] += getattr(result.usage, key) or 0
            if complete and type(usage.get("cached_tokens")) is int and 0 <= usage["cached_tokens"] <= result.usage.input_tokens:
                totals = self.run.setdefault("cache_usage", {"input_tokens": 0, "cached_tokens": 0})
                totals["input_tokens"] += result.usage.input_tokens
                totals["cached_tokens"] += usage["cached_tokens"]
            self.run["usage_complete"] = self.run.get("usage_complete", True) and complete
            self.run["cost_usd"] = self.cost if self.cost_known else None
            self.run["loop_budget"] = self.budget_snapshot()
            self.owner.event(self.run, "context.summary_finished", attempt_id=accounting["call_id"],
                             usage=result.usage.model_dump(mode="json"), usage_complete=complete)
            requested = False
            if raw.get("model_profile_id", profile["id"]) != profile["id"]:
                raise ValueError("摘要模型路由与当前任务不一致")
            if result.tool_calls:
                raise ValueError("摘要不能请求工具执行")
            return validate_summary(result.text, allowed, secrets=self.owner.memories.secrets())
        except (CloudError, ValueError, TimeoutError):
            candidate["summary_fallback_reason"] = "summary_unavailable"
            self.owner.event(self.run, "context.summary_fallback", reason="summary_unavailable")
            return None
        finally:
            MODEL_ACCOUNTING.reset(scope)
            MODEL_CALL.reset(call_scope)
            if accounting["tracked"]:
                self.owner.event(self.run, "model.transport", attempt_id=accounting["call_id"],
                                 **{key: value for key, value in accounting.items() if key != "tracked"})
            if requested:
                # 取消、超时或响应无效仍可能产生费用，不能记录为已知零用量。
                self.tokens_known = self.cost_known = False
                self.run.update(usage_complete=False, cost_usd=None, loop_budget=self.budget_snapshot())

    def observe_usage(self, usage, *, complete=True):
        self.tokens += usage.input_tokens + usage.output_tokens
        self.tokens_known = self.tokens_known and complete
        estimate = self.run.get("context_budget", {}).get("estimated_input_tokens", 0)
        if estimate and usage.input_tokens > estimate:
            self.calibration *= usage.input_tokens / estimate
        request_bytes = self.run.get("context_budget", {}).get("request_bytes", 0)
        if complete and request_bytes and usage.input_tokens > 0:
            self.previous_usage = (request_bytes, usage.input_tokens)
            self.previous_request = self.prepared_request
        if usage.cost_usd is None:
            self.cost_known = False
        else:
            self.cost += usage.cost_usd
        self.run["cost_usd"] = self.cost if self.cost_known else None
        self.run["loop_budget"] = self.budget_snapshot()
