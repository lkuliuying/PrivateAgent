"""phase3 M5/M6: coding tools and agent task orchestration

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tool_calls", sa.Column("task_id", mysql.BIGINT(), nullable=True))
    op.add_column("tool_calls", sa.Column("step_id", mysql.BIGINT(), nullable=True))
    op.create_index("idx_tool_task", "tool_calls", ["task_id", "step_id"])

    op.create_table(
        "agent_tasks",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("session_id", mysql.BIGINT(), nullable=True),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column("goal", mysql.TEXT(), nullable=True),
        sa.Column(
            "status",
            mysql.ENUM(
                "planned",
                "waiting_approval",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                name="agent_task_status_enum",
            ),
            nullable=False,
            server_default="planned",
        ),
        sa.Column("plan_json", mysql.JSON(), nullable=True),
        sa.Column("final_report_md", mysql.MEDIUMTEXT(), nullable=True),
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
            ["session_id"], ["sessions.id"], ondelete="SET NULL", name="fk_agent_task_session"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_agent_task_session", "agent_tasks", ["session_id", "created_at"])
    op.create_index("idx_agent_task_status", "agent_tasks", ["status"])

    op.create_table(
        "agent_task_steps",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("task_id", mysql.BIGINT(), nullable=False),
        sa.Column("ordinal", mysql.INTEGER(), nullable=False),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column("tool_name", mysql.VARCHAR(128), nullable=True),
        sa.Column(
            "status",
            mysql.ENUM(
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
            server_default="planned",
        ),
        sa.Column("tool_call_id", mysql.BIGINT(), nullable=True),
        sa.Column("input_json", mysql.JSON(), nullable=True),
        sa.Column("output_json", mysql.JSON(), nullable=True),
        sa.Column("error_message", mysql.TEXT(), nullable=True),
        sa.Column("started_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("finished_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["agent_tasks.id"], ondelete="CASCADE", name="fk_agent_step_task"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("uk_agent_step_ordinal", "agent_task_steps", ["task_id", "ordinal"], unique=True)
    op.create_index("idx_agent_step_task", "agent_task_steps", ["task_id", "ordinal"])
    op.create_index("idx_agent_step_status", "agent_task_steps", ["status"])

    op.create_table(
        "agent_evidence",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("task_id", mysql.BIGINT(), nullable=False),
        sa.Column("step_id", mysql.BIGINT(), nullable=True),
        sa.Column(
            "kind",
            mysql.ENUM("tool_output", "error", "note", "report", name="agent_evidence_kind_enum"),
            nullable=False,
        ),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column("content_md", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("meta_json", mysql.JSON(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["agent_tasks.id"], ondelete="CASCADE", name="fk_evidence_task"
        ),
        sa.ForeignKeyConstraint(
            ["step_id"], ["agent_task_steps.id"], ondelete="SET NULL", name="fk_evidence_step"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_agent_evidence_task", "agent_evidence", ["task_id", "created_at"])
    op.create_index("idx_agent_evidence_step", "agent_evidence", ["step_id"])


def downgrade() -> None:
    op.drop_table("agent_evidence")
    op.drop_index("idx_agent_step_status", table_name="agent_task_steps")
    op.drop_index("idx_agent_step_task", table_name="agent_task_steps")
    op.drop_index("uk_agent_step_ordinal", table_name="agent_task_steps")
    op.drop_table("agent_task_steps")
    op.drop_index("idx_agent_task_status", table_name="agent_tasks")
    op.drop_index("idx_agent_task_session", table_name="agent_tasks")
    op.drop_table("agent_tasks")
    op.drop_index("idx_tool_task", table_name="tool_calls")
    op.drop_column("tool_calls", "step_id")
    op.drop_column("tool_calls", "task_id")
