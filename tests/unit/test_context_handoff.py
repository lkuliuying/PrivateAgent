"""M2：证据优先级、去重、六类交接内容与旧检查点兼容。"""
import json

import pytest
from test_local_context_history import history_store

from private_agent_core.contracts import ModelMessage, ToolCall
from private_agent_local.context_handoff import (
    PRIORITIES,
    excerpt_window,
    select_evidence,
)
from private_agent_local.context_summary import summary_request
from private_agent_local.reflection import target_hash


def group(store, session, *, key, name="read_code_file", rel_path="src/app.py", success=True, run="run",
          execution=None, content=None, tool_call_id=None, arguments=None):
    """写入一个完整调用组：助手调用与工具结果同一配对。"""
    call = ToolCall(id=tool_call_id or f"call-{key}", name=name,
                    arguments=arguments if arguments is not None else {"rel_path": rel_path})
    assistant = store.context.append(session, run, ModelMessage(role="assistant", content="", tool_calls=(call,)),
                                    key=f"{key}:call", source="model")
    body = content if content is not None else json.dumps({"success": success, "output": {"content": "x" * 800}})
    result = store.context.append(session, run, ModelMessage(role="tool", name=name, tool_call_id=call.id, content=body),
                                  key=f"{key}:result", source="tool", execution=execution)
    return assistant, result


def test_handoff_keeps_early_failure_constraints_and_goal_after_two_compactions(tmp_path):
    store, session = history_store(tmp_path)
    try:
        goal = store.context.append(session, "run", ModelMessage(role="user", content="只读取 src，禁止修改 secrets.txt"),
                                    key="goal", source="user")
        _, failed = group(store, session, key="early", rel_path="src/missing.py", success=False,
                          content=json.dumps({"success": False, "error_code": "file_not_found"}))
        for index in range(30):
            group(store, session, key=f"noise-{index}", rel_path=f"src/noise-{index}.py")
        run = {"goal_version": 2, "completion_policy": {"forbidden_write_paths": ["secrets.txt"]},
               "completion_requirements": [{"requirement_id": "r1", "description": "只读取 src 并报告",
                                            "required": True, "origin": "user"}]}
        first = store.context.compact(session, store.context.begin(session, "first"), run=run)
        store.context.save_checkpoint(session, first)
        for index in range(30, 40):
            group(store, session, key=f"noise-{index}", rel_path=f"src/noise-{index}.py")
        plan = {"plan": {"goal_version": 2, "needs_review": False, "items": [
            {"title": "核对 src/app.py 接口", "status": "in_progress"},
            {"title": "补充验证", "status": "pending"}]},
            "decisions": [{"text": "保留现有接口", "content_ref": None}]}
        second = store.context.compact(session, store.context.begin(session, "second"), task_state=plan, run=run)
        store.context.save_checkpoint(session, second)
        handoff = second["summary"]["handoff"]
        assert handoff["version"] == "1.0"
        # 目标与验收条件是程序投影，并区分用户来源。
        assert handoff["goal"]["goal_version"] == 2
        assert [item["text"] for item in handoff["goal"]["requirements"]] == ["只读取 src 并报告"]
        assert handoff["goal"]["requirements"][0]["kind"] == "user_requirement"
        # 生效限制带原始用户来源，摘要不能解除。
        constraints = handoff["constraints"]["items"]
        assert any("secrets.txt" in item["text"] for item in constraints)
        assert all(item["source_item_ids"] == [goal["item_id"]] for item in constraints)
        # 当前计划与下一步优先于旧摘要。
        assert handoff["plan"]["next_step"] == "核对 src/app.py 接口"
        # 早期失败不因大量无关读取消失。
        failed_ids = {failed["item_id"]}
        assert failed_ids <= {source for item in handoff["findings"]["items"] for source in item["source_item_ids"]}
        assert failed_ids <= {source for item in handoff["unresolved"]["items"] for source in item["source_item_ids"]}
        evidence = {entry["item_id"]: entry for entry in second["summary"]["evidence_selection"]}
        assert evidence[failed["item_id"]]["priority"] == PRIORITIES["unresolved"]
        # 用户原文仍逐字保留在投影历史中。
        assert "只读取 src，禁止修改 secrets.txt" in [message.content for message in store.context.messages(session)
                                                      if message.role == "user"]
        assert goal["item_id"] in second["summary"]["source_item_ids"]
    finally:
        store.db.close()


