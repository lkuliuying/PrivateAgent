"""v1.0：未知模型上下文窗口保持 NULL。

OpenAI 兼容的模型列表并不保证返回上下文窗口。旧结构强制非空，导致未知
模型只能被写成 8192/32768 等猜测值。本迁移允许 NULL，由供应商元数据、
官方目录或用户手动设置提供真实值。

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-28
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _context_column(conn):
    return conn.execute(
        sa.text(
            "SELECT IS_NULLABLE, COLUMN_DEFAULT FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'model_profiles' "
            "AND column_name = 'context_tokens'"
        )
    ).fetchone()


def upgrade() -> None:
    connection = op.get_bind()
    row = _context_column(connection)
    if row and str(row[0]).upper() != "YES":
        op.execute(
            "ALTER TABLE model_profiles "
            "MODIFY COLUMN context_tokens INTEGER NULL DEFAULT 8192"
        )


def downgrade() -> None:
    # 开发库回退可恢复旧约束；正式回退保留 additive schema。
    connection = op.get_bind()
    row = _context_column(connection)
    if row and str(row[0]).upper() == "YES":
        op.execute(
            "UPDATE model_profiles SET context_tokens = 8192 "
            "WHERE context_tokens IS NULL"
        )
        op.execute(
            "ALTER TABLE model_profiles "
            "MODIFY COLUMN context_tokens INTEGER NOT NULL DEFAULT 8192"
        )
