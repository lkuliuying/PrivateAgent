"""Add durable Agent runtime runs, ordered steps, and replayable events.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-02

This migration is additive. Existing chat, task, tool-call, and document rows
are not rewritten or inferred into synthetic runs.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", mysql.CHAR(36), primary_key=True),
        sa.Column("session_id", mysql.BIGINT(), nullable=True),
        sa.Column("trace_id", mysql.VARCHAR(64), nullable=False),
        sa.Column(
            "status",
            mysql.VARCHAR(32),
            nullable=False,
            server_default="created",
        ),
        sa.Column("provider", mysql.VARCHAR(100), nullable=True),
        sa.Column("model", mysql.VARCHAR(200), nullable=True),
        sa.Column("max_steps", mysql.INTEGER(), nullable=False),
        sa.Column("max_tool_calls", mysql.INTEGER(), nullable=False),
        sa.Column("max_wall_time_ms", mysql.BIGINT(), nullable=False),
        sa.Column(
            "last_event_sequence",
            mysql.INTEGER(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "tool_call_count",
            mysql.INTEGER(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "input_tokens",
            mysql.BIGINT(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "output_tokens",
            mysql.BIGINT(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cached_tokens",
            mysql.BIGINT(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("cost_usd", mysql.DECIMAL(18, 8), nullable=True),
        sa.Column("output", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column("error_code", mysql.VARCHAR(128), nullable=True),
        sa.Column("error_message", mysql.TEXT(), nullable=True),
        sa.Column("cancel_requested_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("started_at", mysql.DATETIME(fsp=3), nullable=True),
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
            ["session_id"],
            ["sessions.id"],
            name="fk_agent_runs_session",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("trace_id", name="uk_agent_run_trace"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_agent_run_session_created", "agent_runs", ["session_id", "created_at"]
    )
    op.create_index(
        "idx_agent_run_status_updated", "agent_runs", ["status", "updated_at"]
    )

    op.create_table(
        "run_steps",
        sa.Column("id", mysql.CHAR(36), primary_key=True),
        sa.Column("run_id", mysql.CHAR(36), nullable=False),
        sa.Column("ordinal", mysql.INTEGER(), nullable=False),
        sa.Column("kind", mysql.VARCHAR(32), nullable=False),
        sa.Column(
            "status",
            mysql.VARCHAR(32),
            nullable=False,
            server_default="running",
        ),
        sa.Column("tool_call_id", mysql.VARCHAR(200), nullable=True),
        sa.Column("name", mysql.VARCHAR(200), nullable=True),
        sa.Column("provider", mysql.VARCHAR(100), nullable=True),
        sa.Column("model", mysql.VARCHAR(200), nullable=True),
        sa.Column("provider_request_id", mysql.VARCHAR(300), nullable=True),
        sa.Column("input_json", mysql.JSON(), nullable=True),
        sa.Column("output_json", mysql.JSON(), nullable=True),
        sa.Column("latency_ms", mysql.FLOAT(), nullable=True),
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
            name="fk_run_steps_run",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("run_id", "ordinal", name="uk_run_step_ordinal"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_run_step_run_ordinal", "run_steps", ["run_id", "ordinal"]
    )
    op.create_index("idx_run_step_status", "run_steps", ["status"])
    op.create_index("idx_run_step_tool_call", "run_steps", ["tool_call_id"])

    op.create_table(
        "agent_run_events",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("run_id", mysql.CHAR(36), nullable=False),
        sa.Column("sequence", mysql.INTEGER(), nullable=False),
        sa.Column("event_type", mysql.VARCHAR(64), nullable=False),
        sa.Column("step_id", mysql.CHAR(36), nullable=True),
        sa.Column("payload_json", mysql.JSON(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name="fk_agent_run_events_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["run_steps.id"],
            name="fk_agent_run_events_step",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "run_id", "sequence", name="uk_agent_run_event_sequence"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_agent_run_event_type",
        "agent_run_events",
        ["event_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_agent_run_event_type", table_name="agent_run_events")
    op.drop_table("agent_run_events")
    op.drop_index("idx_run_step_tool_call", table_name="run_steps")
    op.drop_index("idx_run_step_status", table_name="run_steps")
    op.drop_index("idx_run_step_run_ordinal", table_name="run_steps")
    op.drop_table("run_steps")
    op.drop_index("idx_agent_run_status_updated", table_name="agent_runs")
    # MySQL uses idx_agent_run_session_created to enforce the session FK.
    # Dropping the table removes that supporting index safely.
    op.drop_table("agent_runs")
