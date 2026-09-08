"""S3 真实文件、持久日志、受保护回滚与主链验收。"""
import asyncio
import os
import sqlite3
import uuid

import pytest
from test_local_executor import call, close, response, setup, until

from private_agent_core.patches import PatchProposal
from private_agent_local import git_workspace, patchsets, policy
from private_agent_local.patchsets import PatchService
from private_agent_local.runtime import TERMINAL
from private_agent_local.store import SCHEMA_VERSION, Store


@pytest.fixture
def service(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    store = Store(tmp_path / "state.sqlite3")
    run = {"id": "run", "status": "completed", "workspace_id": 1, "permission_mode": "workspace"}
    store.save_run(run)
    yield PatchService(store), run, root
    store.db.close()


async def guard():
    await asyncio.sleep(0)


def propose(service, operations):
    svc, run, root = service
    return svc.propose(run, root, PatchProposal.model_validate({"operations": operations}), str(uuid.uuid4()))


def existing(service, relative, operation="update", **extra):
    svc, run, root = service
    read = svc.repository.read(run, root, relative)
    return {"operation": operation, "rel_path": relative, "snapshot_id": read["snapshot_id"], **extra}


async def apply(service, patch):
    svc, run, root = service
    return await svc.apply(run, root, patch["patch_set_id"], patch["preview_sha256"], guard)


@pytest.mark.asyncio
async def test_multi_file_crlf_bom_tail_create_delete_move_and_rollback(service):
    svc, run, root = service
    before = b"\xef\xbb\xbf" + ("unchanged\r\n" * 2100 + "bad\r\n").encode()
    (root / "中文 空格.py").write_bytes(before)
    (root / "delete.txt").write_text("remove me")
    (root / "move.txt").write_text("keep me")
    patch = propose(service, [
        existing(service, "中文 空格.py", edits=[{"start_line": 2101, "delete_count": 1, "text": "good\n"}]),
        {"operation": "mkdir", "rel_path": "new"}, {"operation": "mkdir", "rel_path": "new/sub"},
        {"operation": "create", "rel_path": "new/sub/file", "content": "created"},
        existing(service, "delete.txt", "delete"), existing(service, "move.txt", "move", new_rel_path="new/moved.txt")])
    assert (root / "delete.txt").exists() and not (root / "new").exists()
    assert (await apply(service, patch))["status"] == "applied"
    assert (root / "中文 空格.py").read_bytes() == before[:-5] + b"good\r\n"
    assert not (root / "delete.txt").exists() and not (root / "move.txt").exists()
    assert (root / "new/moved.txt").read_text() == "keep me"
    assert all(item["verified"] for item in svc.facts(run["id"], patch["patch_set_id"], root))
    rollback = svc.rollback_preview(run, root, patch["patch_set_id"], "rollback")
    assert not rollback["conflicts"] and (await apply(service, rollback))["status"] == "applied"
    assert (root / "中文 空格.py").read_bytes() == before
    assert (root / "delete.txt").read_text() == "remove me" and (root / "move.txt").read_text() == "keep me"
    assert not (root / "new").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("moment", ["read", "preview", "replace"])
async def test_external_edits_at_each_boundary_preserved(service, monkeypatch, moment):
    svc, run, root = service
    target = root / "x"
    target.write_text("before")
    operation = existing(service, "x", content="agent")
    if moment == "read":
        target.write_text("user")
        with pytest.raises(ValueError, match="读取后已变化"):
            propose(service, [operation])
    else:
        patch = propose(service, [operation])
        if moment == "preview":
            target.write_text("user")
        else:
            original = patchsets.replace_one
            def concurrent(root, change):
                target.write_text("user")
                return original(root, change)
            monkeypatch.setattr(patchsets, "replace_one", concurrent)
        assert (await apply(service, patch))["status"] != "applied"
    assert target.read_text() == "user"


@pytest.mark.asyncio
async def test_second_write_failure_and_recovery_retains_later_user_edit(service, monkeypatch):
    svc, run, root = service
    patch = propose(service, [{"operation": "create", "rel_path": name, "content": name} for name in ("a", "b")])
    original = patchsets.replace_one
    def fail_second(root, change):
        if change["rel_path"] == "b":
            raise OSError("disk full")
        return original(root, change)
    monkeypatch.setattr(patchsets, "replace_one", fail_second)
    result = await apply(service, patch)
    assert result["status"] == "partially_applied" and (root / "a").read_text() == "a" and not (root / "b").exists()
    assert [item["journal_status"] for item in svc.facts(run["id"], patch["patch_set_id"], root)] == ["applied", "applying"]
    (root / "a").write_text("user later")
    rollback = svc.rollback_preview(run, root, patch["patch_set_id"], "rollback")
    assert rollback["status"] == "conflicted" and {item["rel_path"] for item in rollback["conflicts"]} == {"a", "b"}
    assert (root / "a").read_text() == "user later"


@pytest.mark.asyncio
async def test_idempotency_preview_tampering_revoke_and_large_diff(service):
    svc, run, root = service
    patch = propose(service, [{"operation": "create", "rel_path": "large", "content": "long line\n" * 9000}])
    public = svc.public(patch)
    assert public["truncated"]
    offset, text = 0, ""
    while offset is not None:
        page = svc.diff_page(run["id"], patch["patch_set_id"], patch["changes"][0]["change_id"], offset, 8000)
        text += page["content"]
        offset = page["next_offset"]
    assert text == patch["changes"][0]["diff"]
    with pytest.raises(ValueError, match="批准绑定"):
        await svc.apply(run, root, patch["patch_set_id"], "0" * 64, guard)
    async def revoke():
        raise ValueError("grant revoked")
    with pytest.raises(ValueError, match="revoked"):
        await svc.apply(run, root, patch["patch_set_id"], patch["preview_sha256"], revoke)
    assert not (root / "large").exists()
    assert (await apply(service, patch))["status"] == "applied"
    stamp = (root / "large").stat().st_mtime_ns
    assert (await apply(service, patch))["status"] == "applied"
    assert (root / "large").stat().st_mtime_ns == stamp
    with pytest.raises(ValueError):
        svc.get("other", patch["patch_set_id"])


@pytest.mark.parametrize("boundary", ["before_intent", "after_intent", "after_disk", "after_record"])
def test_restart_journal_distinguishes_unstarted_before_after_unknown(service, boundary):
    svc, run, root = service
    patch = propose(service, [{"operation": "create", "rel_path": "x", "content": "x"}])
    patch["status"] = "applying"
    svc.save(patch)
    change = patch["changes"][0]
    if boundary != "before_intent":
        svc.journal(patch, change, "applying")
    if boundary in {"after_disk", "after_record"}:
        actual = patchsets.replace_one(root, change)
        if boundary == "after_record":
            svc.journal(patch, change, "applied", after=actual)
    restarted = Store(svc.store.path)
    try:
        recovered = PatchService(restarted)
        assert recovered.get(run["id"], patch["patch_set_id"])["status"] == "interrupted"
        fact = recovered.facts(run["id"], patch["patch_set_id"], root)[0]
        assert fact["verified"] is (boundary == "after_record")
        assert fact["observation"] == ("matches_after" if boundary in {"after_disk", "after_record"} else "matches_before")
        assert (root / "x").exists() is (boundary in {"after_disk", "after_record"})
    finally:
        restarted.db.close()


def test_schema4_upgrade_is_backed_up(service):
    svc, run, root = service
    store = svc.store
    for name in ("execution_chunks", "managed_executions", "patch_journal", "patch_sets", "file_snapshots"):
        store.db.execute(f"DROP TABLE {name}")
    store.db.execute("DELETE FROM schema_migrations WHERE version=?", (SCHEMA_VERSION,))
    store.db.execute("PRAGMA user_version=4")
    store.db.commit()
    reopened = Store(store.path)
    try:
        assert reopened.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert reopened.run("run")["id"] == "run"
        backups = list(store.path.parent.glob("*.pre-v6-*.sqlite3"))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as old:
            assert old.execute("PRAGMA user_version").fetchone()[0] == 4
    finally:
        reopened.db.close()


@pytest.mark.parametrize("operations", [
    [{"operation": "create", "rel_path": "x", "content": "x"}, {"operation": "create", "rel_path": "X", "content": "x"}],
    [{"operation": "create", "rel_path": "x", "content": "x"}, {"operation": "create", "rel_path": "x/sub", "content": "x"}],
    [{"operation": "update", "rel_path": "x", "content": "x"}],
    [{"operation": "mkdir", "rel_path": "../out"}],
])
def test_invalid_patch_contracts_are_rejected_before_any_io(service, operations):
    with pytest.raises(ValueError):
        propose(service, operations)
    assert list(service[2].iterdir()) == []


@pytest.mark.asyncio
async def test_move_rollback_preserves_both_sides_if_source_occupied(service):
    svc, run, root = service
    (root / "source").write_text("original")
    patch = propose(service, [existing(service, "source", "move", new_rel_path="destination")])
    assert (await apply(service, patch))["status"] == "applied"
    (root / "source").write_text("user new")
    rollback = svc.rollback_preview(run, root, patch["patch_set_id"], "rollback-move")
    assert rollback["status"] == "conflicted" and len(rollback["conflicts"]) == 2
    assert (root / "source").read_text() == "user new" and (root / "destination").read_text() == "original"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["intent", "record", "terminal", "cancel"])
