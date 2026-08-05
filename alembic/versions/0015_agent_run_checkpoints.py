"""Add versioned Agent run checkpoints for approval resume.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_run_checkpoints",
        sa.Column("run_id", mysql.CHAR(36), primary_key=True),
        sa.Column("checkpoint_version", mysql.INTEGER(), nullable=False),
        sa.Column("event_sequence", mysql.INTEGER(), nullable=False),
        sa.Column("conversation_json", mysql.JSON(), nullable=False),
        sa.Column("pending_tool_calls_json", mysql.JSON(), nullable=False),
        sa.Column("tool_call_count", mysql.INTEGER(), nullable=False),
        sa.Column("input_tokens", mysql.BIGINT(), nullable=False),
        sa.Column("output_tokens", mysql.BIGINT(), nullable=False),
        sa.Column("cached_tokens", mysql.BIGINT(), nullable=False),
        sa.Column("cost_usd", mysql.DECIMAL(18, 8), nullable=True),
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
            ["run_id"],
            ["agent_runs.id"],
            name="fk_agent_run_checkpoints_run",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "run_id",
            "event_sequence",
            name="uk_agent_run_checkpoint_sequence",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def downgrade() -> None:
    op.drop_table("agent_run_checkpoints")
