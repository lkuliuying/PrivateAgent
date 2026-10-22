"""M0：可重复的长任务轨迹基线与元数据记录。

夹具只证明控制流程与内容保留，不证明真实模型的理解能力、费用或成功率。
"""
import asyncio
import json
import os
import time

import pytest
from test_local_executor import call, close, response, setup, until

from private_agent_core.contracts import ModelMessage

EARLY_FINDING = "早期关键发现：认证模块在启动时读取本机配置文件，禁止修改 secrets.txt"
BASE_GOAL = "检查项目后创建 done.txt；禁止联网"
APPENDED_GOAL = "追加要求：另外创建 report.txt，内容为 baseline"
WINDOW = 26000
READS = 32


def metrics_path(name):
    """隔离运行器提供目录时写入 .run 临时目录；普通 pytest 使用样例目录。"""
    directory = os.environ.get("CODING_VALIDATION_DIR")
    return os.path.join(directory, name) if directory else None


def write_metrics(name, value):
    path = metrics_path(name)
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
    return value


def sequence(*groups):
    """按调用顺序拼接模拟响应；缺少供应商窗口计量时才需要连续压缩。"""
    items = [item for group in groups for item in group]
    for item in items:
        item["usage"] = {"input_tokens": 0, "output_tokens": 2}
    return items


def requests_of(server):
    return [json.loads(payload)["request"] for path, payload in server.calls if path == "/desktop/model/complete"]


def seed_prior(history, session, groups):
    """合成既有历史：早期关键发现与两轮已完成的读取，属于派生视图之前的原始条目。"""
    history.append(session, "prior", ModelMessage(role="user", content=EARLY_FINDING), key="early", source="user")
    for index in range(groups):
        tool = {"id": f"prior-{index}", "name": "read_code_file", "arguments": {"rel_path": f"prior-{index}.txt"}}
        history.append(session, "prior", ModelMessage(role="assistant", content="", tool_calls=(tool,)),
                       key=f"prior-call-{index}", source="model")
        history.append(session, "prior", ModelMessage(role="tool", name="read_code_file", tool_call_id=tool["id"],
            content=json.dumps({"success": True, "output": {"schema_version": "2", "content": "y" * 3000,
                                                            "sha256": "a" * 64}})),
            key=f"prior-result-{index}", source="tool")


def collect(owner, session_id, run, *, started, server, original, runs=None):
    """只记录元数据：估算、压缩前后大小、来源覆盖、次数与失败原因。"""
    checkpoint = owner.store.context.checkpoint(session_id)
    recorded = runs or [run]
    events = [event["type"] for item in recorded for event in item["events"]]
    messages = owner.store.context.messages(session_id)
    executions = [execution for item in recorded for execution in item.get("executions", [])]
    sources = (checkpoint or {}).get("summary", {}).get("source_item_ids", [])
    return {
        "schema": "baseline-metadata/1",
        "window_tokens": WINDOW,
        "requests": len(requests_of(server)),
        "model_requests": sum(item["loop_budget"].get("model_requests", 0) for item in recorded),
        "tool_calls": sum(item["loop_budget"].get("tool_calls", 0) for item in recorded),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "compactions": events.count("context.compaction_completed"),
        "compaction_failures": events.count("context.compaction_failed"),
        "archive_reads": sum(1 for item in executions if item.get("tool_name") == "read_context_content"),
        "failed_tools": sum(1 for item in executions if item.get("error_code")),
        "status": run["status"],
        "error_code": run.get("error_code"),
        "error_message": run.get("error_message"),
        # 计量来源：最终请求预算；分项字段在 M1 后出现，缺失时明确写未知。
        "last_budget": {key: run.get("context_budget", {}).get(key) for key in (
            "estimated_input_tokens", "input_budget_tokens", "request_bytes", "measurement_source",
            "should_compact", "exceeded")},
        "breakdown": run.get("context_budget", {}).get("breakdown", "unavailable"),
        "compaction_metrics": (checkpoint or {}).get("compaction_metrics", "unavailable"),
        "original_items": len(original),
        "total_items": len(owner.store.context.items(session_id)),
        "retained_messages": len(messages),
        "checkpoint_sources": len(sources),
        "checkpoint_covers_original": bool(checkpoint) and set(item["item_id"] for item in original) <= set(sources),
        # 关键来源覆盖：早期证据是否被选中（M2 前只有时间顺序，可能被大量读取淹没）。
        "early_evidence_selected": bool(checkpoint) and original and original[0]["item_id"] in {
            entry["item_id"] for entry in checkpoint["summary"].get("evidence_selection", [])},
        "handoff": (checkpoint or {}).get("summary", {}).get("handoff", "unavailable"),
    }


