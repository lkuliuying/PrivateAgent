"""phase2 tools: tool_calls / trusted_paths / activities

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-04

三表对齐 docs/phase2-plan.md §4.1 与 docs/phase2-requirements.md §5：
utf8mb4 / utf8mb4_unicode_ci / InnoDB。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- tool_calls ----
    op.create_table(
        "tool_calls",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("session_id", mysql.BIGINT(), nullable=True),
        sa.Column("tool_name", mysql.VARCHAR(128), nullable=False),
        sa.Column(
            "risk_level",
            mysql.ENUM("safe", "confirm", "restricted", name="risk_level_enum"),
            nullable=False,
        ),
        sa.Column(
            "status",
            mysql.ENUM(
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
            server_default="pending_approval",
        ),
        sa.Column("input_json", mysql.JSON(), nullable=True),
        sa.Column("output_json", mysql.JSON(), nullable=True),
        sa.Column("error_message", mysql.TEXT(), nullable=True),
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
            ["session_id"], ["sessions.id"], ondelete="CASCADE", name="fk_toolcall_session"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_tool_session", "tool_calls", ["session_id", "created_at"])
    op.create_index("idx_tool_status", "tool_calls", ["status"])

    # ---- trusted_paths ----
    op.create_table(
        "trusted_paths",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("path", mysql.VARCHAR(2048), nullable=False),
        sa.Column(
            "kind",
            mysql.ENUM("file", "directory", name="trusted_path_kind"),
            nullable=False,
        ),
        sa.Column(
            "granted_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        # path 不加 UNIQUE：utf8mb4 下 VARCHAR(2048) 超 3072 字节键长限制；
        # 去重由应用层 TrustedPathRepository.authorize 保证。
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )

    # ---- activities ----
    op.create_table(
        "activities",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("session_id", mysql.BIGINT(), nullable=True),
        sa.Column(
            "kind",
            mysql.ENUM(
                "tool",
                "document_import",
                "reindex",
                "system",
                name="activity_kind",
            ),
            nullable=False,
        ),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column(
            "status",
            mysql.ENUM(
                "pending",
                "waiting_approval",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                name="activity_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("ref_type", mysql.VARCHAR(64), nullable=True),
        sa.Column("ref_id", mysql.BIGINT(), nullable=True),
        sa.Column("detail_json", mysql.JSON(), nullable=True),
        sa.Column("error_message", mysql.TEXT(), nullable=True),
        sa.Column("started_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("finished_at", mysql.DATETIME(fsp=3), nullable=True),
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
            ["session_id"], ["sessions.id"], ondelete="CASCADE", name="fk_activity_session"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_activity_session", "activities", ["session_id", "created_at"])
    op.create_index("idx_activity_status", "activities", ["status"])


def downgrade() -> None:
    op.drop_table("activities")
    op.drop_table("trusted_paths")
    op.drop_table("tool_calls")
