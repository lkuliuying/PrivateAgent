"""phase3 core: projects / project_files / learning_* + documents/doc_chunks 元数据增强

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-05

对齐 docs/archive/phases/phase3-plan.md §4 与 docs/archive/phases/phase3-requirements.md §5（M0–M4 范围）：
- projects / project_files：项目授权与文件索引。
- learning_topics / learning_nodes / learning_notes / learning_cards / learning_quizzes / learning_quiz_attempts：学习系统。
- documents 增列：doc_type / topic / tags_json / language / project_id（M2 元数据过滤）。
- doc_chunks 增列：heading / keywords_json / bm25_text（M2 关键词召回与命中展示）。
不建 agent_tasks 等表（M6 出本次范围）。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- projects ----
    op.create_table(
        "projects",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("name", mysql.VARCHAR(255), nullable=False),
        sa.Column("root_path", mysql.VARCHAR(2048), nullable=False),
        sa.Column("language", mysql.VARCHAR(64), nullable=True),
        sa.Column("framework", mysql.VARCHAR(128), nullable=True),
        sa.Column(
            "status",
            mysql.ENUM("active", "archived", name="project_status_enum"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("last_scanned_at", mysql.DATETIME(fsp=3), nullable=True),
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
    op.create_index("idx_project_status", "projects", ["status"])
    # root_path 不加 UNIQUE（VARCHAR(2048) 在 utf8mb4 下超 3072 字节键长限制），
    # 去重由应用层 ProjectRepository.authorize 保证（先按 root_path 查再插）。

    # ---- project_files ----
    op.create_table(
        "project_files",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("project_id", mysql.BIGINT(), nullable=False),
        sa.Column("rel_path", mysql.VARCHAR(2048), nullable=False),
        sa.Column("language", mysql.VARCHAR(64), nullable=True),
        sa.Column("size_bytes", mysql.BIGINT(), nullable=True),
        sa.Column("content_hash", mysql.CHAR(64), nullable=True),
        sa.Column("mtime", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "is_binary",
            mysql.BOOLEAN(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("indexed_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE", name="fk_projectfile_project"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_project_files_project", "project_files", ["project_id"])
    # 唯一键防重复扫描入库：rel_path 用前缀长度 384（384*4=1536 字节 + BIGINT 8 < 3072 限），
    # 相对路径罕有超 384 字符；mysql_length 指定前缀长度。
    op.create_index(
        "uk_project_file",
        "project_files",
        ["project_id", "rel_path"],
        unique=True,
        mysql_length={"rel_path": 384},
    )

    # ---- learning_topics ----
    op.create_table(
        "learning_topics",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column("goal", mysql.TEXT(), nullable=True),
        sa.Column("level", mysql.VARCHAR(64), nullable=True),
        sa.Column(
            "status",
            mysql.ENUM(
                "active", "paused", "completed", "archived", name="learning_topic_status_enum"
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column("tags_json", mysql.JSON(), nullable=True),
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
    op.create_index("idx_learning_topic_status", "learning_topics", ["status"])

    # ---- learning_nodes ----
    op.create_table(
        "learning_nodes",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("topic_id", mysql.BIGINT(), nullable=False),
        sa.Column("parent_id", mysql.BIGINT(), nullable=True),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column("summary", mysql.TEXT(), nullable=True),
        # mastery_level 用 VARCHAR 而非 ENUM：LLM/用户可赋「掌握/模糊/不会」等灵活标签。
        sa.Column("mastery_level", mysql.VARCHAR(32), nullable=True),
        sa.Column("order_index", mysql.INTEGER(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"], ["learning_topics.id"], ondelete="CASCADE", name="fk_node_topic"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_learning_node_topic", "learning_nodes", ["topic_id", "order_index"])
    op.create_index("idx_learning_node_parent", "learning_nodes", ["parent_id"])

    # ---- learning_notes ----
    op.create_table(
        "learning_notes",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("topic_id", mysql.BIGINT(), nullable=True),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column("body_md", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("source_refs_json", mysql.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["topic_id"], ["learning_topics.id"], ondelete="CASCADE", name="fk_note_topic"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_learning_notes_topic", "learning_notes", ["topic_id"])

    # ---- learning_cards ----
    op.create_table(
        "learning_cards",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("topic_id", mysql.BIGINT(), nullable=False),
        sa.Column("node_id", mysql.BIGINT(), nullable=True),
        sa.Column("front", mysql.TEXT(), nullable=False),
        sa.Column("back", mysql.TEXT(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"], ["learning_topics.id"], ondelete="CASCADE", name="fk_card_topic"
        ),
        sa.ForeignKeyConstraint(
            ["node_id"], ["learning_nodes.id"], ondelete="CASCADE", name="fk_card_node"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_learning_card_topic", "learning_cards", ["topic_id"])

    # ---- learning_quizzes ----
    op.create_table(
        "learning_quizzes",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("topic_id", mysql.BIGINT(), nullable=False),
        sa.Column("node_id", mysql.BIGINT(), nullable=True),
        sa.Column("question", mysql.TEXT(), nullable=False),
        sa.Column("answer", mysql.TEXT(), nullable=False),
        sa.Column("explanation", mysql.TEXT(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"], ["learning_topics.id"], ondelete="CASCADE", name="fk_quiz_topic"
        ),
        sa.ForeignKeyConstraint(
            ["node_id"], ["learning_nodes.id"], ondelete="CASCADE", name="fk_quiz_node"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_learning_quiz_topic", "learning_quizzes", ["topic_id"])

    # ---- learning_quiz_attempts ----
    op.create_table(
        "learning_quiz_attempts",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("quiz_id", mysql.BIGINT(), nullable=False),
        sa.Column("user_answer", mysql.TEXT(), nullable=True),
        sa.Column(
            "result",
            mysql.ENUM("correct", "partial", "wrong", name="learning_quiz_result_enum"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["quiz_id"], ["learning_quizzes.id"], ondelete="CASCADE", name="fk_attempt_quiz"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_learning_attempt_quiz", "learning_quiz_attempts", ["quiz_id"])

    # ---- documents 元数据增强（M2 过滤）----
    op.add_column("documents", sa.Column("doc_type", mysql.VARCHAR(64), nullable=True))
    op.add_column("documents", sa.Column("topic", mysql.VARCHAR(255), nullable=True))
    op.add_column("documents", sa.Column("tags_json", mysql.JSON(), nullable=True))
    op.add_column("documents", sa.Column("language", mysql.VARCHAR(64), nullable=True))
    op.add_column("documents", sa.Column("project_id", mysql.BIGINT(), nullable=True))
    op.create_index("idx_doc_type", "documents", ["doc_type"])
    op.create_index("idx_doc_project", "documents", ["project_id"])

    # ---- doc_chunks 增列（M2 关键词召回与命中展示）----
    op.add_column("doc_chunks", sa.Column("heading", mysql.VARCHAR(512), nullable=True))
    op.add_column("doc_chunks", sa.Column("keywords_json", mysql.JSON(), nullable=True))
    op.add_column("doc_chunks", sa.Column("bm25_text", mysql.MEDIUMTEXT(), nullable=True))


def downgrade() -> None:
    # doc_chunks
    op.drop_column("doc_chunks", "bm25_text")
    op.drop_column("doc_chunks", "keywords_json")
    op.drop_column("doc_chunks", "heading")
    # documents
    op.drop_index("idx_doc_project", table_name="documents")
    op.drop_index("idx_doc_type", table_name="documents")
    op.drop_column("documents", "project_id")
    op.drop_column("documents", "language")
    op.drop_column("documents", "tags_json")
    op.drop_column("documents", "topic")
    op.drop_column("documents", "doc_type")
    # learning
    op.drop_table("learning_quiz_attempts")
    op.drop_table("learning_quizzes")
    op.drop_table("learning_cards")
    op.drop_table("learning_notes")
    op.drop_table("learning_nodes")
    op.drop_table("learning_topics")
    # projects
    op.drop_table("project_files")
    op.drop_table("projects")