@pytest.mark.asyncio
async def test_long_task_baseline_two_compactions_and_real_write(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    owner = app.state.desktop.runtime
    history = owner.store.context
    started = time.monotonic()
    try:
        server.profiles[0]["context_tokens"] = WINDOW
        # 合成资料；不提高窗口，也不放宽既有 26k 回归配置。
        for index in range(READS):
            (root / f"input-{index}.txt").write_text(f"input {index}\n" + "x" * 3000, encoding="utf-8")
        seed_prior(history, body["session_id"], 2)
        original = history.items(body["session_id"])
        reads = [response(call("read_code_file", {"rel_path": f"input-{index}.txt"})) for index in range(READS)]
        # 一次失败后改用另一个文件修正；两项都保留在原始历史中。
        reads.insert(8, response(call("read_code_file", {"rel_path": "missing.txt"})))
        server.responses = sequence(reads,
            [response(call("write_project_file", {"rel_path": "done.txt", "content": "verified data"}))],
            [response(text="已创建并回读")])
        first = (await client.post("/agent-runs", json={**body, "message": BASE_GOAL,
                                                        "permission_mode": "workspace"})).json()
        await asyncio.wait_for(owner.tasks[first["id"]], 180)
        final = owner.store.run(first["id"])
        assert final["status"] == "completed", (final["error_code"], final["error_message"])
        assert (root / "done.txt").read_text(encoding="utf-8") == "verified data"

        # 追加目标：同一会话的第二段任务，验证用户原文累积而不改写旧限制。
        server.responses = sequence(
            [response(call("write_project_file", {"rel_path": "report.txt", "content": "baseline"}))],
            [response(text="已创建 report.txt")])
        appended = (await client.post("/agent-runs", json={**body, "message": APPENDED_GOAL,
                                                           "permission_mode": "workspace"})).json()
        await asyncio.wait_for(owner.tasks[appended["id"]], 180)
        latest = owner.store.run(appended["id"])
        assert latest["status"] == "completed", (latest["error_code"], latest["error_message"])
        assert (root / "report.txt").read_text(encoding="utf-8") == "baseline"

        events = [event["type"] for event in final["events"]]
        assert events.count("context.compaction_completed") >= 2
        # 失败事实保留在原始历史，成功的无关读取不能清除它。
        assert any(item.get("error_code") for item in final["executions"])
        last = json.dumps(requests_of(server)[-1], ensure_ascii=False)
        assert "secrets.txt" in last and "report.txt" in last and "禁止联网" in last
        # 原始条目在压缩前后保持不变，摘要只作为派生视图存在。
        items = history.items(body["session_id"])
        assert items[:len(original)] == original
        assert EARLY_FINDING in [message.content for message in history.messages(body["session_id"])
                                 if message.role == "user"]
        assert APPENDED_GOAL in [message.content for message in history.messages(body["session_id"])
                                 if message.role == "user"]
        checkpoint = history.checkpoint(body["session_id"])
        assert checkpoint is not None
        assert set(item["item_id"] for item in original) <= set(checkpoint["summary"]["source_item_ids"])
        metadata = write_metrics("baseline.json", collect(owner, body["session_id"], latest, started=started,
                                                          server=server, original=original,
                                                          runs=[final, latest]))
        assert metadata["status"] == "completed"
        assert metadata["compactions"] >= 2
        assert metadata["checkpoint_covers_original"] is True
        assert metadata["requests"] == metadata["model_requests"] or metadata["requests"] > 0
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_baseline_is_repeatable_and_stable(tmp_path):
    """同一夹具与模拟响应重复运行，关键计数与原始 ID 稳定。"""
    results = []
    for index in range(2):
        app, client, server, root, body = await setup(tmp_path / str(index))
        owner = app.state.desktop.runtime
        try:
            server.profiles[0]["context_tokens"] = WINDOW
            for number in range(10):
                (root / f"input-{number}.txt").write_text(f"input {number}\n" + "x" * 3000, encoding="utf-8")
            server.responses = sequence(
                [response(call("read_code_file", {"rel_path": f"input-{number}.txt"})) for number in range(10)],
                [response(text="读取完成")])
            run = (await client.post("/agent-runs", json={**body, "message": "检查项目并说明结果"})).json()
            await until(client, run["id"], {"completed", "failed", "limit_exceeded", "cancelled"})
            final = owner.store.run(run["id"])
            results.append({"status": final["status"], "requests": final["loop_budget"]["model_requests"],
                            "ordinals": [item["ordinal"] for item in owner.store.context.items(body["session_id"])],
                            "compactions": sum(event["type"] == "context.compaction_completed"
                                               for event in final["events"])})
        finally:
            await close(app, client)
    assert results[0] == results[1]
    assert results[0]["status"] == "completed" and results[0]["requests"] == 11