async def test_journal_failures_and_cancellation_do_not_hide_effects(service, monkeypatch, failure):
    svc, run, root = service
    patch = propose(service, [{"operation": "create", "rel_path": "x", "content": "created"}])
    journal, save = svc.journal, svc.save
    def fail_journal(patch, change, status, **facts):
        if (failure == "intent" and status == "applying") or (failure == "record" and status == "applied"):
            raise sqlite3.OperationalError("fixture durable write failure")
        return journal(patch, change, status, **facts)
    def fail_save(patch):
        if failure == "terminal" and patch["status"] == "applied":
            raise sqlite3.OperationalError("fixture terminal commit failure")
        return save(patch)
    count = 0
    async def controlled_guard():
        nonlocal count
        count += 1
        if failure == "cancel" and count == 2:
            raise asyncio.CancelledError
    monkeypatch.setattr(svc, "journal", fail_journal)
    monkeypatch.setattr(svc, "save", fail_save)
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await svc.apply(run, root, patch["patch_set_id"], patch["preview_sha256"], controlled_guard)
    else:
        assert (await apply(service, patch))["status"] != "applied"
    assert (root / "x").exists() is (failure in {"record", "terminal"})
    facts = svc.facts(run["id"], patch["patch_set_id"], root)[0]
    assert facts["journal_status"] == {"intent": "not_started", "record": "applying", "terminal": "applied", "cancel": "not_started"}[failure]


