"""记忆管理仅使用临时数据库与固定消息，不调用真实模型或读取用户历史。"""
import hashlib
import json
import sqlite3

import pytest
from test_local_memories import enable, seed

from private_agent_core.contracts import ModelMessage, ToolCall
from private_agent_core.tool_specs import ToolFailure
from private_agent_local.memories import external_context, memory_terms
from private_agent_local.memory_store import MemoryConflict, MemoryInput, MemoryStore
from private_agent_local.memory_tools import SPECS, MemoryTools, authorization_context

pytest_plugins = ["test_local_memories"]


def message(worker, session, text):
    stored = worker.owner.store.create("message", {"session_id": session["id"], "role": "user", "content": text})
    worker.owner.store.context.append(session["id"], session["last_run_id"], ModelMessage(role="user", content=text),
                                      key=f"message:{stored['id']}", source="user")
    return stored


def run_for(worker, session):
    run = worker.owner.store.run_state(session["last_run_id"])
    return {**run, "goal_version": 1, "permission_mode": "workspace", "collaboration_mode": "default"}


def authorization(stored):
    return {"source_message_id": stored["id"], "authorization_quote": stored["content"], "goal_version": 1}


def test_schema1_migration_keeps_active_and_recovers_snapshot(tmp_path):
    path = tmp_path / "memories.sqlite3"
    store = MemoryStore(path)
    item = store.put(1, MemoryInput(title="语言", content="中文"))
    generated = store.put(1, MemoryInput(title="旧约定", content="先测试"), stable_key="test")
    with store.transaction():
        store.db.execute("DROP TABLE memory_revisions")
        store.db.execute("DROP TABLE memory_receipts")
        store.db.execute("PRAGMA user_version=1")
    store.close()
    upgraded = MemoryStore(path)
    try:
        assert upgraded.db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert upgraded.get(1, item["id"])["status"] == "active"
        assert upgraded.get(1, item["id"])["legacy"] is False
        assert upgraded.get(1, generated["id"])["legacy"] is True
        assert upgraded.get(1, generated["id"])["status"] == "active"
        assert len(upgraded.revisions(1, item["id"])) == 1
        backup, = tmp_path.glob("*.bak")
        with sqlite3.connect(backup) as copied:
            assert copied.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        upgraded.close()


def test_migration_failure_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "memories.sqlite3"
    store = MemoryStore(path)
    store.put(1, MemoryInput(title="语言", content="中文"))
    with store.transaction():
        store.db.execute("DROP TABLE memory_revisions")
        store.db.execute("DROP TABLE memory_receipts")
        store.db.execute("PRAGMA user_version=1")
    store.close()
    def fail(*args):
        raise sqlite3.OperationalError("fixture migration failure")
    monkeypatch.setattr(MemoryStore, "_revision", fail)
    with pytest.raises(sqlite3.OperationalError):
        MemoryStore(path)
    with sqlite3.connect(path) as original:
        assert original.execute("PRAGMA user_version").fetchone()[0] == 1
        assert original.execute("SELECT count(*) FROM memories").fetchone()[0] == 1
        assert not original.execute("SELECT name FROM sqlite_master WHERE name='memory_revisions'").fetchone()


