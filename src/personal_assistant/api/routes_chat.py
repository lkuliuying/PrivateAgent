"""聊天流式路由（SSE）。

前端用 fetch + ReadableStream 消费（EventSource 不支持 POST）。
停止生成：前端 abort fetch -> 连接断开 -> 后端生成器 finally 保存已生成部分。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.chat import ChatService
from ..core.db import get_session
from ..core.history import SessionRepository

router = APIRouter(tags=["chat"])


class ToolResultPayload(BaseModel):
    tool_name: str
    output: dict


class ChatRequest(BaseModel):
    session_id: int
    message: str
    knowledge_base: bool = False
    tool_result: ToolResultPayload | None = None


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, db: AsyncSession = Depends(get_session)):
    """SSE 流式对话。事件以 `data: {json}\n\n` 推送。"""
    sess = await SessionRepository(db).get(req.session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")

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
