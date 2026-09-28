"""停滞保护区分重复观察、新证据、合法轮询和旧协议。"""
import pytest
from test_local_executor import call, close, response, setup, until

from private_agent_local.progress import STOP_AT, observe
from private_agent_local.runtime import TERMINAL


def record(run, name="read_code_file", arguments=None, output=None):
    state, warning = observe(run, name, arguments or {"rel_path": "a.py"}, output or {"content": "x"})
    if state is not None:
        run["orchestration_progress"] = state
    return state, warning


def test_repeated_reads_warn_then_stop_despite_rotating_snapshot_ids():
    run = {"recovery_contract_version": "1.0"}
    warnings = []
    for index in range(STOP_AT + 1):
        state, warning = record(run, output={"content": "x", "snapshot_id": str(index), "sha256": "stable"})
        if warning:
            warnings.append(warning)
    assert state["repeats"] == STOP_AT and len(warnings) == 1


def test_alternating_known_reads_still_stalls_but_new_evidence_resets():
    run = {"recovery_contract_version": "1.0"}
    for index in range(8):
        state, _ = record(run, arguments={"rel_path": f"{index % 2}.py"})
    assert state["repeats"] == STOP_AT
    assert record(run, output={"content": "changed"})[0]["repeats"] == 0
    run["goal_version"] = 2
    assert record(run)[0]["repeats"] == 0
    run["workspace_version"] = 2
    assert record(run)[0]["repeats"] == 0
    run["plan"] = {"items": [{"item_key": "test", "status": "in_progress"}]}
    assert record(run)[0]["repeats"] == 0
    assert record(run)[0]["repeats"] == 1
    run["executions"] = [{"id": "test-command", "execution_result": {"exit_code": 1, "outcome": "exited"}}]
    assert record(run)[0]["repeats"] == 0
    assert record(run)[0]["repeats"] == 1
    resumed = {**run, "executions": []}
    assert record(resumed)[0]["repeats"] == 2


def test_active_process_waits_pagination_and_legacy_are_not_stalled():
    run = {"recovery_contract_version": "1.0"}
    for cursor in range(100):
        assert record(run, "read_execution", output={"status": "running"}) == (None, None)
        assert record(run, arguments={"start_line": cursor}, output={"content": "x"})[0]["repeats"] == 0
    assert len(run["orchestration_progress"]["seen"]) == 64
    assert record({}) == (None, None)


def test_tool_search_stalls_without_new_results_and_resets_for_changed_catalog():
    run = {"recovery_contract_version": "1.0"}
    arguments = {"query": "SDK", "limit": 1}
    output = {"matches": [], "loaded_tools": [], "notice": "没有匹配工具"}
    for _ in range(STOP_AT + 1):
        state, _ = record(run, "tool_search", arguments, output)
    assert state["repeats"] == STOP_AT
    output = {"matches": [{"source_id": "sdk", "source_version": "v1"}],
              "loaded_tools": ["call_documentation_tool"], "notice": "已加载"}
    assert record(run, "tool_search", arguments, output)[0]["repeats"] == 0
    assert record(run, "tool_search", arguments, output)[0]["repeats"] == 1
    output["matches"][0]["source_version"] = "v2"
    assert record(run, "tool_search", arguments, output)[0]["repeats"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("tool, arguments", [
    ("read_code_file", {"rel_path": "sample.py"}),
    ("tool_search", {"query": "no_matching_catalog_entry", "limit": 1}),
])
async def test_real_agent_stops_successful_read_loop_and_persists_warning(tmp_path, tool, arguments):
    app, client, server, root, body = await setup(tmp_path)
    try:
        (root / "sample.py").write_text("value = 1\n", encoding="utf-8")
        server.responses = [response({**call(tool, arguments), "id": f"read-{i}"}) for i in range(10)]
        run = (await client.post("/agent-runs", json={**body, "recovery_contract_version": "1.0", "execution_contract_version": "1.0",
                                                    "permission_mode": "readonly"})).json()
        final = await until(client, run["id"], TERMINAL)
        assert final["error_code"] == "no_progress", final
        assert final["tool_call_count"] == STOP_AT + 1
        stored = app.state.desktop.runtime.store.run(run["id"])
        assert stored["orchestration_progress"]["repeats"] == STOP_AT
        assert any(event["type"] == "progress.warning" for event in stored["events"])
        assert any(event["type"] == "progress.stalled" for event in stored["events"])
        app.state.desktop.runtime.recovery.load_checkpoint(stored)
    finally:
        await close(app, client)