def test_conflict_requires_review_and_forgetting_removes_all_text(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    try:
        old = store.put(1, MemoryInput(kind="workflow", title="测试", content="先跑单测"), stable_key="test", source_updated_at="1")
        candidate = store.propose(1, MemoryInput(kind="workflow", title="测试", content="先跑集成"), stable_key="test", source_updated_at="2")
        assert candidate["status"] == "pending_review" and candidate["supersedes_id"] == old["id"]
        assert store.get(1, old["id"])["content"] == "先跑单测"
        assert store.get(1, old["id"])["status"] == "stale"
        accepted = store.review(1, candidate["id"], candidate["version"], "accept")
        assert accepted["id"] == old["id"] and accepted["content"] == "先跑集成" and accepted["origin"] == "user"
        assert len(store.revisions(1, old["id"])) == 3
        store.forget(1, old["id"], accepted["version"])
        assert not store.list(1)
        assert store.db.execute("SELECT count(*) FROM memory_revisions").fetchone()[0] == 0
        assert all(not json.loads(row[0])["content"] for row in store.db.execute("SELECT data FROM memories"))
    finally:
        store.close()


def test_candidate_cannot_overwrite_concurrent_user_edit(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    try:
        old = store.put(1, MemoryInput(kind="workflow", title="测试", content="单测"), stable_key="test", source_updated_at="1")
        candidate = store.propose(1, MemoryInput(kind="workflow", title="测试", content="集成"), stable_key="test", source_updated_at="2")
        store.put(1, MemoryInput(title="测试", content="人工确认"), identifier=old["id"], expected_version=2)
        with pytest.raises(MemoryConflict):
            store.review(1, candidate["id"], 1, "accept")
        assert store.get(1, old["id"])["content"] == "人工确认"
        store.review(1, candidate["id"], 1, "reject")
        assert store.get(1, old["id"])["content"] == "人工确认"
        assert len(store.list(1)) == 1
    finally:
        store.close()


def test_chinese_overlap_and_explainable_state_filter(worker):
    enable(worker)
    session = seed(worker)
    item = worker.store.put(session["project_id"], MemoryInput(title="语言", content="中文"), stable_key="language")
    assert "中文" in memory_terms("用中文回答")
    assert "语" in memory_terms("语")
    messages, ids, entries = worker.recall_with_details(session["id"], session["project_id"], "用中文回答")
    assert messages and ids == [item["id"]] and entries[0]["matched_terms"] == ["中文"]
    worker.store.set_state(session["project_id"], item["id"], item["version"], "stale")
    assert worker.recall_with_details(session["id"], session["project_id"], "用中文回答")[2][0]["reason"] == "stale"
    assert not worker.recall(session["id"], session["project_id"], "用中文回答")[0]


@pytest.mark.asyncio
async def test_search_tools_filter_review_state_before_limit(worker):
    enable(worker)
    session = seed(worker)
    worker.owner.memories = worker
    active = worker.store.put(session["project_id"], MemoryInput(title="语言规则", content="中文"))
    worker.store.put(session["project_id"], MemoryInput(title="语言", content="待确认中文"), status="pending_review")
    result = await MemoryTools(worker.owner).execute(run_for(worker, session), None, {"name": "search_memories", "id": "search", "arguments": {"query": "语言", "limit": 1}})
    assert [item["id"] for item in result["items"]] == [active["id"]]


@pytest.mark.parametrize("tool", ["call_documentation_tool", "call_mcp_tool", "read_web_page"])
def test_external_tools_and_transitive_marks_exclude_source(worker, tool):
    config = enable(worker)
    session = seed(worker)
    worker.owner.store.context.append(session["id"], session["last_run_id"], ModelMessage(role="assistant", tool_calls=(ToolCall(id="external", name=tool, arguments={}),)), key="external", source="model")
    assert worker.source(session, config) is None
    assert external_context([{"external_context": True, "message": {"role": "assistant", "content": "转述"}}])
    assert external_context([{"message": {"role": "tool", "content": json.dumps({"matches": [{"untrusted": True}]})}}])
    assert not external_context([{"message": {"role": "tool", "content": json.dumps({"matches": [{"name": "read_code_file"}]})}}])


@pytest.mark.asyncio
async def test_explicit_save_when_disabled_has_receipt_and_real_source(worker):
    session = seed(worker)
    stored = message(worker, session, "请记住：默认使用中文")
    run = run_for(worker, session)
    worker.owner.memories = worker
    tool = MemoryTools(worker.owner)
    call = {"id": "save", "name": "remember_memory", "arguments": {**authorization(stored), "memory": {"title": "语言", "content": "默认使用中文"}}}
    result = await tool.execute(run, None, call)
    assert result["scope"] == "project" and result["effective_use"] is False
    assert worker.store.settings()["enabled"] is False
    assert await tool.execute(run, None, call) == result
    assert len(worker.store.list(session["project_id"])) == 1
    source = worker.read_source(session["project_id"], result["id"], worker.store.get(session["project_id"], result["id"])["source_item_ids"][0])
    assert source["message_id"] == stored["id"] and "默认使用中文" in source["content"]
    with pytest.raises(KeyError):
        worker.read_source(session["project_id"] + 1, result["id"], source["item_id"])
    changed = {**call, "arguments": {**call["arguments"], "memory": {"title": "语言", "content": "默认使用英文"}}}
    with pytest.raises(ToolFailure, match="不同请求"):
        await tool.execute(run, None, changed)


@pytest.mark.asyncio
@pytest.mark.parametrize("text,quote", [("不要记住中文", "记住中文"), ("如果有用，请记住中文", "请记住中文"), ("示例：记住中文", "记住中文"), ("文档说“记住中文”", "记住中文"), ("记住中文，但不要保存", "记住中文"), ("记住默认中文吗？", "记住默认中文"), ("记住默认中文，如果我随后确认的话。", "记住默认中文"), ("```text\n记住默认中文\n```", "记住默认中文")])
async def test_quoted_conditional_and_negative_messages_cannot_authorize(worker, text, quote):
    session = seed(worker)
    stored = message(worker, session, text)
    worker.owner.memories = worker
    call = {"id": "save", "name": "remember_memory", "arguments": {**authorization(stored), "authorization_quote": quote, "memory": {"title": "语言", "content": "中文"}}}
    with pytest.raises(ToolFailure, match="授权"):
        await MemoryTools(worker.owner).execute(run_for(worker, session), None, call)
    assert not worker.store.list(session["project_id"])


@pytest.mark.asyncio
async def test_complete_authorization_sentence_inside_multiple_sentences(worker):
    session = seed(worker)
    worker.owner.memories = worker
    stored = message(worker, session, "可以开始了吗？请记住：默认中文。然后继续检查代码。")
    result = await MemoryTools(worker.owner).execute(run_for(worker, session), None, {"name": "remember_memory", "id": "save", "arguments": {**authorization(stored), "authorization_quote": "请记住：默认中文", "memory": {"title": "语言", "content": "默认中文"}}})
    assert result["content"] == "默认中文"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    "记住中文，不要跨项目保存", "记住中文，仅当前项目", "记住中文，只在本项目使用",
    "记住中文，不是全局", "记住中文，不要在所有项目使用", "记住中文，不要保存到全局",
    "记住中文，不允许跨项目", "记住中文，跨项目保存但仅当前项目使用",
    "remember 中文, do not save globally", "remember 中文, only for this project",
])
async def test_negative_global_scope_allows_project_only(worker, text):
    session = seed(worker)
    worker.owner.memories = worker
    stored = message(worker, session, text)
    run, tools = run_for(worker, session), MemoryTools(worker.owner)
    args = {**authorization(stored), "memory": {"scope": "user", "kind": "preference", "title": "语言", "content": "中文"}}
    with pytest.raises(ToolFailure) as failure:
        await tools.execute(run, None, {"name": "remember_memory", "id": "global", "arguments": args})
    assert failure.value.code == "memory_scope_not_authorized"
    assert not worker.store.list(session["project_id"])
    args["memory"]["scope"] = "project"
    result = await tools.execute(run, None, {"name": "remember_memory", "id": "project", "arguments": args})
    assert result["scope"] == "project"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["请记住全局偏好：中文", "记住中文，跨项目保存", "记住中文，所有项目都适用", "remember 中文 globally"])
