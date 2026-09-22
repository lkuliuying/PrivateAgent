"""隔离数据库与临时 Git 仓库中的搜索、队列、技能和交接回归。"""
import asyncio
import subprocess

import pytest
from test_local_executor import close, setup

from private_agent_local.skills import manifest
from private_agent_local.turn_queue import TurnQueue
from private_agent_local.worktree_handoff import WorktreeHandoff


@pytest.fixture
async def local(tmp_path):
    value = await setup(tmp_path)
    try:
        yield value
    finally:
        await close(value[0], value[1])


@pytest.mark.asyncio
async def test_message_search_paginates_and_filters_archive_and_timezone(local):
    app, client, _, _, body = local
    store = app.state.desktop.runtime.store
    for number in range(7):
        store.create("message", {"session_id": body["session_id"], "role": "assistant", "content": f"查询目标 {number}"})
    params = {"q": "查询目标", "limit": 3, "since": "2020-01-01T08:00:00+08:00"}
    first = (await client.get("/workspace-search", params=params)).json()
    second = (await client.get("/workspace-search", params={**params, "before": first["next_cursor"]})).json()
    assert len(first["items"]) == len(second["items"]) == 3
    assert {v["message_id"] for v in first["items"]}.isdisjoint(v["message_id"] for v in second["items"])
    assert (await client.post(f"/sessions/{body['session_id']}/archive")).status_code == 200
    assert not (await client.get("/workspace-search", params=params)).json()["items"]
    archived = (await client.get("/workspace-search", params={**params, "archived": "true"})).json()["items"]
    assert archived and all(v["archived"] for v in archived)
    assert not (await client.get("/sessions/recent")).json()
    assert (await client.post(f"/sessions/{body['session_id']}/unarchive")).status_code == 200
    assert (await client.get(f"/sessions/{body['session_id']}")).json()["id"] == body["session_id"]


@pytest.mark.asyncio
async def test_search_reads_full_blob_but_excludes_internal_agents(local):
    app, client, _, _, body = local
    store = app.state.desktop.runtime.store
    message = store.create("message", {"session_id": body["session_id"], "role": "assistant", "content": "a" * 200000 + "唯一正文命中"})
    hits = (await client.get("/workspace-search", params={"q": "唯一正文命中"})).json()["items"]
    assert [v["message_id"] for v in hits] == [message["id"]]
    store.update("session", body["session_id"], agent_parent_run_id="parent")
    assert not (await client.get("/workspace-search", params={"q": "唯一正文命中"})).json()["items"]


def seeded(owner, body):
    created = owner.create({**body, "permission_mode": "readonly", "recovery_contract_version": "1.0", "execution_contract_version": "1.0"}, launch=False)
    return owner.store.run(created["id"])


@pytest.mark.asyncio
async def test_queue_exactly_once_inherits_configuration_and_can_cancel(local, monkeypatch):
    app, _, _, _, body = local
    owner = app.state.desktop.runtime
    run = seeded(owner, body)
    run["allow_subagents"] = True
    queue = owner.turn_queue
    item = queue.enqueue(body["session_id"], run["id"], "request-1", "检查结果")
    assert queue.enqueue(body["session_id"], run["id"], "request-1", "检查结果") == item
    with pytest.raises(ValueError, match="不一致"):
        queue.enqueue(body["session_id"], run["id"], "request-1", "不同内容")
    run["status"] = "completed"
    owner.store.save_run(run)
    launched = []
    monkeypatch.setattr(owner, "launch", launched.append)
    queue.advance(body["session_id"], run["id"])
    queue.advance(body["session_id"], run["id"])
    assert len(launched) == 1
    assert launched[0]["allow_subagents"] is False and launched[0]["permission_mode"] == "readonly"
    assert queue.get(body["session_id"])["state"] == "launched"
    with pytest.raises(ValueError, match="已经启动"):
        queue.cancel(body["session_id"], "request-1")


@pytest.mark.asyncio
async def test_queue_restart_or_failed_run_preserves_input_without_execution(local, monkeypatch):
    app, _, _, _, body = local
    owner = app.state.desktop.runtime
    run = seeded(owner, body)
    queue = owner.turn_queue
    queue.enqueue(body["session_id"], run["id"], "pending", "不要丢失")
    launched = []
    monkeypatch.setattr(owner, "launch", launched.append)
    run["status"] = "failed"
    owner.store.save_run(run)
    queue.advance(body["session_id"], run["id"])
    assert queue.get(body["session_id"])["state"] == "blocked"
    assert queue.cancel(body["session_id"], "pending")["message"] == "不要丢失"
    run["status"] = "running"
    owner.store.save_run(run)
    queue.enqueue(body["session_id"], run["id"], "restart", "重启保留")
    assert TurnQueue(owner).get(body["session_id"])["state"] == "blocked"
    assert not launched


