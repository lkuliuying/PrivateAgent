"""SQLAlchemy ORM 模型，对应 MySQL 5 张业务表。

表结构遵循 ``docs/phase1-plan.md`` §4.2：
字符集 utf8mb4 / utf8mb4_unicode_ci，InnoDB，主键 BIGINT 自增。
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.mysql import (
    BIGINT,
    BOOLEAN,
    CHAR,
    DATE,
    DATETIME,
    ENUM,
    FLOAT,
    INTEGER,
    JSON,
    MEDIUMTEXT,
    TEXT,
    VARCHAR,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ChatSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(
        VARCHAR(255), nullable=False, default="新对话", server_default="新对话"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_updated", "updated_at"),)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        ENUM("user", "assistant", "system", name="message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    session: Mapped[ChatSession] = relationship(back_populates="messages")

    __table_args__ = (Index("idx_session_time", "session_id", "created_at"),)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(VARCHAR(512), nullable=False)
    source_path: Mapped[str | None] = mapped_column(VARCHAR(1024), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(VARCHAR(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(VARCHAR(128), nullable=True)
    chunk_count: Mapped[int] = mapped_column(
        INTEGER, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        ENUM("pending", "processing", "ready", "failed", "deleting", name="doc_status"),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    error_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    # 第二阶段 §4.2：启用/禁用，参与 RAG 检索过滤；last_error_at 记录最近失败时间。
    enabled: Mapped[bool] = mapped_column(
        BOOLEAN, nullable=False, default=True, server_default="1"
    )
    last_error_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    # 第三阶段 §4.5：元数据，供 M2 混合检索按 doc_type/topic/tags/language/project 过滤。
    doc_type: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)
    topic: Mapped[str | None] = mapped_column(VARCHAR(255), nullable=True)
    tags_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    language: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)
    project_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )

    chunks: Mapped[list["DocChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_doc_status", "status"),
        Index("idx_doc_hash", "content_hash"),
        Index("idx_doc_type", "doc_type"),
        Index("idx_doc_project", "project_id"),
    )


class DocChunk(Base):
    __tablename__ = "doc_chunks"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    doc_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(INTEGER, nullable=False)
    content: Mapped[str] = mapped_column(TEXT, nullable=False)
    token_count: Mapped[int | None] = mapped_column(INTEGER, nullable=True)
    # 第三阶段 §4.5：heading 供引用展示；keywords_json/bm25_text 供 M2 关键词召回（预留）。
    heading: Mapped[str | None] = mapped_column(VARCHAR(512), nullable=True)
    keywords_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    bm25_text: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("doc_id", "ordinal", name="uk_doc_ordinal"),
        Index("idx_chunk_doc", "doc_id", "ordinal"),
    )


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(VARCHAR(128), primary_key=True)
    value: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )


# ============================================================================
# 第二阶段：工具调用 / 授权路径 / 活动流
# ============================================================================


class ToolCall(Base):
    """工具调用记录：审批状态机 + 输入输出 + 审计。"""

    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    session_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True
    )
    task_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    step_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    tool_name: Mapped[str] = mapped_column(VARCHAR(128), nullable=False)
    risk_level: Mapped[str] = mapped_column(
        ENUM("safe", "confirm", "restricted", name="risk_level_enum"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        ENUM(
            "pending_approval",
            "approved",
            "rejected",
            "running",
            "succeeded",
            "failed",
            "cancelled",
            name="tool_call_status",
        ),
        nullable=False,
        default="pending_approval",
        server_default="pending_approval",
    )
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )

    __table_args__ = (
        Index("idx_tool_session", "session_id", "created_at"),
        Index("idx_tool_task", "task_id", "step_id"),
        Index("idx_tool_status", "status"),
    )


class TrustedPath(Base):
    """用户授权过的本地文件/目录路径，工具只能访问这些路径。"""

    __tablename__ = "trusted_paths"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    # VARCHAR(2048) 支持长路径；不加 DB UNIQUE（utf8mb4 下超 3072 字节键长限制），
    # 去重由 TrustedPathRepository.authorize 在应用层保证（先 get_by_path 再插入）。
    path: Mapped[str] = mapped_column(VARCHAR(2048), nullable=False)
    kind: Mapped[str] = mapped_column(
        ENUM("file", "directory", name="trusted_path_kind"), nullable=False
    )
    granted_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )


class Activity(Base):
    """活动流：聚合工具调用 / 文档导入 / 索引任务，供活动页展示。"""

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    session_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(
        ENUM(
            "tool",
            "document_import",
            "reindex",
            "system",
            name="activity_kind",
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    status: Mapped[str] = mapped_column(
        ENUM(
            "pending",
            "waiting_approval",
            "running",
            "succeeded",
            "failed",
            "cancelled",
            name="activity_status",
        ),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    ref_type: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)
    ref_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    detail_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )

    __table_args__ = (
        Index("idx_activity_session", "session_id", "created_at"),
        Index("idx_activity_status", "status"),
    )


# ============================================================================
# 第三阶段：项目工作区 / 学习系统
# ============================================================================


class Project(Base):
    """用户授权的代码项目目录。root_path 同步授权到 trusted_paths。"""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    root_path: Mapped[str] = mapped_column(VARCHAR(2048), nullable=False)
    language: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)
    framework: Mapped[str | None] = mapped_column(VARCHAR(128), nullable=True)
    status: Mapped[str] = mapped_column(
        ENUM("active", "archived", name="project_status_enum"),
        nullable=False,
        default="active",
        server_default="active",
    )
    last_scanned_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )

    files: Mapped[list["ProjectFile"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_project_status", "status"),)


class ProjectFile(Base):
    """项目文件索引：扫描时写入，供目录树/搜索/读取使用。"""

    __tablename__ = "project_files"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    rel_path: Mapped[str] = mapped_column(VARCHAR(2048), nullable=False)
    language: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    mtime: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    is_binary: Mapped[bool] = mapped_column(
        BOOLEAN, nullable=False, default=False, server_default="0"
    )
    indexed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)

    project: Mapped[Project] = relationship(back_populates="files")

    __table_args__ = (
        Index("idx_project_files_project", "project_id"),
        # 唯一键（rel_path 前缀 384）防重复扫描入库；前缀长度在迁移里用 mysql_length 指定。
        UniqueConstraint("project_id", "rel_path", name="uk_project_file"),
    )


class LearningTopic(Base):
    """学习主题：围绕一个长期学习目标（如「操作系统」）。"""

    __tablename__ = "learning_topics"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    goal: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    level: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)
    status: Mapped[str] = mapped_column(
        ENUM(
            "active", "paused", "completed", "archived", name="learning_topic_status_enum"
        ),
        nullable=False,
        default="active",
        server_default="active",
    )
    tags_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )

    nodes: Mapped[list["LearningNode"]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )
    notes: Mapped[list["LearningNote"]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_learning_topic_status", "status"),)


class LearningNode(Base):
    """知识节点：学习路线上的一个知识点，可挂父节点形成树。"""

    __tablename__ = "learning_nodes"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("learning_topics.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    mastery_level: Mapped[str | None] = mapped_column(VARCHAR(32), nullable=True)
    order_index: Mapped[int] = mapped_column(INTEGER, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    topic: Mapped[LearningTopic] = relationship(back_populates="nodes")

    __table_args__ = (
        Index("idx_learning_node_topic", "topic_id", "order_index"),
        Index("idx_learning_node_parent", "parent_id"),
    )


class LearningNote(Base):
    """学习笔记：可从对话沉淀，关联主题与来源引用。"""

    __tablename__ = "learning_notes"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    topic_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("learning_topics.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    body_md: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    source_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )

    topic: Mapped[LearningTopic | None] = relationship(back_populates="notes")

    __table_args__ = (Index("idx_learning_notes_topic", "topic_id"),)


class LearningCard(Base):
    """复习卡片：正面提问、背面答案。"""

    __tablename__ = "learning_cards"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("learning_topics.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("learning_nodes.id", ondelete="CASCADE"), nullable=True
    )
    front: Mapped[str] = mapped_column(TEXT, nullable=False)
    back: Mapped[str] = mapped_column(TEXT, nullable=False)
    # 第四阶段 M0：间隔重复调度字段（SM-2）。
    due_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    interval_days: Mapped[int] = mapped_column(INTEGER, nullable=False, default=0, server_default="0")
    ease_factor: Mapped[float] = mapped_column(FLOAT, nullable=False, default=2.5, server_default="2.5")
    review_count: Mapped[int] = mapped_column(INTEGER, nullable=False, default=0, server_default="0")
    lapse_count: Mapped[int] = mapped_column(INTEGER, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    __table_args__ = (
        Index("idx_learning_card_topic", "topic_id"),
        Index("idx_learning_card_due", "topic_id", "due_at"),
    )


class LearningQuiz(Base):
    """练习题：题干、参考答案、解析。"""

    __tablename__ = "learning_quizzes"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("learning_topics.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("learning_nodes.id", ondelete="CASCADE"), nullable=True
    )
    question: Mapped[str] = mapped_column(TEXT, nullable=False)
    answer: Mapped[str] = mapped_column(TEXT, nullable=False)
    explanation: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    __table_args__ = (Index("idx_learning_quiz_topic", "topic_id"),)


class LearningQuizAttempt(Base):
    """答题记录：用户答案与批改结果。"""

    __tablename__ = "learning_quiz_attempts"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    quiz_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("learning_quizzes.id", ondelete="CASCADE"), nullable=False
    )
    user_answer: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    result: Mapped[str] = mapped_column(
        ENUM("correct", "partial", "wrong", name="learning_quiz_result_enum"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    __table_args__ = (Index("idx_learning_attempt_quiz", "quiz_id"),)


# ============================================================================
# 第三阶段 M6：多步任务编排
# ============================================================================


class AgentTask(Base):
    """可观察的多步 Agent 任务。"""

    __tablename__ = "agent_tasks"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    session_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    goal: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    status: Mapped[str] = mapped_column(
        ENUM(
            "plan_draft",
            "plan_approved",
            "planned",
            "waiting_approval",
            "paused",
            "running",
            "succeeded",
            "failed",
            "cancelled",
            name="agent_task_status_enum",
        ),
        nullable=False,
        default="planned",
        server_default="planned",
    )
    plan_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    final_report_md: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )

    steps: Mapped[list["AgentTaskStep"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    evidence: Mapped[list["AgentEvidence"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_agent_task_session", "session_id", "created_at"),
        Index("idx_agent_task_status", "status"),
    )


class AgentTaskStep(Base):
    """任务中的一个可执行步骤，通常关联一个 tool_call。"""

    __tablename__ = "agent_task_steps"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(INTEGER, nullable=False)
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(VARCHAR(128), nullable=True)
    status: Mapped[str] = mapped_column(
        ENUM(
            "planned",
            "waiting_approval",
            "running",
            "succeeded",
            "failed",
            "skipped",
            "cancelled",
            name="agent_step_status_enum",
        ),
        nullable=False,
        default="planned",
        server_default="planned",
    )
    tool_call_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    task: Mapped[AgentTask] = relationship(back_populates="steps")
    evidence: Mapped[list["AgentEvidence"]] = relationship(
        back_populates="step", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("task_id", "ordinal", name="uk_agent_step_ordinal"),
        Index("idx_agent_step_task", "task_id", "ordinal"),
        Index("idx_agent_step_status", "status"),
    )


class AgentEvidence(Base):
    """任务证据：每一步的输入、输出、错误或人工可复制的 Markdown 摘要。"""

    __tablename__ = "agent_evidence"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("agent_task_steps.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(
        ENUM("tool_output", "error", "note", "report", name="agent_evidence_kind_enum"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    content_md: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    task: Mapped[AgentTask] = relationship(back_populates="evidence")
    step: Mapped[AgentTaskStep | None] = relationship(back_populates="evidence")

    __table_args__ = (
        Index("idx_agent_evidence_task", "task_id", "created_at"),
        Index("idx_agent_evidence_step", "step_id"),
    )


# ============================================================================
# 第四阶段 M0：个人工作流（记忆 / 复习 / 补丁集 / 集合 / 抽取）
# ============================================================================


class MemoryItem(Base):
    """长期记忆：偏好/学习/项目/文档/工作流/笔记，可被检索与沉淀。"""

    __tablename__ = "memory_items"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(
        ENUM(
            "preference",
            "learning",
            "project",
            "document",
            "workflow",
            "note",
            name="memory_kind_enum",
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    content_md: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    summary: Mapped[str | None] = mapped_column(VARCHAR(1024), nullable=True)
    source_type: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)
    source_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    # 跨域软引用：不建外键，避免与 projects/learning_topics 循环依赖。
    project_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    topic_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    tags_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(FLOAT, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        BOOLEAN, nullable=False, default=True, server_default="1"
    )
    sensitive: Mapped[bool] = mapped_column(
        BOOLEAN, nullable=False, default=False, server_default="0"
    )
    # 第四阶段 M1：记忆生命周期。draft=候选待确认 / confirmed=已确认 / archived=已归档。
    # 与 enabled（运行时禁用开关）正交：检索默认取 status='confirmed' AND enabled=True。
    status: Mapped[str] = mapped_column(
        ENUM("draft", "confirmed", "archived", name="memory_status_enum"),
        nullable=False,
        default="confirmed",
        server_default="confirmed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )

    events: Mapped[list["MemoryEvent"]] = relationship(
        back_populates="memory", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_memory_kind_enabled", "kind", "enabled"),
        Index("idx_memory_project", "project_id"),
        Index("idx_memory_topic", "topic_id"),
        Index("idx_memory_status", "status", "enabled"),
    )


class MemoryEvent(Base):
    """记忆事件流：创建/使用/编辑/禁用/删除等操作审计。"""

    __tablename__ = "memory_events"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    memory_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("memory_items.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(
        ENUM(
            "created",
            "used",
            "edited",
            "disabled",
            "deleted",
            name="memory_event_type_enum",
        ),
        nullable=False,
    )
    ref_type: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)
    ref_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    detail_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    memory: Mapped[MemoryItem] = relationship(back_populates="events")

    __table_args__ = (Index("idx_memory_event_memory", "memory_id", "created_at"),)


class LearningReview(Base):
    """复习记录：rating 驱动 SM-2 调度，更新所属卡片的 due_at/interval/ease。"""

    __tablename__ = "learning_reviews"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    card_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("learning_cards.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("learning_topics.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[str] = mapped_column(
        ENUM("again", "hard", "good", "easy", name="learning_review_rating_enum"),
        nullable=False,
    )
    previous_due_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    next_due_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    __table_args__ = (
        Index("idx_review_topic_time", "topic_id", "created_at"),
        Index("idx_review_card_time", "card_id", "created_at"),
    )


class ProjectCommandProfile(Base):
    """项目命令模板：test/build/lint/format/typecheck/custom，供任务编排复用。"""

    __tablename__ = "project_command_profiles"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    # 跨域软引用：projects 表在另一域，不建外键。
    project_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    name: Mapped[str] = mapped_column(VARCHAR(128), nullable=False)
    command_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    kind: Mapped[str] = mapped_column(
        ENUM(
            "test",
            "build",
            "lint",
            "format",
            "typecheck",
            "custom",
            name="command_profile_kind_enum",
        ),
        nullable=False,
    )
    timeout_seconds: Mapped[int] = mapped_column(
        INTEGER, nullable=False, default=120, server_default="120"
    )
    enabled: Mapped[bool] = mapped_column(
        BOOLEAN, nullable=False, default=True, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    __table_args__ = (Index("idx_command_profile_project", "project_id", "enabled"),)


class PatchSet(Base):
    """补丁集：一组文件级变更，带审批/应用/回滚状态机。"""

    __tablename__ = "patch_sets"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    # 跨域软引用：projects / agent_tasks 在另一域，不建外键。
    project_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    task_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    status: Mapped[str] = mapped_column(
        ENUM(
            "draft",
            "waiting_approval",
            "applied",
            "rejected",
            "rolled_back",
            name="patch_set_status_enum",
        ),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )

    files: Mapped[list["PatchFile"]] = relationship(
        back_populates="patch_set", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_patch_set_project", "project_id", "created_at"),)


class PatchFile(Base):
    """补丁集中单个文件的变更：diff + 旧/新内容与 sha256。"""

    __tablename__ = "patch_files"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    patch_set_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("patch_sets.id", ondelete="CASCADE"), nullable=False
    )
    rel_path: Mapped[str] = mapped_column(VARCHAR(2048), nullable=False)
    old_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    new_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    diff_text: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    old_content: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    new_content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    status: Mapped[str] = mapped_column(
        ENUM(
            "draft",
            "applied",
            "rejected",
            "rolled_back",
            name="patch_file_status_enum",
        ),
        nullable=False,
        default="draft",
        server_default="draft",
    )

    patch_set: Mapped[PatchSet] = relationship(back_populates="files")

    __table_args__ = (Index("idx_patch_file_set", "patch_set_id"),)


class DocumentCollection(Base):
    """文档集合：围绕一个目标聚合多篇文档，供抽取与检索。"""

    __tablename__ = "document_collections"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    goal: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    tags_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )

    items: Mapped[list["DocumentCollectionItem"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )


class DocumentCollectionItem(Base):
    """集合成员：doc_id 软引用 documents，order_index 决定展示顺序。"""

    __tablename__ = "document_collection_items"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("document_collections.id", ondelete="CASCADE"), nullable=False
    )
    # 跨域软引用：documents 在另一域，不建外键。
    doc_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    order_index: Mapped[int] = mapped_column(
        INTEGER, nullable=False, default=0, server_default="0"
    )

    collection: Mapped[DocumentCollection] = relationship(back_populates="items")

    __table_args__ = (UniqueConstraint("collection_id", "doc_id", name="uk_collection_doc"),)


class DocumentExtraction(Base):
    """文档/集合的结构化抽取：术语/表格摘要/行动项/论断/代码/模板报告。"""

    __tablename__ = "document_extractions"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    # 跨域软引用：documents / document_collections 在另一域，不建外键。
    doc_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    collection_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    kind: Mapped[str] = mapped_column(
        ENUM(
            "terms",
            "table_summary",
            "actions",
            "claims",
            "code",
            "template_report",
            name="extraction_kind_enum",
        ),
        nullable=False,
    )
    content_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content_md: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    source_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    __table_args__ = (
        Index("idx_extraction_doc", "doc_id", "kind"),
        Index("idx_extraction_collection", "collection_id", "kind"),
    )


# ============================================================================
# 第六阶段 M1：主动个人中枢（收件箱 / 提醒 / 目标 / 简报 / 隐私审计）
# ============================================================================


class InboxItem(Base):
    """统一收件箱：聚合聊天/任务/学习/活动/记忆等待处理项。

    source_type/source_id 指向来源对象（软引用，不建外键）；
    target_type/target_id 指向转化后的目标（reminder/agent_task/memory 等）。
    完成/归档不删除原始对象，只改 inbox 自身状态。
    """

    __tablename__ = "inbox_items"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    body_md: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    item_type: Mapped[str] = mapped_column(
        ENUM(
            "todo",
            "reminder",
            "review",
            "approval",
            "failure",
            "memory",
            "note",
            "system",
            name="inbox_item_type_enum",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        ENUM("open", "snoozed", "done", "ignored", "archived", name="inbox_item_status_enum"),
        nullable=False,
        default="open",
        server_default="open",
    )
    priority: Mapped[str] = mapped_column(
        ENUM("low", "normal", "high", "urgent", name="inbox_item_priority_enum"),
        nullable=False,
        default="normal",
        server_default="normal",
    )
    due_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    source_type: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)
    source_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    target_type: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)
    target_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )
    handled_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)

    __table_args__ = (
        Index("idx_inbox_status_due", "status", "due_at"),
        Index("idx_inbox_source", "source_type", "source_id"),
    )


class Reminder(Base):
    """通用提醒：一次性/重复。next_fire_at 由 due_at 初始化，tick 扫描驱动。"""

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    body_md: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    status: Mapped[str] = mapped_column(
        ENUM("active", "snoozed", "done", "cancelled", name="reminder_status_enum"),
        nullable=False,
        default="active",
        server_default="active",
    )
    due_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False)
    # 轻量重复规则 JSON：{freq: none/daily/weekly/monthly, interval: N, ...}。
    recurrence_rule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    next_fire_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    source_type: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)
    source_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )

    __table_args__ = (
        Index("idx_reminder_next", "status", "next_fire_at"),
        Index("idx_reminder_source", "source_type", "source_id"),
    )


class PersonalGoal(Base):
    """跨模块长期目标：关联学习主题/项目/任务/文档集合，支持 check-in 与周回顾。"""

    __tablename__ = "personal_goals"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    description: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    domain: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, default="custom", server_default="custom"
    )
    status: Mapped[str] = mapped_column(
        ENUM("active", "paused", "done", "archived", name="personal_goal_status_enum"),
        nullable=False,
        default="active",
        server_default="active",
    )
    priority: Mapped[str] = mapped_column(
        ENUM("low", "normal", "high", name="personal_goal_priority_enum"),
        nullable=False,
        default="normal",
        server_default="normal",
    )
    start_date: Mapped[date | None] = mapped_column(DATE, nullable=True)
    target_date: Mapped[date | None] = mapped_column(DATE, nullable=True)
    success_criteria_md: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )

    __table_args__ = (Index("idx_goal_status", "status", "priority"),)


class GoalLink(Base):
    """目标关联对象：target_type/target_id 软引用 learning_topic/project/agent_task/collection。

    relation：supports/blocks/evidence/result。同域 goal_id 亦不建 FK CASCADE，
    遵循「不自动级联删除用户数据」。
    """

    __tablename__ = "goal_links"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    target_type: Mapped[str] = mapped_column(VARCHAR(64), nullable=False)
    target_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    relation: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, default="supports", server_default="supports"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    __table_args__ = (
        UniqueConstraint(
            "goal_id", "target_type", "target_id", "relation", name="uk_goal_target"
        ),
        Index("idx_goal_links_goal", "goal_id"),
    )


class GoalCheckin(Base):
    """目标回顾：进度笔记、信心度、阻塞项、下一步。供周回顾引用。"""

    __tablename__ = "goal_checkins"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    checkin_date: Mapped[date] = mapped_column(DATE, nullable=False)
    progress_note_md: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    confidence: Mapped[float | None] = mapped_column(FLOAT, nullable=True)
    blockers_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    next_actions_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    __table_args__ = (Index("idx_goal_checkins_goal_date", "goal_id", "checkin_date"),)


class Briefing(Base):
    """主动简报：today/weekly/learning/project/goal。sources_json 只存摘要与 id。"""

    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(
        ENUM(
            "today",
            "weekly",
            "learning",
            "project",
            "goal",
            name="briefing_kind_enum",
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    body_md: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    sources_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    __table_args__ = (Index("idx_briefing_kind_time", "kind", "created_at"),)


class ProviderCallAudit(Base):
    """远程 Provider 请求级审计：只存类别与估算大小，不存完整 prompt。"""

    __tablename__ = "provider_call_audits"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    provider_type: Mapped[str] = mapped_column(VARCHAR(64), nullable=False)
    model: Mapped[str | None] = mapped_column(VARCHAR(255), nullable=True)
    purpose: Mapped[str] = mapped_column(VARCHAR(64), nullable=False)
    remote: Mapped[bool] = mapped_column(
        BOOLEAN, nullable=False, default=False, server_default="0"
    )
    context_types_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    estimated_input_chars: Mapped[int | None] = mapped_column(INTEGER, nullable=True)
    estimated_output_chars: Mapped[int | None] = mapped_column(INTEGER, nullable=True)
    status: Mapped[str] = mapped_column(
        ENUM(
            "planned",
            "sent",
            "succeeded",
            "failed",
            "cancelled",
            name="provider_audit_status_enum",
        ),
        nullable=False,
        default="planned",
        server_default="planned",
    )
    error_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)

    __table_args__ = (
        Index("idx_provider_audit_time", "created_at"),
        Index("idx_provider_audit_remote", "remote", "created_at"),
    )
