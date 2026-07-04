"""init schema: sessions / messages / documents / doc_chunks / settings

Revision ID: 0001
Revises:
Create Date: 2026-07-04

表结构对齐 docs/phase1-plan.md §4.2：utf8mb4 / utf8mb4_unicode_ci / InnoDB。
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- sessions ----
    op.create_table(
        "sessions",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("title", mysql.VARCHAR(255), nullable=False, server_default="新对话"),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_updated", "sessions", ["updated_at"])

    # ---- messages ----
    op.create_table(
        "messages",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("session_id", mysql.BIGINT(), nullable=False),
        sa.Column(
            "role",
            mysql.ENUM("user", "assistant", "system", name="message_role"),
            nullable=False,
        ),
        sa.Column("content", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], ondelete="CASCADE", name="fk_msg_session"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_session_time", "messages", ["session_id", "created_at"])

    # ---- documents ----
    op.create_table(
        "documents",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("name", mysql.VARCHAR(512), nullable=False),
        sa.Column("source_path", mysql.VARCHAR(1024), nullable=True),
        sa.Column("mime_type", mysql.VARCHAR(128), nullable=True),
        sa.Column("size_bytes", mysql.BIGINT(), nullable=True),
        sa.Column("content_hash", mysql.CHAR(64), nullable=True),
        sa.Column("embedding_model", mysql.VARCHAR(128), nullable=True),
        sa.Column("chunk_count", mysql.INTEGER(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            mysql.ENUM(
                "pending", "processing", "ready", "failed", "deleting", name="doc_status"
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error_message", mysql.TEXT(), nullable=True),
        sa.Column("indexed_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_doc_status", "documents", ["status"])
    op.create_index("idx_doc_hash", "documents", ["content_hash"])

    # ---- doc_chunks ----
    op.create_table(
        "doc_chunks",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("doc_id", mysql.BIGINT(), nullable=False),
        sa.Column("ordinal", mysql.INTEGER(), nullable=False),
        sa.Column("content", mysql.TEXT(), nullable=False),
        sa.Column("token_count", mysql.INTEGER(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["doc_id"], ["documents.id"], ondelete="CASCADE", name="fk_chunk_doc"
        ),
        sa.UniqueConstraint("doc_id", "ordinal", name="uk_doc_ordinal"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_chunk_doc", "doc_chunks", ["doc_id", "ordinal"])

    # ---- settings ----
    op.create_table(
        "settings",
        sa.Column("key", mysql.VARCHAR(128), primary_key=True),
        sa.Column("value", mysql.TEXT(), nullable=True),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_table("doc_chunks")
    op.drop_table("documents")
    op.drop_table("messages")
    op.drop_table("sessions")