async def test_affirmative_global_scope_can_be_saved(worker, text):
    session = seed(worker)
    worker.owner.memories = worker
    stored = message(worker, session, text)
    result = await MemoryTools(worker.owner).execute(run_for(worker, session), None, {"name": "remember_memory", "id": "global", "arguments": {**authorization(stored), "memory": {"scope": "user", "kind": "preference", "title": "语言", "content": "中文"}}})
    assert result["scope"] == "user" and "跨项目偏好" in result["notice"]


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_duplicate_target_returns_candidates_and_management_search_includes_pending(worker, enabled):
    if enabled:
        enable(worker)
    session = seed(worker)
    worker.owner.memories = worker
    tool = MemoryTools(worker.owner)
    first = worker.store.put(session["project_id"], MemoryInput(title="语言", content="中文"))
    second = worker.store.put(session["project_id"], MemoryInput(title="语言", content="英文"), status="pending_review")
    stored = message(worker, session, "先整理现有约定。请遗忘语言。然后继续任务。")
    run = run_for(worker, session)
    with pytest.raises(ToolFailure) as failure:
        await tool.execute(run, None, {"name": "forget_memory", "id": "forget", "arguments": {**authorization(stored), "authorization_quote": "请遗忘语言", "memory_id": first["id"], "expected_version": 1}})
    assert failure.value.code == "memory_target_ambiguous"
    assert first["id"] in str(failure.value) and second["id"] in str(failure.value)
    result = await tool.execute(run, None, {"name": "search_memories", "id": "search", "arguments": {"query": "语言"}})
    assert {item["id"] for item in result["items"]} == {first["id"], second["id"]}
    assert result["management_only"] and all("content" not in item for item in result["items"])
    assert len(worker.store.list(session["project_id"])) == 2