def test_change_verification_is_invalidated_by_later_workspace_version(tmp_path):
    store, session = history_store(tmp_path)
    try:
        store.context.append(session, "run", ModelMessage(role="user", content="修改 src/app.py"), key="goal", source="user")
        execution = {"id": "exec-1", "operation_id": "op-1", "source_sequence": 1}
        store.save_run({"id": "run", "session_id": session, "status": "completed", "workspace_version": 2,
                        "executions": [{"id": "exec-1", "tool_name": "write_project_file", "workspace_version": 1,
                                        "tool_call_id": "call-write", "source_sequence": 1}]})
        _, changed = group(store, session, key="write", name="write_project_file", execution=execution, tool_call_id="call-write")
        group(store, session, key="after-1", rel_path="src/other.py")
        group(store, session, key="after-2", rel_path="src/other.py")
        stale = store.context.compact(session, store.context.begin(session, "stale"), run={
            "workspace_version": 2, "run_outcome": {"goal_outcome": "verified", "unverified_items": []}})
        item = next(entry for entry in stale["summary"]["handoff"]["changes"]["items"]
                    if changed["item_id"] in entry["source_item_ids"])
        assert item["stale"] is True and item["verified"] == "unknown"
        assert item["version"] == "workspace:1"
        assert stale["summary"]["handoff"]["changes"]["status"] == "recheck_required"
        current = store.context.compact(session, store.context.begin(session, "current"), run={
            "workspace_version": 1, "run_outcome": {"goal_outcome": "verified", "unverified_items": []}})
        passed = next(entry for entry in current["summary"]["handoff"]["changes"]["items"]
                      if changed["item_id"] in entry["source_item_ids"])
        assert passed["stale"] is False and passed["verified"] == "passed"
    finally:
        store.db.close()


def test_repeated_reads_do_not_consume_slots_but_failures_are_kept(tmp_path):
    store, session = history_store(tmp_path)
    try:
        store.context.append(session, "run", ModelMessage(role="user", content="检查 src/app.py"), key="goal", source="user")
        first_read = group(store, session, key="read-1", tool_call_id="same-call")
        _, failure = group(store, session, key="read-2", success=False, tool_call_id="failed-call",
                           content=json.dumps({"success": False, "error": "missing"}))
        last_read = group(store, session, key="read-3", tool_call_id="latest-call")
        group(store, session, key="tail-1")
        group(store, session, key="tail-2")
        checkpoint = store.context.compact(session, store.context.begin(session, "dedupe"),
                                           task_state={"plan": {"items": [{"title": "检查 src/app.py", "status": "in_progress"}]}})
        selected = {entry["item_id"] for entry in checkpoint["summary"]["evidence_selection"]}
        assert last_read[1]["item_id"] in selected
        assert first_read[1]["item_id"] not in selected
        assert failure["item_id"] in selected
        assert any(failure["item_id"] in item["source_item_ids"]
                   for item in checkpoint["summary"]["handoff"]["unresolved"]["items"])
    finally:
        store.db.close()


def test_handoff_marks_missing_sources_unknown_and_old_checkpoints_stay_readable(tmp_path):
    store, session = history_store(tmp_path)
    try:
        store.context.append(session, "run", ModelMessage(role="user", content="检查项目"), key="goal", source="user")
        for index in range(4):
            group(store, session, key=f"read-{index}")
        checkpoint = store.context.compact(session, store.context.begin(session, "plain"))
        handoff = checkpoint["summary"]["handoff"]
        # 没有运行状态时不伪造目标、计划或验证。
        assert handoff["goal"]["status"] == "unknown"
        assert handoff["plan"]["status"] == "unknown"
        assert handoff["plan"]["next_step"] is None
        # 只有普通成功读取时没有可交接的发现，明确写 unknown 而不是编造结论。
        assert handoff["findings"]["status"] == "unknown" and handoff["findings"]["items"] == []
        assert handoff["changes"]["status"] == "unknown" and handoff["unresolved"]["status"] == "unknown"
        # 旧检查点缺少新增派生字段仍可读取原历史。
        legacy = {key: value for key, value in checkpoint.items() if key != "compaction_metrics"}
        legacy["summary"] = {key: value for key, value in legacy["summary"].items() if key != "handoff"}
        store.context.save_checkpoint(session, legacy)
        assert store.context.checkpoint(session)["summary"].get("handoff") is None
        assert store.context.messages(session)
        page = store.context.read(session, legacy["id"], 0, 200)
        assert page["content"]
        assert store.context.items(session)
    finally:
        store.db.close()


