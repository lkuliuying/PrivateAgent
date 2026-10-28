"""压缩前的证据选择与六类交接投影。

只用确定性事实（用户原文、工具执行记录、计划、纠错与验证结果）构造交接；
模型生成的解释只能作为有来源的参考，不能补造版本、权限或完成状态。
"""
from __future__ import annotations

import re

# 证据优先级：数字越小越优先；同一优先级按原始序号稳定排序。
PRIORITIES = {
    "unresolved": 1,      # 当前目标相关、尚未解决的失败证据
    "current_step": 2,    # 当前步骤依赖的接口、文件与用户决定
    "change": 3,          # 本轮真实修改及相关验证
    "prior_summary": 4,   # 仍有效的既有摘要来源
    "supporting": 5,      # 最近的普通读取与重复结果
}
WRITE_TOOLS = frozenset({"write_project_file", "apply_project_patch"})
MAX_SECTION_ITEMS = 8
TEXT_LIMIT = 200
# 摘录预算：单条最多 1000 字符；命中当前步骤词时取命中窗口，否则保留首尾。
EXCERPT_LIMIT = 1000
# 剩余预算低于该值时不再追加新摘录：太短的片段没有信息量，还会挤占批次预算。
MIN_EXCERPT_CHARS = 24


def _text(value, limit=TEXT_LIMIT) -> str:
    return " ".join(str(value or "").split())[:limit]


