"""隔离本机记忆的生命周期、生成权限、预算和跨会话使用。"""
import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from test_local_executor import TERMINAL, close, response, setup, until

from private_agent_core.contracts import ModelMessage, ToolCall
from private_agent_local.memories import Memories
from private_agent_local.memory_store import (
    MemoryConflict,
    MemoryInput,
    MemorySettings,
    MemoryStore,
)
from private_agent_local.runtime import Runtime
from private_agent_local.store import Store


class Model:
    def __init__(self):
        self.requests = []
        self.entered = asyncio.Event()
        self.release = None
        self.result = None
        self.secrets = {"fixture": "fixture-known-sensitive-value"}

    async def profiles(self, token):
        return [{"id": "model", "is_default": True, "enabled": True, "context_tokens": 100000}]

    async def complete(self, token, profile_id, request):
        self.requests.append(request)
        self.entered.set()
        if self.release:
            await self.release.wait()
        sources = json.loads(request["messages"][-1]["content"])["messages"]
        value = self.result or {"memories": [{"scope": "project", "kind": "workflow", "title": "测试约定",
            "content": "提交前先运行当前模块的单元测试。", "stable_key": "模块测试", "source_item_ids": [sources[0]["id"]]}]}
        return response(text=json.dumps(value, ensure_ascii=False))


@pytest.fixture
def worker(tmp_path):
    store = Store(tmp_path / "projects.sqlite3")
    owner = SimpleNamespace(store=store, cloud=Model(), token="fixture")
    value = Memories(owner)
    yield value
    assert not value.task or value.task.done(), "测试必须关闭后台任务"
    value.store.close()
    store.db.close()


def enable(worker, **changes):
    current = worker.store.settings()
    values = MemorySettings(enabled=True, **changes)
    return worker.store.save_settings(values, current["version"])


def seed(worker, *, users=2, status="completed", age=600):
    store = worker.owner.store
    project = store.create("project", {"name": "测试项目"})
    session = store.create("session", {"project_id": project["id"]})
    run = {"id": f"run-{session['id']}", "project_id": project["id"], "session_id": session["id"],
           "status": status, "model_profile_id": "model", "completed_at": (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()}
    store.save_run(run)
    for index in range(users):
        store.context.append(session["id"], run["id"], ModelMessage(role="user", content=f"项目约定 {index}：先运行模块测试。"), key=f"user-{index}", source="user")
        store.context.append(session["id"], run["id"], ModelMessage(role="assistant", content="收到，后续按此约定。"), key=f"reply-{index}", source="model")
    return store.update("session", session["id"], last_run_id=run["id"])


def test_store_persistence_versions_scope_and_forgetting(tmp_path):
    path = tmp_path / "memories.sqlite3"
    store = MemoryStore(path)
    try:
        assert store.settings()["enabled"] is False
        item = MemoryInput(title="测试方式", content="运行模块测试")
        first = store.put(10, item, stable_key="workflow:test", source_updated_at="2026-01-01")
        assert not store.list(20)
        with pytest.raises(MemoryConflict):
            store.put(10, item, identifier=first["id"], expected_version=99)
        edit = store.put(10, item.model_copy(update={"content": "运行集成测试"}), identifier=first["id"], expected_version=1)
        assert edit["origin"] == "user" and edit["version"] == 2
        assert store.put(10, item, stable_key="workflow:test", source_updated_at="2026-02-01") is None
        store.forget(10, edit["id"], 2)
        assert not store.list(10)
        assert store.put(10, item, stable_key="workflow:test", source_updated_at="2026-03-01") is None
        assert store.put(10, item.model_copy(update={"content": "运行集成测试"}), stable_key="another") is None
        global_item = store.put(10, MemoryInput(scope="user", kind="preference", title="语言", content="默认使用中文"))
        assert store.list(20)[0]["id"] == global_item["id"]
    finally:
        store.close()
    reopened = MemoryStore(path)
    try:
        assert len(reopened.list(10)) == 1
        tombstone = json.loads(reopened.db.execute("SELECT data FROM memories WHERE deleted=1").fetchone()[0])
        assert tombstone["content"] == "" and tombstone["source_item_ids"] == []
    finally:
        reopened.close()


@pytest.mark.parametrize("data", [
    {"scope": "user", "kind": "project", "title": "不适合共享", "content": "项目知识"},
    {"title": "凭据", "content": "password=fixture-password-value"},
    {"title": "", "content": "空标题"},
    {"title": "长内容", "content": "x" * 1601},
])
def test_invalid_memory_is_rejected(data):
    with pytest.raises(ValueError):
        MemoryInput.model_validate(data)


def test_generated_path_correction_preserves_case_sensitive_content(tmp_path):
    store = MemoryStore(tmp_path / "memories.sqlite3")
    try:
        first = store.put(1, MemoryInput(title="入口", content="src/Foo.py"), stable_key="entry", source_updated_at="2026-01-01")
        corrected = store.put(1, MemoryInput(title="入口", content="src/foo.py"), stable_key="entry", source_updated_at="2026-01-02")
        assert corrected["id"] == first["id"] and corrected["content"] == "src/foo.py"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_opt_in_watermark_and_independent_use_generate(worker):
    old = seed(worker)
    assert not await worker.tick() and not worker.owner.cloud.requests
    enable(worker)
    assert worker.source(old, worker.store.settings()) is None
    session = seed(worker)
    assert await worker.tick()
    assert len(worker.owner.cloud.requests) == 1
    records = worker.store.list(session["project_id"])
    assert len(records) == 1 and records[0]["source_item_ids"]
    assert worker.store.cursor(session["id"]) > 0
    assert not await worker.tick()
    policy = worker.store.session(session["id"])
    worker.store.save_session(session["id"], False, True, policy["version"])
    assert worker.recall(session["id"], session["project_id"], "测试") == ([], [])
    worker.store.save_session(session["id"], True, False, policy["version"] + 1)
    messages, ids = worker.recall(session["id"], session["project_id"], "测试")
    assert ids == [records[0]["id"]] and "不是项目规则" in messages[0].content
    assert not worker.allowed(session["id"], "generate_memories")


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["short", "active", "recent", "external", "secret", "session_off", "global_off", "expired"])
async def test_ineligible_sessions_never_call_model(worker, condition):
    config = enable(worker)
    session = seed(worker, users=1 if condition == "short" else 2,
                   status="running" if condition == "active" else "completed",
                   age=0 if condition == "recent" else 31 * 86400 if condition == "expired" else 600)
    if condition == "external":
        worker.owner.store.context.append(session["id"], session["last_run_id"], ModelMessage(role="assistant",
            tool_calls=(ToolCall(id="external", name="call_documentation_tool", arguments={}),)), key="external", source="model")
    elif condition == "secret":
        # 两条有效用户陈述的要求不能用带凭据的消息凑数。
        items = worker.owner.store.context.items(session["id"])
        worker.owner.cloud.secrets["whole-message"] = items[0]["message"]["content"]
    elif condition == "session_off":
        worker.store.save_session(session["id"], True, False, 1)
    elif condition == "global_off":
        worker.store.save_settings(MemorySettings(enabled=True, generate_memories=False), config["version"])
    assert not await worker.tick()
    assert worker.owner.cloud.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["settings", "edit", "source", "delete", "new_run"])
