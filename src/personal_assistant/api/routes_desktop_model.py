"""Authenticated inference for desktop-owned projects; never executes file tools."""
from __future__ import annotations

import asyncio
from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.contracts import ModelRequest, ModelResponse
from ..agents.runtime import CancellationToken
from ..core.db import get_session
from .auth_dependencies import current_principal

router = APIRouter(prefix="/desktop", tags=["desktop-model"])
MAX_REQUEST_BYTES = 2 * 1024 * 1024
_inference_slots = asyncio.Semaphore(4)


class DesktopModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_profile_id: str | None = Field(default=None, max_length=128)
    request: ModelRequest


async def parse_inference_request(request: Request) -> DesktopModelRequest:
    """Bound the body before JSON parsing; do not echo model input in errors."""
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_REQUEST_BYTES:
            raise HTTPException(413, "模型上下文超过 2 MB，请缩小任务范围")
        body.extend(chunk)
    try:
        value = DesktopModelRequest.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "本机模型请求格式无效") from None
    if len(value.request.messages) > 100 or len(value.request.tools) > 32:
        raise HTTPException(422, "模型消息或工具数量超出范围")
    return value


async def resolve_gateway(db: AsyncSession, payload: DesktopModelRequest):
    # Reuse the existing account-scoped provider resolution. This transient ORM
    # value is never added to a session, persisted, or scheduled as a server run.
    from ..core.model_profiles import ModelProfileService, ModelProfileUnsupported
    from ..core.models import AgentRun as AgentRunRecord
    from .routes_agent_runs import _model_gateway_for_run

    profile_id = payload.model_profile_id
    if profile_id is None:
        profiles = await ModelProfileService(db).list()
        profile_id = next((p.id for p in profiles if p.enabled and p.is_default), None)
    try:
        if profile_id and payload.request.reasoning_effort:
            profile = await ModelProfileService(db).get(profile_id)
            if profile is None or payload.request.reasoning_effort not in (profile.reasoning_efforts or []):
                raise ModelProfileUnsupported("模型不支持所选推理强度")
        return await _model_gateway_for_run(db, AgentRunRecord(model_profile_id=profile_id))
    except ModelProfileUnsupported:
        raise HTTPException(422, "所选服务器模型不可用，请检查模型配置") from None


@router.post("/model/complete", response_model=ModelResponse)
async def complete_desktop_model(
    request: Request, response: Response, db: AsyncSession = Depends(get_session)
) -> ModelResponse:
    current_principal(request)
    payload = await parse_inference_request(request)
    gateway = await resolve_gateway(db, payload)
    try:
        async with asyncio.timeout(1):
            await _inference_slots.acquire()
    except TimeoutError:
        raise HTTPException(503, "模型服务繁忙，请稍后重试") from None
    cancellation = CancellationToken()
    inference = asyncio.create_task(gateway.complete(payload.request, cancellation=cancellation))

    async def disconnected() -> None:
        while not await request.is_disconnected():
            await asyncio.sleep(0.5)
        cancellation.cancel()
        inference.cancel()

    watcher = asyncio.create_task(disconnected())
    try:
        response.headers["Cache-Control"] = "no-store"
        async with asyncio.timeout(180):
            return await inference
    except asyncio.CancelledError:
        cancellation.cancel()
        raise
    except TimeoutError:
        raise HTTPException(504, "模型服务响应超时") from None
    except Exception:
        # Provider errors can contain request bodies/credentials. Never return
        # or log them here. The model gateway maintains its own safe telemetry.
        raise HTTPException(502, "服务器模型调用失败，请检查模型服务状态") from None
    finally:
        if not inference.done():
            inference.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await inference
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
        _inference_slots.release()