def excerpt_window(text: str, terms: list[str] | tuple[str, ...], limit: int = EXCERPT_LIMIT) -> dict:
    """按命中词取附近窗口，无法定位时保留首尾；结果带范围与截断标记。

    只处理公开正文（已剔除不透明状态）。预算包含省略标记本身，对任意
    limit ≥ 0 都保证 `len(excerpt) <= limit`，range 非负、不倒置且在原文范围内；
    预算不足以容纳标记时退化为无标记窗口或空摘录，绝不复制超出上限的原文。
    """
    text = text or ""
    limit = max(0, int(limit))
    if len(text) <= limit:
        return {"excerpt": text, "range": [0, len(text)], "truncated": False}
    if limit == 0:
        return {"excerpt": "", "range": [0, 0], "truncated": True}
    folded = text.casefold()
    position, matched = -1, ""
    for term in terms:
        if not term:
            continue
        found = folded.find(str(term).casefold())
        if found >= 0 and (position < 0 or found < position):
            position, matched = found, str(term)
    head_marker, tail_marker, middle_marker = "[前面省略]\n", "\n[后面省略]", "\n[中间省略]\n"
    if position < 0:
        room = limit - len(middle_marker)
        if room <= 0:
            # 连中间省略标记都放不下：只给出上限内的开头片段，仍标记为截断。
            return {"excerpt": text[:limit], "range": [0, limit], "truncated": True}
        head = max(1, room * 7 // 10)
        tail = room - head
        excerpt = text[:head] + middle_marker + (text[-tail:] if tail > 0 else "")
        return {"excerpt": excerpt, "range": [0, 0], "truncated": True}
    # 命中位置前后各留一部分上下文，尽量让结论本身完整落在窗口内。
    margin = len(head_marker) + len(tail_marker)
    if limit <= margin + 4:
        # 预算太小时标记没有意义：只取命中附近的正文，不添加任何标记。
        size = limit
        start = max(0, min(len(text) - size, position - size // 3))
        end = min(len(text), start + size)
        start = max(0, end - size)
        return {"excerpt": text[start:end], "range": [start, end], "truncated": True}
    budget = limit - margin
    # 命中词本身优先完整落入窗口；放不下时才允许窗口截断它。
    lead = max(0, (budget - len(matched)) // 3)
    start = max(0, position - lead)
    end = min(len(text), start + budget)
    start = max(0, end - budget)
    if not start <= position < end:
        # 极端位置下保证命中仍在窗口内，且窗口不越界。
        start = max(0, min(position, len(text) - budget))
        end = min(len(text), start + budget)
    prefix = head_marker if start > 0 else ""
    suffix = tail_marker if end < len(text) else ""
    return {"excerpt": prefix + text[start:end] + suffix, "range": [start, end], "truncated": True}


def target_of(call: dict) -> str:
    """工具调用的公开定位信息；不含文件正文、搜索文本或命令输出。"""
    arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
    for key in ("rel_path", "item_id", "patch_set_id", "attachment_id", "source_id"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return _text(value, 120)
    if isinstance(arguments.get("query"), str):
        return "查询：" + _text(arguments["query"], 120)
    command = arguments.get("command") or arguments.get("argv")
    if isinstance(command, list):
        command = " ".join(str(part) for part in command)
    return _text(command, 120) if isinstance(command, str) else ""


def _terms_from_texts(texts) -> list[str]:
    """从文本中提取确定性定位词：路径、英文标识符与中文片段。"""
    terms: list[str] = []
    for text in texts:
        if not isinstance(text, str):
            continue
        terms.extend(re.findall(r"[A-Za-z_][A-Za-z0-9_./\\-]{2,}", text))
        terms.extend(re.findall(r"[\u3400-\u9fff]{2,4}", text))
    # 去重并保持稳定顺序，避免长标题把候选名额占满。
    return list(dict.fromkeys(term.casefold() for term in terms))[:24]


def step_terms(task_state: dict | None) -> list[str]:
    """当前步骤的确定性关键词：标题、说明中的路径与英文标识符。"""
    plan = (task_state or {}).get("plan") or {}
    items = [item for item in plan.get("items", []) if item.get("status") == "in_progress"]
    items = items or [item for item in plan.get("items", []) if item.get("status") == "pending"][:1]
    return _terms_from_texts([text for item in items for text in (item.get("title"), item.get("detail"))])


def handoff_keywords(handoff: dict) -> list[str]:
    """摘要摘录的定位词：当前步骤与验收条件中的确定性词项。"""
    plan = (handoff or {}).get("plan") or {}
    texts = [plan.get("next_step") or ""]
    texts.extend(str(item.get("text") or "") for item in plan.get("items", []))
    texts.extend(str(item.get("text") or "") for item in ((handoff or {}).get("goal") or {}).get("requirements", []))
    return _terms_from_texts(texts)


def select_evidence(prefix: list[dict], *, facts: list[dict], failures: set[str], changed: set[str],
                    task_state: dict | None, stale: set[str], dedupe: dict[str, tuple] | None = None,
                    limit: int = 64) -> list[dict]:
    """按优先级稳定排序压缩候选；同一来源只占一个名额。

    证据身份始终使用上下文条目的唯一 ID，调用与结果的目标关系按完整
    assistant/tool 组绑定，不使用可能被供应商复用的裸调用 ID 作跨组身份。
    只有调用方证明“同一范围且同一结果”的重复读取才合并，并保留最近一次；
    版本、范围或结果未知时不合并，失败结果与写入记录永不合并。
    """
    terms = step_terms(task_state)
    # 目标按组绑定：assistant 调用只作用于其后紧跟的工具结果。
    result_target: dict[str, tuple[str, str]] = {}
    pending: dict[str, tuple[str, str]] = {}
    for item in prefix:
        message = item["message"]
        calls = message.get("tool_calls") or []
        if calls:
            pending = {call.get("id"): (call.get("name") or "", target_of(call)) for call in calls}
            continue
        if item["role"] == "tool":
            pair = pending.get(item.get("tool_call_id") or "")
            # 组内找不到对应调用时只保留消息自带名称，不跨组猜测目标。
            result_target[item["item_id"]] = pair or (message.get("name") or "", "")
    keep: set[str] = set()
    repeated: dict[tuple, str] = {}
    for item in prefix:
        identifier = item["item_id"]
        key = (dedupe or {}).get(identifier)
        # 无可证明的去重键（写入、失败、版本未知）一律保留。
        if not key:
            keep.add(identifier)
            continue
        repeated[key] = identifier
    keep.update(repeated.values())
    selected = []
    for item in prefix:
        identifier, role = item["item_id"], item["role"]
        if identifier not in keep:
            continue
        message = item["message"]
        calls = message.get("tool_calls") or []
        if role == "tool":
            name, target = result_target.get(identifier, (message.get("name") or "", ""))
        elif calls:
            # 调用本身也按其参数参与当前步骤匹配，避免只选中调用而漏掉结果。
            name = " ".join(str(call.get("name") or "") for call in calls)
            target = " ".join(target_of(call) for call in calls)
        else:
            name, target = "", ""
        haystack = (name + " " + target).casefold()
        matches = [term for term in terms if term in haystack]
        if identifier in failures and role == "tool":
            priority, reason = PRIORITIES["unresolved"], "failed_result"
        elif identifier in changed and role == "tool":
            priority, reason = PRIORITIES["change"], "changed_file"
        elif matches:
            priority, reason = PRIORITIES["current_step"], "current_step:" + matches[0]
        elif identifier in stale:
            priority, reason = PRIORITIES["prior_summary"], "stale_evidence"
        else:
            priority, reason = PRIORITIES["supporting"], "recent_support"
        selected.append({"item_id": identifier, "priority": priority, "reason": reason,
                         "ordinal": item.get("ordinal", 0), "stale": identifier in stale})
    selected.sort(key=lambda entry: (entry["priority"], entry["ordinal"]))
    return selected[:limit]


def _source_ids(prefix: list[dict], limit: int = 4) -> list[str]:
    """现行限制来自用户原文；只附最近的真实用户来源标识。"""
    return [item["item_id"] for item in prefix if item["role"] == "user"][-limit:]


def _policy_items(policy: dict, sources: list[str]) -> list[dict]:
    items = []

    def add(text: str, kind: str = "user_requirement"):
        items.append({"category": "constraint", "kind": kind, "text": _text(text),
                      "source_item_ids": list(sources), "version": None, "stale": False})

    if policy.get("preview_only"):
        add("用户要求只调研并汇报，不实施修改")
    if policy.get("writes_forbidden"):
        add("用户禁止修改文件")
    if policy.get("commands_forbidden"):
        add("用户要求不运行命令")
    if policy.get("tests_forbidden"):
        add("用户禁止运行测试")
    if policy.get("network_forbidden"):
        add("用户禁止联网，外部请求不执行")
    for path in policy.get("forbidden_write_paths", [])[:4]:
        add(f"禁止修改路径：{path}")
    for group in policy.get("access_scopes", [])[:2]:
        add("限定读取路径：" + "、".join(str(path) for path in group)[:160])
    for group in policy.get("write_scopes", [])[:2]:
        add("限定修改路径：" + "、".join(str(path) for path in group)[:160])
    for note in policy.get("unperformed", [])[:2]:
        add(note, kind="note")
    return items[:MAX_SECTION_ITEMS]


def _goal_items(run: dict) -> list[dict]:
    items = []
    for requirement in (run.get("completion_requirements") or [])[:MAX_SECTION_ITEMS]:
        items.append({"category": "requirement",
                      "kind": "user_requirement" if requirement.get("origin") == "user" else "unknown",
                      "text": _text(requirement.get("description"), 240),
                      "source_item_ids": [], "version": None, "stale": False,
                      "requirement_id": requirement.get("requirement_id"),
                      "required": bool(requirement.get("required", True))})
    return items


def _plan_items(task_state: dict | None) -> list[dict]:
    plan = (task_state or {}).get("plan") or {}
    return [{"category": "plan_step", "kind": "model_report", "text": _text(item.get("title")),
             "status": item.get("status"), "source_item_ids": [], "version": None, "stale": False}
            for item in (plan.get("items") or [])][:MAX_SECTION_ITEMS]


def _next_step(task_state: dict | None) -> str | None:
    plan = (task_state or {}).get("plan") or {}
    items = plan.get("items") or []
    for status in ("in_progress", "pending"):
        for item in items:
            if item.get("status") == status:
                return _text(item.get("title"), 240)
    return None


def _decision_items(task_state: dict | None) -> list[dict]:
    return [{"category": "decision", "kind": "model_report", "text": _text(note.get("text")),
             "source_item_ids": [note["content_ref"]] if note.get("content_ref") else [],
             "version": None, "stale": False}
            for note in ((task_state or {}).get("decisions") or [])][:4]


def _finding_items(facts: list[dict], evidence: list[dict], failures: set[str], changed: set[str],
                   excerpt_ids: list[str], resolved: list[dict]) -> list[dict]:
    """关键发现只陈述可核对的工具事实，模型解释单独标注为报告。"""
    order = {entry["item_id"]: index for index, entry in enumerate(evidence)}
    items = []
    for fact in facts:
        if fact["result_item_id"] not in failures and fact["result_item_id"] not in changed:
            continue
        items.append({"category": "finding", "kind": "observation",
                      "text": _text(f"{fact['tool']} {fact.get('target') or ''} "
                                    + ("失败" if fact["result_item_id"] in failures else "已修改")),
                      "source_item_ids": [fact["call_item_id"], fact["result_item_id"]],
                      "version": fact.get("version"), "stale": fact.get("stale", False)})
    # 已有可信解决证据的历史失败仍作为事实保留，但不再列为未解决。
    for fact in resolved:
        if len(items) >= MAX_SECTION_ITEMS:
            break
        items.append({"category": "finding", "kind": "observation", "resolved": True,
                      "text": _text(f"{fact['tool']} {fact.get('target') or ''} 此前失败，已由同目标成功调用解决"),
                      "source_item_ids": [fact["result_item_id"]],
                      "version": fact.get("version"), "stale": fact.get("stale", False)})
    # 与当前步骤相关的普通读取作为辅助发现，排在失败与修改之后。
    for entry in sorted(evidence, key=lambda item: order.get(item["item_id"], 0))[:MAX_SECTION_ITEMS]:
        if len(items) >= MAX_SECTION_ITEMS:
            break
        if entry["priority"] != PRIORITIES["current_step"] or entry["item_id"] in excerpt_ids:
            continue
        items.append({"category": "finding", "kind": "observation",
                      "text": _text("相关证据：" + entry["reason"]),
                      "source_item_ids": [entry["item_id"]],
                      "version": None, "stale": entry["stale"]})
    return items[:MAX_SECTION_ITEMS]


def _change_items(changes: list[dict], workspace_version: int | None, outcome: dict | None) -> list[dict]:
    verified = (outcome or {}).get("goal_outcome") == "verified"
    items = []
    for change in changes:
        stale = workspace_version is not None and change.get("version") != workspace_version
        items.append({"category": "change", "kind": "observation",
                      "text": _text(f"修改 {change.get('target') or '文件'}"),
                      "source_item_ids": [change["result_item_id"]],
                      "version": None if change.get("version") is None else f"workspace:{change['version']}",
                      # 修改成功不等于验证成功；工作区后续变化时旧验证不再成立。
                      "verified": "passed" if verified and not stale else "unknown",
                      "stale": stale})
    return items[:MAX_SECTION_ITEMS]


def _split_failures(run: dict, facts: list[dict], failures: set[str]) -> tuple[list[dict], list[dict], list[dict]]:
    """区分当前未解决、已有可信解决证据与状态未知的失败事实。

    只使用纠错状态中同目标的 open/resolved 记录：无关成功不会清除失败，
    已解决的历史失败也不会被重新打开；没有对应记录时归入“待核对”，不伪造结论。
    """
    entries = (run.get("reflection_state") or {}).get("entries") or []
    open_targets = {entry.get("target_hash") for entry in entries if entry.get("status") == "open"}
    resolved_targets = {entry.get("target_hash") for entry in entries
                        if entry.get("status") in {"resolved", "superseded"}}
    opened, resolved, unknown = [], [], []
    for fact in facts:
        if fact["result_item_id"] not in failures:
            continue
        target = fact.get("target_hash")
        if target and target in open_targets:
            opened.append(fact)
        elif target and target in resolved_targets:
            resolved.append(fact)
        else:
            unknown.append(fact)
    return opened, resolved, unknown


def _unresolved_items(run: dict, opened: list[dict], unknown: list[dict],
                      task_state: dict | None) -> list[dict]:
    items = []
    entries = [entry for entry in ((run.get("reflection_state") or {}).get("entries") or [])
               if entry.get("status") == "open"]
    by_target = {fact.get("target_hash"): fact for fact in opened if fact.get("target_hash")}
    for entry in entries[-MAX_SECTION_ITEMS:]:
        fact = by_target.pop(entry.get("target_hash"), None)
        items.append({"category": "unresolved", "kind": "observation", "state": "open",
                      "text": _text(f"{entry.get('tool_name') or '工具'} 未解决：{entry.get('error_code')} "
                                    f"（尝试 {entry.get('attempts')} 次）"),
                      "source_item_ids": [fact["result_item_id"]] if fact else [],
                      "version": fact.get("version") if fact else None, "stale": False,
                      "attempts": entry.get("attempts"), "error_code": entry.get("error_code")})
    for fact in opened:
        if len(items) >= MAX_SECTION_ITEMS:
            break
        if any(fact["result_item_id"] in item["source_item_ids"] for item in items):
            continue
        items.append({"category": "unresolved", "kind": "observation", "state": "open",
                      "text": _text(f"失败的工具结果：{fact['tool']} {fact.get('target') or ''}"),
                      "source_item_ids": [fact["result_item_id"]], "version": fact.get("version"),
                      "stale": fact.get("stale", False)})
    # 没有纠错记录可核对的失败：保留来源并标“待核对”，不声称已解决。
    for fact in unknown:
        if len(items) >= MAX_SECTION_ITEMS:
            break
        items.append({"category": "unresolved", "kind": "observation", "state": "unknown",
                      "text": _text(f"失败需核对：{fact['tool']} {fact.get('target') or ''}"),
                      "source_item_ids": [fact["result_item_id"]], "version": fact.get("version"),
                      "stale": fact.get("stale", False)})
    plan = (task_state or {}).get("plan") or {}
    if plan.get("needs_review"):
        items.append({"category": "unresolved", "kind": "observation", "state": "unknown",
                      "text": "计划待复核：目标已变化", "source_item_ids": [], "version": None, "stale": False})
    for message in (run.get("run_outcome") or {}).get("unverified_items", [])[:4]:
        items.append({"category": "unresolved", "kind": "observation", "state": "unknown",
                      "text": _text(message), "source_item_ids": [], "version": None, "stale": False})
    return items[:MAX_SECTION_ITEMS]


def build_handoff(*, run: dict, task_state: dict | None, prefix: list[dict], evidence: list[dict],
                  facts: list[dict], failures: set[str], changes: list[dict], streak: set[str],
                  workspace_version: int | None, excerpts: list[dict]) -> dict:
    """形成六类交接内容；来源不足的类别明确写 unknown。"""
    sources = _source_ids(prefix)
    goal_items = _goal_items(run)
    constraints = _policy_items(run.get("completion_policy") or {}, sources)
    plan_items = _plan_items(task_state)
    excerpt_ids = [entry["source_item_id"] for entry in excerpts]
    opened_facts, resolved_facts, unknown_facts = _split_failures(run, facts, failures)
    findings = _finding_items(facts, evidence, failures, {item["result_item_id"] for item in changes},
                              excerpt_ids, resolved_facts)
    # 助手历史分析只能作为报告，且必须带来源；不覆盖工具事实。
    for excerpt in excerpts[:4]:
        if len(findings) >= MAX_SECTION_ITEMS:
            break
        findings.append({"category": "finding", "kind": "model_report", "text": _text(excerpt["excerpt"]),
                         "source_item_ids": [excerpt["source_item_id"]], "version": None,
                         "stale": excerpt["source_item_id"] in streak})
    findings.extend(_decision_items(task_state))
    findings = findings[:MAX_SECTION_ITEMS]
    change_items = _change_items(changes, workspace_version, run.get("run_outcome"))
    unresolved = _unresolved_items(run, opened_facts, unknown_facts, task_state)
    stale_any = any(entry["stale"] for entry in change_items)
    unverified_any = any(entry.get("state") == "unknown" for entry in unresolved)

    def section(items: list[dict], note: str, *, status: str | None = None) -> dict:
        value = {"status": status or ("known" if items else "unknown"), "items": items, "note": note}
        return value

    return {"version": "1.0",
            "goal": {"status": "known" if goal_items or run.get("goal_version") else "unknown",
                     "goal_version": run.get("goal_version"),
                     "source_item_ids": sources[-1:] if sources else [],
                     "requirements": goal_items,
                     "note": "程序从用户原文投影的目标与验收条件，不由模型重写授权"},
            "constraints": section(constraints, "现行限制来自用户原文与确定性策略，执行器每轮重新检查；摘要不能解除"),
            "plan": {"status": "known" if task_state else "unknown",
                     "goal_version": ((task_state or {}).get("plan") or {}).get("goal_version"),
                     "next_step": _next_step(task_state), "items": plan_items,
                     "note": "当前计划优先于旧摘要中的计划；步骤勾选不是验收证据"},
            "findings": section(findings, "观察与用户要求、模型报告分开标注；模型解释不能补造版本"),
            "changes": section(change_items, "修改成功不等于验证成功；工作区版本变化后旧验证需重新核对",
                               status="recheck_required" if stale_any else None),
            "unresolved": section(unresolved, "未解决问题不会因无关成功读取而清除；状态未知的失败标为待核对",
                                  status="recheck_required" if unverified_any and not opened_facts else None)}
