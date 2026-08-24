"""v0.9.0 H3 契约迁移：workspace 生命周期状态扩展（计划 §4.3）。

变更（additive）：
- ``project_workspaces.status`` ENUM 追加 ``creating`` / ``cleanup_pending``
  两个 worktree 生命周期态；既有值保留。
- MySQL 8 支持 ENUM 成员追加（MySQL 5.7 需整列重建——用条件判断兼容）。

DDL 幂等；正式应用回退不执行本迁移的 downgrade。

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-23
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WORKSPACE_STATUSES = (
    "active",
    "missing",
    "dirty",
    "archived",
    "conflict",
    "creating",
    "cleanup_pending",
)


def _enum_has_value(conn, table: str, column: str, value: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT COLUMN_TYPE FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    if row is None:
        return True
    column_type = str(row[0] or "")
    return f"'{value}'" in column_type


def upgrade() -> None:
    connection = op.get_bind()
    if not _enum_has_value(
        connection, "project_workspaces", "status", "cleanup_pending"
    ):
        op.execute(
            "ALTER TABLE project_workspaces "
            "MODIFY COLUMN status ENUM("
            f"{','.join(repr(s) for s in _WORKSPACE_STATUSES)}) "
            "NOT NULL DEFAULT 'active'"
        )


def downgrade() -> None:
    # 仅开发库验证；正式回退保留 schema（计划 §10）
    connection = op.get_bind()
    if _enum_has_value(
        connection, "project_workspaces", "status", "cleanup_pending"
    ):
        # 回退前须无新状态行（测试库保证）
        op.execute(
            "UPDATE project_workspaces SET status='active'"
            " WHERE status IN ('creating', 'cleanup_pending')"
        )
        legacy = ("active", "missing", "dirty", "archived", "conflict")
        op.execute(
            "ALTER TABLE project_workspaces "
            "MODIFY COLUMN status ENUM("
            f"{','.join(repr(s) for s in legacy)}) "
            "NOT NULL DEFAULT 'active'"
        )
