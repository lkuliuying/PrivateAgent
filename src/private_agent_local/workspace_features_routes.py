"""工作台增强接口复用本机认证、工作区及运行权限边界。"""
from fastapi import Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field


class QueueInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: str = Field(min_length=1, max_length=64)
    run_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=32000)


class HandoffInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_id: str = Field(min_length=1, max_length=64)
    session_id: int = Field(gt=0)


class SkillSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    enabled: bool


class SkillCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    scope: str = Field(pattern=r"^(user|project)$")
    content: str = Field(min_length=1, max_length=64000)


def install_workspace_features(app, local):
    from .integration_mcp import SelectionInput, SourceInput

    @app.get("/projects/{project_id}/handoffs")
    async def handoffs(project_id: int, runtime=Depends(local)):
        return {"items": runtime.store.get("project", project_id).get("worktree_handoffs", [])}

    @app.post("/projects/{project_id}/workspaces/{workspace_id}/handoff-preview")
    async def handoff_preview(project_id: int, workspace_id: int, runtime=Depends(local)):
        from .worktree_handoff import WorktreeHandoff
        service = WorktreeHandoff(runtime)
        return service.public(await service.preview(project_id, workspace_id))

    @app.post("/projects/{project_id}/workspaces/{workspace_id}/handoff")
    async def handoff_apply(project_id: int, workspace_id: int, data: HandoffInput, runtime=Depends(local)):
        from .worktree_handoff import WorktreeHandoff
        return await WorktreeHandoff(runtime).apply(project_id, workspace_id, data.version, data.request_id, data.session_id)

    @app.get("/projects/{project_id}/integrations")
    async def integrations(project_id: int, runtime=Depends(local)):
        return {"items": [{**source, "connection": runtime.integrations.connection_state(source["id"])} for source in runtime.integrations.sources(project_id)]}

    @app.post("/projects/{project_id}/integrations", status_code=201)
    async def integration_create(project_id: int, data: SourceInput, runtime=Depends(local)):
        return runtime.integrations.create(project_id, data)

    @app.post("/projects/{project_id}/integrations/{source_id}/connect")
    async def integration_connect(project_id: int, source_id: str, runtime=Depends(local)):
        return runtime.integrations.connect(project_id, source_id)

    @app.put("/projects/{project_id}/integrations/{source_id}")
    async def integration_select(project_id: int, source_id: str, data: SelectionInput, runtime=Depends(local)):
        return runtime.integrations.select(project_id, source_id, data)

    @app.delete("/projects/{project_id}/integrations/{source_id}")
    async def integration_remove(project_id: int, source_id: str, runtime=Depends(local)):
        await runtime.integrations.remove(project_id, source_id)
        return {"deleted": True}

    @app.get("/projects/{project_id}/skills")
    async def skills(project_id: int, runtime=Depends(local)):
        return {"items": runtime.skills.catalog(project_id)}

    @app.get("/projects/{project_id}/skills/{skill_id}")
    async def skill_content(project_id: int, skill_id: str, version: str, runtime=Depends(local)):
        return runtime.skills.content(project_id, skill_id, version)

    @app.put("/projects/{project_id}/skills/{skill_id}")
    async def skill_select(project_id: int, skill_id: str, data: SkillSelection, runtime=Depends(local)):
        runtime.skills.enable(project_id, skill_id, data.expected_version, data.enabled)
        return {"updated": True}

    @app.post("/projects/{project_id}/skills", status_code=201)
    async def skill_create(project_id: int, data: SkillCreate, runtime=Depends(local)):
        from . import files
        from .skills import manifest
        manifest(data.content)
        if runtime.secret_filter.contains_secret(data.content):
            raise ValueError("技能包含疑似敏感信息，未保存")
        root = runtime.skills.roots(project_id)[data.scope]
        root.mkdir(parents=True, exist_ok=True)
        directory = files.within(root, data.name, allow_missing=True)
        directory.mkdir(exist_ok=True)
        target = files.within(root, data.name + "/SKILL.md", allow_missing=True)
        with target.open("x", encoding="utf-8", newline="") as stream:
            stream.write(data.content)
        return {"created": True, "id": data.scope + ":" + data.name}

    @app.get("/sessions/{session_id}/review")
    async def task_review(session_id: int, scope: str = Query(default="last_turn", pattern="^(last_turn|task|workspace)$"), cursor: str | None = Query(default=None, max_length=1024), runtime=Depends(local)):
        from .task_review import inspect
        return await inspect(runtime, session_id, scope, cursor)

    @app.get("/sessions/{session_id}/review/diff")
    async def task_diff(session_id: int, path: str = Query(min_length=1, max_length=1024), staged: bool = False, offset: int = Query(default=0, ge=0), version: str | None = Query(default=None, pattern=r"^[a-f0-9]{64}$"), runtime=Depends(local)):
        from .task_review import diff
        return await diff(runtime, session_id, path, staged, offset, version)

    @app.get("/agent-runs/{run_id}/browser-evidence")
    async def browser_evidence(run_id: str, runtime=Depends(local)):
        return {"items": runtime.store.run_state(run_id).get("browser_evidence", [])}

    @app.get("/agent-runs/{run_id}/browser-evidence/{screenshot_id}")
    async def browser_screenshot(run_id: str, screenshot_id: str, runtime=Depends(local)):
        import re
        run = runtime.store.run_state(run_id)
        if not re.fullmatch(r"[a-f0-9]{32}", screenshot_id) or not any(item["screenshot_id"] == screenshot_id for item in run.get("browser_evidence", [])):
            raise ValueError("截图不属于当前运行")
        from . import files
        path = files.within(runtime.store.path.parent, "browser-artifacts/" + screenshot_id + ".png")
        if path.stat().st_size > 8 * 1024 * 1024 or path.stat().st_nlink != 1:
            raise ValueError("截图文件大小或身份异常")
        return Response(path.read_bytes(), media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/agent-runs/{run_id}/agents")
    async def child_agents(run_id: str, runtime=Depends(local)):
        return {"items": runtime.agents.public(run_id)}

    @app.post("/agent-runs/{run_id}/agents/{child_id}/cancel")
    async def cancel_child(run_id: str, child_id: str, runtime=Depends(local)):
        if not any(item["id"] == child_id for item in runtime.agents.children(run_id)):
            raise ValueError("子任务不属于当前运行")
        return await runtime.cancel(child_id)

    @app.get("/sessions/{session_id}/turn-queue")
    async def queue_state(session_id: int, runtime=Depends(local)):
        return {"item": runtime.turn_queue.get(session_id)}

    @app.post("/sessions/{session_id}/turn-queue")
    async def enqueue(session_id: int, data: QueueInput, runtime=Depends(local)):
        return runtime.turn_queue.enqueue(session_id, data.run_id, data.request_id, data.message)

    @app.delete("/sessions/{session_id}/turn-queue/{request_id}")
    async def dequeue(session_id: int, request_id: str, runtime=Depends(local)):
        return runtime.turn_queue.cancel(session_id, request_id)
