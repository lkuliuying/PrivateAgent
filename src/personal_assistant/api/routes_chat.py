"""聊天流式路由（SSE）。

前端用 fetch + ReadableStream 消费（EventSource 不支持 POST）。
停止生成：前端 abort fetch -> 连接断开 -> 后端生成器 finally 保存已生成部分。
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import personal_assistant.core.db as dbmod

from ..agents import (
    AgentRunLimits,
    AgentRunRepository,
    ModelMessage,
    RagCitationOutputVerifier,
    ToolApprovalRepository,
)
from ..api.routes_agent_runs import (
    AGENT_SYSTEM_PROMPT,
    agent_run_coordinator,
    get_agent_tool_bundle,
    require_agent_runtime_owner,
)
from ..config import settings as cfg
from ..context import (
    ContextBudgetExceededError,
    context_event_payload,
    prepare_agent_context,
)
from ..core.chat import ChatService
from ..core.compatibility import compatibility_telemetry
from ..core.db import get_session
from ..core.history import MessageRepository, SessionRepository
from ..core.provider import ProviderRouter
from ..core.rag_citation_evidence import load_durable_rag_citation_sources
from ..core.settings import SettingsService
from ..core.timeutil import utcnow
from ..logging_setup import get_logger

router = APIRouter(tags=["chat"])
logger = get_logger(__name__)


class ToolResultPayload(BaseModel):
    tool_name: str
    output: dict


class ChatRequest(BaseModel):
    session_id: int
    message: str
    knowledge_base: bool = False
    tool_result: ToolResultPayload | None = None


class AgentChatOutputProjectionError(RuntimeError):
    """A completed run cannot be safely projected into the legacy chat contract."""


def _chat_route_mode(req: ChatRequest) -> str:
    """Return one fixed-label routing reason without inspecting message content.

    0.3.0 M1：agent_runtime（普通聊天）与 agent_runtime_rag（知识库聊天）
    分开计，便于区分普通与 RAG 流量；两者都走 durable Runtime。
    """

    if not cfg.chat_agent_runtime_enabled:
        return "legacy_runtime_disabled"
    if req.tool_result is not None:
        return "legacy_tool_result"
    if req.knowledge_base and not cfg.agent_rag_tools_enabled:
        return "legacy_rag_tools_disabled"
    if req.knowledge_base and not cfg.agent_output_verification_enabled:
        return "legacy_output_verification_disabled"
    return "agent_runtime_rag" if req.knowledge_base else "agent_runtime"


async def _project_agent_chat_output(
    db: AsyncSession,
    *,
    run_id: str,
    output: str,
) -> tuple[str, list[dict]]:
    """Expose verified RAG JSON as a readable answer plus trusted source metadata."""

    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return output, []
    if not isinstance(payload, dict) or set(payload) != {"answer", "citations"}:
        return output, []

    try:
        trusted_sources = await load_durable_rag_citation_sources(db, run_id=run_id)
        verification = await RagCitationOutputVerifier(trusted_sources).verify(
            output,
            attempt=1,
        )
    except Exception as exc:  # noqa: BLE001
        raise AgentChatOutputProjectionError(
            "持久化引用证据不可用，已拒绝展示未经复核的回答"
        ) from exc
    if not verification.passed:
        raise AgentChatOutputProjectionError(
            "持久化回答未通过引用复核，已拒绝展示"
        )

    indexed = {
        (source.index_version_id, source.chunk_id): source
        for source in trusted_sources
    }
    projected_sources: list[dict] = []
    for citation in payload["citations"]:
        source = indexed[(citation["index_version_id"], citation["chunk_id"])]
        if source.doc_name is None or source.ordinal is None:
            raise AgentChatOutputProjectionError(
                "持久化引用缺少可展示的来源元数据"
            )
        projected_sources.append(
            {
                "doc_name": source.doc_name,
                "ordinal": source.ordinal,
                "chunk_id": source.chunk_id,
                "heading": source.heading,
                "score": source.score,
                "fusion_score": source.fusion_score,
                "bm25_score": source.bm25_score,
                "rerank_score": source.rerank_score,
                "matched_via": list(source.matched_via),
                "matched_keywords": list(source.matched_keywords),
            }
        )
    return payload["answer"], projected_sources


def _drain_agent_output(queue: asyncio.Queue[str] | None) -> list[str]:
    if queue is None:
        return []
    deltas: list[str] = []
    while True:
        try:
            deltas.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return deltas


def _run_cleanup_finally(
    run_id: str, output_queue: asyncio.Queue[str] | None
) -> None:
    """事件生成器 finally 的同步收尾（release_output_queue 幂等）。"""
    agent_run_coordinator.release_output_queue(run_id, output_queue)


async def _converge_disconnected_run(run_id: str) -> None:
    """SSE 断线/客户端关闭时的收敛收尾（0.3.0 M2 修复）。

    - 活跃 run：请求持久化取消并停止协调器任务；
    - waiting_approval：拒绝待审审批并收敛为 cancelled——
      否则断线后的等待审批 run 只能靠审批 TTL 过期才收敛；
    - 其他终态：无需处理。
    """
    if agent_run_coordinator.is_active(run_id):
        async with dbmod.async_session_factory() as cancel_db:
            try:
                await AgentRunRepository(cancel_db).request_cancellation(run_id)
            except Exception:  # noqa: BLE001
                await cancel_db.rollback()
        agent_run_coordinator.cancel(run_id)
        return
    async with dbmod.async_session_factory() as pending_db:
        try:
            pending = await AgentRunRepository(pending_db).get_run(run_id)
            if pending is not None and pending.status == "waiting_approval":
                approvals = ToolApprovalRepository(pending_db)
                for approval in await approvals.list_for_run(run_id):
                    if approval.status == "pending":
                        try:
                            await approvals.reject(approval.id)
                        except Exception:  # noqa: BLE001
                            pass
                await AgentRunRepository(pending_db).cancel_waiting_approval(
                    run_id,
                    error="SSE 断线，等待审批的运行已收敛",
                    error_code="disconnected",
                )
        except Exception:  # noqa: BLE001
            await pending_db.rollback()


async def _build_agent_model(db: AsyncSession):
    provider_settings = await SettingsService(db).get_all()
    return ProviderRouter(provider_settings).model_gateway()


async def _agent_chat_stream(
    req: ChatRequest,
    db: AsyncSession,
) -> StreamingResponse:
    messages_repository = MessageRepository(db)
    history = await messages_repository.list_by_session(req.session_id)
    is_first_turn = len(history) == 0

    system_prompt = AGENT_SYSTEM_PROMPT
    if req.knowledge_base:
        system_prompt += (
            "用户已明确启用本地知识库。仅在问题需要本地资料时调用 "
            "search_knowledge_base，并只使用工具实际返回且可引用的证据回答；"
            "没有相关资料时应明确说明，不得编造来源。"
        )

    # 0.3.0 M2：会话历史经 ContextBuilder 预算与最近消息保留策略选择；
    # 开启时记忆/摘要/RAG 片段受 budget 约束，敏感摘要被排除。预算超限时
    # 明确报错，不创建 run、不把同一消息再交给 legacy 执行（先于 model/tool
    # 构造做预算检查，快速失败）。
    context_metadata = None
    if cfg.agent_context_builder_enabled:
        try:
            prepared = await prepare_agent_context(
                db,
                system_policy=system_prompt,
                current_request=req.message,
                session_id=req.session_id,
                knowledge_base=req.knowledge_base,
            )
        except ContextBudgetExceededError:
            service = ChatService(db)

            async def budget_error_events():
                yield service.event_to_sse(
                    {
                        "type": "error",
                        "run_id": None,
                        "message": "上下文预算不足，无法执行本次请求，"
                        "请新建会话或精简内容后重试",
                    }
                )

            return StreamingResponse(
                budget_error_events(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        runtime_messages = prepared.messages
        context_metadata = context_event_payload(prepared)
    else:
        runtime_messages = [
            ModelMessage(
                role="system",
                content=system_prompt,
            )
        ]
        runtime_messages.extend(
            ModelMessage(role=message.role, content=message.content)
            for message in history
            if message.role in {"user", "assistant", "system"}
        )
        runtime_messages.append(ModelMessage(role="user", content=req.message))

    model = await _build_agent_model(db)
    tool_bundle = await get_agent_tool_bundle(db)
    limits = AgentRunLimits()
    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    await repository.create_run(
        run_id=run_id,
        limits=limits,
        session_id=req.session_id,
    )
    await messages_repository.add(req.session_id, "user", req.message)

    structured_rag_output = bool(
        cfg.agent_output_verification_enabled
        and tool_bundle is not None
        and tool_bundle.output_verifier_factory is not None
    )
    output_queue = agent_run_coordinator.start(
        run_id=run_id,
        model=model,
        messages=tuple(runtime_messages),
        limits=limits,
        tool_definitions=tool_bundle.definitions if tool_bundle is not None else (),
        tool_dispatcher_factory=(
            tool_bundle.dispatcher_factory if tool_bundle is not None else None
        ),
        output_verifier_factory=(
            tool_bundle.output_verifier_factory if tool_bundle is not None else None
        ),
        stream_output=not structured_rag_output,
        context_metadata=context_metadata,
    )

    service = ChatService(db)

    async def event_gen():
        announced_approvals: set[str] = set()
        streamed_parts: list[str] = []
        try:
            # 首个 yield 必须在 try 内：async generator 在 yield 处被注入
            # 异常（断线取消）时，try/finally 之外的代码不会执行，收尾会丢失。
            yield service.event_to_sse({"type": "run", "run_id": run_id})
            while True:
                for delta in _drain_agent_output(output_queue):
                    streamed_parts.append(delta)
                    yield service.event_to_sse({"type": "token", "content": delta})
                try:
                    async with dbmod.async_session_factory() as poll_db:
                        run_repository = AgentRunRepository(poll_db)
                        approval_repository = ToolApprovalRepository(poll_db)
                        current = await run_repository.get_run(run_id)
                        if current is None:
                            yield service.event_to_sse(
                                {"type": "error", "message": "运行记录不存在"}
                            )
                            return
                        current_status = current.status
                        output = current.output
                        error = current.error_message
                        error_code = current.error_code
                        run_approvals = (
                            await approval_repository.list_for_run(run_id)
                            if current_status
                            in {"running", "waiting_approval", "completed"}
                            else []
                        )
                        if current_status == "waiting_approval" and any(
                            approval.status == "pending" and approval.expires_at <= utcnow()
                            for approval in run_approvals
                        ):
                            await approval_repository.expire_due()
                            await run_repository.cancel_waiting_approval(
                                run_id,
                                error="tool approval expired",
                                error_code="approval_expired",
                            )
                            current_status = "cancelled"
                            error = "tool approval expired"
                            error_code = "approval_expired"
                except Exception:  # noqa: BLE001
                    # MySQL 短暂断连等持久层故障：失败关闭，向用户给出明确错误，
                    # 不伪造 run 终态（run 由下次启动 recovery 收敛），不崩溃进程。
                    logger.warning(
                        "chat run poll failed",
                        run_id=run_id,
                        error_type="persistence_unavailable",
                    )
                    yield service.event_to_sse(
                        {
                            "type": "error",
                            "run_id": run_id,
                            "message": "数据库暂时不可用，运行状态暂无法同步，请稍后重试",
                        }
                    )
                    return

                for approval in run_approvals:
                    if approval.id in announced_approvals:
                        continue
                    announced_approvals.add(approval.id)
                    yield service.event_to_sse(
                        {
                            "type": "approval",
                            "run_id": run_id,
                            "approval": {
                                "id": approval.id,
                                "run_id": run_id,
                                "tool_call_id": approval.tool_call_id,
                                "tool_name": approval.tool_name,
                                "tool_version": approval.tool_version,
                                "arguments_sha256": approval.arguments_sha256,
                                "risk_level": approval.risk_level,
                                "required_capabilities": list(
                                    approval.required_capabilities_json or []
                                ),
                                "status": approval.status,
                                "expires_at": approval.expires_at.isoformat(),
                                "created_at": approval.created_at.isoformat(),
                            },
                        }
                    )

                if current_status == "waiting_approval":
                    await asyncio.sleep(0.1)
                    continue

                if current_status == "completed":
                    assistant_content = output or ""
                    for delta in _drain_agent_output(output_queue):
                        streamed_parts.append(delta)
                        yield service.event_to_sse({"type": "token", "content": delta})
                    try:
                        async with dbmod.async_session_factory() as write_db:
                            assistant_content, sources = (
                                await _project_agent_chat_output(
                                    write_db,
                                    run_id=run_id,
                                    output=assistant_content,
                                )
                            )
                            saved = await AgentRunRepository(
                                write_db
                            ).persist_chat_output_message_once(
                                run_id,
                                session_id=req.session_id,
                                content=assistant_content,
                            )
                    except AgentChatOutputProjectionError as exc:
                        yield service.event_to_sse(
                            {
                                "type": "error",
                                "run_id": run_id,
                                "message": str(exc),
                            }
                        )
                        return
                    streamed_content = "".join(streamed_parts)
                    remainder = (
                        assistant_content[len(streamed_content) :]
                        if assistant_content.startswith(streamed_content)
                        else ""
                    )
                    if remainder:
                        yield service.event_to_sse(
                            {"type": "token", "content": remainder}
                        )
                    yield service.event_to_sse(
                        {
                            "type": "done",
                            "run_id": run_id,
                            "message_id": saved.id,
                            "content": assistant_content,
                            "sources": sources,
                            "memories": [],
                        }
                    )
                    if is_first_turn:
                        title = " ".join(req.message.split())[:12] or "新对话"
                        async with dbmod.async_session_factory() as title_db:
                            await SessionRepository(title_db).rename(
                                req.session_id,
                                title,
                            )
                        yield service.event_to_sse({"type": "title", "title": title})
                    return
                if current_status in {
                    "failed",
                    "cancelled",
                    "timed_out",
                    "limit_exceeded",
                }:
                    if (
                        current_status != "cancelled"
                        or error_code == "approval_expired"
                    ):
                        yield service.event_to_sse(
                            {
                                "type": "error",
                                "run_id": run_id,
                                "message": error or f"运行终止：{current_status}",
                            }
                        )
                    return
                if not agent_run_coordinator.is_active(run_id):
                    yield service.event_to_sse(
                        {
                            "type": "error",
                            "run_id": run_id,
                            "message": "运行进程已中断，可通过运行记录诊断",
                        }
                    )
                    return
                await asyncio.sleep(0.05)
        finally:
            # 断线取消（CancelledError）会打断 finally 内的 await：先捕获取消、
            # 完成收敛收尾，再重抛，保证 waiting_approval/活跃 run 都能收敛
            # （0.3.0 M2 修复，不能只依赖审批 TTL 过期）。
            cancelled: asyncio.CancelledError | None = None
            try:
                await _converge_disconnected_run(run_id)
            except asyncio.CancelledError as exc:
                cancelled = exc
                try:
                    await _converge_disconnected_run(run_id)
                except asyncio.CancelledError:
                    pass
            finally:
                _run_cleanup_finally(run_id, output_queue)
            if cancelled is not None:
                raise cancelled

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, db: AsyncSession = Depends(get_session)):
    """SSE 流式对话。事件以 `data: {json}\n\n` 推送。"""
    sess = await SessionRepository(db).get(req.session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")

    route_mode = _chat_route_mode(req)
    compatibility_telemetry.record(
        path="/chat/stream",
        mode=route_mode,
        outcome="routed",
    )
    logger.info(
        "chat compatibility path routed",
        compatibility_path="/chat/stream",
        compatibility_mode=route_mode,
        compatibility_outcome="routed",
    )
    if route_mode in {"agent_runtime", "agent_runtime_rag"}:
        require_agent_runtime_owner()
        return await _agent_chat_stream(req, db)

    service = ChatService(db)
    tool_result = req.tool_result.model_dump() if req.tool_result else None

    async def event_gen():
        try:
            async for event in service.stream_reply(
                req.session_id,
                req.message,
                req.knowledge_base,
                tool_result=tool_result,
            ):
                yield service.event_to_sse(event)
        except Exception as e:  # noqa: BLE001
            yield service.event_to_sse({"type": "error", "message": f"服务器错误: {e}"})

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chat/agent-runs/{run_id}/stream")
async def continue_agent_chat_stream(
    run_id: str,
    db: AsyncSession = Depends(get_session),
):
    """Reconnect the desktop UI to a durable chat run after an app reload."""

    if not cfg.chat_agent_runtime_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    run = await AgentRunRepository(db).get_run(run_id)
    if run is None or run.session_id is None:
        compatibility_telemetry.record(
            path="/chat/agent-runs/:id/stream",
            mode="agent_runtime",
            outcome="not_found",
        )
        raise HTTPException(status_code=404, detail="Agent chat run not found")
    compatibility_telemetry.record(
        path="/chat/agent-runs/:id/stream",
        mode="agent_runtime",
        outcome="reconnected",
    )
    session_id = run.session_id
    service = ChatService(db)
    output_queue = agent_run_coordinator.output_queue(run_id)

    async def event_gen():
        streamed_parts: list[str] = []
        try:
            # 首个 yield 必须在 try 内（见 _agent_chat_stream 同注释）
            yield service.event_to_sse({"type": "run", "run_id": run_id})
            while True:
                for delta in _drain_agent_output(output_queue):
                    streamed_parts.append(delta)
                    yield service.event_to_sse({"type": "token", "content": delta})
                try:
                    async with dbmod.async_session_factory() as poll_db:
                        current = await AgentRunRepository(poll_db).get_run(run_id)
                        if current is None or current.session_id != session_id:
                            yield service.event_to_sse(
                                {"type": "error", "message": "Agent chat run not found"}
                            )
                            return
                        current_status = current.status
                        output = current.output
                        error = current.error_message
                except Exception:  # noqa: BLE001
                    # MySQL 短暂断连等持久层故障：失败关闭（见 _agent_chat_stream 注释）
                    logger.warning(
                        "chat continuation poll failed",
                        run_id=run_id,
                        error_type="persistence_unavailable",
                    )
                    yield service.event_to_sse(
                        {
                            "type": "error",
                            "run_id": run_id,
                            "message": "数据库暂时不可用，运行状态暂无法同步，请稍后重试",
                        }
                    )
                    return

                if current_status == "completed":
                    assistant_content = output or ""
                    for delta in _drain_agent_output(output_queue):
                        streamed_parts.append(delta)
                        yield service.event_to_sse({"type": "token", "content": delta})
                    try:
                        async with dbmod.async_session_factory() as write_db:
                            assistant_content, sources = (
                                await _project_agent_chat_output(
                                    write_db,
                                    run_id=run_id,
                                    output=assistant_content,
                                )
                            )
                            saved = await AgentRunRepository(
                                write_db
                            ).persist_chat_output_message_once(
                                run_id,
                                session_id=session_id,
                                content=assistant_content,
                            )
                    except AgentChatOutputProjectionError as exc:
                        yield service.event_to_sse(
                            {
                                "type": "error",
                                "run_id": run_id,
                                "message": str(exc),
                            }
                        )
                        return
                    streamed_content = "".join(streamed_parts)
                    remainder = (
                        assistant_content[len(streamed_content) :]
                        if assistant_content.startswith(streamed_content)
                        else ""
                    )
                    if remainder:
                        yield service.event_to_sse(
                            {"type": "token", "content": remainder}
                        )
                    yield service.event_to_sse(
                        {
                            "type": "done",
                            "run_id": run_id,
                            "message_id": saved.id,
                            "content": assistant_content,
                            "sources": sources,
                            "memories": [],
                        }
                    )
                    return
                if current_status in {
                    "failed",
                    "cancelled",
                    "timed_out",
                    "limit_exceeded",
                }:
                    if current_status != "cancelled":
                        yield service.event_to_sse(
                            {
                                "type": "error",
                                "run_id": run_id,
                                "message": error
                                or f"Agent run stopped: {current_status}",
                            }
                        )
                    return
                if (
                    current_status != "waiting_approval"
                    and not agent_run_coordinator.is_active(run_id)
                ):
                    yield service.event_to_sse(
                        {
                            "type": "error",
                            "run_id": run_id,
                            "message": "Agent run process is no longer active",
                        }
                    )
                    return
                await asyncio.sleep(0.05)
        finally:
            cancelled: asyncio.CancelledError | None = None
            try:
                await _converge_disconnected_run(run_id)
            except asyncio.CancelledError as exc:
                cancelled = exc
                try:
                    await _converge_disconnected_run(run_id)
                except asyncio.CancelledError:
                    pass
            finally:
                _run_cleanup_finally(run_id, output_queue)
            if cancelled is not None:
                raise cancelled

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
