"""Add the default-off MCP client registry and bounded call audit.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", mysql.CHAR(36), primary_key=True),
        sa.Column("name", mysql.VARCHAR(128), nullable=False),
        sa.Column(
            "transport",
            mysql.ENUM("stdio", "streamable_http", name="mcp_transport_enum"),
            nullable=False,
        ),
        sa.Column("command", mysql.VARCHAR(2048), nullable=True),
        sa.Column("args_json", mysql.JSON(), nullable=True),
        sa.Column("working_directory", mysql.VARCHAR(2048), nullable=True),
        sa.Column("url", mysql.VARCHAR(2048), nullable=True),
        sa.Column("env_json", mysql.JSON(), nullable=True),
        sa.Column("secret_refs_json", mysql.JSON(), nullable=True),
        sa.Column("allow_insecure_local", mysql.BOOLEAN(), nullable=False, server_default="0"),
        sa.Column("allow_private_network", mysql.BOOLEAN(), nullable=False, server_default="0"),
        sa.Column("trusted", mysql.BOOLEAN(), nullable=False, server_default="0"),
        sa.Column("enabled", mysql.BOOLEAN(), nullable=False, server_default="0"),
        sa.Column("allowed_tools_json", mysql.JSON(), nullable=True),
        sa.Column("timeout_ms", mysql.INTEGER(), nullable=False, server_default="30000"),
        sa.Column("max_output_bytes", mysql.INTEGER(), nullable=False, server_default="262144"),
        sa.Column("status", mysql.VARCHAR(32), nullable=False, server_default="disabled"),
        sa.Column("last_error_code", mysql.VARCHAR(64), nullable=True),
        sa.Column("discovery_tools_json", mysql.JSON(), nullable=True),
        sa.Column("discovery_resources_json", mysql.JSON(), nullable=True),
        sa.Column("discovery_prompts_json", mysql.JSON(), nullable=True),
        sa.Column("discovery_sha256", mysql.CHAR(64), nullable=True),
        sa.Column("last_checked_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("discovered_at", mysql.DATETIME(fsp=3), nullable=True),
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
        sa.UniqueConstraint("name", name="uk_mcp_server_name"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_mcp_server_enabled_status",
        "mcp_servers",
        ["enabled", "trusted", "status"],
    )

    op.create_table(
        "mcp_call_logs",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("server_id", mysql.CHAR(36), nullable=False),
        sa.Column("run_id", mysql.CHAR(36), nullable=True),
        sa.Column("tool_name", mysql.VARCHAR(128), nullable=False),
        sa.Column("request_sha256", mysql.CHAR(64), nullable=False),
        sa.Column("status", mysql.VARCHAR(32), nullable=False),
        sa.Column("error_code", mysql.VARCHAR(64), nullable=True),
        sa.Column("duration_ms", mysql.INTEGER(), nullable=False),
        sa.Column("output_bytes", mysql.INTEGER(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["mcp_servers.id"],
            name="fk_mcp_call_server",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name="fk_mcp_call_run",
            ondelete="SET NULL",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_mcp_call_server_time",
        "mcp_call_logs",
        ["server_id", "created_at"],
    )
    op.create_index(
        "idx_mcp_call_run_time",
        "mcp_call_logs",
        ["run_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("mcp_call_logs")
    op.drop_table("mcp_servers")
