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
from datetime import datetime, timedelta

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
    LearningReviewRepository,
    LearningTopicRepository,
)
from .review_scheduler import CardState, RATING_QUALITY, schedule
from .settings import SettingsService
from .timeutil import utcnow

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
        self.reviews = LearningReviewRepository(db)
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

    # ============ 间隔重复复习（M2）============

    async def submit_card_review(
        self, card_id: int, rating: str, now: datetime | None = None
    ) -> dict:
        """提交卡片评分：跑 SM-2 调度 → 更新卡片调度字段 → 写复习记录。

        返回 {card, review}：card 为刷新后的卡片，review 为新建的复习记录。
        """
        if rating not in RATING_QUALITY:
            raise ValueError(f"未知评分: {rating}")
        card = await self.cards.get(card_id)
        if card is None:
            raise LearningNotFound(f"复习卡片不存在: {card_id}")
        now = now or utcnow()
        # 在 update_scheduling 的 commit 前捕获旧值：commit 会 expire 该对象，
        # 之后再读 card.due_at 会从 DB 重载为新值，导致 previous_due_at 错记。
        prev_due_at = card.due_at
        topic_id = card.topic_id
        prev_state = CardState(
            interval_days=card.interval_days,
            ease_factor=card.ease_factor,
            review_count=card.review_count,
            lapse_count=card.lapse_count,
        )
        result = schedule(prev_state, rating, now=now)
        await self.cards.update_scheduling(
            card_id,
            interval_days=result.interval_days,
            ease_factor=result.ease_factor,
            review_count=result.review_count,
            lapse_count=result.lapse_count,
            due_at=result.due_at,
        )
        review = await self.reviews.create(
            card_id=card_id,
            topic_id=topic_id,
            rating=rating,
            previous_due_at=prev_due_at,
            next_due_at=result.due_at,
        )
        fresh = await self.cards.get_fresh(card_id)
        return {"card": fresh or card, "review": review}

    async def list_reviews_today(
        self, topic_id: int | None = None, now: datetime | None = None
    ) -> list:
        """今日到期复习卡片（due_at 为空或<=now）。可跨主题或限定主题。"""
        now = now or utcnow()
        if topic_id is not None:
            await self.get_topic(topic_id)
        return await self.cards.list_due(now, topic_id=topic_id)

    async def topic_dashboard(self, topic_id: int, now: datetime | None = None) -> dict:
        """主题学习仪表盘：卡片/复习/掌握度统计 + 近 7 天复习数。"""
        topic = await self.get_topic(topic_id)
        now = now or utcnow()
        cards = await self.cards.list_by_topic(topic_id)
        nodes = await self.nodes.list_by_topic(topic_id)
        due = [c for c in cards if c.due_at is None or c.due_at <= now]
        reviewed = [c for c in cards if c.review_count > 0]
        lapses = sum(c.lapse_count for c in cards)
        mastered = [n for n in nodes if n.mastery_level == "mastered"]
        weak_nodes = [n for n in nodes if n.mastery_level in ("vague", "unknown")]
        since = now - timedelta(days=7)
        reviews_7d = await self.reviews.list_since(topic_id, since)
        rating_counts: dict[str, int] = {}
        for r in reviews_7d:
            rating_counts[r.rating] = rating_counts.get(r.rating, 0) + 1
        return {
            "topic_id": topic_id,
            "topic_title": topic.title,
            "total_cards": len(cards),
            "due_today": len(due),
            "reviewed_cards": len(reviewed),
            "total_lapses": lapses,
            "total_nodes": len(nodes),
            "mastered_nodes": len(mastered),
            "weak_nodes": len(weak_nodes),
            "reviews_7d": len(reviews_7d),
            "rating_counts_7d": rating_counts,
        }

    async def weak_points(self, topic_id: int) -> list[dict]:
        """薄弱点：掌握度模糊/未会的知识节点 + 反复遗忘(lapse>0)的卡片。"""
        await self.get_topic(topic_id)
        nodes = await self.nodes.list_by_topic(topic_id)
        cards = await self.cards.list_by_topic(topic_id)
        out: list[dict] = []
        for n in nodes:
            if n.mastery_level in ("vague", "unknown"):
                out.append(
                    {
                        "kind": "node",
                        "id": n.id,
                        "title": n.title,
                        "summary": n.summary,
                        "mastery_level": n.mastery_level,
                    }
                )
        for c in cards:
            if c.lapse_count > 0:
                out.append(
                    {
                        "kind": "card",
                        "id": c.id,
                        "title": c.front,
                        "lapse_count": c.lapse_count,
                        "due_at": c.due_at.isoformat() if c.due_at else None,
                    }
                )
        return out

    async def wrong_answers(self, topic_id: int) -> list[dict]:
        """错题本：主题下所有批改为错误/部分错误的答题记录。"""
        await self.get_topic(topic_id)
        rows = await self.attempts.list_wrong_by_topic(topic_id)
        return [
            {
                "attempt_id": a.id,
                "quiz_id": q.id,
                "question": q.question,
                "reference_answer": q.answer,
                "explanation": q.explanation,
                "user_answer": a.user_answer,
                "result": a.result,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a, q in rows
        ]

    async def weekly_report(self, topic_id: int, now: datetime | None = None) -> dict:
        """生成主题学习周报 Markdown：汇 7 天复习/错题/薄弱 → LLM 生成。"""
        topic = await self.get_topic(topic_id)
        now = now or utcnow()
        since = now - timedelta(days=7)
        reviews = await self.reviews.list_since(topic_id, since)
        wrong = await self.wrong_answers(topic_id)
        weak = await self.weak_points(topic_id)
        rating_counts: dict[str, int] = {}
        for r in reviews:
            rating_counts[r.rating] = rating_counts.get(r.rating, 0) + 1
        stats = {
            "reviews_7d": len(reviews),
            "rating_counts": rating_counts,
            "wrong_count": len(wrong),
            "weak_count": len(weak),
        }
        context = self._build_report_context(topic, reviews, wrong, weak, stats)
        report_md = await self._llm_weekly_report(topic, context)
        return {"report_md": report_md, "stats": stats}

    def _build_report_context(
        self, topic, reviews, wrong, weak, stats: dict
    ) -> str:
        lines = [f"# 学习主题：{topic.title}", f"目标：{topic.goal or '（未指定）'}"]
        lines.append("\n## 近 7 天统计")
        lines.append(f"- 复习次数：{stats['reviews_7d']}")
        rc = stats["rating_counts"]
        lines.append(
            f"- 评分分布：忘记 {rc.get('again', 0)} / 模糊 {rc.get('hard', 0)} / "
            f"记得 {rc.get('good', 0)} / 熟练 {rc.get('easy', 0)}"
        )
        lines.append(f"- 错题数：{stats['wrong_count']}")
        lines.append(f"- 薄弱点数：{stats['weak_count']}")
        if weak:
            lines.append("\n## 薄弱知识点")
            for w in weak[:10]:
                lines.append(f"- [{w['kind']}] {w.get('title', '')}")
        if wrong:
            lines.append("\n## 近期错题（最多 10 条）")
            for item in wrong[:10]:
                lines.append(f"- {item['question']}")
        return "\n".join(lines)

    async def _llm_weekly_report(self, topic, context: str) -> str:
        provider = await self._get_provider()
        prompt = (
            "你是学习教练。基于下方学习统计数据，为用户生成一份简明的本周学习报告（Markdown）。"
            "包含：本周进展、薄弱点与建议、下周复习重点。语气鼓励、具体、可执行。"
            f"\n\n{context}"
        )
        try:
            return await provider.chat(
                [
                    {"role": "system", "content": "你输出 Markdown 格式的学习周报。"},
                    {"role": "user", "content": prompt},
                ]
            )
        except ProviderError as e:
            logger.warning("weekly_report LLM failed", error=str(e))
            return (
                f"## {topic.title} 学习周报\n\n"
                f"（LLM 生成失败，以下为原始统计）\n\n{context}"
            )

    async def review_context(self, topic_id: int, now: datetime | None = None) -> str:
        """供记忆候选抽取用的复习上下文文本（近 7 天复习 + 错题 + 薄弱）。"""
        topic = await self.get_topic(topic_id)
        now = now or utcnow()
        since = now - timedelta(days=7)
        reviews = await self.reviews.list_since(topic_id, since)
        wrong = await self.wrong_answers(topic_id)
        weak = await self.weak_points(topic_id)
        rating_counts: dict[str, int] = {}
        for r in reviews:
            rating_counts[r.rating] = rating_counts.get(r.rating, 0) + 1
        stats = {
            "reviews_7d": len(reviews),
            "rating_counts": rating_counts,
            "wrong_count": len(wrong),
            "weak_count": len(weak),
        }
        return self._build_report_context(topic, reviews, wrong, weak, stats)
