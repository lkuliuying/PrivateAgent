"""记忆候选生成服务：从任务报告 / 聊天记录抽取可沉淀的长期记忆。

照 ChatService._get_provider 模式构造 OllamaProvider（抽取任务用低温度保证 JSON
稳定）。候选落库为 status='draft'，由用户在记忆页确认后转 confirmed。
学习复习来源 defer 到 M2（复习数据尚无写入路径）。
"""
from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .history import MessageRepository, SessionRepository
from .learning import LearningNotFound, LearningService
from .memory import MemoryService
from .models import MemoryItem
from .provider import OllamaProvider, ProviderError
from .repo_tasks import AgentEvidenceRepository, AgentTaskRepository
from .settings import SettingsService

logger = get_logger(__name__)

CANDIDATE_SYSTEM_PROMPT = (
    "你是一个记忆抽取助手。从用户提供的任务报告或对话中，抽取值得长期记住的用户记忆："
    "用户偏好（解释风格/语言/技术栈）、学习状态（当前主题/薄弱点/目标）、"
    "项目经验（结构/常用命令/历史问题/修复记录）、文档洞察、工作流经验、笔记。"
    "每条记忆输出一个 JSON 对象，字段：kind（preference/learning/project/document/workflow/note）、"
    "title（简短标题）、content_md（详细内容）、summary（一句话摘要，可省）、"
    "confidence（0-1 把握度，可省）。只抽取确实值得沉淀的；没有则返回空数组 []。"
    "严格只输出一个 JSON 数组，不要任何解释或 markdown 代码块标记。"
)

# 候选抽取上下文长度上限（字符），超过则截断。
CANDIDATE_CONTEXT_CHAR_LIMIT = 8000

_VALID_KINDS = {"preference", "learning", "project", "document", "workflow", "note"}


def _to_float(v: object) -> float | None:
    try:
        f = float(v)  # type: ignore[arg-type]
        return f if 0.0 <= f <= 1.0 else None
    except (TypeError, ValueError):
        return None