async def test_inflight_changes_discard_generation(worker, change):
    config = enable(worker)
    session = seed(worker)
    worker.owner.cloud.release = asyncio.Event()
    task = asyncio.create_task(worker.tick())
    await worker.owner.cloud.entered.wait()
    if change == "settings":
        worker.store.save_settings(MemorySettings(), config["version"])
    elif change == "edit":
        worker.revision += 1
    elif change == "source":
        worker.owner.store.context.append(session["id"], session["last_run_id"], ModelMessage(role="user", content="不要记住本会话"), key="change", source="user")
    elif change == "delete":
        worker.owner.store.delete_session(session["id"])
    else:
        worker.owner.store.save_run({"id": "new", "status": "running"})
    worker.owner.cloud.release.set()
    await task
    assert not worker.store.list(session["project_id"])
    assert worker.store.cursor(session["id"]) == 0
    assert worker.store.status()["last_attempt"]["state"] == "failed"


@pytest.mark.asyncio
async def test_invalid_sources_fail_atomically_and_daily_budget(worker):
    enable(worker, max_calls_per_day=1)
    session = seed(worker)
    worker.owner.cloud.result = {"memories": [{"title": "伪造来源", "content": "无依据", "stable_key": "fake", "source_item_ids": ["missing"]}]}
    assert await worker.tick()
    assert not worker.store.list(session["project_id"]) and not worker.store.cursor(session["id"])
    worker.retry_after.clear()
    await worker.tick()
    assert len(worker.owner.cloud.requests) == 1
    assert worker.status()["calls_today"] == 1 and worker.status()["error"]


@pytest.mark.asyncio
async def test_known_credentials_are_excluded_from_recall_and_generation_index(worker):
    enable(worker)
    session = seed(worker)
    secret = worker.owner.cloud.secrets["fixture"]
    worker.store.put(session["project_id"], MemoryInput(title=secret, content="曾在凭据尚未加载时保存的文本"))
    assert worker.recall(session["id"], session["project_id"], "文本") == ([], [])
    await worker.tick()
    assert secret not in json.dumps(worker.owner.cloud.requests)


