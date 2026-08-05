"""Add traceable conversation summaries and versioned memory facts.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memory_items",
        sa.Column("stable_key", mysql.VARCHAR(64), nullable=True),
    )
    op.add_column(
        "memory_items",
        sa.Column("memory_version", mysql.INTEGER(), nullable=False, server_default="1"),
    )
    op.add_column(
        "memory_items",
        sa.Column("content_sha256", mysql.CHAR(64), nullable=True),
    )
    op.add_column(
        "memory_items",
        sa.Column("importance", mysql.FLOAT(), nullable=False, server_default="0.5"),
    )
    op.add_column(
        "memory_items",
        sa.Column("expires_at", mysql.DATETIME(fsp=3), nullable=True),
    )
    op.add_column(
        "memory_items",
        sa.Column(
            "sensitivity_level",
            mysql.VARCHAR(32),
            nullable=True,
            server_default="normal",
        ),
    )
    op.add_column(
        "memory_items",
        sa.Column("confirmed_at", mysql.DATETIME(fsp=3), nullable=True),
    )
    op.add_column(
        "memory_items",
        sa.Column("last_confirmed_at", mysql.DATETIME(fsp=3), nullable=True),
    )
    op.add_column(
        "memory_items",
        sa.Column("deleted_at", mysql.DATETIME(fsp=3), nullable=True),
    )
    op.execute(
        "UPDATE memory_items SET "
        "stable_key = LOWER(SHA2(CONCAT('memory:', id), 256)), "
        "content_sha256 = LOWER(SHA2(content_md, 256)), "
        "sensitivity_level = IF(`sensitive` = 1, 'sensitive', 'normal'), "
        "confirmed_at = IF(`status` = 'confirmed', created_at, NULL), "
        "last_confirmed_at = IF(`status` = 'confirmed', created_at, NULL)"
    )
    op.alter_column(
        "memory_items",
        "stable_key",
        existing_type=mysql.VARCHAR(64),
        nullable=False,
    )
    op.alter_column(
        "memory_items",
        "content_sha256",
        existing_type=mysql.CHAR(64),
        nullable=False,
    )
    op.alter_column(
        "memory_items",
        "sensitivity_level",
        existing_type=mysql.VARCHAR(32),
        nullable=False,
        server_default="normal",
    )
    op.create_index(
        "uk_memory_stable_key",
        "memory_items",
        ["stable_key"],
        unique=True,
    )
    op.create_index(
        "idx_memory_active_expiry",
        "memory_items",
        ["deleted_at", "status", "enabled", "expires_at"],
    )

    op.create_table(
        "memory_revisions",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("memory_id", mysql.BIGINT(), nullable=False),
        sa.Column("stable_key", mysql.VARCHAR(64), nullable=False),
        sa.Column("memory_version", mysql.INTEGER(), nullable=False),
        sa.Column("kind", mysql.VARCHAR(32), nullable=False),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column("content_md", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("content_sha256", mysql.CHAR(64), nullable=False),
        sa.Column("summary", mysql.VARCHAR(1024), nullable=True),
        sa.Column("state_json", mysql.JSON(), nullable=True),
        sa.Column("change_type", mysql.VARCHAR(32), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.UniqueConstraint(
            "memory_id",
            "memory_version",
            name="uk_memory_revision_version",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_memory_revision_stable",
        "memory_revisions",
        ["stable_key", "memory_version"],
    )
    op.execute(
        "INSERT INTO memory_revisions "
        "(memory_id, stable_key, memory_version, kind, title, content_md, "
        "content_sha256, summary, state_json, change_type, created_at) "
        "SELECT id, stable_key, memory_version, kind, title, content_md, "
        "content_sha256, summary, NULL, 'backfilled', created_at "
        "FROM memory_items"
    )

    op.create_table(
        "memory_conflicts",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("left_memory_id", mysql.BIGINT(), nullable=False),
        sa.Column("right_memory_id", mysql.BIGINT(), nullable=False),
        sa.Column("reason", mysql.TEXT(), nullable=False),
        sa.Column("status", mysql.VARCHAR(32), nullable=False),
        sa.Column("resolution_json", mysql.JSON(), nullable=True),
        sa.Column("resolved_at", mysql.DATETIME(fsp=3), nullable=True),
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
            ["left_memory_id"],
            ["memory_items.id"],
            name="fk_memory_conflict_left",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["right_memory_id"],
            ["memory_items.id"],
            name="fk_memory_conflict_right",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "left_memory_id",
            "right_memory_id",
            name="uk_memory_conflict_pair",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_memory_conflict_status",
        "memory_conflicts",
        ["status", "updated_at"],
    )

    op.create_table(
        "conversation_summaries",
        sa.Column("id", mysql.CHAR(36), primary_key=True),
        sa.Column("session_id", mysql.BIGINT(), nullable=False),
        sa.Column("first_message_id", mysql.BIGINT(), nullable=True),
        sa.Column("last_message_id", mysql.BIGINT(), nullable=True),
        sa.Column("source_message_count", mysql.INTEGER(), nullable=False),
        sa.Column("source_sha256", mysql.CHAR(64), nullable=False),
        sa.Column("summary_text", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("summary_version", mysql.INTEGER(), nullable=False),
        sa.Column("prompt_version", mysql.VARCHAR(32), nullable=False),
        sa.Column("provider", mysql.VARCHAR(100), nullable=True),
        sa.Column("model", mysql.VARCHAR(200), nullable=True),
        sa.Column("input_tokens", mysql.BIGINT(), nullable=False),
        sa.Column("output_tokens", mysql.BIGINT(), nullable=False),
        sa.Column(
            "sensitive",
            mysql.BOOLEAN(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("status", mysql.VARCHAR(32), nullable=False),
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
            ["session_id"],
            ["sessions.id"],
            name="fk_conversation_summary_session",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["first_message_id"],
            ["messages.id"],
            name="fk_conversation_summary_first",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_message_id"],
            ["messages.id"],
            name="fk_conversation_summary_last",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "session_id",
            "source_sha256",
            "summary_version",
            name="uk_conversation_summary_source_version",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_conversation_summary_active",
        "conversation_summaries",
        ["session_id", "status", "last_message_id"],
    )


def downgrade() -> None:
    # Whole-table removal lets MySQL clean FK-supporting indexes safely.
    op.drop_table("conversation_summaries")
    op.drop_table("memory_conflicts")
    op.drop_table("memory_revisions")
    op.drop_index("idx_memory_active_expiry", table_name="memory_items")
    op.drop_index("uk_memory_stable_key", table_name="memory_items")
    op.drop_column("memory_items", "deleted_at")
    op.drop_column("memory_items", "last_confirmed_at")
    op.drop_column("memory_items", "confirmed_at")
    op.drop_column("memory_items", "sensitivity_level")
    op.drop_column("memory_items", "expires_at")
    op.drop_column("memory_items", "importance")
    op.drop_column("memory_items", "content_sha256")
    op.drop_column("memory_items", "memory_version")
    op.drop_column("memory_items", "stable_key")
