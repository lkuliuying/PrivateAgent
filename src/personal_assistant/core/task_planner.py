"""第四阶段 M5：可编辑任务计划生成。

计划生成保持保守：先从本地项目命令配置、长期记忆和可用工具生成一个
可审阅草稿；用户批准后才进入既有 AgentTaskService 执行链。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .memory import MemoryService
from .repo_patch_sets import ProjectCommandProfileRepository
from .repo_projects import ProjectRepository
from .tools import default_registry


class TaskPlannerService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def generate(
        self,
        *,
        title: str,
        goal: str,
        project_id: int | None = None,
    ) -> dict:
        """生成可编辑计划 JSON。

        返回结构与 agent_tasks.plan_json 兼容：
        {"goal": str, "steps": [...], "context": {...}}
        """
        context: dict = {
            "memories": [],
            "project": None,
            "commands": [],
            "tools": sorted(default_registry._tools.keys()),  # noqa: SLF001
        }

        if project_id is not None:
            project = await ProjectRepository(self.db).get(project_id)
            if project is not None:
                context["project"] = {
                    "id": project.id,
                    "name": project.name,
                    "root_path": project.root_path,
                    "language": project.language,
                    "framework": project.framework,
                }
                commands = await ProjectCommandProfileRepository(
                    self.db
                ).list_by_project(project_id, enabled=True)
                context["commands"] = [
                    {
                        "id": c.id,
                        "name": c.name,
                        "kind": c.kind,
                        "command_json": c.command_json,
                    }
                    for c in commands
                ]

        memories = await MemoryService(self.db).retrieve_for_context(goal, top_k=5)
        context["memories"] = MemoryService.format_sources(memories)

        steps = self._steps_from_context(goal, project_id, context)
        return {"goal": goal, "title": title, "steps": steps, "context": context}

    @staticmethod
    def _steps_from_context(
        goal: str, project_id: int | None, context: dict
    ) -> list[dict]:
        base = {"project_id": project_id} if project_id else {}
        steps: list[dict] = []

        if project_id:
            steps.append(
                {
                    "title": "检查项目当前状态",
                    "tool_name": "get_git_status",
                    "input_json": base,
                    "risk": "safe",
                    "expected_output": "确认工作区状态和潜在未提交改动。",
                }
            )
            steps.append(
                {
                    "title": "查看当前 diff",
                    "tool_name": "get_git_diff",
                    "input_json": base,
                    "risk": "safe",
                    "expected_output": "了解现有改动，避免覆盖用户工作。",
                }
            )

        command = TaskPlannerService._preferred_command(context.get("commands") or [])
        if command:
            steps.append(
                {
                    "title": f"运行项目命令：{command['name']}",
                    "tool_name": "run_whitelisted_command",
                    "input_json": {
                        **base,
                        "command": command["command"],
                        "timeout": command.get("timeout_seconds", 120),
                    },
                    "risk": "confirm",
                    "expected_output": "得到验证输出；失败时作为诊断证据。",
                }
            )
        elif project_id:
            steps.append(
                {
                    "title": "运行默认测试命令",
                    "tool_name": "run_whitelisted_command",
                    "input_json": {**base, "command": "pytest -q"},
                    "risk": "confirm",
                    "expected_output": "用默认白名单命令验证项目。",
                }
            )

        if "修" in goal or "改" in goal or "fix" in goal.lower():
            steps.append(
                {
                    "title": "生成需要用户审阅的修改建议",
                    "tool_name": "propose_patch",
                    "input_json": {
                        **base,
                        "rel_path": "",
                        "instruction": goal,
                    },
                    "risk": "safe",
                    "expected_output": "产出补丁预览，后续写入仍需单独审批。",
                }
            )

        if project_id:
            steps.append(
                {
                    "title": "收集最终 diff",
                    "tool_name": "get_git_diff",
                    "input_json": base,
                    "risk": "safe",
                    "expected_output": "汇总执行后的项目变化。",
                }
            )

        if not steps:
            steps.append(
                {
                    "title": "记录任务分析",
                    "tool_name": "list_documents",
                    "input_json": {},
                    "risk": "safe",
                    "expected_output": "收集可用资料，形成后续人工可编辑步骤。",
                }
            )

        return steps

    @staticmethod
    def _preferred_command(commands: list[dict]) -> dict | None:
        priority = ["test", "typecheck", "lint", "build", "format", "custom"]
        for kind in priority:
            for c in commands:
                if c.get("kind") != kind:
                    continue
                cmd_json = c.get("command_json") or {}
                command = cmd_json.get("command") or cmd_json.get("args")
                if command:
                    return {
                        "name": c.get("name") or kind,
                        "command": command,
                        "timeout_seconds": c.get("timeout_seconds", 120),
                    }
        return None
