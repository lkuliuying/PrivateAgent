"""对话编排：历史注入 + 流式输出 + 首轮标题生成 + 可选 RAG。

模型参数（温度/上下文/模型名）从 settings 表动态读取，支持运行时调整。
M1 采用最简链路（ChatOllama.astream），LangGraph 留待后续复杂编排。

事件类型：
  token / done(含 sources 与 memories) / title / error
停止生成：前端断开 -> 生成器 finally 保存已生成部分。
"""
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .history import MessageRepository, SessionRepository
from .provider import OllamaProvider, ProviderError, ProviderRouter, classify_error
from .repo_privacy import ProviderCallAuditRepository
from .settings import SettingsService
from .timeutil import utcnow

logger = get_logger(__name__)

SYSTEM_PROMPT = "你是一个有用的私人助手，请用中文简洁、准确地回答用户的问题。"

TITLE_PROMPT = (
    "请根据下面的对话，生成一个简短的中文会话标题，不超过12个字，"
    "不要加引号或标点符号，只输出标题本身。\n\n"
    "用户：{user}\n\n助手：{assistant}"
)


def _format_tool_result(tool_name: str, output: dict) -> str:
    """把工具执行结果格式化为注入 system prompt 的上下文片段。"""
    if tool_name == "read_file":
        content = output.get("content", "")
        size = output.get("size_bytes", 0)
        trunc = "（已截断）" if output.get("truncated") else ""
        return (
            f"【工具 read_file 已读取文件】（{size} 字节{trunc}）：\n"
            f"{content}\n\n请基于以上文件内容回答用户。"
        )
    # 通用格式：JSON 摘要（截断防止过长）
    dump = json.dumps(output, ensure_ascii=False)
    if len(dump) > 2000:
        dump = dump[:2000] + "…（截断）"
    return f"【工具 {tool_name} 执行结果】：\n{dump}\n\n请基于以上结果回答用户。"


