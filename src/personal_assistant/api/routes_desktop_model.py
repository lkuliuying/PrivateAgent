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
from ..llm.contracts import ModelGatewayError
from ..logging_setup import get_logger
from .auth_dependencies import current_principal

router = APIRouter(prefix="/desktop", tags=["desktop-model"])
MAX_REQUEST_BYTES = 2 * 1024 * 1024
_inference_slots = asyncio.Semaphore(4)
logger = get_logger(__name__)
MODEL_ERRORS = {
    "not_configured": (422, "当前账号未配置默认模型，请在模型配置中选择并启用模型"),
    "invalid_configuration": (422, "服务器模型配置无效，请检查模型服务地址和参数"),
    "missing_api_key": (503, "服务器模型未配置 API Key，请在模型配置中重新保存密钥"),
    "unauthorized": (502, "模型供应商认证失败，请检查 API Key 和模型访问权限"),
    "model_not_found": (422, "模型供应商未找到所选模型，请检查模型名称和服务地址"),
    "unsupported_capability": (422, "所选服务器模型不可用或不支持当前能力，请检查模型配置"),
    "provider_rejected_request": (502, "模型供应商拒绝请求，请检查模型能力、工具参数和推理强度配置"),
    "rate_limited": (429, "模型供应商请求限额已达到，请检查配额或稍后重试"),
    "network_error": (503, "服务器无法连接模型供应商，请检查模型服务地址和服务器网络"),
    "provider_unavailable": (503, "模型供应商暂不可用，请稍后重试"),
    "timeout": (504, "模型服务响应超时，请稍后重试"),
    "invalid_response": (502, "模型供应商响应格式无效，请检查模型接口兼容性"),
    "provider_error": (502, "服务器模型调用失败，请联系管理员检查模型服务状态"),
}


def model_http_error(code: str) -> HTTPException:
    """仅返回固定分类和文案，不输出供应商异常正文、请求或凭据。"""
    safe_code = code if code in MODEL_ERRORS else "provider_error"
    status, message = MODEL_ERRORS[safe_code]
    logger.warning("desktop_model_failed", error_code=safe_code, status_code=status)
    return HTTPException(status, message, headers={
        "X-Model-Error-Code": safe_code, "Cache-Control": "no-store",
    })


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
        if profile_id is None:
            # 联网版没有默认模型时不能回落到服务器上的旧全局 Ollama 配置。
            raise model_http_error("not_configured")
    try:
        if profile_id and payload.request.reasoning_effort:
            profile = await ModelProfileService(db).get(profile_id)
            if profile is None or payload.request.reasoning_effort not in (profile.reasoning_efforts_json or []):
                raise ModelProfileUnsupported("模型不支持所选推理强度")
        return await _model_gateway_for_run(db, AgentRunRecord(model_profile_id=profile_id))
    except ModelProfileUnsupported:
        raise model_http_error("unsupported_capability") from None
    except ValueError:
        raise model_http_error("invalid_configuration") from None


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
        raise model_http_error("timeout") from None
    except ModelGatewayError as error:
        raise model_http_error(error.code) from None
    except Exception:
        # 未知异常只记录固定分类，不让异常正文或堆栈中的凭据进入日志。
        raise model_http_error("provider_error") from None
    finally:
        if not inference.done():
            inference.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await inference
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
        _inference_slots.release()
