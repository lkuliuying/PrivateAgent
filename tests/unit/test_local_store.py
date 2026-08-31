"""验证旧记录迁移、事务边界和中断恢复，不接触用户数据库。"""
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from private_agent_local.store import INLINE_BYTES, SCHEMA_VERSION, Store


def legacy_database(path, *, corrupt=False):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE objects(id INTEGER PRIMARY KEY,kind TEXT,data TEXT)")
    db.execute("CREATE TABLE runs(id TEXT PRIMARY KEY,data TEXT)")
    project = {"id": 7, "name": "旧项目", "root_path": "fixture", "status": "active"}
    db.execute("INSERT INTO objects VALUES (?,?,?)", (7, "project", json.dumps(project)))
    run = {"id": "legacy-run", "status": "completed", "session_id": 9, "output": "旧结果",
           "events": [{"sequence": 1, "type": "run.completed", "payload": {"output": "旧结果"}}],
           "approvals": [{"id": "approval", "status": "consumed", "preview": {"diff": "旧内容"}}], "executions": []}
    db.execute("INSERT INTO runs VALUES (?,?)", (run["id"], "invalid-json" if corrupt else json.dumps(run)))
    db.commit()
    db.close()
    return project, run


def test_migration_preserves_ids_content_backup_and_is_idempotent(tmp_path):
    path = tmp_path / "projects.sqlite3"
    project, run = legacy_database(path)
    store = Store(path)
    assert store.get("project", 7) == project
    assert store.run(run["id"]) == run
    assert store.create("session", {"project_id": 7})["id"] == 8
    evidence = json.loads(store.db.execute("SELECT evidence FROM schema_migrations").fetchone()[0])
    assert evidence["counts"] == {"objects": 1, "runs": 1}
    backup = tmp_path / evidence["backup"]["filename"]
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == evidence["backup"]["sha256"]
    with sqlite3.connect(backup) as old:
        assert json.loads(old.execute("SELECT data FROM runs").fetchone()[0]) == run
    store.db.close()
    restarted = Store(path)
    assert restarted.run(run["id"]) == run
    assert len(list(tmp_path.glob("*.pre-v2-*.sqlite3"))) == 1
    assert restarted.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    restarted.db.close()


def test_failed_migration_rolls_back_schema_and_preserves_source(tmp_path):
    path = tmp_path / "broken.sqlite3"
    legacy_database(path, corrupt=True)
    with pytest.raises(ValueError):
        Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT data FROM runs").fetchone()[0] == "invalid-json"
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM objects").fetchone()[0] == 1
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='schema_migrations'").fetchall()


def test_v2_upgrade_backs_up_and_preserves_records(tmp_path):
    path = tmp_path / "v2.sqlite3"
    original = Store(path)
    project = original.create("project", {"name": "原项目", "root_path": "fixture"})
    original.db.execute("DROP TABLE history_imports")
    original.db.execute("DELETE FROM schema_migrations WHERE version=3")
    original.db.execute("PRAGMA user_version=2")
    original.db.commit()
    original.db.close()
    current = Store(path)
    try:
        assert current.get("project", project["id"]) == project
        assert current.db.execute("PRAGMA user_version").fetchone()[0] == 3
        evidence = json.loads(current.db.execute("SELECT evidence FROM schema_migrations WHERE version=3").fetchone()[0])
        backup = tmp_path / evidence["backup"]["filename"]
        assert hashlib.sha256(backup.read_bytes()).hexdigest() == evidence["backup"]["sha256"]
        with sqlite3.connect(backup) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 2
    finally:
        current.db.close()


def test_events_append_immutable_and_status_changes_rollback_together(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    run = {"id": "run", "status": "running", "events": [{"sequence": 1, "type": "run.started"}]}
    store.save_run(run)
    run["events"].append({"sequence": 2, "type": "model.started"})
    store.save_run(run)
    assert [e["sequence"] for e in store.events("run", after=1)] == [2]
    run["status"] = "completed"
    run["events"][0]["type"] = "tampered"
    with pytest.raises(ValueError, match="不可修改"):
        store.save_run(run)
    assert store.run_state("run")["status"] == "running"
    assert store.events("run")[0]["type"] == "run.started"
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.create("message", {"session_id": 1, "content": "事务内消息"})
            raise RuntimeError("fixture")
    assert store.list("message", session_id=1) == []
    store.db.close()


def test_large_content_uses_verified_artifact_and_detects_tampering(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    item = store.create("message", {"session_id": 1, "content": "中" * INLINE_BYTES})
    packed = store.db.execute("SELECT data FROM messages").fetchone()[0]
    reference = json.loads(packed)
    assert len(packed) < 200 and "$artifact" in reference
    assert store.get("message", item["id"]) == item
    (store.blobs / reference["$artifact"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        store.get("message", item["id"])
    store.db.close()


def test_restart_revokes_grants_and_marks_side_effects_unknown(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = Store(path)
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    grant = store.grant(1, 2, expires)
    assert store.active_grant(1)["id"] == grant["id"]
    store.save_run({"id": "run", "status": "running", "approvals": [{"id": "a", "status": "pending"}],
                    "executions": [{"id": "e", "status": "running"}]})
    store.db.close()
    restarted = Store(path)
    run = restarted.run("run")
    assert run["status"] == "failed"
    assert run["executions"][0]["status"] == "unknown"
    assert run["approvals"][0]["status"] == "cancelled"
    assert run["events"][-1]["payload"]["replayed"] is False
    assert restarted.active_grant(1) is None
    assert restarted.db.execute("SELECT count(*) FROM audit_events WHERE kind='full_access.revoked'").fetchone()[0] == 1
    restarted.db.close()
