"""M2：未知现场的结构化阻塞项与人工核对闭环；原始事实只读，决定追加。"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from test_local_executor import close, response, setup, until

from private_agent.agent.recovery import ControlConflict
from private_agent.agent.runtime import TERMINAL, Runtime
from private_agent.storage.store import Store, encode


def helper():
    return Path(__file__).parents[1] / "coding_acceptance" / "recovery_process.py"


def crash(directory, boundary):
    result = subprocess.run([sys.executable, "-B", str(helper()), str(directory), boundary],
                            capture_output=True, timeout=30)
    assert result.returncode == 23, result.stderr.decode(errors="replace")


def run_id_of(directory):
    db = sqlite3.connect(directory / "state.sqlite3")
    try:
        return db.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()[0]
    finally:
        db.close()


def edit_run(directory, identifier, mutate):
    db = sqlite3.connect(directory / "state.sqlite3")
    try:
        (data,) = db.execute("SELECT data FROM runs WHERE id=?", (identifier,)).fetchone()
        value = json.loads(data)
        mutate(value)
        db.execute("UPDATE runs SET data=? WHERE id=?", (encode(value), identifier))
        db.commit()
    finally:
        db.close()


def add_unknown_mcp(directory, identifier):
    """构造一条已派发但无回执的 MCP 写执行，以及随之保留的未确认副作用。"""
    execution = {"id": "exec-mcp", "operation_id": "op-mcp", "status": "unknown", "error_code": "execution_unknown",
                 "command": None, "mcp_call": {"phase": "dispatched", "readonly": False, "tool": "memory_write",
                                               "source_id": "mem", "call_id": "call-1"}}
    db = sqlite3.connect(directory / "state.sqlite3")
    try:
        db.execute("INSERT INTO executions(run_id,id,data) VALUES (?,?,?)", (identifier, execution["id"], encode(execution)))
        db.commit()
    finally:
        db.close()
    edit_run(directory, identifier, lambda run: run.setdefault("uncertain_operations", []).append(
        {"operation_id": "op-mcp", "scope": {"kind": "external", "source_id": "mem", "tool": "memory_write"}}))


def open_helpers(directory):
    store = Store(directory / "state.sqlite3")
    return store, Runtime(store, None, "fixture")


def reconcile_data(report, item, decision, request_id="reconcile-1", note="已在远端控制台核对写入结果",
                   evidence=None):
    return {"request_id": request_id, "expected_state_version": report["state_version"],
            "checkpoint_id": report["checkpoint_id"], "item_id": item["item_id"], "kind": item["kind"],
            "decision": decision, "note": note,
            "evidence": item.get("evidence") if evidence is None else evidence}


def test_dispatched_mcp_write_needs_manual_statement(tmp_path):
    crash(tmp_path, "model.requested")
    identifier = run_id_of(tmp_path)

    add_unknown_mcp(tmp_path, identifier)
    store, owner = open_helpers(tmp_path)
    try:
        run = store.run(identifier)
        report = owner.recovery.inspect(run)
        item = next(detail for detail in report["blocker_details"] if detail["kind"] == "mcp_write")
        assert item["status"] == "open" and item["resolvable"] is True
        assert item["actions"] == ["externally_confirmed", "externally_failed"]
        assert item["source"] == "machine" and item["item_id"]
        assert report["can_resume"] is False

        import asyncio
        asyncio.run(owner.controls.request(identifier, "reconcile",
                                           reconcile_data(report, item, "externally_confirmed")))
        after = store.run(identifier)
        second = owner.recovery.inspect(after)
        # 人工核对只解除该项对续跑的阻塞，不产生成功证据。
        assert second["can_resume"] is True, second["blockers"]
        resolution = second["resolutions"][0]
        assert resolution["source"] == "user_statement" and resolution["verified"] is False
        assert resolution["decision"] == "externally_confirmed"
        # 原始事实保持：执行仍为 unknown，未确认副作用仍在，不自动重放。
        execution = next(entry for entry in after["executions"] if entry["id"] == "exec-mcp")
        assert execution["status"] == "unknown" and execution["error_code"] == "execution_unknown"
        assert after["uncertain_operations"]
        # 同一项不会被再次核对。
        with pytest.raises(ValueError):
            asyncio.run(owner.controls.request(identifier, "reconcile",
                                               reconcile_data(second, item, "externally_failed",
                                                              request_id="reconcile-2")))
    finally:
        store.db.close()


def test_reconcile_is_idempotent_and_rejects_changed_payload(tmp_path):
    crash(tmp_path, "model.requested")
    identifier = run_id_of(tmp_path)
    add_unknown_mcp(tmp_path, identifier)
    store, owner = open_helpers(tmp_path)
    try:
        import asyncio
        run = store.run(identifier)
        report = owner.recovery.inspect(run)
        item = next(detail for detail in report["blocker_details"] if detail["kind"] == "mcp_write")
        data = reconcile_data(report, item, "externally_confirmed")
        first = asyncio.run(owner.controls.request(identifier, "reconcile", data))
        again = asyncio.run(owner.controls.request(identifier, "reconcile", data))
        assert again["resolution_id"] == first["resolution_id"]
        changed = store.run(identifier)
        assert len(changed.get("recovery_resolutions") or []) == 1
        rows = store.db.execute("SELECT COUNT(*) FROM run_control_requests WHERE run_id=? AND kind='reconcile'",
                                (identifier,)).fetchone()[0]
        assert rows == 1
        # 同一 request_id 换内容必须冲突，不能覆盖已提交的核对记录。
        with pytest.raises(ControlConflict):
            asyncio.run(owner.controls.request(identifier, "reconcile",
                                               {**data, "note": "换一个说法重新核对这件事"}))
        # 过期版本与历史检查点都拒绝。
        with pytest.raises(ControlConflict):
            asyncio.run(owner.controls.request(identifier, "reconcile",
                                               {**data, "request_id": "reconcile-3"}))
        with pytest.raises(ControlConflict):
            asyncio.run(owner.controls.request(identifier, "reconcile",
                                               {**data, "request_id": "reconcile-4", "checkpoint_id": "stale"}))
    finally:
        store.db.close()


def test_file_conflict_cannot_be_unlocked(tmp_path):
    crash(tmp_path, "patch.disk")
    identifier = run_id_of(tmp_path)
    (tmp_path / "project" / "a.txt").write_text("third", encoding="utf-8")
    store, owner = open_helpers(tmp_path)
    try:
        import asyncio
        run = store.run(identifier)
        report = owner.recovery.inspect(run)
        item = next(detail for detail in report["blocker_details"]
                    if detail["kind"] == "file_operation" and detail["target"]["relative_path"] == "a.txt")
        assert item["resolvable"] is False and item["actions"] == []
        assert item["reason"] and "不能忽略冲突解锁" in item["reason"]
        with pytest.raises(ValueError):
            asyncio.run(owner.controls.request(identifier, "reconcile",
                                               reconcile_data(report, item, "record_observation",
                                                              note="我认为这个文件其实写对了")))
        assert (tmp_path / "project" / "a.txt").read_text(encoding="utf-8") == "third"
        assert not store.run(identifier).get("recovery_resolutions")
    finally:
        store.db.close()


def test_unreadable_path_keeps_block_without_guessing(tmp_path):
    """路径被目录替换或不可读时只保留阻塞，不猜测文件内容，也不能提交核对解锁。"""
    crash(tmp_path, "patch.intent")
    identifier = run_id_of(tmp_path)
    target = tmp_path / "project" / "a.txt"
    target.unlink()
    target.mkdir()
    store, owner = open_helpers(tmp_path)
    try:
        import asyncio
        report = owner.recovery.inspect(store.run(identifier))
        item = next(detail for detail in report["blocker_details"]
                    if detail["kind"] == "file_operation" and detail["target"]["relative_path"] == "a.txt")
        assert item["resolvable"] is False and item["actions"] == []
        assert item["evidence"]["actual_sha256"] is None
        assert report["can_resume"] is False
        with pytest.raises(ValueError):
            asyncio.run(owner.controls.request(identifier, "reconcile",
                                               reconcile_data(report, item, "record_observation")))
        assert target.is_dir()
        assert not store.run(identifier).get("recovery_resolutions")
    finally:
        store.db.close()


def test_machine_observation_resolves_applying_file_without_rewriting_facts(tmp_path):
    crash(tmp_path, "patch.intent")
    identifier = run_id_of(tmp_path)
    assert (tmp_path / "project" / "a.txt").read_text(encoding="utf-8") == "before"
    store, owner = open_helpers(tmp_path)
    try:
        import asyncio
        run = store.run(identifier)
        report = owner.recovery.inspect(run)
        assert report["can_resume"] is False
        item = next(detail for detail in report["blocker_details"] if detail["kind"] == "file_operation")
        assert item["resolvable"] is True and item["actions"] == ["record_observation"]
        asyncio.run(owner.controls.request(identifier, "reconcile",
                                           reconcile_data(report, item, "record_observation",
                                                          note="重新读取确认文件仍是写入前内容")))
        after = store.run(identifier)
        second = owner.recovery.inspect(after)
        assert second["can_resume"] is True, second["blockers"]
        assert second["resolutions"][0]["source"] == "machine_observation"
        assert second["resolutions"][0]["verified"] is True
        # 原始补丁日志仍是 applying：核对只追加决定，不改写历史事实。
        fact = next(entry for entry in second["patch_facts"] if entry["rel_path"] == "a.txt")
        assert fact["journal_status"] == "applying"
    finally:
        store.db.close()


def test_unknown_command_cannot_be_cleared_by_statement(tmp_path):
    crash(tmp_path, "execution.started")
    identifier = run_id_of(tmp_path)
    store, owner = open_helpers(tmp_path)
    try:
        import asyncio
        run = store.run(identifier)
        report = owner.recovery.inspect(run)
        item = next(detail for detail in report["blocker_details"] if detail["kind"] == "command")
        assert item["resolvable"] is False and item["actions"] == []
        assert "不能凭 PID" in (item["reason"] or "")
        with pytest.raises(ValueError):
            asyncio.run(owner.controls.request(identifier, "reconcile",
                                               reconcile_data(report, item, "record_observation",
                                                              note="进程肯定已经停了")))
        # 放弃可以记录，但本地活动未确认静止时不释放租约。
        abandon = next(detail for detail in report["blocker_details"] if detail["kind"] == "abandon_task")
        assert abandon["resolvable"] is True and owner.recovery.local_activity(run)
        asyncio.run(owner.controls.request(identifier, "reconcile",
                                           reconcile_data(report, abandon, "abandon", note="放弃后续恢复，保留已改动")))
        after = store.run(identifier)
        assert after["recovery_abandoned_at"]
        assert owner.recovery.local_activity(after)
        assert owner.recovery.inspect(after)["can_resume"] is False
    finally:
        store.db.close()


def seed_second_file_journal(store, identifier):
    """构造“写第二个文件前退出”的现场：同一补丁组里 b.txt 也停在 applying。"""
    patch_id, data = store.db.execute("SELECT id,data FROM patch_sets WHERE run_id=?", (identifier,)).fetchone()
    patch = store._unpack(data)
    change = next(item for item in patch["changes"] if item["rel_path"] == "b.txt")
    sequence = store.db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM patch_journal WHERE patch_set_id=?",
                                (patch_id,)).fetchone()[0]
    store.db.execute("INSERT INTO patch_journal VALUES (?,?,?)",
                     (patch_id, sequence, store._pack({"change_id": change["change_id"], "rel_path": "b.txt",
                                                       "status": "applying", "created_at": "2026-10-22T00:00:00+00:00"})))
    store.db.commit()


def test_file_decisions_are_bound_to_each_path(tmp_path):
    """同一补丁组的两个文件分别核对：一个文件的决定不能解锁另一个文件。"""
    crash(tmp_path, "patch.disk")
    identifier = run_id_of(tmp_path)
    store, owner = open_helpers(tmp_path)
    try:
        import asyncio
        seed_second_file_journal(store, identifier)
        report = owner.recovery.inspect(store.run(identifier))
        files = {detail["target"]["relative_path"]: detail for detail in report["blocker_details"]
                 if detail["kind"] == "file_operation"}
        assert set(files) == {"a.txt", "b.txt"}, files
        # 两个文件共享同一原始操作标识，但必须各有一条阻塞项。
        assert files["a.txt"]["item_id"] != files["b.txt"]["item_id"]
        assert files["a.txt"]["evidence"] != files["b.txt"]["evidence"]

        asyncio.run(owner.controls.request(identifier, "reconcile",
                                           reconcile_data(report, files["a.txt"], "record_observation",
                                                          note="重新读取确认 a.txt 已是写入后内容")))
        after_first = owner.recovery.inspect(store.run(identifier))
        remaining = [detail for detail in after_first["blocker_details"]
                     if detail["kind"] == "file_operation" and detail["status"] == "open"]
        assert [detail["target"]["relative_path"] for detail in remaining] == ["b.txt"]
        assert after_first["can_resume"] is False

        # 另一个文件用同一 request_id 的内容提交必须被拒绝，不能借用 a.txt 的核对依据。
        with pytest.raises(ControlConflict):
            asyncio.run(owner.controls.request(identifier, "reconcile",
                                               reconcile_data(after_first, remaining[0], "record_observation",
                                                              request_id="reconcile-2",
                                                              evidence=files["a.txt"]["evidence"])))

        asyncio.run(owner.controls.request(identifier, "reconcile",
                                           reconcile_data(after_first, remaining[0], "record_observation",
                                                          request_id="reconcile-3",
                                                          note="重新读取确认 b.txt 仍是写入前内容")))
        after_second = owner.recovery.inspect(store.run(identifier))
        assert after_second["can_resume"] is True, after_second["blockers"]
        assert len(after_second["resolutions"]) == 2
        # 原始补丁日志仍停在 applying，核对只追加决定。
        assert {fact["journal_status"] for fact in after_second["patch_facts"]
                if fact["rel_path"] in {"a.txt", "b.txt"}} == {"applying"}
    finally:
        store.db.close()


def test_stale_observation_stops_unblocking_after_file_changes(tmp_path):
    """核对后文件又被改动：旧决定失去放行效力，阻塞项自动回到待核对。"""
    crash(tmp_path, "patch.intent")
    identifier = run_id_of(tmp_path)
    target = tmp_path / "project" / "a.txt"
    store, owner = open_helpers(tmp_path)
    try:
        import asyncio
        report = owner.recovery.inspect(store.run(identifier))
        item = next(detail for detail in report["blocker_details"] if detail["kind"] == "file_operation")
        asyncio.run(owner.controls.request(identifier, "reconcile",
                                           reconcile_data(report, item, "record_observation",
                                                          note="重新读取确认文件仍是写入前内容")))
        assert owner.recovery.inspect(store.run(identifier))["can_resume"] is True

        target.write_text("third", encoding="utf-8")
        stale = owner.recovery.inspect(store.run(identifier))
        detail = next(entry for entry in stale["blocker_details"] if entry["kind"] == "file_operation")
        assert detail["status"] == "open" and detail["resolvable"] is False
        assert detail["stale_resolution"]["resolution_id"]
        assert stale["can_resume"] is False
        # 已提交的决定仍是审计事实，不被删除。
        assert len(store.run(identifier).get("recovery_resolutions") or []) == 1
    finally:
        store.db.close()


@pytest.fixture
async def api(tmp_path):
    values = await setup(tmp_path)
    subprocess.run(["git", "init"], cwd=values[3], check=True, capture_output=True)
    values[4]["recovery_contract_version"] = "1.0"
    try:
        yield values
    finally:
        await close(values[0], values[1])


@pytest.mark.asyncio
async def test_reconcile_endpoint_maps_conflicts(api):
    api[2].responses = [response(text="只解释")]
    run_id = (await api[1].post("/agent-runs", json={**api[4], "message": "只解释"})).json()["id"]
    await until(api[1], run_id, TERMINAL)
    report = (await api[1].get(f"/agent-runs/{run_id}/recovery")).json()
    payload = {"request_id": "reconcile-api", "expected_state_version": 0, "checkpoint_id": "stale",
               "item_id": "x" * 32, "kind": "mcp_write", "decision": "externally_confirmed",
               "note": "远端已确认写入结果"}
    response_ = await api[1].post(f"/agent-runs/{run_id}/recovery/reconcile", json=payload)
    assert response_.status_code == 409, response_.text
    assert response_.json()["error_code"] == "run_state_conflict"
    assert response_.json()["state_version"] == report["state_version"]
    # 旧字段仍在，新前端可以不解析中文而按结构化详情渲染。
    assert {"can_resume", "blockers", "checkpoint_id", "state_version", "blocker_details"} <= set(report)