@pytest.mark.asyncio
async def test_synthetic_recovery_and_stale_version_cannot_authorize(worker):
    session = seed(worker)
    worker.owner.memories = worker
    run = run_for(worker, session)
    assert authorization_context(worker.owner, run) is None
    stored = message(worker, session, "请记住中文")
    call = {"id": "save", "name": "remember_memory", "arguments": {**authorization(stored), "goal_version": 2, "memory": {"title": "语言", "content": "中文"}}}
    with pytest.raises(ToolFailure, match="任务目标"):
        await MemoryTools(worker.owner).execute(run, None, call)
    call["arguments"]["goal_version"] = 1
    call["arguments"]["memory"].update(scope="user", kind="preference")
    with pytest.raises(ToolFailure, match="全局"):
        await MemoryTools(worker.owner).execute(run, None, call)


@pytest.mark.asyncio
async def test_receipt_failure_rolls_back_memory(worker, monkeypatch):
    session = seed(worker)
    stored = message(worker, session, "请记住中文")
    worker.owner.memories = worker
    def fail(*args):
        raise sqlite3.OperationalError("fixture receipt failure")
    monkeypatch.setattr(worker.store, "save_receipt", fail)
    call = {"id": "save", "name": "remember_memory", "arguments": {**authorization(stored), "memory": {"title": "语言", "content": "中文"}}}
    with pytest.raises(sqlite3.OperationalError):
        await MemoryTools(worker.owner).execute(run_for(worker, session), None, call)
    assert not worker.store.list(session["project_id"])


