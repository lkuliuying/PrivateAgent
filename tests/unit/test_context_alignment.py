"""输入预算、语义续接、来源归档及失败恢复的隔离回归。"""
import asyncio
import json

import pytest
from test_local_compaction import seed
from test_local_context_history import history_store
from test_local_executor import TERMINAL, close, response, setup, until

from private_agent_core.context import request_budget
from private_agent_core.contracts import ModelMessage, ModelRequest
from private_agent_local.context_summary import summary_request, validate_summary


def test_compaction_precedes_small_window_hard_limit_and_honors_lower_override():
    request = ModelRequest(messages=(ModelMessage(role="user", content="x" * 4700),))
    for capacity, reserve in ((8192, 2048), (8192, 7000), (None, 2048), (1024, 1024)):
        budget = request_budget(request, capacity, reserve)
        assert budget["auto_compact_threshold_tokens"] <= budget["input_budget_tokens"]
        assert not budget["exceeded"] or budget["should_compact"]
    assert request_budget(request, 32000, 2048, auto_compact_token_limit=1000)["should_compact"]
    assert request_budget(request, 8192, 2048, auto_compact_token_limit=999999)["auto_compact_threshold_tokens"] < 5632


def test_large_archive_does_not_grow_the_request_index_and_is_session_scoped(tmp_path):
    store, session = history_store(tmp_path)
    try:
        seed(store, session, count=80)
        first = store.context.compact(session, store.context.begin(session, "first"))
        seed(store, session, start=80, count=80)
        candidate = store.context.compact(session, store.context.begin(session, "second"))
        store.context.save_checkpoint(session, candidate)
        assert len(json.dumps(candidate["messages"])) < len(json.dumps(first["messages"])) + 1500
        assert len(candidate["summary"]["completed_work"]) > 150
        page = store.context.read(session, candidate["id"], 0, 6000)
        assert page["next_offset"] == 6000
        assert page["total_chars"] > 6000
        with pytest.raises(ValueError, match="当前会话"):
            store.context.read(session + 1, candidate["id"], 0, 100)
        with pytest.raises(ValueError, match="分页"):
            store.context.read(session, candidate["id"], -1, 100)
    finally:
        store.db.close()


def test_summary_is_bounded_requires_known_sources_and_rejects_secrets():
    items = [{"item_id": "source", "role": "assistant", "message": {"content": "决定保留现有接口，因为调用者依赖它。" * 1000}}]
    request, sources = summary_request(items, None, capacity=8192, structured=False)
    assert not request.tools and not request_budget(request, 8192, 1024)["exceeded"]
    with pytest.raises(ValueError, match="没有可"):
        summary_request(items, None, capacity=8192, structured=False, secrets=(items[0]["message"]["content"],))
    entry = {"kind": "decision", "text": "保留现有接口以兼容调用者", "source_item_ids": ["source"]}
    assert validate_summary(json.dumps({"entries": [entry]}), sources)["entries"][0] == entry
    with pytest.raises(ValueError, match="秘密"):
        validate_summary(json.dumps({"entries": [entry]}, ensure_ascii=False), sources, secrets=(entry["text"],))
    for change in ({"source_item_ids": ["invented"]}, {"text": "password=synthetic-fixture-value"}, {"text": "x" * 241}):
        with pytest.raises(ValueError):
            validate_summary(json.dumps({"entries": [{**entry, **change}]}), sources)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["valid", "invalid", "failure", "malformed", "wrong_profile"])
