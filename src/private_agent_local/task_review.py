"""任务审阅聚合持久补丁、实际验证结果和当前工作区差异。"""
from __future__ import annotations

from . import git_tools


def read_run(session, run):
    if run["session_id"] != session["id"]:
        raise ValueError("运行不属于当前任务")
    return run


async def inspect(owner, session_id, scope="last_turn", cursor=None):
    session = owner.store.get("session", session_id)
    root = owner.root(session["project_id"], session["workspace_id"])
    if scope == "workspace":
        run = {"permission_mode": "readonly", "completion_policy": {}}
        status = await git_tools.execute(run, root, "get_git_status", {"rel_path": ".", "cursor": cursor, "limit": 200})
        return {"scope": scope, "runs": [], "workspace": status}
    if scope == "last_turn":
        runs = [read_run(session, owner.store.run_state(session["last_run_id"]))] if session.get("last_run_id") else []
    elif scope == "task":
        rows = owner.store.db.execute("SELECT id FROM runs WHERE session_id=? ORDER BY rowid DESC LIMIT 201", (session_id,)).fetchall()
        if len(rows) > 200:
            raise ValueError("当前任务超过 200 轮，请按最近一轮审阅或拆分任务")
        runs = [owner.store.run_state(row[0]) for row in rows]
    else:
        raise ValueError("不支持的审阅范围")
    result = []
    for run in runs:
        result.append({"id": run["id"], "status": run["status"], "created_at": run["created_at"],
                       "workspace_id": run["workspace_id"], "outcome": run.get("run_outcome"),
                       "patch_count": len(owner.patches.list(run["id"]))})
    return {"scope": scope, "runs": result, "workspace": None}


async def diff(owner, session_id, relative, staged=False, offset=0, version=None):
    session = owner.store.get("session", session_id)
    root = owner.root(session["project_id"], session["workspace_id"])
    run = {"permission_mode": "readonly", "completion_policy": {}}
    return await git_tools.execute(run, root, "get_git_diff", {"rel_path": relative, "staged": staged, "offset": offset, "limit": 16000, "expected_version": version})