def test_summary_request_keeps_high_priority_early_sources_and_required_state():
    items = [{"item_id": f"id-{index}", "ordinal": index + 1, "role": "tool",
              "message": {"content": "x" * 300}} for index in range(30)]
    prioritized = [f"id-{index}" for index in range(30)]
    request, refs = summary_request(items, None, capacity=32000, structured=False, prioritized=prioritized,
                                    required_state={"goal": {"goal_version": 3}})
    packet = json.loads(request.messages[-1].content)
    assert packet["required_state"]["goal"]["goal_version"] == 3
    assert len(packet["sources"]) == 24
    assert packet["sources"][0]["id"] == "id-0"
    assert "id-0" in refs
    # 容量不足时先丢最低优先级来源，最高优先级的早期证据保留。
    small, small_refs = summary_request(items, None, capacity=4096, structured=False, prioritized=prioritized,
                                        required_state={"goal": {"goal_version": 3}})
    keep = json.loads(small.messages[-1].content)
    assert 1 <= len(keep["sources"]) < 24 and keep["sources"][0]["id"] == "id-0"
    assert keep["required_state"]["goal"]["goal_version"] == 3
    # 来源顺序不做优先级要求时仍按最近优先，结果确定。
    default, _ = summary_request(items, None, capacity=32000, structured=False)
    assert json.loads(default.messages[-1].content)["sources"][0]["id"] == "id-29"


def test_select_evidence_orders_by_priority_then_ordinal():
    prefix = [
        {"item_id": "user", "role": "user", "ordinal": 1, "message": {"content": "目标"}},
        {"item_id": "noise", "role": "tool", "ordinal": 2, "message": {"content": "x", "name": "read_code_file"},
         "tool_call_id": "c-noise"},
        {"item_id": "failure", "role": "tool", "ordinal": 3, "message": {"content": "x", "name": "read_code_file"},
         "tool_call_id": "c-fail"},
        {"item_id": "change", "role": "tool", "ordinal": 4, "message": {"content": "x", "name": "write_project_file"},
         "tool_call_id": "c-write"},
    ]
    selected = select_evidence(prefix, facts=[], failures={"failure"}, changed={"change"},
                               task_state=None, stale=set())
    assert [entry["item_id"] for entry in selected] == ["failure", "change", "user", "noise"]
    assert [entry["priority"] for entry in selected] == [1, 3, 5, 5]
    assert selected[0]["reason"] == "failed_result" and selected[1]["reason"] == "changed_file"


def test_handoff_goal_section_exposes_requirements_only(tmp_path):
    """F3：目标区段只暴露 requirements，避免与前端 items 双写不一致。"""
    store, session = history_store(tmp_path)
    try:
        store.context.append(session, "run", ModelMessage(role="user", content="只读取 src 并报告"), key="goal", source="user")
        for index in range(3):
            group(store, session, key=f"read-{index}")
        run = {"goal_version": 2, "completion_requirements": [
            {"requirement_id": "r1", "description": "只读取 src 并报告", "required": True, "origin": "user"}]}
        handoff = store.context.compact(session, store.context.begin(session, "goal"), run=run)["summary"]["handoff"]
        assert "items" not in handoff["goal"]
        assert handoff["goal"]["requirements"][0]["text"] == "只读取 src 并报告"
        assert handoff["goal"]["requirements"][0]["kind"] == "user_requirement"
        assert handoff["goal"]["status"] == "known" and handoff["goal"]["goal_version"] == 2
        # 其余五个区段仍使用统一的 items 字段。
        for name in ("constraints", "plan", "findings", "changes", "unresolved"):
            assert "items" in handoff[name]
    finally:
        store.db.close()


