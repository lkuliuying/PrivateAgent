"""phase4 M1: memory_items.status — 候选记忆 draft/confirmed/archived 生命周期

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-07

对齐 docs/archive/phases/phase4-plan.md M1 与用户决策「候选记忆落库为 draft 待确认」：
- memory_items 增列 status ENUM('draft','confirmed','archived') NOT NULL DEFAULT 'confirmed'。
- status 为生命周期（draft=候选待确认 / confirmed=已确认 / archived=已归档），
  与 enabled（运行时禁用开关）正交：检索默认取 status='confirmed' AND enabled=True。
- 候选生成（任务报告/聊天）落库为 draft，用户确认后 PATCH 转 confirmed。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memory_items",
        sa.Column(
            "status",
            mysql.ENUM("draft", "confirmed", "archived", name="memory_status_enum"),
            nullable=False,
            server_default="confirmed",
        ),
    )
    op.create_index("idx_memory_status", "memory_items", ["status", "enabled"])


def downgrade() -> None:
    op.drop_index("idx_memory_status", table_name="memory_items")
    op.drop_column("memory_items", "status")
