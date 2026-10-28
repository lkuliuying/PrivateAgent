"""保留旧只读子任务的历史查询与取消清理，不再创建新子任务。"""
from __future__ import annotations

import asyncio

READ_TOOLS = frozenset({"tool_search", "read_code_file", "list_project_directory", "search_project_files", "get_git_status", "get_git_diff", "list_skills", "load_skill", "read_skill_reference"})
TOOLS = frozenset({"run_readonly_agents"})


class ReadonlyAgents:
    def __init__(self, owner):
        self.owner = owner

    def children(self, run_id):
        return [self.owner.store.run_state(session["last_run_id"]) for session in self.owner.store.list("session")
                if session.get("agent_parent_run_id") == run_id and session.get("last_run_id")]

    def public(self, run_id):
        self.owner.store.run_state(run_id)
        return [{"id": run["id"], "title": run.get("agent_title", "只读子任务"), "status": run["status"],
                 "output": (run.get("output") or "")[:12000], "error": run.get("error_message"),
                 "input_tokens": run.get("input_tokens", 0), "output_tokens": run.get("output_tokens", 0),
                 "cost_usd": run.get("cost_usd"), "budget": run.get("loop_budget", {})} for run in self.children(run_id)]

    async def cancel_children(self, run_id):
        children = [self.owner.tasks[run["id"]] for run in self.children(run_id) if run["id"] in self.owner.tasks]
        for task in children:
            task.cancel()
        if children:
            await asyncio.gather(*children, return_exceptions=True)