@pytest.mark.asyncio
async def test_generated_memory_requires_query_overlap_but_manual_context_remains(worker):
    enable(worker)
    session = seed(worker)
    await worker.tick()
    assert worker.store.list(session["project_id"])
    assert worker.recall(session["id"], session["project_id"], "unrelated_keyword") == ([], [])
    manual = worker.store.put(session["project_id"], MemoryInput(title="项目偏好", content="所有代码注释使用中文"))
    messages, ids = worker.recall(session["id"], session["project_id"], "unrelated_keyword")
    assert messages and ids == [manual["id"]]


@pytest.mark.asyncio
async def test_model_timeout_preserves_sources_and_backoff(worker):
    enable(worker)
    session = seed(worker)
    before = worker.owner.store.context.items(session["id"])
    async def fail(*args):
        raise TimeoutError("测试模型超时")
    worker.owner.cloud.complete = fail
    await worker.tick()
    assert worker.store.status()["last_attempt"]["state"] == "failed"
    assert worker.owner.store.context.items(session["id"]) == before
    assert worker.store.cursor(session["id"]) == 0
    assert not await worker.tick()


@pytest.mark.asyncio
async def test_failed_transaction_does_not_advance_cursor(worker, monkeypatch):
    enable(worker)
    session = seed(worker)
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("fixture storage failure")
    monkeypatch.setattr(worker.store, "extracted", fail)
    await worker.tick()
    assert not worker.store.list(session["project_id"]) and not worker.store.cursor(session["id"])


@pytest.mark.asyncio
async def test_background_stop_cancels_inflight_model_and_saves_no_memory(worker):
    enable(worker)
    session = seed(worker)
    worker.owner.cloud.release = asyncio.Event()
    worker.start()
    await asyncio.wait_for(worker.owner.cloud.entered.wait(), 2)
    await worker.stop()
    assert worker.task is None and not worker.store.list(session["project_id"])
    assert worker.store.status()["last_attempt"]["state"] == "cancelled"


@pytest.mark.asyncio
async def test_generation_reuses_stable_key_for_corrections_and_honors_forgetting(worker):
    enable(worker)
    session = seed(worker)
    await worker.tick()
    first = worker.store.list(session["project_id"])[0]
    for batch in range(2):
        sources = []
        for index in range(2):
            entry = worker.owner.store.context.append(session["id"], session["last_run_id"],
                ModelMessage(role="user", content=f"更新约定 {batch}-{index}：测试改用集成测试"), key=f"change-{batch}-{index}", source="user")
            sources.append(entry["item_id"])
        worker.owner.cloud.result = {"memories": [{"scope": "project", "kind": "workflow", "title": "测试约定",
            "content": f"改用集成测试，版本 {batch}", "stable_key": first["stable_key"], "source_item_ids": sources}]}
        assert await worker.tick()
        if batch == 0:
            corrected, = worker.store.list(session["project_id"])
            assert corrected["id"] == first["id"] and corrected["version"] == 2
            assert corrected["content"] == "改用集成测试，版本 0"
            worker.store.forget(session["project_id"], corrected["id"], 2)
        else:
            assert worker.store.list(session["project_id"]) == []


def test_deleted_sources_are_cleaned_but_global_forgetting_survives_history_deletion(worker):
    session = seed(worker)
    source = {"source_session_id": session["id"], "source_project_id": session["project_id"], "source_updated_at": session["updated_at"]}
    project_item = worker.store.put(session["project_id"], MemoryInput(title="项目", content="事实"), stable_key="project", **source)
    preference = MemoryInput(scope="user", kind="preference", title="偏好", content="中文回答")
    forgotten = worker.store.put(session["project_id"], preference, stable_key="language", **source)
    worker.store.forget(session["project_id"], forgotten["id"], 1)
    worker.store.save_session(session["id"], False, False, 1)
    worker.owner.store.delete_session(session["id"])
    worker.reconcile()
    with pytest.raises(KeyError):
        worker.store.get(session["project_id"], project_item["id"])
    assert worker.store.put(session["project_id"], preference, stable_key="language", source_updated_at="2099") is None
    assert worker.store.session(session["id"])["version"] == 1


def test_reopening_marks_interrupted_attempt_and_preserves_daily_limit(tmp_path):
    path = tmp_path / "memories.sqlite3"
    store = MemoryStore(path)
    store.begin_attempt(1, 1)
    store.close()
    reopened = MemoryStore(path)
    try:
        assert reopened.status()["last_attempt"]["state"] == "cancelled"
        with pytest.raises(ValueError, match="上限"):
            reopened.begin_attempt(1, 1)
    finally:
        reopened.close()