@pytest.mark.asyncio
async def test_skill_creation_explicit_enable_and_version_revocation(local):
    app, client, _, root, body = local
    base = f"/projects/{body['project_id']}/skills"
    content = "---\nname: 审阅\ndescription: 检查代码\n---\n只读取代码并给出证据。"
    result = await client.post(base, json={"name": "review", "scope": "project", "content": content})
    assert result.status_code == 201, result.text
    item, = (await client.get(base)).json()["items"]
    assert not item["enabled"]
    assert (await client.put(base + "/project:review", json={"enabled": True, "expected_version": item["version"]})).status_code == 200
    owner = app.state.desktop.runtime
    run = {**body, "permission_mode": "readonly", "completion_policy": {}}
    loaded = owner.skills.execute(run, root, {"name": "load_skill", "arguments": {"skill_id": "project:review", "expected_version": item["version"]}})
    assert loaded["content"] == content
    (root / ".agents/skills/review/reference.md").write_text("参考内容", encoding="utf-8")
    reference_call = {"name": "read_skill_reference", "arguments": {"skill_id": "project:review", "expected_version": item["version"], "rel_path": "reference.md"}}
    assert "参考内容" in str(owner.skills.execute(run, root, reference_call))
    reference_call["arguments"]["rel_path"] = "../../outside.md"
    with pytest.raises(ValueError):
        owner.skills.execute(run, root, reference_call)
    (root / ".agents/skills/review/SKILL.md").write_text(content + "\n修改", encoding="utf-8")
    assert not (await client.get(base)).json()["items"][0]["enabled"]
    with pytest.raises(ValueError):
        owner.skills.content(body["project_id"], "project:review", item["version"])
    assert (await client.post(base, json={"name": "../outside", "scope": "user", "content": content})).status_code == 422
    assert not list(root.parent.glob("outside*"))


@pytest.mark.parametrize("text", ["no header", "---\nname: missing\n---", '---\nname: test\ndescription: test\nrequires: ["../script"]\n---'])
def test_skill_manifest_rejects_unsupported_dependencies(text):
    with pytest.raises(ValueError):
        manifest(text)


def git(root, *args):
    return subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", *args], cwd=root, check=True, capture_output=True)


@pytest.mark.asyncio
async def test_handoff_conflict_version_retry_and_retained_source(local):
    app, client, _, root, body = local
    owner = app.state.desktop.runtime
    git(root, "init")
    (root / "note.txt").write_bytes(b"base\n")
    git(root, "add", "note.txt")
    git(root, "commit", "-m", "fixture")
    worktree = owner.workspaces.create_worktree(body["project_id"], "HEAD", "isolated-1")
    source = owner.root(body["project_id"], worktree["id"])
    owner.store.update("session", body["session_id"], workspace_id=worktree["id"])
    (source / "note.txt").write_bytes(b"changed\n")
    (source / "nested").mkdir()
    (source / "nested/new.txt").write_bytes(b"new\n")
    (root / "note.txt").write_bytes(b"local change\n")
    service = WorktreeHandoff(owner)
    conflict = await service.preview(body["project_id"], worktree["id"])
    assert conflict["conflicts"][0]["rel_path"] == "note.txt"
    with pytest.raises(ValueError, match="冲突"):
        await service.apply(body["project_id"], worktree["id"], conflict["version"], "handoff-1", body["session_id"])
    (root / "note.txt").write_bytes(b"base\r\n")
    preview = await service.preview(body["project_id"], worktree["id"])
    assert not preview["conflicts"]
    result = await service.apply(body["project_id"], worktree["id"], preview["version"], "handoff-2", body["session_id"])
    assert result["state"] == "applied", result
    assert (root / "note.txt").read_bytes() == b"changed\n"
    assert (root / "nested/new.txt").read_bytes() == b"new\n"
    assert source.is_dir() and (source / "note.txt").exists()
    assert await service.apply(body["project_id"], worktree["id"], preview["version"], "handoff-2", body["session_id"]) == result
    history = (await client.get(f"/projects/{body['project_id']}/handoffs")).json()
    assert history["items"][-1]["state"] == "applied"
    review = await client.get(f"/sessions/{body['session_id']}/review?scope=workspace")
    assert review.status_code == 200 and review.json()["workspace"]["is_git"]


@pytest.mark.asyncio
async def test_child_guard_rejects_parent_generation_change(local):
    app, _, _, _, body = local
    owner = app.state.desktop.runtime
    parent = seeded(owner, body)
    owner.live[parent["id"]] = parent
    child = {"agent_parent_run_id": parent["id"], "agent_parent_generation": parent.get("generation", 0), "recovery_contract_version": "1.0"}
    owner.controls.guard(child)
    parent["generation"] = parent.get("generation", 0) + 1
    with pytest.raises(asyncio.CancelledError):
        await owner.controls._boundary(child, model=True)
    owner.live.pop(parent["id"])
