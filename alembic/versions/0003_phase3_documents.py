"""phase3 documents enhancement: enabled + last_error_at

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-05

对齐 docs/phase2-plan.md §4.2 与 docs/phase2-requirements.md §5：
documents 增加 enabled（启用/禁用，参与 RAG 检索过滤）与 last_error_at（最近失败时间）。
0002 迁移遗漏了 documents 表增强，本迁移补齐。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # enabled：BOOLEAN 在 MySQL 即 TINYINT(1)；server_default=1 让历史文档默认启用。
    op.add_column(
        "documents",
        sa.Column(
            "enabled",
            mysql.BOOLEAN(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "documents",
        sa.Column("last_error_at", mysql.DATETIME(fsp=3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "last_error_at")
    op.drop_column("documents", "enabled")