@pytest.mark.asyncio
async def test_disabled_management_search_update_and_forget_never_leaks_receipt_body(worker):
    session = seed(worker)
    worker.owner.memories = worker
    tool = MemoryTools(worker.owner)
    saved = worker.store.put(session["project_id"], MemoryInput(title="语言", content="默认中文"))
    stored = message(worker, session, "请纠正记忆语言：默认英文")
    run = run_for(worker, session)
    found = await tool.execute(run, None, {"name": "search_memories", "id": "search", "arguments": {"query": "语言"}})
    assert found["management_only"] is True and found["items"][0]["id"] == saved["id"]
    assert "content" not in found["items"][0]
    call = {"name": "update_memory", "id": "update", "arguments": {**authorization(stored), "memory_id": saved["id"], "expected_version": 1, "memory": {"title": "语言", "content": "默认英文"}}}
    updated = await tool.execute(run, None, call)
    assert updated["content"] == "默认英文" and "未启用使用" in updated["notice"]
    forgotten_message = message(worker, session, "请遗忘语言")
    forgotten = await tool.execute(run, None, {"name": "forget_memory", "id": "forget", "arguments": {**authorization(forgotten_message), "memory_id": saved["id"], "expected_version": 2}})
    assert "content" not in forgotten and "已遗忘" in forgotten["notice"]
    replay = await tool.execute(run, None, call)
    assert "content" not in replay and "未重新创建" in replay["notice"]
    assert all("默认英文" not in row[0] for row in worker.store.db.execute("SELECT data FROM memory_receipts"))


@pytest.mark.asyncio
async def test_saved_content_must_be_in_user_quote(worker):
    session = seed(worker)
    worker.owner.memories = worker
    stored = message(worker, session, "请记住中文")
    with pytest.raises(ToolFailure, match="不得新增"):
        await MemoryTools(worker.owner).execute(run_for(worker, session), None, {"name": "remember_memory", "id": "save", "arguments": {**authorization(stored), "memory": {"title": "无关", "content": "自动部署生产"}}})
    assert not worker.store.list(session["project_id"])


def test_source_checks_complete_public_text_and_shared_mcp_credentials(worker):
    from private_agent_local.secret_filter import SecretFilter
    session = seed(worker)
    secret = "fixture-mcp-credential-without-token-pattern"
    worker.owner.secret_filter = SecretFilter(lambda: [secret])
    stored = message(worker, session, "公开前文 " + secret + " 公开后文")
    source, = [item for item in worker.owner.store.context.items(session["id"]) if item["message"]["content"] == stored["content"]]
    item = worker.store.put(session["project_id"], MemoryInput(title="参考", content="公开内容"), sources=[source["item_id"]], source_session_id=session["id"])
    with pytest.raises(ValueError, match="敏感"):
        worker.read_source(session["project_id"], item["id"], source["item_id"], 0, 3)
    with pytest.raises(ValueError, match="凭据"):
        worker.save(session["project_id"], MemoryInput(title="凭据", content=secret))