def test_evidence_dedupe_requires_same_range_and_same_result(tmp_path):
    """F1：同一范围且同一结果才合并；不同区间、不同版本与不同执行记录保留。"""
    store, session = history_store(tmp_path)
    try:
        store.context.append(session, "run", ModelMessage(role="user", content="检查 src/auth.py"), key="goal", source="user")
        read_100 = {"rel_path": "src/auth.py", "start_line": 100, "line_count": 20}
        read_200 = {"rel_path": "src/auth.py", "start_line": 200, "line_count": 20}
        first = group(store, session, key="r100", arguments=read_100,
                      content=json.dumps({"success": True, "output": {"content": "A" * 60}}))
        repeat = group(store, session, key="r100-again", arguments=read_100,
                       content=json.dumps({"success": True, "output": {"content": "A" * 60}}))
        other_range = group(store, session, key="r200", arguments=read_200,
                            content=json.dumps({"success": True, "output": {"content": "B" * 60}}))
        new_version = group(store, session, key="r100-v2", arguments=read_100,
                            content=json.dumps({"success": True, "output": {"content": "C" * 60}}))
        group(store, session, key="tail-1")
        group(store, session, key="tail-2")
        checkpoint = store.context.compact(session, store.context.begin(session, "dedupe"))
        selected = {entry["item_id"] for entry in checkpoint["summary"]["evidence_selection"]}
        # 同范围同结果的较早重复被合并，只保留最近一次。
        assert repeat[1]["item_id"] in selected and first[1]["item_id"] not in selected
        # 不同读取区间与同区间不同版本内容都保留。
        assert other_range[1]["item_id"] in selected and new_version[1]["item_id"] in selected
        # 原始条目全部保留，去重只影响证据名额。
        assert len(store.context.items(session)) == 13
    finally:
        store.db.close()


def test_evidence_dedupe_keeps_failures_and_writes(tmp_path):
    """F1：失败结果与写入回执永不合并，即使参数与内容相同。"""
    store, session = history_store(tmp_path)
    try:
        store.context.append(session, "run", ModelMessage(role="user", content="写入并读取"), key="goal", source="user")
        failure = json.dumps({"success": False, "error": "missing"})
        first = group(store, session, key="fail-1", rel_path="src/missing.py", success=False, content=failure)
        second = group(store, session, key="fail-2", rel_path="src/missing.py", success=False, content=failure)
        writes = [group(store, session, key=f"write-{index}", name="write_project_file",
                        arguments={"rel_path": "src/app.py", "content": "x"}) for index in range(2)]
        group(store, session, key="tail-1")
        group(store, session, key="tail-2")
        checkpoint = store.context.compact(session, store.context.begin(session, "keep"))
        selected = {entry["item_id"] for entry in checkpoint["summary"]["evidence_selection"]}
        assert {first[1]["item_id"], second[1]["item_id"]} <= selected
        assert all(item[1]["item_id"] in selected for item in writes)
    finally:
        store.db.close()


def test_resolved_failure_is_history_not_unresolved(tmp_path):
    """F5：已有可信解决证据的失败不再列为未解决，仍保留为历史事实。"""
    store, session = history_store(tmp_path)
    try:
        store.context.append(session, "run", ModelMessage(role="user", content="读取 src/missing.py"), key="goal", source="user")
        _, failed = group(store, session, key="failed", rel_path="src/missing.py", success=False,
                          content=json.dumps({"success": False, "error": "missing"}))
        group(store, session, key="fixed", rel_path="src/missing.py")
        group(store, session, key="tail-1")
        group(store, session, key="tail-2")
        entry = {"key": "k", "kind": "tool", "tool_name": "read_code_file", "category": "tool",
                 "target_hash": target_hash("read_code_file", {"rel_path": "src/missing.py"}),
                 "error_code": "file_not_found", "signature": "s", "attempts": 1, "status": "resolved",
                 "workspace_version": 0, "source": {}}
        run = {"reflection_state": {"entries": [entry]}}
        checkpoint = store.context.compact(session, store.context.begin(session, "resolved"), run=run)
        handoff = checkpoint["summary"]["handoff"]
        assert all(failed["item_id"] not in item["source_item_ids"] for item in handoff["unresolved"]["items"])
        assert handoff["unresolved"]["status"] == "unknown"
        resolved = [item for item in handoff["findings"]["items"] if item.get("resolved")]
        assert resolved and failed["item_id"] in resolved[0]["source_item_ids"]
        # 未解决问题本身没有被“解决”覆盖：open 记录仍在未解决列表。
        entry.update(status="open")
        reopened = store.context.compact(session, store.context.begin(session, "open"), run={
            "reflection_state": {"entries": [entry]}})
        open_items = reopened["summary"]["handoff"]["unresolved"]["items"]
        assert any(failed["item_id"] in item["source_item_ids"] for item in open_items)
        # 没有纠错记录可核对时保留失败但标为待核对，不伪造已解决。
        unknown = store.context.compact(session, store.context.begin(session, "unknown"), run={})
        unknown_items = unknown["summary"]["handoff"]["unresolved"]["items"]
        assert any(item.get("state") == "unknown" for item in unknown_items)
    finally:
        store.db.close()


