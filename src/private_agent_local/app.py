"""Loopback-only desktop API. No cloud filesystem endpoints are proxied here."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from . import files, migration
from .cloud import Cloud, CloudError
from .local_models import LocalModels
from .runtime import TERMINAL, Runtime, snapshot
from .store import Store, now

ORIGINS = ["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"]
CAPABILITIES = {
    "chat_execution_mode": "agent_runtime", "legacy_tool_planner_enabled": False,
    "agent_read_only_tools_enabled": True, "rag_chat_runtime_enabled": False,
    "patch_workflow_enabled": True, "command_workflow_enabled": True,
    "http_workflow_enabled": False, "sql_readonly_workflow_enabled": False,
    "agent_runs_api_enabled": True, "coding_agent_ui_enabled": True,
    "project_bound_runs_enabled": True, "coding_workspace_auto_approve": True,
    "coding_full_access_supported": True, "coding_full_access_audit": True,
    "coding_full_access_revoke": True, "coding_context_budget_enabled": True,
    "coding_execution_detail_enabled": True, "coding_worktree_enabled": False,
    "coding_diagnostic_commands_enabled": True, "product_timezone": "Asia/Shanghai",
}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectInput(Input):
    name: str = Field(min_length=1, max_length=255)
    root_path: str = Field(min_length=1, max_length=4096)


class Binding(Input):
    project_id: int = Field(gt=0)
    workspace_id: int = Field(gt=0)


class ProjectContextInput(Input):
    project_id: int | None = Field(default=None, gt=0)


class SessionInput(Binding):
    title: str = Field(default="新任务", min_length=1, max_length=255)
    kind: Literal["coding"] = "coding"


class TitleInput(Input):
    title: str = Field(min_length=1, max_length=255)


class AttachmentInput(Input):
    source_path: str = Field(min_length=1, max_length=4096)


class RunInput(Binding):
    session_id: int = Field(gt=0)
    message: str = Field(min_length=1, max_length=32000)
    permission_mode: Literal["readonly", "confirm", "workspace", "full_access"] = "confirm"
    model_profile_id: str | None = Field(default=None, max_length=128)
    reasoning_effort: str | None = Field(default=None, max_length=32)
    client_request_id: str | None = Field(default=None, max_length=100)


class HistorySource(Input):
    path: str = Field(min_length=1, max_length=4096)


class HistoryImport(HistorySource):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mappings: dict[str, str] = Field(default_factory=dict, max_length=1000)


class DesktopState:
    def __init__(self, data_dir: Path, cloud: Cloud | LocalModels):
        self.data_dir, self.cloud = data_dir, cloud
        self.runtime: Runtime | None = None
        self.lock = asyncio.Lock()
        self.verified_at = 0.0

    async def bind(self, token: str, *, existing_only=False) -> Runtime:
        async with self.lock:
            if existing_only and (not self.runtime or not hmac.compare_digest(self.runtime.token, token)):
                raise HTTPException(401, "本机账号会话已切换，请重新登录")
            if self.runtime and hmac.compare_digest(self.runtime.token, token) and time.monotonic() - self.verified_at < 60:
                return self.runtime
            identity = await self.cloud.identity(token)
            if self.runtime and hmac.compare_digest(self.runtime.token, token):
                self.verified_at = time.monotonic()
                return self.runtime
            account = hashlib.sha256(f"{self.cloud.origin}\0{identity['id']}".encode()).hexdigest()
            if self.runtime:
                previous, self.runtime = self.runtime, None
                await previous.close()
            self.runtime = Runtime(Store(self.data_dir / account / "projects.sqlite3"), self.cloud, token)
            self.runtime.owner_id = identity["id"]
            self.verified_at = time.monotonic()
            return self.runtime

    async def clear(self):
        async with self.lock:
            if self.runtime:
                previous, self.runtime = self.runtime, None
                await previous.close()
            self.verified_at = 0


def create_app(*, data_dir: Path, cloud: Cloud | LocalModels, nonce: str, port: int = 0, shutdown=None) -> FastAPI:
    if len(nonce) < 32:
        raise ValueError("本机启动凭证过短")
    state = DesktopState(data_dir, cloud)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await state.clear()
        await cloud.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.desktop = state

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        expected_host = f"127.0.0.1:{port}" if port else "127.0.0.1"
        if request.headers.get("host") != expected_host or request.headers.get("origin", ORIGINS[0]) not in ORIGINS:
            return JSONResponse({"detail": "不允许的本机请求来源"}, status_code=403)
        if not hmac.compare_digest(request.headers.get("x-privateagent-local", ""), nonce):
            return JSONResponse({"detail": "本机连接凭证无效"}, status_code=403)
        # Bound all mutation bodies before Pydantic parses them.
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 2 * 1024 * 1024:
                return JSONResponse({"detail": "请求超过大小限制"}, status_code=413)
            body.extend(chunk)
        request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-PrivateAgent-Local"])

    @app.exception_handler(KeyError)
    async def missing(request, error):
        return JSONResponse({"detail": "当前账号的本机记录不存在"}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(OSError)
    async def filesystem_error(request, error):
        return JSONResponse({"detail": "本机文件不可访问，请检查目录及权限"}, status_code=422)

    @app.exception_handler(CloudError)
    async def cloud_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    def bearer(request: Request) -> str:
        authorization = request.headers.get("authorization", "")
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        if not token or len(token) > 16384:
            raise HTTPException(401, "请先登录服务器账号")
        return token

    async def local(request: Request) -> Runtime:
        token = bearer(request)
        if not state.runtime or not hmac.compare_digest(state.runtime.token, token):
            raise HTTPException(401, "本机执行器尚未绑定当前账号，请重新登录")
        return await state.bind(token, existing_only=True)

    @app.get("/health")
    async def health():
        return {"status": "ok", "mode": "desktop-local", "protocol": 1}

    @app.get("/")
    async def info():
        return {"mode": "desktop-local", "version": "unified", "optional_services": not isinstance(cloud, LocalModels)}

    @app.post("/auth/local")
    async def enter_local():
        if not isinstance(cloud, LocalModels):
            raise HTTPException(404, "此连接需要服务器账号登录")
        await state.bind(cloud.token)
        return {"access_token": cloud.token, "token_type": "bearer",
                "expires_at": None, "user": cloud.user}

    @app.get("/auth/me")
    async def local_user(request: Request):
        if not isinstance(cloud, LocalModels):
            raise HTTPException(404)
        return await cloud.identity(bearer(request))

    @app.post("/auth/logout")
    async def local_logout():
        if not isinstance(cloud, LocalModels):
            raise HTTPException(404)
        await state.clear()
        cloud.revoke_identity()
        return {"logged_out": True}

    @app.get("/agent-model-profiles")
    async def local_profiles(request: Request, runtime: Runtime = Depends(local)):
        if not getattr(cloud, "local_inference", False):
            raise HTTPException(404)
        return await cloud.profiles(bearer(request))

    @app.post("/identity")
    async def identity(request: Request):
        await state.bind(bearer(request))
        return {"ready": True}

    @app.post("/identity/clear")
    async def clear():
        await state.clear()
        return {"cleared": True}

    @app.post("/internal/shutdown")
    async def stop():
        await state.clear()
        if shutdown:
            shutdown()
        return {"stopping": True}

    @app.get("/capabilities")
    async def capabilities():
        return CAPABILITIES

    @app.get("/local-history/export")
    async def export_local_history(runtime: Runtime = Depends(local)):
        archive = migration.archive_sqlite(runtime.store.path, authority=cloud.origin, owner_id=runtime.owner_id)
        content = migration.encode_archive(archive)
        return Response(content, media_type="application/json", headers={"Content-Disposition": 'attachment; filename="privateagent-history.json"'})

    @app.post("/local-history/preview")
    async def preview_local_history(data: HistorySource, runtime: Runtime = Depends(local)):
        return migration.preview_history(data.path, authority=cloud.origin, owner_id=runtime.owner_id)

    @app.post("/local-history/import")
    async def import_local_history(data: HistoryImport, runtime: Runtime = Depends(local)):
        return migration.apply_history(runtime.store, data.path, data.sha256, data.mappings, authority=cloud.origin, owner_id=runtime.owner_id)

    @app.get("/local-history/imports")
    async def imported_history(runtime: Runtime = Depends(local)):
        return [json.loads(row[0]) for row in runtime.store.db.execute("SELECT data FROM history_imports ORDER BY rowid DESC")]

    @app.post("/local-history/imports/{import_id}/rollback")
    async def rollback_local_history(import_id: str, runtime: Runtime = Depends(local)):
        return migration.rollback_history(runtime.store, import_id)

    @app.get("/local-history/imports/{import_id}/records")
    async def imported_records(import_id: str, kind: str, offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100), runtime: Runtime = Depends(local)):
        if kind not in migration.FIELDS:
            raise ValueError("未知历史类型")
        row = runtime.store.db.execute("SELECT archive FROM history_imports WHERE id=?", (import_id,)).fetchone()
        if not row:
            raise KeyError("迁移记录不存在")
        records = runtime.store._unpack(row[0])["records"][kind]
        return {"total": len(records), "items": records[offset:offset + limit], "readonly": True}

    @app.get("/local-history/imports/{import_id}/export")
    async def export_imported_history(import_id: str, runtime: Runtime = Depends(local)):
        row = runtime.store.db.execute("SELECT archive FROM history_imports WHERE id=?", (import_id,)).fetchone()
        if not row:
            raise KeyError("迁移记录不存在")
        return Response(migration.encode_archive(runtime.store._unpack(row[0])), media_type="application/json")

    def workspace(runtime, project):
        candidates = [w for w in runtime.store.list("workspace") if w["project_id"] == project["id"]]
        return candidates[0] if candidates else runtime.store.create("workspace", {
            "project_id": project["id"], "kind": "root", "root_path": project["root_path"], "branch_name": None,
            "head_sha": None, "status": "active", "last_used_at": now()})

    def project_create(runtime, name, root, authorized):
        root = str(files.authorize_root(str(root)))
        existing = next((p for p in runtime.store.list("project") if p["root_path"] == root), None)
        if existing:
            return existing
        project = runtime.store.create("project", {"name": name, "root_path": root, "status": "active", "authorized": authorized})
        workspace(runtime, project)
        return project

    @app.get("/projects")
    async def projects(runtime: Runtime = Depends(local)):
        return runtime.store.list("project")

    @app.post("/projects", status_code=201)
    async def create_project(data: ProjectInput, runtime: Runtime = Depends(local)):
        return project_create(runtime, data.name, data.root_path, True)

    def home_candidate(runtime, create=False):
        root = str(Path.home().resolve())
        project = next((p for p in runtime.store.list("project") if p["root_path"] == root), None)
        created = project is None and create
        if created:
            project = project_create(runtime, "当前用户目录", root, False)
        return {"available": True, "exists": project is not None, "created": created,
                "authorized": bool(project and project["authorized"]), "project_id": project["id"] if project else None,
                "workspace_id": workspace(runtime, project)["id"] if project else None, "name": project["name"] if project else None}

    @app.get("/projects/user-home-candidate")
    async def home(runtime: Runtime = Depends(local)):
        return home_candidate(runtime)

    @app.post("/projects/user-home")
    async def create_home(runtime: Runtime = Depends(local)):
        return home_candidate(runtime, True)

    @app.post("/projects/{project_id}/authorize-scope")
    async def authorize(project_id: int, runtime: Runtime = Depends(local)):
        return runtime.store.update("project", project_id, authorized=True)

    @app.get("/projects/{project_id}/workspaces")
    async def workspaces(project_id: int, runtime: Runtime = Depends(local)):
        runtime.store.get("project", project_id)
        return [w for w in runtime.store.list("workspace") if w["project_id"] == project_id]

    @app.post("/projects/{project_id}/workspaces/root/ensure", status_code=201)
    async def ensure_workspace(project_id: int, runtime: Runtime = Depends(local)):
        return workspace(runtime, runtime.store.get("project", project_id))

    @app.get("/projects/{project_id}/workspaces/{workspace_id}")
    async def get_workspace(project_id: int, workspace_id: int, runtime: Runtime = Depends(local)):
        runtime.root(project_id, workspace_id)
        return runtime.store.get("workspace", workspace_id)

    @app.get("/projects/{project_id}/search")
    async def search(project_id: int, query: str = Query(min_length=1, max_length=200),
                     kind: Literal["name", "content"] = "name", runtime: Runtime = Depends(local)):
        project = runtime.store.get("project", project_id)
        root = runtime.root(project_id, workspace(runtime, project)["id"])
        return files.search_files(root, query, content=kind == "content")

    @app.post("/projects/{project_id}/workspaces/{workspace_id}/attachments")
    async def attachment(project_id: int, workspace_id: int, data: AttachmentInput, runtime: Runtime = Depends(local)):
        root = runtime.root(project_id, workspace_id)
        source = Path(data.source_path)
        if not source.is_absolute() or source.is_symlink() or files.secret_path(source) or source.resolve() != source:
            raise ValueError("只能附加直接选择的普通本机文本文件，不能附加凭据或链接")
        text = files.read_text(source)
        # The explicit file picker action authorizes copying this one file, never replacing existing files.
        relative = f"attachment-{uuid.uuid4().hex[:12]}-{source.name}"
        preview = files.patch_preview(root, relative, text)
        files.apply_patch(root, preview, text)
        return {"rel_path": relative, "name": source.name, "language": source.suffix.lstrip(".") or None}

    @app.post("/projects/context")
    async def activate_project(data: ProjectContextInput, runtime: Runtime = Depends(local)):
        await runtime.activate_project(data.project_id)
        return {"project_id": data.project_id}

    def session_list(runtime, project_id=None, kind=None, q="", limit=1000):
        values = [s for s in runtime.store.list("session") if not s.get("archived_at")
                  and (project_id is None or s["project_id"] == project_id)
                  and (kind is None or s["kind"] == kind) and q.casefold() in s["title"].casefold()]
        return sorted(values, key=lambda s: (s.get("pinned_at") or "", s["updated_at"]), reverse=True)[:limit]

    @app.get("/sessions")
    async def sessions(project_id: int | None = None, kind: str | None = None, runtime: Runtime = Depends(local)):
        return session_list(runtime, project_id, kind)

    @app.get("/sessions/recent")
    @app.get("/sessions/search")
    async def recent(kind: str | None = None, q: str = Query(default="", max_length=200),
                     limit: int = Query(default=30, ge=1, le=100), runtime: Runtime = Depends(local)):
        return session_list(runtime, kind=kind, q=q, limit=limit)

    @app.post("/sessions", status_code=201)
    async def create_session(data: SessionInput, runtime: Runtime = Depends(local)):
        runtime.root(data.project_id, data.workspace_id)
        return runtime.store.create("session", {**data.model_dump(), "last_run_id": None, "pinned_at": None, "archived_at": None})

    @app.get("/sessions/{session_id}/messages")
    async def messages(session_id: int, runtime: Runtime = Depends(local)):
        runtime.store.get("session", session_id)
        return list(reversed(runtime.store.list("message", session_id=session_id)))

    @app.get("/sessions/{session_id}/latest-agent-run")
    async def latest_run(session_id: int, runtime: Runtime = Depends(local)):
        return {"run_id": runtime.store.get("session", session_id)["last_run_id"]}

    @app.get("/sessions/{session_id}/context-budget")
    async def get_context_budget(session_id: int, model_profile_id: str | None = Query(default=None, max_length=128),
                                 runtime: Runtime = Depends(local)):
        return await runtime.context_budget(session_id, model_profile_id)

    def grant_state(session, grant):
        return {"active": grant is not None, "grant_id": grant["id"] if grant else None,
                "session_id": session["id"], "project_id": session["project_id"],
                "granted_at": grant["granted_at"] if grant else None, "expires_at": grant["expires_at"] if grant else None}

    @app.get("/sessions/{session_id}/full-access-grant")
    async def full_access_state(session_id: int, runtime: Runtime = Depends(local)):
        session = runtime.store.get("session", session_id)
        grant = runtime.store.active_grant(session_id)
        if grant and grant["project_id"] != session["project_id"]:
            runtime.store.revoke_grant(grant["id"], "project_switch")
            grant = None
        return grant_state(session, grant)

    @app.post("/sessions/{session_id}/full-access-grant", status_code=201)
    async def grant_full_access(session_id: int, runtime: Runtime = Depends(local)):
        session = runtime.store.get("session", session_id)
        if runtime.project_context_set and runtime.active_project_id != session["project_id"]:
            raise ValueError("项目已切换，请重新选择当前会话后授权")
        runtime.root(session["project_id"], session["workspace_id"])
        grant = runtime.store.active_grant(session_id)
        if grant and grant["project_id"] != session["project_id"]:
            await runtime.revoke_grant(grant["id"])
            grant = None
        if grant is None:
            expires = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
            grant = runtime.store.grant(session_id, session["project_id"], expires)
        return grant_state(session, grant)

    @app.delete("/full-access-grants/{grant_id}")
    async def revoke_full_access(grant_id: str, runtime: Runtime = Depends(local)):
        return {"revoked": await runtime.revoke_grant(grant_id)}

    @app.patch("/sessions/{session_id}/title")
    async def rename_session(session_id: int, data: TitleInput, runtime: Runtime = Depends(local)):
        return runtime.store.update("session", session_id, title=data.title)

    @app.post("/sessions/{session_id}/{action}")
    async def session_action(session_id: int, action: Literal["archive", "unarchive", "pin", "unpin"], runtime: Runtime = Depends(local)):
        key = "archived_at" if action in {"archive", "unarchive"} else "pinned_at"
        return runtime.store.update("session", session_id, **{key: now() if action in {"archive", "pin"} else None})

    @app.post("/agent-runs", status_code=201)
    async def create_run(data: RunInput, runtime: Runtime = Depends(local)):
        return runtime.create(data.model_dump())

    @app.get("/agent-runs/{run_id}")
    async def get_run(run_id: str, runtime: Runtime = Depends(local)):
        return snapshot(runtime.store.run_state(run_id))

    @app.post("/agent-runs/{run_id}/cancel")
    async def cancel(run_id: str, runtime: Runtime = Depends(local)):
        return await runtime.cancel(run_id)

    @app.get("/agent-runs/{run_id}/events")
    async def events(run_id: str, after_sequence: int = Query(default=0, ge=0),
                     limit: int = Query(default=1000, ge=1, le=1000), runtime: Runtime = Depends(local)):
        run = runtime.store.run_state(run_id)
        return {"items": runtime.store.events(run_id, after_sequence, limit), "last_sequence": run["last_event_sequence"]}

    @app.get("/agent-runs/{run_id}/events/stream")
    async def stream(run_id: str, after_sequence: int = Query(default=0, ge=0), runtime: Runtime = Depends(local)):
        runtime.store.run(run_id)

        async def iterate():
            cursor = after_sequence
            while state.runtime is runtime:
                run = runtime.store.run_state(run_id)
                for event in runtime.store.events(run_id, cursor):
                    if event["sequence"] > cursor:
                        yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                        cursor = event["sequence"]
                if run["status"] in TERMINAL:
                    yield "data: " + json.dumps({"sequence": cursor + 1, "type": "run.terminal", "payload": {"status": run["status"]}}) + "\n\n"
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(iterate(), media_type="text/event-stream")

    @app.get("/agent-runs/{run_id}/approvals")
    async def approvals(run_id: str, runtime: Runtime = Depends(local)):
        return [{k: v for k, v in a.items() if k != "preview"} for a in runtime.store.run(run_id)["approvals"]]

    @app.get("/agent-runs/{run_id}/approvals/{approval_id}/preview")
    async def preview(run_id: str, approval_id: str, runtime: Runtime = Depends(local)):
        for approval in runtime.store.run(run_id)["approvals"]:
            if approval["id"] == approval_id:
                return approval["preview"]
        raise KeyError(approval_id)

    @app.post("/agent-runs/{run_id}/approvals/{approval_id}/{decision}")
    async def decide(run_id: str, approval_id: str, decision: Literal["approve", "reject"], runtime: Runtime = Depends(local)):
        runtime.decide(run_id, approval_id, decision == "approve")
        return {"accepted": True}

    @app.get("/agent-runs/{run_id}/executions")
    async def executions(run_id: str, runtime: Runtime = Depends(local)):
        return runtime.store.run(run_id)["executions"]

    @app.get("/agent-runs/{run_id}/executions/{execution_id}/output")
    async def output(run_id: str, execution_id: str, after_seq: int = Query(default=-1, ge=-1), runtime: Runtime = Depends(local)):
        execution = next((e for e in runtime.store.run(run_id)["executions"] if e["id"] == execution_id), None)
        if execution is None:
            raise KeyError(execution_id)
        lines = []
        for key in ("stdout", "stderr"):
            for line in (execution.get("output") or {}).get(key, "").splitlines():
                lines.append({"seq": len(lines), "kind": key, "text": line})
        return {"lines": [line for line in lines if line["seq"] > after_seq], "last_seq": len(lines) - 1,
                "finished": execution["status"] != "running"}

    return app
