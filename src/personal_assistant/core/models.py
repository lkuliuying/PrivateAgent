"""SQLAlchemy ORM 模型，对应 MySQL 5 张业务表。

表结构遵循 ``docs/phase1-plan.md`` §4.2：
字符集 utf8mb4 / utf8mb4_unicode_ci，InnoDB，主键 BIGINT 自增。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.mysql import (
    BIGINT,
    BOOLEAN,
    CHAR,
    DATETIME,
    ENUM,
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
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    __table_args__ = (Index("idx_learning_card_topic", "topic_id"),)


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
            "planned",
            "waiting_approval",
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
