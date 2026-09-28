"""关联真实调用步骤与本机事件；上下文归属不构成完成或授权证据。"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_CALL_STEP: ContextVar[tuple[str, str] | None] = ContextVar("local_observer_call_step", default=None)
_CALL_PREFIXES = ("model.", "tool.", "execution.", "patch_set.", "plan.", "context.", "input.", "progress.")
_ACTIVE = {"running", "waiting_approval"}


def plan_context(run: dict) -> dict | None:
    plan = run.get("plan")
    if not plan or plan.get("needs_review") or plan.get("goal_version") != run.get("goal_version", 1):
        return None
    active = [item for item in plan.get("items", []) if item.get("status") == "in_progress"]
    if len(active) != 1:
        return None
    return {"item_key": active[0]["item_key"], "plan_version": plan["version"],
            "goal_version": run.get("goal_version", 1), "source": "model_report"}


def sync_steps(run: dict, steps) -> None:
    """只在核心事件边界复制步骤；高频输出复用已冻结的轻量关联信息。"""
    prior = {item["id"]: item for item in run.get("steps", [])}
    current_plan = plan_context(run)
    result = []
    for step in steps:
        value = step.model_dump(mode="json")
        old = prior.get(value["id"])
        context = old.get("plan_context") if old is not None else current_plan
        if context is not None:
            value["plan_context"] = dict(context)
        if value["status"] == "running" and old is not None:
            if old.get("status") == "waiting_approval":
                value["status"] = "waiting_approval"
            if old.get("waiting_for"):
                value["waiting_for"] = old["waiting_for"]
        result.append(value)
    run["steps"] = result


def invocation_step(run: dict, *, tool_call_id: str | None = None) -> str | None:
    for step in reversed(run.get("steps", [])):
        if step.get("status") not in _ACTIVE:
            continue
        if tool_call_id is None and step.get("kind") == "model":
            return step["id"]
        if tool_call_id is not None and step.get("kind") == "tool" and step.get("tool_call_id") == tool_call_id:
            return step["id"]
    return None


@contextmanager
def call_scope(run: dict, step_id: str | None):
    """每个异步调用独立持有绑定，子任务继承原调用而不跟随随后开始的步骤。"""
    token = _CALL_STEP.set((run["id"], step_id) if step_id else None)
    try:
        yield
    finally:
        _CALL_STEP.reset(token)


def current_metadata(run: dict) -> dict:
    current = _CALL_STEP.get()
    if current is None or current[0] != run["id"]:
        return {}
    step = next((item for item in run.get("steps", []) if item["id"] == current[1]), None)
    if step is None:
        return {}
    return {"step_id": step["id"], **({"plan_context": dict(step["plan_context"])} if step.get("plan_context") else {})}


def event_metadata(run: dict, event_type: str, payload: dict, step_id: str | None) -> tuple[str | None, dict]:
    """执行标识优先于调用上下文；旧记录缺少标识时不猜测最近步骤。"""
    data = dict(payload)
    explicit = data.pop("step_id", None)
    if step_id is not None and explicit is not None and step_id != explicit:
        raise ValueError("事件步骤标识冲突")
    step_id = step_id or explicit
    if step_id is None and data.get("execution_id"):
        execution = next((item for item in run.get("executions", []) if item["id"] == data["execution_id"]), None)
        # 外部或旧执行缺少关联时，不能借当前调用把它挂到另一个步骤。
        step_id = execution.get("step_id") if execution else None
    elif step_id is None and event_type.startswith(_CALL_PREFIXES):
        step_id = current_metadata(run).get("step_id")
    if step_id is None and event_type in {"input.resolved", "input.invalidated"}:
        matches = [item for item in run.get("steps", [])
                   if data.get("input_id") and (item.get("waiting_for") or {}).get("input_id") == data["input_id"]]
        if len(matches) == 1:
            step_id = matches[0]["id"]
    if step_id is not None:
        step = next((item for item in run.get("steps", []) if item["id"] == step_id), None)
        if step is None:
            raise ValueError("事件步骤不属于当前运行")
        if step.get("plan_context"):
            data["plan_context"] = dict(step["plan_context"])
    return step_id, data


def observe_wait(run: dict, event_type: str, step_id: str | None, payload: dict) -> None:
    if step_id is None:
        return
    changes = None
    if event_type == "tool.approval_required":
        changes = {"status": "waiting_approval", "waiting_for": {"approval_id": payload["approval_id"]}}
    elif event_type == "input.requested":
        changes = {"waiting_for": {"input_id": payload["pending_input"]["input_id"]}}
    elif event_type in {"tool.started", "tool.approval_resolved", "input.resolved", "input.invalidated"}:
        changes = {"status": "running", "waiting_for": None}
    if changes is not None:
        run["steps"] = [{**step, **changes} if step["id"] == step_id and step.get("status") in _ACTIVE else step
                        for step in run.get("steps", [])]


def finish_interrupted_steps(run: dict, status: str, at: str) -> None:
    if status == "completed":
        return
    state = status if status in {"cancelled", "timed_out"} else "failed"
    run["steps"] = [{**step, "status": state, "completed_at": at, "waiting_for": None,
                     "error": "运行已结束，未完成调用的结果未确认"}
                    if step.get("status") in _ACTIVE else step for step in run.get("steps", [])]
