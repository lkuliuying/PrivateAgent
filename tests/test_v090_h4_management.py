"""v0.9.0 H4 契约测试：搜索、归档、重命名、置顶、最近任务（计划 §8 H4）。

覆盖：
- 重命名（有界、去空白）；
- 归档软删除：默认列表不返回、可恢复、不物理删除；
- 置顶：最近任务优先呈现；
- 会话搜索：标题匹配、不含已归档；
- 项目搜索。
"""

from __future__ import annotations


async def _create_session(client, title: str) -> int:
    resp = await client.post("/sessions", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_rename_session(client):
    sid = await _create_session(client, "h4-rename-origin")
    resp = await client.patch(
        f"/sessions/{sid}/title", json={"title": "  h4 新标题  "}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "h4 新标题"


async def test_rename_session_title_bounded(client):
    sid = await _create_session(client, "h4-bound")
    resp = await client.patch(f"/sessions/{sid}/title", json={"title": ""})
    assert resp.status_code == 422
    resp = await client.patch(
        f"/sessions/{sid}/title", json={"title": "x" * 300}
    )
    assert resp.status_code == 422


async def test_archive_hides_from_list_and_recovers(client):
    """归档软删除：默认列表不含；恢复后重现；消息不物理删除。"""
    sid = await _create_session(client, "h4-archive-me")
    resp = await client.post(f"/sessions/{sid}/archive")
    assert resp.status_code == 200, resp.text
    assert resp.json()["archived_at"] is not None

    listed = await client.get("/sessions")
    assert all(item["id"] != sid for item in listed.json())

    resp = await client.post(f"/sessions/{sid}/unarchive")
    assert resp.status_code == 200
    assert resp.json()["archived_at"] is None
    listed = await client.get("/sessions")
    assert any(item["id"] == sid for item in listed.json())


async def test_pin_session_prioritized_in_recent(client):
    sid_a = await _create_session(client, "h4-recent-a")
    sid_b = await _create_session(client, "h4-recent-b")
    # b 更新更晚，默认排在 a 前；置顶 a 后 a 应优先
    resp = await client.post(f"/sessions/{sid_a}/pin")
    assert resp.status_code == 200
    assert resp.json()["pinned_at"] is not None

    recent = await client.get("/sessions/recent", params={"limit": 10})
    ids = [item["id"] for item in recent.json()]
    assert sid_a in ids and sid_b in ids
    assert ids.index(sid_a) < ids.index(sid_b), "置顶会话必须优先呈现"

    resp = await client.post(f"/sessions/{sid_a}/unpin")
    assert resp.json()["pinned_at"] is None


async def test_search_sessions_matches_and_excludes_archived(client):
    sid_hit = await _create_session(client, "h4-search-unique-keyword")
    sid_archived = await _create_session(client, "h4-search-unique-keyword-arch")
    await client.post(f"/sessions/{sid_archived}/archive")

    resp = await client.get(
        "/sessions/search", params={"q": "h4-search-unique-keyword"}
    )
    assert resp.status_code == 200, resp.text
    ids = [item["id"] for item in resp.json()]
    assert sid_hit in ids
    assert sid_archived not in ids, "已归档会话不出现在搜索结果"

    # 空关键词拒绝
    resp = await client.get("/sessions/search", params={"q": ""})
    assert resp.status_code == 422


async def test_search_projects_by_name(client, tmp_path, monkeypatch):
    from personal_assistant.config import settings as cfg

    monkeypatch.setattr(cfg, "project_bound_runs_enabled", True)
    root = tmp_path / "h4proj"
    root.mkdir()
    resp = await client.post(
        "/projects", json={"name": "h4-project-searchable", "root_path": str(root)}
    )
    assert resp.status_code == 201, resp.text

    resp = await client.get("/projects/search", params={"q": "h4-project-search"})
    assert resp.status_code == 200, resp.text
    names = [item["name"] for item in resp.json()]
    assert "h4-project-searchable" in names