def test_historical_analysis_window_reaches_middle_evidence(tmp_path):
    """F2：助手长正文中段的关键结论按当前步骤词进入历史分析摘录。"""
    store, session = history_store(tmp_path)
    try:
        store.context.append(session, "run", ModelMessage(role="user", content="核对 src/auth.py 的版本校验"), key="goal", source="user")
        marker = "MIDDLE_CONTRACT_REQUIRES_VERSION_CHECK"
        store.context.append(session, "run", ModelMessage(role="assistant",
            content="前置说明。" * 300 + marker + "结论。" * 300), key="analysis", source="model")
        group(store, session, key="read-1")
        group(store, session, key="read-2")
        plan = {"plan": {"items": [{"title": "核对版本校验 MIDDLE_CONTRACT_REQUIRES_VERSION_CHECK 的逻辑",
                                    "status": "in_progress"}]}}
        checkpoint = store.context.compact(session, store.context.begin(session, "window"), task_state=plan)
        excerpts = checkpoint["summary"]["historical_analysis"]
        assert excerpts and marker in excerpts[0]["excerpt"]
        assert excerpts[0]["truncated"] is True and excerpts[0]["range"][1] > 400
        assert sum(len(item["excerpt"]) for item in excerpts) <= 1200
    finally:
        store.db.close()


def test_excerpt_window_bounds_and_fallbacks():
    text = "x" * 5000
    window = excerpt_window(text, ["missing"], 1000)
    assert window["truncated"] is True and len(window["excerpt"]) <= 1000
    assert "[中间省略]" in window["excerpt"]
    hit = excerpt_window(("前" * 800) + "KEY_MARKER" + ("后" * 800), ["KEY_MARKER"], 400)
    assert "KEY_MARKER" in hit["excerpt"] and len(hit["excerpt"]) <= 400
    assert hit["range"][1] > hit["range"][0] and hit["truncated"] is True
    assert excerpt_window("short", ["x"], 400) == {"excerpt": "short", "range": [0, 5], "truncated": False}


@pytest.mark.parametrize("limit", list(range(0, 30)) + [32, 48, 64, 128, 399, 400, 401, 999, 1000, 1001])
@pytest.mark.parametrize("hit", [True, False])
def test_excerpt_window_never_exceeds_limit(limit, hit):
    """R1：任意 limit 与命中/未命中分支都不得越界，range 必须有效。"""
    text = ("前" * 600) + ("KEY_MARKER" if hit else "") + ("后" * 3000)
    window = excerpt_window(text, ["KEY_MARKER"] if hit else ["missing"], limit)
    assert len(window["excerpt"]) <= limit
    start, end = window["range"]
    assert 0 <= start <= end <= len(text)
    if hit and limit >= 25:
        # 标记预算（15）足够容纳 10 字符命中词时才保证命中词完整可见。
        assert "KEY_MARKER" in window["excerpt"]
    if len(text) > limit:
        assert window["truncated"] is True


def test_compact_analysis_excerpts_stay_within_budget_with_tiny_remainder(tmp_path):
    """R1：真实 compact 路径中剩余 1 字符时不得复制超出上限的正文。"""
    store, session = history_store(tmp_path)
    try:
        store.context.append(session, "run", ModelMessage(role="user", content="检查项目"), key="goal", source="user")
        for index, size in enumerate((399, 400, 400, 5000)):
            store.context.append(session, "run", ModelMessage(role="assistant", content="摘" * size),
                                key=f"analysis-{index}", source="model")
        group(store, session, key="tail-1")
        group(store, session, key="tail-2")
        checkpoint = store.context.compact(session, store.context.begin(session, "budget"))
        excerpts = checkpoint["summary"]["historical_analysis"]
        assert sum(len(item["excerpt"]) for item in excerpts) <= 1200
        assert all(len(item["excerpt"]) <= 400 for item in excerpts)
        # 剩余预算不足时省略该条，而不是生成 1 字符或超长摘录。
        assert len(excerpts) == 3
        # 同样不得通过摘要消息撑大投影。
        assert sum(len(item["excerpt"]) for item in excerpts) == 1199
    finally:
        store.db.close()