def test_future_schema_is_rejected_without_changing_database_bytes(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
        db.execute("CREATE TABLE future_payload(value TEXT)")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="更新版本"):
        MemoryStore(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not list(tmp_path.glob("*-wal"))


def test_memory_tools_use_deferred_execution_protocol():
    assert all(spec.execution_protocol for spec in SPECS)


@pytest.mark.asyncio
@pytest.mark.parametrize("scope,kind,content,raw,direct,expected", [
    ("project", "preference", "默认使用中文", "我默认使用中文", True, "active"),
    ("project", "preference", "默认使用中文", "默认使用中文", False, "pending_review"),
    ("project", "preference", "默认使用英文", "我默认使用中文", True, "pending_review"),
    ("project", "preference", "默认使用中文", "示例：默认使用中文", True, "pending_review"),
    ("project", "preference", "默认版本是 3.2", "默认版本是 3.2", True, "pending_review"),
    ("project", "workflow", "默认先测试", "默认先测试", True, "pending_review"),
    ("user", "preference", "默认使用中文", "默认使用中文", True, "pending_review"),
])
async def test_only_verified_project_stable_preferences_auto_activate(worker, scope, kind, content, raw, direct, expected):
    enable(worker)
    session = seed(worker)
    if direct:
        message(worker, session, raw)
    else:
        worker.owner.store.context.append(session["id"], session["last_run_id"], ModelMessage(role="user", content=raw), key="recovery:synthetic", source="user")
    source = worker.owner.store.context.items(session["id"])[-1]
    worker.owner.cloud.result = {"memories": [{"scope": scope, "kind": kind, "title": "偏好", "content": content, "stable_key": "preference", "source_item_ids": [source["item_id"]]}]}
    assert await worker.tick()
    item, = worker.store.list(session["project_id"])
    assert item["status"] == expected and item["legacy"] is False
    assert worker.store.status()["last_attempt"]["state"] == "completed"
    if scope == "user":
        assert item["review_reason"] == "cross_project"
        assert not worker.recall(session["id"], session["project_id"], "中文")[0]


def test_editing_conflict_candidate_confirms_single_topic_without_losing_revisions(worker):
    session = seed(worker)
    project = session["project_id"]
    old = worker.store.put(project, MemoryInput(title="语言", content="中文"), stable_key="language", source_updated_at="1")
    candidate = worker.store.propose(project, MemoryInput(title="语言", content="英文"), stable_key="language", source_updated_at="2")
    result = worker.save(project, MemoryInput(title="语言", content="中英文对照"), identifier=candidate["id"], expected_version=candidate["version"])
    assert result["id"] == old["id"] and result["status"] == "active" and result["origin"] == "user"
    assert len(worker.store.list(project)) == 1
    assert len(worker.store.revisions(project, old["id"])) == 3
    assert worker.store.db.execute("SELECT count(*) FROM memory_revisions WHERE memory_id=?", (candidate["id"],)).fetchone()[0] == 0


@pytest.mark.parametrize("action", ["accept", "edit"])
def test_confirming_or_editing_previous_value_closes_conflict_group(worker, action):
    session = seed(worker)
    project = session["project_id"]
    old = worker.store.put(project, MemoryInput(title="语言", content="中文"), stable_key="language", source_updated_at="1")
    candidate = worker.store.propose(project, MemoryInput(title="语言", content="英文"), stable_key="language", source_updated_at="2")
    with pytest.raises(MemoryConflict):
        if action == "accept":
            worker.store.review(project, old["id"], 1, "accept")
        else:
            worker.save(project, MemoryInput(title="语言", content="中英文对照"), identifier=old["id"], expected_version=1)
    assert len(worker.store.list(project)) == 2
    if action == "accept":
        result = worker.store.review(project, old["id"], 2, "accept")
        assert result["content"] == "中文"
    else:
        result = worker.save(project, MemoryInput(title="语言", content="中英文对照"), identifier=old["id"], expected_version=2)
        assert result["content"] == "中英文对照"
    assert result["id"] == old["id"] and result["version"] == 3 and result["status"] == "active"
    assert len(worker.store.list(project)) == 1
    assert worker.store.db.execute("SELECT count(*) FROM memory_revisions WHERE memory_id=?", (candidate["id"],)).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_session_recall_metadata_keeps_used_version_after_later_edit(worker):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from private_agent_local.memory_routes import install_memory_routes

    enable(worker)
    session = seed(worker)
    worker.owner.memories = worker
    item = worker.store.put(session["project_id"], MemoryInput(title="语言", content="中文"))
    _, ids, entries = worker.recall_with_details(session["id"], session["project_id"], "中文")
    used_date = entries[0]["updated_at"]
    run = worker.owner.store.run_state(session["last_run_id"])
    worker.owner.store.save_run({**run, "memory_context": {"recalled_ids": ids, "omitted_ids": [], "entries": entries}})
    updated = worker.save(session["project_id"], MemoryInput(title="语言", content="英文"), identifier=item["id"], expected_version=1)
    app = FastAPI()
    install_memory_routes(app, lambda: worker.owner)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        response = await client.get(f"/sessions/{session['id']}/memory-settings")
    entry, = response.json()["last_recall"]["entries"]
    assert entry["version"] == 1 and updated["version"] == 2
    assert entry["updated_at"] == used_date