@pytest.mark.asyncio
async def test_root_identity_preview_tampering_and_readonly_are_rejected(service):
    svc, run, root = service
    patch = propose(service, [{"operation": "create", "rel_path": "x", "content": "x"}])
    corrupted = svc.get(run["id"], patch["patch_set_id"])
    corrupted["changes"][0]["after"]["text"] = "tampered"
    svc.save(corrupted)
    with pytest.raises(ValueError, match="批准绑定"):
        await apply(service, patch)
    svc.save(patch)
    with pytest.raises(ValueError):
        await svc.apply({**run, "permission_mode": "readonly"}, root, patch["patch_set_id"], patch["preview_sha256"], guard)
    old = root.with_name("previous-root")
    assert root.resolve().parent == old.resolve().parent and not old.exists()
    root.rename(old)
    root.mkdir()
    with pytest.raises(ValueError, match="工作区"):
        await apply(service, patch)
    assert not (root / "x").exists() and not (old / "x").exists()


def test_git_baseline_dirty_parent_repo_and_nested_repository_protection(service):
    from test_local_git import initialize_repository
    svc, run, root = service
    initialize_repository(root)
    (root / "tracked.txt").write_text("user change")
    (root / "user file.txt").write_text("user untracked")
    baseline = git_workspace.inspect(root)
    assert baseline["dirty"] and {item["rel_path"] for item in baseline["dirty_entries"]} == {"tracked.txt", "user file.txt"}
    child = root / "child"
    child.mkdir()
    assert git_workspace.inspect(child)["is_git"] is False
    (child / ".git").write_text("gitdir: fixture")
    with pytest.raises(ValueError, match="嵌套"):
        propose(service, [{"operation": "create", "rel_path": "child/x", "content": "x"}])
    assert (root / "tracked.txt").read_text() == "user change"


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell 入口")
@pytest.mark.parametrize("mode", ["confirm", "workspace", "full_access"])
def test_all_powershell_file_write_actions_are_closed(service, mode):
    for name in policy.POWERSHELL_FILE_WRITES:
        with pytest.raises(ValueError, match="统一补丁工具"):
            policy.powershell_plan(service[2], name, [], mode)