class ChatService:
    def __init__(
        self, db: AsyncSession, provider: OllamaProvider | None = None
    ) -> None:
        self.db = db
        self._provider = provider
        self.sessions = SessionRepository(db)
        self.messages = MessageRepository(db)

    async def _get_provider(self) -> OllamaProvider:
        """从 settings 读取模型参数构造 Provider（支持运行时调整）。"""
        if self._provider is not None:
            return self._provider
        s = await SettingsService(self.db).get_all()
        return ProviderRouter(s).chat_provider()

    async def stream_reply(
        self,
        session_id: int,
        user_content: str,
        knowledge_base: bool = False,
        tool_result: dict | None = None,
    ) -> AsyncIterator[dict]:
        """对指定会话流式生成回复。

        knowledge_base=True 时启用 RAG 检索。
        tool_result 非空时（plan-then-reply：工具执行后），把工具结果注入 system 上下文，
        让助手基于结果作答；工具结果持久化在 tool_calls 表，不进 messages。
        """
        history = await self.messages.list_by_session(session_id)
        is_first_turn = len(history) == 0
        await self.messages.add(session_id, "user", user_content)

        provider_settings = await SettingsService(self.db).get_all()
        router = ProviderRouter(provider_settings)
        privacy_scope = router.privacy_scope()
        provider = self._provider or router.chat_provider()

        # 构造 system prompt
        sources: list[dict] = []
        memories_used: list[dict] = []
        if knowledge_base:
            from .rag import RagService

            rag = RagService(self.db)
            chunks, evidence = await rag.retrieve_with_evidence(user_content, top_k=5)
            if chunks:
                sources = rag.format_sources(chunks)
            system_content = rag.build_system_prompt(chunks, evidence=evidence)
        else:
            system_content = SYSTEM_PROMPT

        # 长期记忆注入（独立于 knowledge_base；失败容错降级为空，不阻断聊天）
        try:
            from .memory import MemoryService

            mem_svc = MemoryService(self.db)
            mems = await mem_svc.retrieve_for_context(user_content, top_k=5)
            if mems:
                memories_used = mem_svc.format_sources(mems)
                system_content = (
                    system_content
                    + "\n\n以下是关于用户的长期记忆，回答时请酌情参考：\n"
                    + mem_svc.format_memory_context(mems)
                )
                await mem_svc.record_usage(
                    [m.id for m in mems], ref_type="chat_session", ref_id=session_id
                )
        except Exception:  # noqa: BLE001
            logger.exception("memory injection failed, continuing without memory")

        # 工具结果注入
        if tool_result:
            system_content = system_content + "\n\n" + _format_tool_result(
                tool_result.get("tool_name", "工具"), tool_result.get("output") or {}
            )

        msgs: list[dict[str, str]] = [{"role": "system", "content": system_content}]
        for m in history:
            msgs.append({"role": m.role, "content": m.content})
        msgs.append({"role": "user", "content": user_content})

        audit_id: int | None = None
        input_chars = sum(len(m["content"]) for m in msgs)
        if privacy_scope.get("remote_provider_enabled") and privacy_scope.get(
            "provider_type"
        ) in {"openai", "claude"}:
            context_types = ["chat_messages"]
            if knowledge_base:
                context_types.append("kb_chunks")
            if memories_used:
                context_types.append("memories")
            if tool_result:
                context_types.append("tool_result")
            audit = await ProviderCallAuditRepository(self.db).create(
                provider_type=str(privacy_scope.get("provider_type")),
                purpose="chat",
                model=provider_settings.get(
                    f"{privacy_scope.get('provider_type')}_model"
                ),
                remote=True,
                context_types_json=context_types,
                estimated_input_chars=input_chars,
                estimated_input_tokens=input_chars // 4,
                status="sent",
                started_at=utcnow(),
            )
            audit_id = audit.id

        logger.info(
            "chat start",
            session_id=session_id,
            first_turn=is_first_turn,
            kb=knowledge_base,
        )

        t0 = time.monotonic()
        saved = False
        collected: list[str] = []
        try:
            async for token in provider.chat_stream(msgs):
                collected.append(token)
                yield {"type": "token", "content": token}

            assistant_content = "".join(collected)
            msg = await self.messages.add(
                session_id, "assistant", assistant_content
            )
            saved = True
            yield {
                "type": "done",
                "message_id": msg.id,
                "content": assistant_content,
                "sources": sources,
                "memories": memories_used,
            }

            if is_first_turn:
                title = await self._generate_title(
                    session_id, user_content, assistant_content, provider
                )
                if title:
                    yield {"type": "title", "title": title}

            if audit_id is not None:
                await ProviderCallAuditRepository(self.db).finish(
                    audit_id,
                    status="succeeded",
                    estimated_output_chars=len(assistant_content),
                    estimated_output_tokens=len(assistant_content) // 4,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )

        except ProviderError as e:
            code = classify_error(e)
            logger.warning(
                "chat provider error",
                session_id=session_id,
                error=str(e),
                code=code,
            )
            # M6 降级：远程失败时回退本地 Ollama（非流式，done 覆盖主调部分 token）。
            fallback_used = False
            if privacy_scope.get("remote_provider_enabled"):
                try:
                    fallback = router.fallback_provider()
                    fb_content = await fallback.chat(msgs)
                    msg = await self.messages.add(
                        session_id, "assistant", fb_content
                    )
                    saved = True
                    fallback_used = True
                    yield {
                        "type": "done",
                        "message_id": msg.id,
                        "content": fb_content,
                        "sources": sources,
                        "memories": memories_used,
                        "fallback_used": True,
                    }
                    if is_first_turn:
                        title = await self._generate_title(
                            session_id, user_content, fb_content, fallback
                        )
                        if title:
                            yield {"type": "title", "title": title}
                except Exception as fb_e:  # noqa: BLE001
                    logger.warning(
                        "ollama fallback failed",
                        session_id=session_id,
                        error=str(fb_e),
                    )
                    fallback_used = False
            if audit_id is not None:
                await ProviderCallAuditRepository(self.db).finish(
                    audit_id,
                    status="failed",
                    error_message=str(e),
                    error_code=code,
                    fallback_used=fallback_used,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
            if not fallback_used:
                diagnostic = {
                    "provider_type": privacy_scope.get("provider_type"),
                    "error_code": code,
                    "error": str(e),
                    "audit_id": audit_id,
                }
                yield {
                    "type": "error",
                    "message": str(e),
                    "error_code": code,
                    "diagnostic": diagnostic,
                }
        except Exception as e:  # noqa: BLE001
            code = classify_error(e)
            logger.exception("chat stream failed", session_id=session_id)
            if audit_id is not None:
                await ProviderCallAuditRepository(self.db).finish(
                    audit_id,
                    status="failed",
                    error_message=str(e),
                    error_code=code,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
            yield {
                "type": "error",
                "message": f"生成失败: {e}",
                "error_code": code,
            }
        finally:
            if not saved and collected:
                try:
                    await self.messages.add(
                        session_id, "assistant", "".join(collected)
                    )
                    logger.info(
                        "chat stopped, partial saved",
                        session_id=session_id,
                        chars=len("".join(collected)),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("save partial failed", session_id=session_id)

    async def _generate_title(
        self,
        session_id: int,
        user_content: str,
        assistant_content: str,
        provider: OllamaProvider,
    ) -> str | None:
        """基于首轮对话生成标题，失败时返回 None（保留默认「新对话」）。"""
        prompt = TITLE_PROMPT.format(
            user=user_content[:500], assistant=assistant_content[:500]
        )
        try:
            raw = await provider.chat([{"role": "user", "content": prompt}])
            title = raw.strip().strip("\"'""''「」").strip().replace("\n", " ")
            title = title[:30]
            if not title:
                return None
            await self.sessions.rename(session_id, title)
            logger.info("title generated", session_id=session_id, title=title)
            return title
        except Exception as e:  # noqa: BLE001
            logger.warning("title generation failed", session_id=session_id, error=str(e))
            return None

    @staticmethod
    def event_to_sse(event: dict) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
