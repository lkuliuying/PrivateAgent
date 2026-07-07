"""学习复习路由（第四阶段 M2）。

- GET    /learning/reviews/today            今日到期复习卡片（可按主题过滤）
- POST   /learning/cards/{id}/review        提交卡片评分，SM-2 更新 due_at
- GET    /learning/topics/{id}/dashboard    主题学习仪表盘（卡片/复习/掌握度统计）
- GET    /learning/topics/{id}/weak-points  薄弱知识点 + 反复遗忘卡片
- GET    /learning/topics/{id}/wrong-answers 错题本（错误/部分错误答题）
- POST   /learning/topics/{id}/weekly-report 生成学习周报 Markdown
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.learning import LearningNotFound, LearningService

router = APIRouter(tags=["learning-reviews"])

ReviewRating = Literal["again", "hard", "good", "easy"]


# ---- Schemas ----


class ReviewRequest(BaseModel):
    rating: ReviewRating


class CardScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic_id: int
    node_id: int | None
    front: str
    back: str
    created_at: datetime
    due_at: datetime | None
    interval_days: int
    ease_factor: float
    review_count: int
    lapse_count: int


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    card_id: int
    topic_id: int
    rating: str
    previous_due_at: datetime | None
    next_due_at: datetime | None
    created_at: datetime


class ReviewResponse(BaseModel):
    card: CardScheduleOut
    review: ReviewOut


class DashboardOut(BaseModel):
    topic_id: int
    topic_title: str
    total_cards: int
    due_today: int
    reviewed_cards: int
    total_lapses: int
    total_nodes: int
    mastered_nodes: int
    weak_nodes: int
    reviews_7d: int
    rating_counts_7d: dict[str, int]


class WeakPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    id: int
    title: str
    summary: str | None = None
    mastery_level: str | None = None
    lapse_count: int | None = None
    due_at: str | None = None


class WrongAnswerOut(BaseModel):
    attempt_id: int
    quiz_id: int
    question: str
    reference_answer: str
    explanation: str | None
    user_answer: str | None
    result: str
    created_at: str | None


class WeeklyReportStats(BaseModel):
    reviews_7d: int
    rating_counts: dict[str, int]
    wrong_count: int
    weak_count: int


class WeeklyReportOut(BaseModel):
    report_md: str
    stats: WeeklyReportStats


# ---- Routes ----


@router.get("/learning/reviews/today", response_model=list[CardScheduleOut])
async def list_reviews_today(
    topic_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
):
    """今日到期复习卡片（due_at 为空或<=now）。不传 topic_id 则跨主题。"""
    try:
        return await LearningService(db).list_reviews_today(topic_id=topic_id)
    except LearningNotFound:
        raise HTTPException(404, "学习主题不存在")


@router.post("/learning/cards/{card_id}/review", response_model=ReviewResponse)
async def review_card(
    card_id: int, req: ReviewRequest, db: AsyncSession = Depends(get_session)
):
    """提交卡片评分：SM-2 调度更新 due_at/interval/ease，并写复习记录。"""
    try:
        return await LearningService(db).submit_card_review(card_id, req.rating)
    except LearningNotFound:
        raise HTTPException(404, "复习卡片不存在")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/learning/topics/{topic_id}/dashboard", response_model=DashboardOut)
async def topic_dashboard(topic_id: int, db: AsyncSession = Depends(get_session)):
    """主题学习仪表盘：卡片/复习/掌握度统计 + 近 7 天复习数。"""
    try:
        return await LearningService(db).topic_dashboard(topic_id)
    except LearningNotFound:
        raise HTTPException(404, "学习主题不存在")


@router.get(
    "/learning/topics/{topic_id}/weak-points", response_model=list[WeakPointOut]
)
async def weak_points(topic_id: int, db: AsyncSession = Depends(get_session)):
    """薄弱点：掌握度模糊/未会的节点 + 反复遗忘(lapse>0)的卡片。"""
    try:
        return await LearningService(db).weak_points(topic_id)
    except LearningNotFound:
        raise HTTPException(404, "学习主题不存在")


@router.get(
    "/learning/topics/{topic_id}/wrong-answers", response_model=list[WrongAnswerOut]
)
async def wrong_answers(topic_id: int, db: AsyncSession = Depends(get_session)):
    """错题本：主题下所有批改为错误/部分错误的答题记录。"""
    try:
        return await LearningService(db).wrong_answers(topic_id)
    except LearningNotFound:
        raise HTTPException(404, "学习主题不存在")


@router.post(
    "/learning/topics/{topic_id}/weekly-report", response_model=WeeklyReportOut
)
async def weekly_report(topic_id: int, db: AsyncSession = Depends(get_session)):
    """生成主题学习周报 Markdown（LLM 失败回退为原始统计）。"""
    try:
        return await LearningService(db).weekly_report(topic_id)
    except LearningNotFound:
        raise HTTPException(404, "学习主题不存在")