def test_memory_startup_failure_releases_primary_store(tmp_path):
    path = tmp_path / "projects.sqlite3"
    store = Store(path)
    with sqlite3.connect(tmp_path / "memories.sqlite3") as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="更新版本"):
        Runtime(store, Model(), "fixture")
    with pytest.raises(sqlite3.ProgrammingError):
        store.db.execute("SELECT 1")
    recovered = Store(path)
    recovered.db.close()


@pytest.mark.asyncio
async def test_api_manual_memory_cross_session_recall_conflict_and_account_isolation(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        config = (await client.get("/local-memories/settings")).json()
        assert not config["enabled"]
        data = MemorySettings(enabled=True, generate_memories=False).model_dump()
        assert (await client.put("/local-memories/settings", json={**data, "expected_version": config["version"]})).status_code == 200
        assert (await client.put("/local-memories/settings", json={**data, "expected_version": config["version"]})).status_code == 409
        url = f"/local-memories/items?project_id={body['project_id']}"
        record = (await client.post(url, json={"title": "约定", "content": "需要测试时使用模块单元测试"})).json()
        server.responses = [response(text="已理解项目约定")]
        run = (await client.post("/agent-runs", json=body)).json()
        await until(client, run["id"], TERMINAL)
        request = [json.loads(raw)["request"] for path, raw in server.calls if path == "/desktop/model/complete"][-1]
        assert record["content"] in json.dumps(request, ensure_ascii=False)
        state = (await client.get(f"/sessions/{body['session_id']}/memory-settings")).json()
        assert state["last_recall"]["recalled_ids"] == [record["id"]]
        assert (await client.post(url, json={"title": "凭据", "content": "Bearer fixture-secret-value"})).status_code == 422
        assert (await client.delete(f"/local-memories/items/{record['id']}?project_id={body['project_id']}&expected_version=8")).status_code == 409
        assert (await client.delete(f"/local-memories/items/{record['id']}?project_id={body['project_id']}&expected_version=1")).status_code == 204
        assert (await client.get(url)).json() == []
        runtime = app.state.desktop.runtime
        runtime.memories.store.put(body["project_id"], MemoryInput(scope="user", kind="preference", title="语言", content="中文"))
        await app.state.desktop.activate("account-b", app.state.desktop.cloud.origin, 2)
        assert app.state.desktop.runtime.memories.store.list(body["project_id"]) == []
        assert runtime.memories.closed
        assert (await client.get("/local-memories/settings")).status_code == 401
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_optional_memory_is_dropped_before_context_overflow(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        runtime = app.state.desktop.runtime
        enable(runtime.memories, generate_memories=False)
        server.profiles[0]["context_tokens"] = 100000
        server.responses = [response(text="已收到")]
        baseline = (await client.post("/agent-runs", json=body)).json()
        await until(client, baseline["id"], TERMINAL)
        estimate = runtime.store.run(baseline["id"])["context_budget"]["estimated_input_tokens"]
        # 以真实请求大小构造边界，避免把工具 schema 大小写死在测试中。
        server.profiles[0]["context_tokens"] = int((estimate + 2500) / 0.8)
        for index in range(4):
            runtime.memories.store.put(body["project_id"], MemoryInput(title=f"项目参考 {index}", content="字" * 1500))
        server.responses = [response(text="完成")]
        run = (await client.post("/agent-runs", json=body)).json()
        result = await until(client, run["id"], TERMINAL)
        assert result["status"] == "completed", result.get("error_message")
        stored = runtime.store.run(run["id"])
        assert stored["memory_context"]["omitted_ids"] and not stored["memory_context"]["recalled_ids"]
        assert not any(e["type"] == "context.compaction_started" for e in stored["events"])
    finally:
        await close(app, client)


def test_compaction_keeps_bounded_analysis_sources_and_original_user_constraints(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    session = store.create("session", {})["id"]
    try:
        for index in range(8):
            store.context.append(session, "run", ModelMessage(role="user", content=f"约束 {index}：不部署"), key=f"u{index}", source="user")
            store.context.append(session, "run", ModelMessage(role="assistant", content=("password=fixture-sensitive" if index == 5 else "分析与后续步骤" * 100)), key=f"a{index}", source="model")
        before = store.context.items(session)
        compacted = store.context.compact(session, store.context.begin(session, "analysis"))
        excerpts = compacted["summary"]["historical_analysis"]
        assert excerpts and sum(len(item["excerpt"]) for item in excerpts) <= 1200
        assert all(item["source_item_id"] in {item["item_id"] for item in before} for item in excerpts)
        assert "fixture-sensitive" not in json.dumps(compacted["summary"])
        assert "未经重新核验" in compacted["summary"]["analysis_status"]
        assert store.context.items(session) == before
        for index in range(8):
            assert f"约束 {index}：不部署" in json.dumps(compacted["messages"], ensure_ascii=False)
    finally:
        store.db.close()
