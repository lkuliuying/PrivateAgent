"""分页检索本机项目、任务和消息；长消息沿用内容仓库，不截断检索正文。"""
from __future__ import annotations

from datetime import datetime, timezone


def search(store, *, query="", project_id=None, status=None, archived=False, since=None, before=None, limit=40):
    needle = query.strip().casefold()
    since_at = datetime.fromisoformat(since.replace("Z", "+00:00")) if since else None
    if since_at and since_at.tzinfo is None:
        since_at = since_at.replace(tzinfo=timezone.utc)
    projects = {p["id"]: p for p in store.list("project")}
    sessions = {s["id"]: s for s in store.list("session")}
    rows = store.db.execute(
        "SELECT id, kind, data FROM (SELECT id, 'project' AS kind, data FROM projects "
        "UNION ALL SELECT id, 'session', data FROM sessions UNION ALL SELECT id, 'message', data FROM messages) "
        "WHERE id < ? ORDER BY id DESC LIMIT 2501", (before or 2**63 - 1,)
    ).fetchall()
    items, last, examined = [], None, 0
    for item_id, kind, packed in rows[:2500]:
        last, examined = item_id, examined + 1
        item = store._unpack(packed)
        session = item if kind == "session" else sessions.get(item.get("session_id"))
        project = item if kind == "project" else projects.get((session or {}).get("project_id"))
        if not project or project.get("status") != "active":
            continue
        if project_id is not None and project["id"] != project_id:
            continue
        if session and session.get("agent_parent_run_id") or archived and not session:
            continue
        if session and bool(session.get("archived_at")) != archived:
            continue
        run_status = "idle"
        if session and session.get("last_run_id"):
            row = store.db.execute("SELECT status FROM runs WHERE id=?", (session["last_run_id"],)).fetchone()
            run_status = row[0] if row else "idle"
        if status and (not session or run_status != status):
            continue
        updated = datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        if since_at and updated < since_at:
            continue
        content = str(item.get("content", "")) if kind == "message" else str(item.get("title", item.get("name", "")))
        if kind == "message" and (not needle or item.get("role") not in {"user", "assistant"}):
            continue
        at = content.casefold().find(needle)
        if at < 0:
            continue
        start = max(0, at - 65)
        items.append({"kind": kind, "project_id": project["id"], "project_name": project["name"],
                      "session_id": session["id"] if session else None,
                      "message_id": item_id if kind == "message" else None,
                      "title": session["title"] if session else project["name"],
                      "excerpt": ("…" if start else "") + content[start:start + 220],
                      "updated_at": item["updated_at"], "status": run_status,
                      "archived": bool((session or {}).get("archived_at"))})
        if len(items) >= limit:
            break
    more = bool(last and (examined < len(rows)))
    return {"items": items, "next_cursor": last if more else None, "examined": examined}