def test_reused_call_id_across_groups_keeps_both_results(tmp_path):
    """R2：供应商跨组复用调用 ID 时，两份不同读取都必须保留证据优先级。"""
    store, session = history_store(tmp_path)
    try:
        store.context.append(session, "run", ModelMessage(role="user", content="核对 src/critical.py"), key="goal", source="user")
        similar, critical = "same-call", "src/critical.py"
        first = group(store, session, key="crit-1", rel_path=critical, tool_call_id=similar,
                      arguments={"rel_path": critical, "start_line": 10, "line_count": 20},
                      content=json.dumps({"success": True, "output": {"content": "A" * 60}}))
        second = group(store, session, key="crit-2", rel_path=critical, tool_call_id=similar,
                       arguments={"rel_path": critical, "start_line": 200, "line_count": 20},
                       content=json.dumps({"success": True, "output": {"content": "B" * 60}}))
        for index in range(32):
            group(store, session, key=f"noise-{index}", rel_path=f"src/noise-{index}.py", tool_call_id=similar)
        group(store, session, key="tail-1")
        group(store, session, key="tail-2")
        plan = {"plan": {"items": [{"title": "核对 src/critical.py 的分支逻辑", "status": "in_progress"}]}}
        checkpoint = store.context.compact(session, store.context.begin(session, "reuse"), task_state=plan)
        selection = {entry["item_id"]: entry for entry in checkpoint["summary"]["evidence_selection"]}
        assert first[1]["item_id"] in selection and second[1]["item_id"] in selection
        # 两份结果都按当前步骤识别，而不是只有第一份。
        assert selection[second[1]["item_id"]]["priority"] == 2
        assert selection[first[1]["item_id"]]["priority"] == 2
        # 真正送入摘要请求的来源包含两份结果，而不只是 completed_work 里还有事实。
        identifiers = set(checkpoint["summary"]["source_item_ids"])
        sources = [item for item in store.context.items(session) if item["item_id"] in identifiers]
        request, refs = summary_request(
            sources, checkpoint, capacity=32000, structured=False,
            prioritized=[entry["item_id"] for entry in checkpoint["summary"]["evidence_selection"]])
        packet = json.loads(request.messages[-1].content)
        sent = {entry["id"] for entry in packet["sources"]}
        assert {first[1]["item_id"], second[1]["item_id"]} <= sent <= refs
    finally:
        store.db.close()


def test_reused_call_id_with_different_targets_uses_own_arguments(tmp_path):
    """R2：复用 ID 但目标不同时，优先级按各自调用参数计算，不跨组绑定。"""
    store, session = history_store(tmp_path)
    try:
        store.context.append(session, "run", ModelMessage(role="user", content="核对 src/critical.py"), key="goal", source="user")
        reused = "shared-id"
        critical = group(store, session, key="step", rel_path="src/critical.py", tool_call_id=reused)
        other = group(store, session, key="other", rel_path="src/other.py", tool_call_id=reused)
        group(store, session, key="tail-1")
        group(store, session, key="tail-2")
        plan = {"plan": {"items": [{"title": "核对 src/critical.py 的分支逻辑", "status": "in_progress"}]}}
        checkpoint = store.context.compact(session, store.context.begin(session, "targets"), task_state=plan)
        selection = {entry["item_id"]: entry for entry in checkpoint["summary"]["evidence_selection"]}
        assert selection[critical[1]["item_id"]]["priority"] == 2
        assert selection[other[1]["item_id"]]["priority"] == 5
        assert selection[other[1]["item_id"]]["reason"] == "recent_support"
    finally:
        store.db.close()


def test_summary_request_includes_middle_of_long_result():
    """F2：位于长工具结果中部的关键结论必须真正进入摘要请求。"""
    marker = "MIDDLE_CONTRACT_REQUIRES_VERSION_CHECK"
    body = json.dumps({"success": True, "output": {"content": "填充说明。" * 400 + marker + "结论。" * 400}},
                      ensure_ascii=False)
    items = [{"item_id": "source", "ordinal": 1, "role": "tool", "message": {"content": body}}]
    request, refs = summary_request(items, None, capacity=32000, structured=False, prioritized=["source"],
                                    keywords=["版本校验", "version check", marker])
    packet = json.loads(request.messages[-1].content)
    source = packet["sources"][0]
    assert marker in source["excerpt"]
    assert source["truncated"] is True and source["range"][1] > 400
    assert len(source["excerpt"]) <= 1000 and "source" in refs
