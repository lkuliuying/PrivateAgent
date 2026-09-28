"""按操作日志及范围摘要区分任务、既有和无法精确归属的修改。"""
from __future__ import annotations

from . import git_workspace
from .completion import workspace_state


def changes(before, after):
    if before.get("digest") is None or after.get("digest") is None:
        return {"complete": False, "items": []}
    old, new = before["files"], after["files"]
    return {"complete": True, "items": [{"rel_path": path, "before_sha256": old.get(path), "after_sha256": new.get(path),
        "operation": "create" if path not in old else "delete" if path not in new else "update"}
        for path in sorted(old.keys() | new.keys()) if old.get(path) != new.get(path)]}


def review(owner, run):
    root = owner.root(run["project_id"], run["workspace_id"])
    history = [owner.store.run(identifier) for identifier in run.get("ancestor_run_ids", [])] + [run]
    if any(item.get("logical_task_id") != run.get("logical_task_id") or item["session_id"] != run["session_id"] for item in history):
        raise ValueError("变更记录不属于同一逻辑任务")
    task, latest, commands = [], {}, []
    for item in history:
        for patch in owner.patches.list(item["id"]):
            facts = owner.patches.facts(item["id"], patch["patch_set_id"], root)
            task.append({"run_id": item["id"], **patch, "facts": facts})
            for fact in facts:
                if fact["journal_status"] != "not_started":
                    latest[fact["rel_path"]] = fact
        commands.extend({"run_id": item["id"], "execution_id": e["id"], **e["candidate_changes"]}
                        for e in item["executions"] if e.get("candidate_changes"))
    current = workspace_state(root)
    baseline = history[0].get("review_baseline", {})
    delta = changes(baseline, current)
    external = [item for item in delta["items"] if not latest.get(item["rel_path"], {}).get("verified")]
    for path, fact in latest.items():
        if fact["observation"] in {"conflict", "unreadable"} and not any(item["rel_path"] == path for item in external):
            external.append({"rel_path": path, "operation": "unknown", "before_sha256": fact["sha256"], "after_sha256": current.get("files", {}).get(path)})
    return {"run_id": run["id"], "task_changes": task,
            "preexisting_changes": history[0].get("git_baseline", {}).get("dirty_entries", []),
            "external_or_unattributed": external, "command_candidates": commands,
            "current_git": git_workspace.inspect(root), "snapshot_complete": delta["complete"],
            "limitations": ["命令前后摘要仅提供候选变化，不能排除同时发生的外部写入", "扫描不包含凭据、链接、忽略的构建目录；超出 10000 文件或 64 MiB 时明确不完整", "二进制和范围外变化仅显示摘要；只有补丁日志提供可回读的全文差异"]}
