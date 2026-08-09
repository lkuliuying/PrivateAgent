"""Add bounded streaming tool execution output.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-09

v0.5.0 B2（命令可信执行闭环）：executor 在运行期间把 stdout/stderr 行以
有界方式持久化，供桌面端轮询展示实时输出。约束：

- 每行有界（VARCHAR(8192)），每执行有行数上限（执行器侧强制）；
- 写入前已按执行器脱敏策略处理，不含明文 secret；
- ``(execution_id, seq)`` 唯一，轮询按 ``after_seq`` 续读；
- additive 迁移：旧版本应用回退可读取原表，不依赖本表。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tool_execution_output",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("run_id", mysql.CHAR(36), nullable=False),
        sa.Column("execution_id", mysql.CHAR(36), nullable=False),
        sa.Column("seq", mysql.INTEGER(), nullable=False),
        sa.Column("kind", mysql.VARCHAR(8), nullable=False),
        sa.Column("text", mysql.VARCHAR(8192), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name="fk_tool_execution_output_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["agent_tool_executions.id"],
            name="fk_tool_execution_output_execution",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "execution_id",
            "seq",
            name="uk_tool_execution_output_seq",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_tool_execution_output_exec",
        "tool_execution_output",
        ["execution_id", "seq"],
    )


def downgrade() -> None:
    op.drop_table("tool_execution_output")
