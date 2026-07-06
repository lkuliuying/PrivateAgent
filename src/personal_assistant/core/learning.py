"""学习系统服务：主题 CRUD + 路线/练习/卡片生成 + 答题批改。

生成类操作基于知识库检索（HybridRetriever）为 LLM 提供资料上下文，
避免空泛输出。LLM 输出 JSON，解析失败时回退为空结果（不抛）。

工具风险：create_learning_plan/generate_quiz/grade_quiz_answer 为 safe（只读+生成）；
save_learning_note/create_review_cards 为 confirm（写入用户数据）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .provider import OllamaProvider, ProviderError
from .repo import DocChunkRepository
from .repo_learning import (
    LearningAttemptRepository,
    LearningCardRepository,
    LearningNodeRepository,
    LearningNoteRepository,
    LearningQuizRepository,
    LearningTopicRepository,
)
from .settings import SettingsService

logger = get_logger(__name__)


class LearningNotFound(LookupError):
    """学习主题/笔记/练习不存在。"""


@dataclass
class GradeResult:
    result: str  # correct / partial / wrong
    explanation: str


# ============ LLM JSON 解析 ============

def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    return text


def parse_json_array(raw: str) -> list:
    """从 LLM 输出提取首个 JSON 数组；失败返回 []。"""
    text = _strip_fence(raw)
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            # 兼容 {"nodes": [...]} / {"plan": [...]} 包装
            for v in obj.values():
                if isinstance(v, list):
                    return v
    except Exception:  # noqa: BLE001
        pass
    # 回退：找首个 [ 到匹配 ]
    start = text.find("[")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        end = -1
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            try:
                obj = json.loads(text[start : end + 1])
                if isinstance(obj, list):
                    return obj
            except Exception:  # noqa: BLE001
                pass
        start = text.find("[", start + 1)
    return []


def parse_json_object(raw: str) -> dict | None:
    """从 LLM 输出提取首个 JSON 对象；失败返回 None。"""
    text = _strip_fence(raw)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        pass
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        end = -1
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            try:
                obj = json.loads(text[start : end + 1])
                if isinstance(obj, dict):
                    return obj
            except Exception:  # noqa: BLE001
                pass
        start = text.find("{", start + 1)
    return None


class LearningService:
    def __init__(self, db: AsyncSession, provider: OllamaProvider | None = None) -> None:
        self.db = db
        self._provider = provider
        self.topics = LearningTopicRepository(db)
        self.nodes = LearningNodeRepository(db)
        self.notes = LearningNoteRepository(db)
        self.cards = LearningCardRepository(db)
        self.quizzes = LearningQuizRepository(db)
        self.attempts = LearningAttemptRepository(db)
        self.chunk_repo = DocChunkRepository(db)

    async def _get_provider(self) -> OllamaProvider:
        if self._provider is not None:
            return self._provider
        s = await SettingsService(self.db).get_all()
        return OllamaProvider(
            llm_model=s["llm_model"],
            temperature=float(s["llm_temperature"]),
            context_length=int(s["llm_context_length"]),
        )

    # ============ 主题 CRUD ============

    async def create_topic(
        self, *, title: str, goal: str | None = None, level: str | None = None,
        tags: list[str] | None = None,
    ) -> object:
        return await self.topics.create(title=title, goal=goal, level=level, tags=tags)

    async def get_topic(self, topic_id: int):
        t = await self.topics.get(topic_id)
        if t is None:
            raise LearningNotFound(f"学习主题不存在: {topic_id}")
        return t

    async def list_topics(self):
        return await self.topics.list()

    async def update_topic(self, topic_id: int, **kwargs):
        await self.get_topic(topic_id)
        await self.topics.update(topic_id, **kwargs)

    async def list_nodes(self, topic_id: int):
        await self.get_topic(topic_id)
        return await self.nodes.list_by_topic(topic_id)

    async def set_node_mastery(self, node_id: int, mastery: str):
        node = await self.nodes.get(node_id)
        if node is None:
            raise LearningNotFound(f"知识节点不存在: {node_id}")
        await self.nodes.update_mastery(node_id, mastery)

    # ============ 笔记 ============

    async def save_note(
        self, *, topic_id: int | None, title: str, body_md: str,
        source_refs: list | None = None,
    ):
        if topic_id is not None:
            await self.get_topic(topic_id)
        return await self.notes.create(
            topic_id=topic_id, title=title, body_md=body_md, source_refs=source_refs
        )

    async def list_notes(self, topic_id: int | None = None):
        return await self.notes.list_by_topic(topic_id)

    # ============ 上下文收集 ============

    async def _gather_context(self, topic, source_doc_ids: list[int] | None = None, top_k: int = 8) -> str:
        """为生成收集资料上下文：指定文档取其切片，否则按主题目标混合检索。"""
        if source_doc_ids:
            chunks = []
            for did in source_doc_ids[:5]:
                chunks.extend(await self.chunk_repo.list_by_doc(did))
            contents = [c.content for c in chunks[: top_k * 2]]
        else:
            from .hybrid_retrieval import HybridRetriever

            retriever = HybridRetriever(self.db, provider=self._provider)
            query = f"{topic.title} {topic.goal or ''}".strip()
            results = await retriever.retrieve(query, top_k=top_k)
            contents = [r.content for r in results]
        return "\n\n".join(contents)[:8000]

    # ============ 路线生成 ============

    async def generate_plan(
        self, topic_id: int, source_doc_ids: list[int] | None = None
    ) -> list:
        topic = await self.get_topic(topic_id)
        context = await self._gather_context(topic, source_doc_ids)
        provider = await self._get_provider()
        prompt = (
            "你是学习规划师。基于下方资料，为以下学习主题生成一条由浅入深的学习路线，"
            "包含 5-8 个知识节点。只输出 JSON 数组，每项形如 "
            '{"title":"节点标题","summary":"一句话说明"}。'
            f"\n\n学习主题：{topic.title}\n目标：{topic.goal or '（未指定）'}"
            f"\n\n资料：\n{context}"
        )
        try:
            raw = await provider.chat(
                [{"role": "system", "content": "你只输出合法 JSON 数组，不要任何额外文字。"},
                 {"role": "user", "content": prompt}]
            )
        except ProviderError as e:
            logger.warning("generate_plan LLM failed", error=str(e))
            return []
        items = parse_json_array(raw)
        nodes = [
            {"title": str(i.get("title", f"节点{n+1}")), "summary": str(i.get("summary", ""))}
            for n, i in enumerate(items)
            if isinstance(i, dict)
        ]
        if not nodes:
            return []
        return await self.nodes.add_many(topic_id, nodes)

    # ============ 练习题生成 ============

    async def generate_quiz(
        self, topic_id: int, source_doc_ids: list[int] | None = None, count: int = 5
    ) -> list:
        topic = await self.get_topic(topic_id)
        context = await self._gather_context(topic, source_doc_ids)
        provider = await self._get_provider()
        n = max(1, min(count, 10))
        prompt = (
            f"基于下方资料，为学习主题「{topic.title}」生成 {n} 道练习题（含参考答案与解析）。"
            "只输出 JSON 数组，每项形如 "
            '{"question":"题目","answer":"参考答案","explanation":"解析"}。'
            f"\n\n资料：\n{context}"
        )
        try:
            raw = await provider.chat(
                [{"role": "system", "content": "你只输出合法 JSON 数组，不要任何额外文字。"},
                 {"role": "user", "content": prompt}]
            )
        except ProviderError as e:
            logger.warning("generate_quiz LLM failed", error=str(e))
            return []
        items = parse_json_array(raw)
        quizzes = [
            {
                "question": str(i.get("question", "")),
                "answer": str(i.get("answer", "")),
                "explanation": str(i.get("explanation", "")),
            }
            for i in items
            if isinstance(i, dict) and i.get("question")
        ]
        if not quizzes:
            return []
        return await self.quizzes.add_many(topic_id, quizzes)

    async def list_quizzes(self, topic_id: int):
        await self.get_topic(topic_id)
        return await self.quizzes.list_by_topic(topic_id)

    # ============ 答题批改 ============

    async def grade_attempt(self, quiz_id: int, user_answer: str) -> GradeResult:
        quiz = await self.quizzes.get(quiz_id)
        if quiz is None:
            raise LearningNotFound(f"练习题不存在: {quiz_id}")
        provider = await self._get_provider()
        prompt = (
            "你是阅卷助手。判定用户答案是否正确，只输出 JSON 对象："
            '{"result":"correct|partial|wrong","explanation":"判定说明"}。'
            f"\n\n题目：{quiz.question}\n参考答案：{quiz.answer}"
            f"\n用户答案：{user_answer}"
        )
        result = "wrong"
        explanation = ""
        try:
            raw = await provider.chat(
                [{"role": "system", "content": "你只输出合法 JSON 对象。"},
                 {"role": "user", "content": prompt}]
            )
            obj = parse_json_object(raw) or {}
            r = str(obj.get("result", "wrong")).lower()
            if r in ("correct", "partial", "wrong"):
                result = r
            explanation = str(obj.get("explanation", ""))
        except ProviderError as e:
            logger.warning("grade_attempt LLM failed", error=str(e))
            explanation = f"批改失败: {e}"
        await self.attempts.create(quiz_id=quiz_id, user_answer=user_answer, result=result)
        return GradeResult(result=result, explanation=explanation)

    # ============ 复习卡片 ============

    async def create_cards(
        self, topic_id: int, source_doc_ids: list[int] | None = None, count: int = 5
    ) -> list:
        topic = await self.get_topic(topic_id)
        context = await self._gather_context(topic, source_doc_ids)
        provider = await self._get_provider()
        n = max(1, min(count, 10))
        prompt = (
            f"基于下方资料，为学习主题「{topic.title}」生成 {n} 张复习卡片。"
            "只输出 JSON 数组，每项形如 "
            '{"front":"正面问题","back":"背面要点答案"}。'
            f"\n\n资料：\n{context}"
        )
        try:
            raw = await provider.chat(
                [{"role": "system", "content": "你只输出合法 JSON 数组，不要任何额外文字。"},
                 {"role": "user", "content": prompt}]
            )
        except ProviderError as e:
            logger.warning("create_cards LLM failed", error=str(e))
            return []
        items = parse_json_array(raw)
        cards = [
            {"front": str(i.get("front", "")), "back": str(i.get("back", ""))}
            for i in items
            if isinstance(i, dict) and i.get("front")
        ]
        if not cards:
            return []
        return await self.cards.add_many(topic_id, cards)

    async def list_cards(self, topic_id: int):
        await self.get_topic(topic_id)
        return await self.cards.list_by_topic(topic_id)
