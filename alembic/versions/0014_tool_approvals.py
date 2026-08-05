"""Add parameter-bound, expiring, one-time Agent tool approvals.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-02

The migration is additive and does not rewrite legacy ``tool_calls`` rows.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tool_approvals",
        sa.Column("id", mysql.CHAR(36), primary_key=True),
        sa.Column("run_id", mysql.CHAR(36), nullable=False),
        sa.Column("step_id", mysql.CHAR(36), nullable=True),
        sa.Column("tool_call_id", mysql.VARCHAR(200), nullable=False),
        sa.Column("tool_name", mysql.VARCHAR(64), nullable=False),
        sa.Column("tool_version", mysql.VARCHAR(32), nullable=False),
        sa.Column("arguments_json", mysql.JSON(), nullable=False),
        sa.Column("arguments_sha256", mysql.CHAR(64), nullable=False),
        sa.Column("risk_level", mysql.VARCHAR(32), nullable=False),
        sa.Column("required_capabilities_json", mysql.JSON(), nullable=False),
        sa.Column(
            "status",
            mysql.VARCHAR(32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("expires_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("approval_token_sha256", mysql.CHAR(64), nullable=True),
        sa.Column("decision_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("consumed_at", mysql.DATETIME(fsp=3), nullable=True),
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
            name="fk_tool_approvals_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["run_steps.id"],
            name="fk_tool_approvals_step",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "run_id",
            "tool_call_id",
            name="uk_tool_approval_run_call",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_tool_approval_status_expiry",
        "tool_approvals",
        ["status", "expires_at"],
    )
    op.create_index("idx_tool_approval_step", "tool_approvals", ["step_id"])


def downgrade() -> None:
    # MySQL uses idx_tool_approval_step to enforce the step foreign key.
    # Dropping the table removes both indexes and constraints safely.
    op.drop_table("tool_approvals")
