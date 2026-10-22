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
        patches = owner.patches.list(run["id"])
        result.append({"id": run["id"], "status": run["status"], "created_at": run["created_at"],
                       "workspace_id": run["workspace_id"], "outcome": run.get("run_outcome"),
                       "patch_count": len(patches), **_chain(owner, run, patches)})
    return {"scope": scope, "runs": result, "workspace": None}


def _chain(owner, run, patches):
    """按运行轮次展示续跑链与恢复来源；只读已提交事实，不改写旧结论。"""
    handoff = run.get("model_handoff") or {}
    return {"resumed_from_run_id": run.get("resumed_from_run_id"),
            "logical_task_id": run.get("logical_task_id"),
            "ancestor_count": len(run.get("ancestor_run_ids") or []),
            "error_code": run.get("error_code"),
            "error_message": run.get("error_message"),
            "recovery_class": owner.recovery.classification(run),
            "resolution_count": len(owner.recovery.resolutions(run)),
            "model_switch": bool(handoff),
            "model_switch_from": handoff.get("from_model_name"),
            "model_switch_to": handoff.get("to_model_name"),
            "patch_status": sorted({patch["status"] for patch in patches}),
            "rollback_available": any(patch["kind"] != "rollback" and patch["status"] in
                                      {"applied", "partially_applied", "failed", "interrupted"} for patch in patches)}


async def diff(owner, session_id, relative, staged=False, offset=0, version=None):
    session = owner.store.get("session", session_id)
    root = owner.root(session["project_id"], session["workspace_id"])
    run = {"permission_mode": "readonly", "completion_policy": {}}
    return await git_tools.execute(run, root, "get_git_diff", {"rel_path": relative, "staged": staged, "offset": offset, "limit": 16000, "expected_version": version})
