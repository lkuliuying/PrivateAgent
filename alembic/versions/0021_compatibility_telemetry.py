"""Add durable compatibility telemetry windows for retirement observation.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-06

R3 §6.4：跨版本观察窗口需要跨进程/跨重启的持久化遥测。每个进程启动创建
一个窗口（scope_key），计数按 (path, mode, outcome) 落库；查询跨窗口聚合，
用于验证"观察窗口内 legacy 调用为 0"。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compatibility_telemetry",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("scope", mysql.VARCHAR(32), nullable=False),
        sa.Column("scope_key", mysql.VARCHAR(64), nullable=False),
        sa.Column("path", mysql.VARCHAR(64), nullable=False),
        sa.Column("mode", mysql.VARCHAR(32), nullable=False),
        sa.Column("outcome", mysql.VARCHAR(32), nullable=False),
        sa.Column("calls", mysql.INTEGER(), nullable=False, server_default="0"),
        sa.Column(
            "started_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.Column(
            "last_flushed_at",
            mysql.DATETIME(fsp=3),
            nullable=True,
        ),
        sa.Column(
            "ended_at",
            mysql.DATETIME(fsp=3),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "scope",
            "scope_key",
            "path",
            "mode",
            "outcome",
            name="uk_compat_telemetry_cell",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_compat_telemetry_window",
        "compatibility_telemetry",
        ["scope", "started_at"],
    )


def downgrade() -> None:
    op.drop_table("compatibility_telemetry")
