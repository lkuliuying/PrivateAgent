"""本机记忆管理与会话策略；所有操作沿用当前身份隔离。"""
from fastapi import Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .memory_store import MemoryConflict, MemoryInput, MemorySettings, sensitive


class SettingsInput(MemorySettings):
    expected_version: int = Field(ge=1)


class EditInput(MemoryInput):
    expected_version: int = Field(ge=1)


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    use_memories: bool
    generate_memories: bool
    expected_version: int = Field(ge=1)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=1)
    decision: str = Field(pattern="^(accept|reject|stale)$")


def install_memory_routes(app, local):
    @app.exception_handler(MemoryConflict)
    async def conflict(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    def scope(runtime, project_id):
        if project_id is not None:
            runtime.store.get("project", project_id)
        return project_id or 0

    def validate(runtime, data, project_id):
        if data.scope == "project" and project_id is None:
            raise ValueError("项目记忆必须选择所属项目")
        if sensitive(data.title + data.content, runtime.memories.secrets()):
            raise ValueError("记忆含疑似凭据，未保存")
        return scope(runtime, project_id)

    @app.get("/local-memories/settings")
    async def settings(runtime=Depends(local)):
        return runtime.memories.store.settings()

    @app.put("/local-memories/settings")
    async def save_settings(data: SettingsInput, runtime=Depends(local)):
        worker = runtime.memories
        await worker.stop()
        try:
            return worker.store.save_settings(MemorySettings.model_validate(data.model_dump(exclude={"expected_version"})), data.expected_version)
        finally:
            worker.start()

    @app.get("/local-memories/status")
    async def status(runtime=Depends(local)):
        return runtime.memories.status()

    @app.get("/local-memories/items")
    async def items(project_id: int | None = Query(default=None, ge=1), runtime=Depends(local)):
        return runtime.memories.store.list(scope(runtime, project_id))

    @app.get("/local-memories/search")
    async def search(query: str = Query(min_length=1, max_length=500), project_id: int | None = Query(default=None, ge=1), runtime=Depends(local)):
        return runtime.memories.search(scope(runtime, project_id), query, limit=20)

    @app.get("/local-memories/items/{memory_id}")
    async def item(memory_id: str, project_id: int | None = Query(default=None, ge=1), runtime=Depends(local)):
        return runtime.memories.store.get(scope(runtime, project_id), memory_id)

    @app.get("/local-memories/items/{memory_id}/revisions")
    async def revisions(memory_id: str, project_id: int | None = Query(default=None, ge=1), runtime=Depends(local)):
        return runtime.memories.store.revisions(scope(runtime, project_id), memory_id)

    @app.get("/local-memories/items/{memory_id}/sources/{source_id}")
    async def source(memory_id: str, source_id: str, project_id: int | None = Query(default=None, ge=1),
                     offset: int = Query(default=0, ge=0), limit: int = Query(default=2000, ge=1, le=6000), runtime=Depends(local)):
        return runtime.memories.read_source(scope(runtime, project_id), memory_id, source_id, offset, limit)

    @app.post("/local-memories/items/{memory_id}/review")
    async def review(memory_id: str, data: ReviewInput, project_id: int | None = Query(default=None, ge=1), runtime=Depends(local)):
        project = scope(runtime, project_id)
        runtime.memories.revision += 1
        return runtime.memories.store.review(project, memory_id, data.expected_version, data.decision)

    @app.post("/local-memories/items", status_code=201)
    async def create(data: MemoryInput, project_id: int | None = Query(default=None, ge=1), runtime=Depends(local)):
        project = validate(runtime, data, project_id)
        return runtime.memories.save(project, data)

    @app.put("/local-memories/items/{memory_id}")
    async def edit(memory_id: str, data: EditInput, project_id: int | None = Query(default=None, ge=1), runtime=Depends(local)):
        project = validate(runtime, data, project_id)
        return runtime.memories.save(project, MemoryInput.model_validate(data.model_dump(exclude={"expected_version"})),
                                         identifier=memory_id, expected_version=data.expected_version)

    @app.delete("/local-memories/items/{memory_id}", status_code=204)
    async def forget(memory_id: str, expected_version: int = Query(ge=1), project_id: int | None = Query(default=None, ge=1), runtime=Depends(local)):
        project = scope(runtime, project_id)
        runtime.memories.revision += 1
        runtime.memories.store.forget(project, memory_id, expected_version)
        return Response(status_code=204)

    @app.get("/sessions/{session_id}/memory-settings")
    async def session_settings(session_id: int, runtime=Depends(local)):
        session = runtime.store.get("session", session_id)
        last = runtime.store.run_state(session["last_run_id"]) if session.get("last_run_id") else {}
        recall = last.get("memory_context")
        if recall:
            # 仅在读取时补齐当前标题；运行持久记录不增加遗忘正文副本。
            recall = {**recall, "run_id": last.get("id"), "entries": [dict(entry) for entry in recall.get("entries", [])]}
            for entry in recall["entries"]:
                try:
                    record = runtime.memories.store.get(session["project_id"], entry["memory_id"])
                    entry.update(title=record["title"], project_id=record["project_id"])
                    if "updated_at" not in entry and entry.get("version") == record["version"]:
                        entry["updated_at"] = record["updated_at"]
                except KeyError:
                    entry.update(title="记忆已遗忘或不可用", available=False)
        return {**runtime.memories.store.session(session_id),
                "effective_use": runtime.memories.allowed(session_id, "use_memories"),
                "effective_generate": runtime.memories.allowed(session_id, "generate_memories"),
                "last_recall": recall}

    @app.put("/sessions/{session_id}/memory-settings")
    async def save_session(session_id: int, data: SessionInput, runtime=Depends(local)):
        runtime.store.get("session", session_id)
        runtime.memories.revision += 1
        runtime.memories.store.save_session(session_id, data.use_memories, data.generate_memories, data.expected_version)
        return await session_settings(session_id, runtime)