class MemoryCandidateService:
    def __init__(
        self, db: AsyncSession, provider: OllamaProvider | None = None
    ) -> None:
        self.db = db
        self._provider = provider
        self.tasks = AgentTaskRepository(db)
        self.evidence = AgentEvidenceRepository(db)
        self.messages = MessageRepository(db)
        self.memory = MemoryService(db)

    async def _get_provider(self) -> OllamaProvider:
        """从 settings 读取模型参数构造 Provider；抽取任务用低温度保证 JSON 稳定。"""
        if self._provider is not None:
            return self._provider
        s = await SettingsService(self.db).get_all()
        return OllamaProvider(
            llm_model=s["llm_model"],
            temperature=0.1,
            context_length=int(s["llm_context_length"]),
        )

    # ---------------- 来源：任务报告 ----------------
    async def generate_from_task(self, task_id: int) -> list[MemoryItem]:
        task = await self.tasks.get(task_id)
        if task is None:
            raise LookupError(f"任务不存在: {task_id}")
        report = task.final_report_md or ""
        evidence = await self.evidence.list_by_task(task_id)
        ev_text = "\n\n".join(
            f"### {e.title}\n{e.content_md}" for e in evidence if e.kind != "report"
        )
        context = f"# 任务：{task.title}\n目标：{task.goal or ''}\n\n## 最终报告\n{report}"
        if ev_text:
            context += f"\n\n## 证据\n{ev_text}"
        context = _truncate(context, CANDIDATE_CONTEXT_CHAR_LIMIT)
        project_id = self._extract_project_id(task.plan_json)
        items = await self._extract(context)
        return await self._persist(
            items,
            source_type="agent_task",
            source_id=task_id,
            project_id=project_id,
        )

    # ---------------- 来源：聊天记录 ----------------
    async def generate_from_chat(
        self, session_id: int, limit: int = 20
    ) -> list[MemoryItem]:
        # 会话不存在抛 LookupError（路由转 404），与 task/learning_review 分支一致。
        session = await SessionRepository(self.db).get(session_id)
        if session is None:
            raise LookupError(f"会话不存在: {session_id}")
        msgs = await self.messages.list_by_session(session_id)
        if not msgs:
            return []
        recent = msgs[-limit:]
        dialogue = "\n".join(
            f"{'用户' if m.role == 'user' else '助手'}：{m.content}" for m in recent
        )
        context = f"# 对话记录（会话 {session_id}）\n{dialogue}"
        context = _truncate(context, CANDIDATE_CONTEXT_CHAR_LIMIT)
        items = await self._extract(context)
        return await self._persist(
            items, source_type="chat_session", source_id=session_id
        )

    # ---------------- 来源：学习复习（M2）----------------
    async def generate_from_learning_review(self, topic_id: int) -> list[MemoryItem]:
        """从学习主题近 7 天复习/错题/薄弱点抽取候选记忆（落库 draft）。

        上下文由 LearningService.review_context 构建（无 LLM），抽取用低温度
        Provider 保证 JSON 稳定。主题不存在抛 LookupError（路由转 404）。
        """
        svc = LearningService(self.db, provider=self._provider)
        try:
            context = await svc.review_context(topic_id)
        except LearningNotFound as e:
            raise LookupError(str(e)) from e
        items = await self._extract(context)
        return await self._persist(
            items,
            source_type="learning_review",
            source_id=topic_id,
            topic_id=topic_id,
        )

    # ---------------- 内部 ----------------
    async def _extract(self, context: str) -> list[dict]:
        provider = await self._get_provider()
        raw = await provider.chat(
            [
                {"role": "system", "content": CANDIDATE_SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ]
        )
        return self._parse_candidates(raw)

    async def _persist(
        self,
        items: list[dict],
        *,
        source_type: str,
        source_id: int,
        project_id: int | None = None,
        topic_id: int | None = None,
    ) -> list[MemoryItem]:
        created: list[MemoryItem] = []
        for c in items:
            mem = await self.memory.create(
                kind=c["kind"],
                title=c["title"],
                content_md=c["content_md"],
                summary=c["summary"],
                source_type=source_type,
                source_id=source_id,
                project_id=project_id,
                topic_id=topic_id,
                confidence=c["confidence"],
                status="draft",
            )
            created.append(mem)
        logger.info(
            "memory candidates generated",
            source_type=source_type,
            source_id=source_id,
            count=len(created),
        )
        return created

    @staticmethod
    def _extract_project_id(plan_json: dict | None) -> int | None:
        """从 task.plan_json.steps[].input_json.project_id 反解项目归属。"""
        if not plan_json:
            return None
        for step in plan_json.get("steps", []) or []:
            pid = (step.get("input_json") or {}).get("project_id")
            if pid:
                try:
                    return int(pid)
                except (TypeError, ValueError):
                    return None
        return None

    @staticmethod
    def _parse_candidates(raw: str) -> list[dict]:
        """解析 LLM 输出的候选 JSON 数组，容错 strip 代码块标记。"""
        text = raw.strip()
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text[:4].lower() == "json":
                    text = text[4:]
                text = text.strip()
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            arr = json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise ProviderError(f"记忆候选响应解析失败: {e}") from e
        if not isinstance(arr, list):
            return []
        out: list[dict] = []
        for it in arr:
            if not isinstance(it, dict):
                continue
            title = (it.get("title") or "").strip()
            content = (it.get("content_md") or it.get("content") or "").strip()
            if not title or not content:
                continue
            kind = (it.get("kind") or "note").strip()
            if kind not in _VALID_KINDS:
                kind = "note"
            summary = (it.get("summary") or "").strip()
            out.append(
                {
                    "kind": kind,
                    "title": title[:255],
                    "content_md": content,
                    "summary": summary[:1024] or None,
                    "confidence": _to_float(it.get("confidence")),
                }
            )
        return out


def _truncate(text: str, limit: int) -> str:
    if len(text) > limit:
        return text[:limit] + "\n...（截断）"
    return text
