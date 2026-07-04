"""SQLAlchemy ORM 模型，对应 MySQL 5 张业务表。

表结构遵循 ``docs/phase1-plan.md`` §4.2：
字符集 utf8mb4 / utf8mb4_unicode_ci，InnoDB，主键 BIGINT 自增。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.mysql import (
    BIGINT,
    CHAR,
    DATETIME,
    ENUM,
    INTEGER,
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