@pytest.mark.asyncio
async def test_runtime_patch_asgi_approval_completion_and_rollback(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        (root / "x.py").write_text("before\n")
        runtime = app.state.desktop.runtime
        server.profiles[0]["context_tokens"] = 128000
        stage = 0
        async def model(*_):
            nonlocal stage
            stage += 1
            run = runtime.store.runs()[0]
            if stage == 1:
                return response(call("read_code_file", {"rel_path": "x.py"}))
            if stage == 2:
                return response(call("propose_project_patch", {"operations": [
                    {"operation": "update", "rel_path": "x.py", "snapshot_id": runtime.repository.latest(run["id"], "x.py"),
                     "edits": [{"start_line": 1, "delete_count": 1, "text": "after\n"}]},
                    {"operation": "create", "rel_path": "new.txt", "content": "new"}]}))
            if stage == 3:
                patch = runtime.patches.list(run["id"])[0]
                return response(call("apply_project_patch", {"patch_set_id": patch["patch_set_id"], "preview_sha256": patch["preview_sha256"]}))
            return response(text="文件已修改并回读")
        runtime.cloud.complete = model
        created = (await client.post("/agent-runs", json={**body, "message": "更新 x.py 和新增 new.txt"})).json()
        run_id = created["id"]
        await until(client, run_id, {"waiting_approval"})
        assert (root / "x.py").read_text() == "before\n"
        approval = (await client.get(f"/agent-runs/{run_id}/approvals")).json()[0]
        preview = (await client.get(f"/agent-runs/{run_id}/approvals/{approval['id']}/preview")).json()
        assert len(preview["changes"]) == 2
        await client.post(f"/agent-runs/{run_id}/approvals/{approval['id']}/approve")
        final = await until(client, run_id, TERMINAL)
        assert final["goal_outcome"] == "verified", final
        listing = (await client.get(f"/agent-runs/{run_id}/patches")).json()
        assert listing["patches"][0]["status"] == "applied"
        patch_id = preview["patch_set_id"]
        rollback = (await client.post(f"/agent-runs/{run_id}/patches/{patch_id}/rollback-preview", json={"operation_id": "undo"})).json()
        result = await client.post(f"/agent-runs/{run_id}/patches/{rollback['patch_set_id']}/apply", json={"preview_sha256": rollback["preview_sha256"]})
        assert result.json()["status"] == "applied", result.text
        assert (root / "x.py").read_text() == "before\n" and not (root / "new.txt").exists()
        assert (await client.get(f"/agent-runs/{run_id}")).json()["goal_outcome"] == "unknown"
        stamp = (root / "x.py").stat().st_mtime_ns
        events_before = len(runtime.store.events(run_id))
        repeated = await client.post(f"/agent-runs/{run_id}/patches/{rollback['patch_set_id']}/apply", json={"preview_sha256": rollback["preview_sha256"]})
        assert repeated.json() == result.json()
        assert len(runtime.store.events(run_id)) == events_before and (root / "x.py").stat().st_mtime_ns == stamp
        client.headers["Authorization"] = "Bearer account-b"
        await client.post("/identity")
        assert (await client.get(f"/agent-runs/{run_id}/patches")).status_code == 404
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_py07_actual_task_tail_patch_preserves_user_files(tmp_path):
    from coding_task_baseline import judge, load_catalog, materialize
    task = next(item for item in load_catalog()["tasks"] if item["id"] == "PY07")
    root = tmp_path / "PY07"
    materialize(task, root)
    initial = judge(task, root)
    assert initial["passed"] is False and initial["reason"] == "assertion_failed"
    store = Store(tmp_path / "task.sqlite3")
    run = {"id": "py07", "status": "completed", "workspace_id": 1, "permission_mode": "workspace"}
    store.save_run(run)
    svc = PatchService(store)
    try:
        relative = task["editable_files"][0]
        lines = (root / relative).read_text(encoding="utf-8").splitlines(keepends=True)
        read = svc.repository.read(run, root, relative, len(lines), 1)
        patch = svc.propose(run, root, PatchProposal.model_validate({"operations": [{"operation": "update", "rel_path": relative,
            "snapshot_id": read["snapshot_id"], "edits": [{"start_line": len(lines), "delete_count": 1,
                "text": "    return value['items'][value['start']-1:value['end']]\n"}]}]}), "py07-fix")
        assert (await svc.apply(run, root, patch["patch_set_id"], patch["preview_sha256"], guard))["status"] == "applied"
        result = judge(task, root)
        assert result["passed"] is True, result
        assert (root / relative).read_text(encoding="utf-8").splitlines(keepends=True)[:-1] == lines[:-1]
    finally:
        store.db.close()
