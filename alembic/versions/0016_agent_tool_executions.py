"""Add leased, auditable and replay-safe Agent tool executions.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_tool_executions",
        sa.Column("id", mysql.CHAR(36), primary_key=True),
        sa.Column("run_id", mysql.CHAR(36), nullable=False),
        sa.Column("step_id", mysql.CHAR(36), nullable=True),
        sa.Column("tool_call_id", mysql.VARCHAR(200), nullable=False),
        sa.Column("tool_name", mysql.VARCHAR(64), nullable=False),
        sa.Column("tool_version", mysql.VARCHAR(32), nullable=False),
        sa.Column("arguments_json", mysql.JSON(), nullable=False),
        sa.Column("arguments_sha256", mysql.CHAR(64), nullable=False),
        sa.Column("execution_key_sha256", mysql.CHAR(64), nullable=True),
        sa.Column("risk_level", mysql.VARCHAR(32), nullable=False),
        sa.Column("required_capabilities_json", mysql.JSON(), nullable=False),
        sa.Column("approval_id", mysql.CHAR(36), nullable=True),
        sa.Column("status", mysql.VARCHAR(32), nullable=False),
        sa.Column("attempt_count", mysql.INTEGER(), nullable=False),
        sa.Column("claim_token_sha256", mysql.CHAR(64), nullable=True),
        sa.Column("lease_expires_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("output_json", mysql.JSON(), nullable=True),
        sa.Column("output_sha256", mysql.CHAR(64), nullable=True),
        sa.Column("output_size_bytes", mysql.BIGINT(), nullable=True),
        sa.Column("error_code", mysql.VARCHAR(64), nullable=True),
        sa.Column("error_message", mysql.TEXT(), nullable=True),
        sa.Column("started_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("completed_at", mysql.DATETIME(fsp=3), nullable=True),
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
            name="fk_agent_tool_executions_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["run_steps.id"],
            name="fk_agent_tool_executions_step",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"],
            ["tool_approvals.id"],
            name="fk_agent_tool_executions_approval",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "run_id",
            "tool_call_id",
            name="uk_agent_tool_execution_run_call",
        ),
        sa.UniqueConstraint(
            "run_id",
            "execution_key_sha256",
            name="uk_agent_tool_execution_run_key",
        ),
        sa.UniqueConstraint("approval_id", name="uk_agent_tool_execution_approval"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_agent_tool_execution_status_lease",
        "agent_tool_executions",
        ["status", "lease_expires_at"],
    )
    op.create_index(
        "idx_agent_tool_execution_step",
        "agent_tool_executions",
        ["step_id"],
    )


def downgrade() -> None:
    # The step/approval indexes support foreign keys; table removal cleans all safely.
    op.drop_table("agent_tool_executions")
