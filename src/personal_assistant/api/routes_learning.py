"""学习系统路由（第三阶段 M3）。

- POST   /learning/topics              创建学习主题
- GET    /learning/topics              主题列表
- GET    /learning/topics/{id}         主题详情
- PATCH  /learning/topics/{id}         更新主题（title/goal/level/status/tags）
- POST   /learning/topics/{id}/plan    基于资料生成学习路线（节点）
- GET    /learning/topics/{id}/nodes   主题下知识节点
- POST   /learning/nodes/{id}/mastery  更新节点掌握程度
- POST   /learning/notes               保存学习笔记
- GET    /learning/notes               笔记列表（可按 topic 过滤）
- POST   /learning/topics/{id}/quizzes 生成练习题
- GET    /learning/topics/{id}/quizzes 主题练习题
- POST   /learning/quiz-attempts       提交答案并批改
- POST   /learning/topics/{id}/cards   生成复习卡片
- GET    /learning/topics/{id}/cards   主题复习卡片
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.learning import LearningNotFound, LearningService

router = APIRouter(tags=["learning"])


# ---- Schemas ----

class TopicCreate(BaseModel):
    title: str
    goal: str | None = None
    level: str | None = None
    tags: list[str] | None = None

    @field_validator("title")
    @classmethod
    def _check_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title 不能为空")
        return v[:255]


class TopicUpdate(BaseModel):
    title: str | None = None
    goal: str | None = None
    level: str | None = None
    status: str | None = None
    tags: list[str] | None = None


class TopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    goal: str | None
    level: str | None
    status: str
    tags_json: list | None
    created_at: datetime
    updated_at: datetime


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    topic_id: int
    parent_id: int | None
    title: str
    summary: str | None
    mastery_level: str | None
    order_index: int


class NoteCreate(BaseModel):
    topic_id: int | None = None
    title: str
    body_md: str
    source_refs: list | None = None


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    topic_id: int | None
    title: str
    body_md: str
    source_refs_json: list | None
    created_at: datetime
    updated_at: datetime


class GenerateRequest(BaseModel):
    source_doc_ids: list[int] | None = None
    count: int = 5


class QuizOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    topic_id: int
    node_id: int | None
    question: str
    answer: str
    explanation: str | None
    created_at: datetime


class AttemptRequest(BaseModel):
    quiz_id: int
    user_answer: str

    @field_validator("user_answer")
    @classmethod
    def _check_answer(cls, v: str) -> str:
        if v is None:
            return ""
        return v


class AttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    quiz_id: int
    user_answer: str | None
    result: str
    created_at: datetime


class GradeResponse(BaseModel):
    result: str
    explanation: str
    attempt: AttemptOut


class CardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    topic_id: int
    node_id: int | None
    front: str
    back: str
    created_at: datetime


class MasteryRequest(BaseModel):
    mastery: str

    @field_validator("mastery")
    @classmethod
    def _check(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("mastery 不能为空")
        return v[:32]


# ---- Routes ----

@router.get("/learning/topics", response_model=list[TopicOut])
async def list_topics(db: AsyncSession = Depends(get_session)):
    return await LearningService(db).list_topics()


@router.post("/learning/topics", response_model=TopicOut, status_code=201)
async def create_topic(req: TopicCreate, db: AsyncSession = Depends(get_session)):
    return await LearningService(db).create_topic(
        title=req.title, goal=req.goal, level=req.level, tags=req.tags
    )


@router.get("/learning/topics/{topic_id}", response_model=TopicOut)
async def get_topic(topic_id: int, db: AsyncSession = Depends(get_session)):
    try:
        return await LearningService(db).get_topic(topic_id)
    except LearningNotFound:
        raise HTTPException(404, "学习主题不存在")


@router.patch("/learning/topics/{topic_id}", response_model=TopicOut)
async def update_topic(
    topic_id: int, req: TopicUpdate, db: AsyncSession = Depends(get_session)
):
    svc = LearningService(db)
    try:
        await svc.get_topic(topic_id)
    except LearningNotFound:
        raise HTTPException(404, "学习主题不存在")
    await svc.update_topic(
        topic_id,
        title=req.title,
        goal=req.goal,
        level=req.level,
        status=req.status,
        tags=req.tags,
    )
    return await svc.get_topic(topic_id)


@router.post("/learning/topics/{topic_id}/plan", response_model=list[NodeOut])
async def generate_plan(
    topic_id: int, req: GenerateRequest, db: AsyncSession = Depends(get_session)
):
    try:
        return await LearningService(db).generate_plan(topic_id, req.source_doc_ids)
    except LearningNotFound:
        raise HTTPException(404, "学习主题不存在")


@router.get("/learning/topics/{topic_id}/nodes", response_model=list[NodeOut])
async def list_nodes(topic_id: int, db: AsyncSession = Depends(get_session)):
    try:
        return await LearningService(db).list_nodes(topic_id)
    except LearningNotFound:
        raise HTTPException(404, "学习主题不存在")


@router.post("/learning/nodes/{node_id}/mastery")
async def set_node_mastery(
    node_id: int, req: MasteryRequest, db: AsyncSession = Depends(get_session)
):
    try:
        await LearningService(db).set_node_mastery(node_id, req.mastery)
    except LearningNotFound:
        raise HTTPException(404, "知识节点不存在")
    return {"ok": True, "node_id": node_id, "mastery": req.mastery}


@router.post("/learning/notes", response_model=NoteOut, status_code=201)
async def save_note(req: NoteCreate, db: AsyncSession = Depends(get_session)):
    try:
        return await LearningService(db).save_note(
            topic_id=req.topic_id,
            title=req.title,
            body_md=req.body_md,
            source_refs=req.source_refs,
        )
    except LearningNotFound:
        raise HTTPException(404, "学习主题不存在")


@router.get("/learning/notes", response_model=list[NoteOut])
async def list_notes(
    topic_id: int | None = Query(default=None), db: AsyncSession = Depends(get_session)
):
    return await LearningService(db).list_notes(topic_id)


@router.post("/learning/topics/{topic_id}/quizzes", response_model=list[QuizOut])
async def generate_quiz(
    topic_id: int, req: GenerateRequest, db: AsyncSession = Depends(get_session)
):
    try:
        return await LearningService(db).generate_quiz(
            topic_id, req.source_doc_ids, count=req.count
        )
    except LearningNotFound:
        raise HTTPException(404, "学习主题不存在")


@router.get("/learning/topics/{topic_id}/quizzes", response_model=list[QuizOut])
async def list_quizzes(topic_id: int, db: AsyncSession = Depends(get_session)):
    try:
        return await LearningService(db).list_quizzes(topic_id)
    except LearningNotFound:
        raise HTTPException(404, "学习主题不存在")


@router.post("/learning/quiz-attempts", response_model=GradeResponse)
async def grade_attempt(req: AttemptRequest, db: AsyncSession = Depends(get_session)):
    try:
        grade = await LearningService(db).grade_attempt(req.quiz_id, req.user_answer)
    except LearningNotFound:
        raise HTTPException(404, "练习题不存在")
    # 取最新一条 attempt 返回
    attempts = await LearningService(db).attempts.list_by_quiz(req.quiz_id)
    latest = attempts[0] if attempts else None
    return GradeResponse(
        result=grade.result,
        explanation=grade.explanation,
        attempt=AttemptOut.model_validate(latest) if latest else None,  # type: ignore[arg-type]
    )


@router.post("/learning/topics/{topic_id}/cards", response_model=list[CardOut])
async def generate_cards(
    topic_id: int, req: GenerateRequest, db: AsyncSession = Depends(get_session)
):
    try:
        return await LearningService(db).create_cards(
            topic_id, req.source_doc_ids, count=req.count
        )
    except LearningNotFound:
        raise HTTPException(404, "学习主题不存在")


@router.get("/learning/topics/{topic_id}/cards", response_model=list[CardOut])
async def list_cards(topic_id: int, db: AsyncSession = Depends(get_session)):
    try:
        return await LearningService(db).list_cards(topic_id)
    except LearningNotFound:
        raise HTTPException(404, "学习主题不存在")
