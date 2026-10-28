"""M1：活动耗时以单调时钟与已提交回执为准，离线间隔不计入且末段明确未知。"""
import asyncio
import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_local_executor import close, response, setup, until

from private_agent.agent.runtime import TERMINAL, Runtime
from private_agent.storage.store import Store, encode


def helper():
    return Path(__file__).parents[1] / "coding_acceptance" / "recovery_process.py"


def crash(directory, boundary="model.requested"):
    """在真实子进程里到达指定日志边界后直接退出，模拟断电或进程被杀。"""
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
    """直接改写运行 JSON，用于构造旧版本遗留的现场。"""
    db = sqlite3.connect(directory / "state.sqlite3")
    try:
        (data,) = db.execute("SELECT data FROM runs WHERE id=?", (identifier,)).fetchone()
        value = json.loads(data)
        mutate(value)
        db.execute("UPDATE runs SET data=? WHERE id=?", (encode(value), identifier))
        db.commit()
    finally:
        db.close()


def edit_checkpoint_created_at(directory, moment):
    """同时改写检查点数据与摘要，模拟很久以前最后确认的一次提交。"""
    db = sqlite3.connect(directory / "state.sqlite3")
    try:
        row = db.execute("SELECT id,data FROM run_checkpoints ORDER BY rowid DESC LIMIT 1").fetchone()
        value = json.loads(row[1])
        value["created_at"] = moment
        db.execute("UPDATE run_checkpoints SET data=?,sha256=? WHERE id=?",
                   (encode(value), hashlib.sha256(encode(value).encode()).hexdigest(), row[0]))
        db.commit()
    finally:
        db.close()


def test_offline_day_is_not_counted_as_active_time(tmp_path):
    crash(tmp_path)
    identifier = run_id_of(tmp_path)
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    edit_checkpoint_created_at(tmp_path, yesterday)
    store = Store(tmp_path / "state.sqlite3")
    try:
        run = store.run(identifier)
        budget = run["loop_budget"]
        assert run["status"] == "interrupted"
        # 旧实现会把 now - 检查点时间加进活动耗时并填满预算；离线一天不属于活动时间。
        assert budget["active_seconds"] < 60, budget
        assert budget["active_seconds"] < run["context_limits"]["max_active_seconds"]
        assert budget["recovery_time_policy"] == "confirmed_only"
        assert run["timing"]["source"] == "restart" and run["timing"]["unconfirmed_tail"] is True
        owner = Runtime(store, None, "fixture")
        report = owner.recovery.inspect(run)
        assert report["can_resume"] is True, report["blockers"]
        assert any("末段耗时未确认" in item for item in report["limitations"])
    finally:
        store.db.close()


def test_legacy_record_without_timing_keeps_committed_budget(tmp_path):
    crash(tmp_path)
    identifier = run_id_of(tmp_path)

    def legacy(run):
        run.pop("timing", None)
        run["loop_budget"].update(active_seconds=7.5)
        run["loop_budget"].pop("recovery_time_policy", None)

    edit_run(tmp_path, identifier, legacy)
    store = Store(tmp_path / "state.sqlite3")
    try:
        run = store.run(identifier)
        assert run["loop_budget"]["active_seconds"] == 7.5
        assert run["timing"]["unconfirmed_tail"] is True
    finally:
        store.db.close()


def test_conservative_legacy_budget_is_not_reduced(tmp_path):
    crash(tmp_path)
    identifier = run_id_of(tmp_path)
    limit = json.loads(sqlite3.connect(tmp_path / "state.sqlite3").execute(
        "SELECT data FROM runs WHERE id=?", (identifier,)).fetchone()[0])["context_limits"]["max_active_seconds"]

    def filled(run):
        run.pop("timing", None)
        run["loop_budget"].update(active_seconds=limit, recovery_time_policy="conservative_until_restart")

    edit_run(tmp_path, identifier, filled)
    store = Store(tmp_path / "state.sqlite3")
    try:
        run = store.run(identifier)
        # 旧版本按保守策略填满的预算不回减，只保留该兼容标签。
        assert run["loop_budget"]["active_seconds"] == limit
        assert run["loop_budget"]["recovery_time_policy"] == "conservative_until_restart"
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


