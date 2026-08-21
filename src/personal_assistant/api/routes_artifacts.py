"""v0.6.0 RunArtifact API 路由（C0 契约 §4.2/§7.2/§8）。

``POST /agent-runs/{run_id}/artifacts`` 只冻结产物引用（kind/title/
rel_path/content_sha256/metadata），写入后发 ``artifact.created`` durable
事件。flag ``PA_AGENT_RUN_PLAN_ENABLED`` 关闭时整体不可见。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from ..core.db import get_session
from ..core.run_artifact import ArtifactValidationError, RunArtifactService

router = APIRouter(prefix="/agent-runs", tags=["run-artifacts"])


class ArtifactCreateRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=512)
    rel_path: str | None = Field(default=None, max_length=2048)
    step_id: str | None = Field(default=None, max_length=36)
    content_sha256: str | None = Field(default=None, max_length=64)
    metadata: dict | None = None


def _require_artifacts_enabled() -> None:
    if not cfg.agent_run_plan_enabled:
        raise HTTPException(status_code=404, detail="Not found")


def _artifact_error(status: int, error_code: str, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status,
        content={"error_code": error_code, "detail": detail},
    )


@router.post(
    "/{run_id}/artifacts",
    response_model=dict,
    status_code=201,
    dependencies=[Depends(_require_artifacts_enabled)],
)
async def create_run_artifact(
    run_id: str,
    request: ArtifactCreateRequest,
    db: AsyncSession = Depends(get_session),
):
    """创建 run 产物引用并写 artifact.created 事件。"""
    from ..agents.repository import AgentRunRepository

    run = await AgentRunRepository(db).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    svc = RunArtifactService(db)
    try:
        return await svc.create_artifact(
            run_id=run_id,
            kind=request.kind,
            title=request.title,
            rel_path=request.rel_path,
            step_id=request.step_id,
            content_sha256=request.content_sha256,
            metadata=request.metadata,
        )
    except ArtifactValidationError as exc:
        return _artifact_error(422, "artifact_invalid", str(exc))


@router.get(
    "/{run_id}/artifacts",
    response_model=list[dict],
    dependencies=[Depends(_require_artifacts_enabled)],
)
async def list_run_artifacts(
    run_id: str,
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
):
    """run 产物引用列表（重连纠偏快照的组成部分；E3 支持 limit/offset 分页）。"""
    from ..agents.repository import AgentRunRepository

    run = await AgentRunRepository(db).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return await RunArtifactService(db).list_artifacts(
        run_id, limit=limit, offset=offset
    )
