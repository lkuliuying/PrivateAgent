"""S2-T03/T04：原始有序历史、缺失结果、幂等及迁移事务。"""
import json
import sqlite3

import pytest
from test_local_executor import TERMINAL, call, close, response, setup, until

from private_agent_core.contracts import ModelMessage, ToolCall
from private_agent_local.store import SCHEMA_VERSION, Store


def history_store(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    session = store.create("session", {})["id"]
    return store, session


def test_idempotent_context_and_session_scoped_content(tmp_path):
    store, session = history_store(tmp_path)
    try:
        message = ModelMessage(role="user", content="内容" * 20000)
        first = store.context.append(session, "run", message, key="one", source="user")
        assert store.context.append(session, "run", message, key="one", source="user") == first
        assert len(store.context.items(session)) == 1
        with pytest.raises(ValueError, match="冲突"):
            store.context.append(session, "run", ModelMessage(role="user", content="different"), key="one", source="user")
        with pytest.raises(ValueError, match="当前会话"):
            store.context.read(session + 1, first["item_id"], 0, 100)
        page = store.context.read(session, first["item_id"], 0, 100)
        assert len(page["content"]) == 100 and page["next_offset"] == 100
    finally:
        store.db.close()


def test_missing_result_recovered_as_unknown_without_replay(tmp_path):
    store, session = history_store(tmp_path)
    call = ToolCall(id="call", name="write_project_file", arguments={"rel_path": "x", "content": "x"})
    store.context.append(session, "run", ModelMessage(role="assistant", tool_calls=(call,)), key="call", source="model")
    store.save_run({"id": "run", "session_id": session, "status": "running"})
    path = store.path
    store.db.close()
    recovered = Store(path)
    try:
        items = recovered.context.items(session)
        assert len(items) == 2 and items[1]["tool_call_id"] == "call"
        assert "result_unknown" in items[1]["message"]["content"]
        recovered.context.close_pending(session, "run")
        assert len(recovered.context.items(session)) == 2
    finally:
        recovered.db.close()


@pytest.mark.parametrize("fail", [False, True])
def test_v3_context_migration_backup_and_failure_rollback(tmp_path, monkeypatch, fail):
    store, session = history_store(tmp_path)
    original = store.create("message", {"session_id": session, "role": "user", "content": "原始消息"})
    path = store.path
    store.db.execute("DROP TABLE context_items")
    store.db.execute("DROP TABLE context_checkpoints")
    store.db.execute("DELETE FROM schema_migrations")
    store.db.execute("PRAGMA user_version=3")
    store.db.commit()
    store.db.close()
    schema = Store._context_schema
    if fail:
        def broken(self):
            schema(self)
            raise sqlite3.OperationalError("fixture migration failure")
        monkeypatch.setattr(Store, "_context_schema", broken)
        with pytest.raises(sqlite3.OperationalError):
            Store(path)
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 3
            assert not db.execute("SELECT name FROM sqlite_master WHERE name='context_items'").fetchall()
    else:
        current = Store(path)
        try:
            assert current.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
            current.context.import_legacy(session)
            current.context.import_legacy(session)
            assert len(current.context.items(session)) == 2
            assert current.context.items(session)[0]["source"] == "legacy"
            assert current.get("message", original["id"]) == original
        finally:
            current.db.close()
    backups = list(tmp_path.glob("*.pre-v4-*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3


@pytest.mark.asyncio
async def test_early_constraint_after_twelve_messages_and_tool_pairing(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        store = app.state.desktop.runtime.store
        for i in range(16):
            store.create("message", {"session_id": body["session_id"], "role": "user" if i % 2 == 0 else "assistant",
                                    "content": "早期禁止项：不要修改 protected.txt" if i == 0 else f"历史 {i}"})
        server.responses = [response(call("read_code_file", {"rel_path": "missing.txt"}), call("list_project_directory", {})), response(text="读取结果已检查")]
        run = (await client.post("/agent-runs", json={**body, "client_request_id": "idempotent"})).json()
        await until(client, run["id"], TERMINAL)
        await client.post("/agent-runs", json={**body, "client_request_id": "idempotent"})
        requests = [json.loads(data)["request"] for path, data in server.calls if path == "/desktop/model/complete"]
        assert "早期禁止项" in json.dumps(requests[-1], ensure_ascii=False)
        items = store.context.items(body["session_id"])
        assert len([i for i in items if i["run_id"] == run["id"] and i["source"] == "user"]) == 1
        calls = next(i["message"]["tool_calls"] for i in items if i["kind"] == "tool_call")
        results = [i for i in items if i["role"] == "tool"]
        assert [r["tool_call_id"] for r in results] == [c["id"] for c in calls]
        executions = store.run(run["id"])["executions"]
        assert [r["execution_id"] for r in results] == [execution["id"] for execution in executions]
        assert [r["source_sequence"] for r in results] == [execution["source_sequence"] for execution in executions]
        assert json.loads(results[0]["message"]["content"])["success"] is False
        assert len([i for i in items if i["message"]["content"] == "读取结果已检查"]) == 1
    finally:
        await close(app, client)
