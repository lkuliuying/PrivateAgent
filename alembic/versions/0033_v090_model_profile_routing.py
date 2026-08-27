"""v0.9.0 H1-D 契约迁移：model_profiles 具体模型路由字段（计划 §5.8）。

变更（additive）：
- ``model_profiles.model_name`` VARCHAR(200) NULL：具体模型路由字段，
  Runtime 创建 run 时按 run 绑定 profile 的该字段解析实际 provider/model，
  不再回落全局 ``llm_model/openai_model/claude_model``。历史 profile 为
  NULL，由启动升级 reconcile 幂等回填或经设置页补全。
- ``model_profiles.is_default`` BOOLEAN NOT NULL DEFAULT 0：默认 Coding
  profile 标记（服务层排他维护唯一性）。

不改动既有列与数据；DDL 幂等；正式应用回退不执行本迁移的 downgrade。

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-23
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return bool(row and row[0])


def upgrade() -> None:
    connection = op.get_bind()
    if not _column_exists(connection, "model_profiles", "model_name"):
        op.execute(
            "ALTER TABLE model_profiles "
            "ADD COLUMN model_name VARCHAR(200) NULL"
        )
    if not _column_exists(connection, "model_profiles", "is_default"):
        op.execute(
            "ALTER TABLE model_profiles "
            "ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT 0"
        )


def downgrade() -> None:
    # 仅开发库验证；正式回退保留 schema（计划 §10）
    connection = op.get_bind()
    if _column_exists(connection, "model_profiles", "is_default"):
        op.execute("ALTER TABLE model_profiles DROP COLUMN is_default")
    if _column_exists(connection, "model_profiles", "model_name"):
        op.execute("ALTER TABLE model_profiles DROP COLUMN model_name")