async def hold_model(api, monkeypatch):
    """让模型调用停在可控点，运行保持活动以便观察周期回执。"""
    owner = api[0].state.desktop.runtime
    owner.heartbeat_interval = 0.05
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(*args, **kwargs):
        entered.set()
        await release.wait()
        return response(text="只解释")

    monkeypatch.setattr(owner.cloud, "complete", slow)
    return owner, entered, release


@pytest.mark.asyncio
async def test_periodic_receipt_updates_budget_without_events(api, monkeypatch):
    owner, entered, release = await hold_model(api, monkeypatch)
    result = await api[1].post("/agent-runs", json={**api[4], "message": "只解释"})
    assert result.status_code == 201, result.text
    run_id = result.json()["id"]
    await entered.wait()
    created = owner.store.run(run_id)
    events = owner.store.db.execute("SELECT COUNT(*) FROM events WHERE run_id=?", (run_id,)).fetchone()[0]
    checkpoints = owner.store.db.execute("SELECT COUNT(*) FROM run_checkpoints WHERE run_id=?", (run_id,)).fetchone()[0]
    await asyncio.sleep(0.35)
    later = owner.store.run(run_id)
    assert later["timing"]["source"] == "periodic", later["timing"]
    assert later["timing"]["last_receipt_at"] > created["timing"]["last_receipt_at"]
    assert later["loop_budget"]["active_seconds"] > created["loop_budget"]["active_seconds"]
    assert later["status"] == "running"
    # 周期回执只更新运行 JSON：不产生公开事件，也不生成完整恢复检查点。
    assert owner.store.db.execute("SELECT COUNT(*) FROM events WHERE run_id=?", (run_id,)).fetchone()[0] == events
    assert owner.store.db.execute("SELECT COUNT(*) FROM run_checkpoints WHERE run_id=?", (run_id,)).fetchone()[0] == checkpoints
    release.set()
    final = await until(api[1], run_id, TERMINAL)
    assert final["status"] == "completed"
    assert final["timing"]["source"] == "finish" and final["timing"]["unconfirmed_tail"] is False
    assert run_id not in owner.heartbeats


@pytest.mark.asyncio
async def test_paused_wait_does_not_count_as_active(api, monkeypatch):
    owner, entered, release = await hold_model(api, monkeypatch)
    run_id = (await api[1].post("/agent-runs", json={**api[4], "message": "只解释"})).json()["id"]
    await entered.wait()
    report = (await api[1].get(f"/agent-runs/{run_id}/recovery")).json()
    paused = await api[1].post(f"/agent-runs/{run_id}/pause",
                               json={"request_id": "pause-1", "expected_state_version": report["state_version"]})
    assert paused.status_code in {200, 202}, paused.text
    await until(api[1], run_id, {"paused"})
    await asyncio.sleep(0.3)
    first = owner.store.run(run_id)
    await asyncio.sleep(0.3)
    second = owner.store.run(run_id)
    # 暂停期间不计活动耗时，回执继续写入但不能增长。
    assert second["timing"]["last_receipt_at"] > first["timing"]["last_receipt_at"]
    assert abs(second["loop_budget"]["active_seconds"] - first["loop_budget"]["active_seconds"]) < 0.05
    release.set()


@pytest.mark.asyncio
async def test_cancel_stops_receipts_and_keeps_terminal_state(api, monkeypatch):
    owner, entered, release = await hold_model(api, monkeypatch)
    run_id = (await api[1].post("/agent-runs", json={**api[4], "message": "只解释"})).json()["id"]
    await entered.wait()
    report = (await api[1].get(f"/agent-runs/{run_id}/recovery")).json()
    cancelled = await api[1].post(f"/agent-runs/{run_id}/cancel",
                                  json={"request_id": "cancel-1", "expected_state_version": report["state_version"]})
    assert cancelled.status_code in {200, 202}, cancelled.text
    await until(api[1], run_id, TERMINAL)
    assert run_id not in owner.heartbeats
    settled = owner.store.run(run_id)
    await asyncio.sleep(0.3)
    after = owner.store.run(run_id)
    # 迟到回执不得把终态或最后确认的活动时间改回去。
    assert after["status"] == settled["status"] == "cancelled"
    assert after["timing"] == settled["timing"]
    release.set()