async def test_semantic_compaction_uses_budget_and_failure_preserves_fact_history(tmp_path, mode):
    app, client, server, root, body = await setup(tmp_path)
    owner = app.state.desktop.runtime
    seed(owner.store, body["session_id"])
    original = owner.store.context.items(body["session_id"])
    calls = []

    async def compact(token, profile, request):
        calls.append(request)
        assert request["tools"] == []
        if mode == "failure":
            raise TimeoutError
        if mode == "malformed":
            return []
        packet = json.loads(request["messages"][-1]["content"])
        identifier = packet["sources"][-1]["id"] if mode in {"valid", "wrong_profile"} else "invented"
        result = response(text=json.dumps({"entries": [{"kind": "pending", "text": "依据读取结果继续核对", "source_item_ids": [identifier]}]}))
        if mode == "wrong_profile":
            result["model_profile_id"] = "another-model"
        return result

    owner.cloud.compact_context = compact
    server.responses = [response(text="检查完成")]
    try:
        run = (await client.post("/agent-runs", json=body)).json()
        final = await until(client, run["id"], TERMINAL)
        assert final["status"] == "completed", final.get("error_message")
        assert len(calls) == 1 and final["loop_budget"]["model_requests"] == 2
        checkpoint = owner.store.context.checkpoint(body["session_id"])
        assert checkpoint["summary_strategy"] == ("model" if mode == "valid" else "extractive")
        state = (await client.get(f"/sessions/{body['session_id']}/context")).json()
        assert state["checkpoint"]["summary_strategy"] == checkpoint["summary_strategy"]
        assert owner.store.context.items(body["session_id"])[:len(original)] == original
        if mode == "valid":
            assert checkpoint["summary"]["working_summary"]["entries"][0]["kind"] == "pending"
        else:
            assert checkpoint["summary_fallback_reason"] == "summary_unavailable"
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_cancel_during_summary_does_not_commit_checkpoint(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    owner = app.state.desktop.runtime
    seed(owner.store, body["session_id"])
    original = owner.store.context.items(body["session_id"])
    started, released = asyncio.Event(), asyncio.Event()

    async def compact(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            released.set()

    owner.cloud.compact_context = compact
    try:
        run = (await client.post("/agent-runs", json=body)).json()
        await asyncio.wait_for(started.wait(), 2)
        await client.post(f"/agent-runs/{run['id']}/cancel")
        final = await until(client, run["id"], TERMINAL)
        assert final["status"] == "cancelled"
        assert released.is_set()
        assert owner.store.context.checkpoint(body["session_id"]) is None
        assert owner.store.context.items(body["session_id"])[:len(original)] == original
        assert not [path for path, _ in server.calls if path == "/desktop/model/complete"]
    finally:
        await close(app, client)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["model", "instructions"])
async def test_changes_while_summary_waits_reject_stale_checkpoint(tmp_path, change):
    app, client, server, root, body = await setup(tmp_path)
    owner = app.state.desktop.runtime
    rule = root / "AGENTS.md"
    rule.write_text("保留现有接口", encoding="utf-8")
    await client.post(f"/projects/{body['project_id']}/instruction-trust", json={"trusted": True})
    seed(owner.store, body["session_id"])
    original = owner.store.context.items(body["session_id"])
    started, release = asyncio.Event(), asyncio.Event()

    async def compact(token, profile, request):
        started.set()
        await release.wait()
        source = json.loads(request["messages"][-1]["content"])["sources"][-1]["id"]
        return response(text=json.dumps({"entries": [{"kind": "pending", "text": "继续核对接口", "source_item_ids": [source]}]}))

    owner.cloud.compact_context = compact
    try:
        run = (await client.post("/agent-runs", json=body)).json()
        await asyncio.wait_for(started.wait(), 2)
        if change == "model":
            server.profiles[0]["context_tokens"] = 64000
        else:
            rule.write_text("新增兼容性要求", encoding="utf-8")
        release.set()
        final = await until(client, run["id"], TERMINAL)
        assert final["status"] == "failed"
        assert final["compaction_state"] == "failed"
        assert owner.store.context.checkpoint(body["session_id"]) is None
        assert owner.store.context.items(body["session_id"])[:len(original)] == original
        assert not [path for path, _ in server.calls if path == "/desktop/model/complete"]
    finally:
        release.set()
        await close(app, client)


@pytest.mark.asyncio
async def test_required_context_cannot_fit_without_spending_summary_request(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    owner = app.state.desktop.runtime
    seed(owner.store, body["session_id"])
    server.profiles[0]["context_tokens"] = 8192
    calls = []

    async def compact(*args):
        calls.append(args)
        return response(text="{}")

    owner.cloud.compact_context = compact
    try:
        run = (await client.post("/agent-runs", json={**body, "message": "x" * 16000})).json()
        final = await until(client, run["id"], TERMINAL)
        assert final["status"] == "limit_exceeded" and final["error_code"] == "context_limit"
        assert calls == []
        assert not [path for path, _ in server.calls if path == "/desktop/model/complete"]
        assert owner.store.context.checkpoint(body["session_id"]) is None
        assert any(item["message"]["content"] == "x" * 16000 for item in owner.store.context.items(body["session_id"]))
    finally:
        await close(app, client)
