"""v0.9.0 H0 契约迁移：会话绑定审计与 full_access 授予。

冻结依据：``docs/releases/v0.9.0/v0.9.0-h0-contracts-20260823.md`` §4.3/§6.3。

变更（全部 additive，既有表与列不动）：
- 新增 ``session_project_bindings``：legacy/unbound 会话显式绑定项目的审计行。
  绑定本身写回 ``sessions.project_id/workspace_id/kind``（既有列）；本表只
  追加事实（何时、绑定到哪个项目/workspace），不做批量猜测绑定。
- 新增 ``full_access_grants``：``full_access`` 独立 capability 的会话级授予。
  有效期（expires_at）+ 撤销（revoked_at/revoke_reason）+ 到期/退出应用自动
  失效；同一会话同一时间至多一个有效授予（唯一约束由应用层 + 部分索引语义
  共同保证，MySQL 无部分索引，用 revoked_at NULL 语义 + 应用层校验）。

DDL 幂等（if_not_exists / 存在性检查）：与 0027–0030 同口径。
正式应用回退不执行本迁移的 downgrade；downgrade 仅用于开发库/克隆库验证。

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-23
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(conn, table: str, index: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = :t AND index_name = :i"
        ),
        {"t": table, "i": index},
    ).fetchone()
    return row is not None


def _constraint_exists(conn, name: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_schema = DATABASE() AND constraint_name = :n"
        ),
        {"n": name},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    connection = op.get_bind()
    # ============================================================
    # 1. session_project_bindings（绑定审计；只追加事实）
    # ============================================================
    op.create_table(
        "session_project_bindings",
        sa.Column("id", mysql.BIGINT(), nullable=False, autoincrement=True),
        sa.Column("session_id", mysql.BIGINT(), nullable=False),
        sa.Column("project_id", mysql.BIGINT(), nullable=False),
        sa.Column("workspace_id", mysql.BIGINT(), nullable=False),
        sa.Column(
            "bound_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_session_binding_session",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_session_binding_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["project_workspaces.id"],
            name="fk_session_binding_workspace",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_session_project_bindings"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
        if_not_exists=True,
    )
    if not _index_exists(
        connection, "session_project_bindings", "idx_session_binding_session"
    ):
        op.create_index(
            "idx_session_binding_session",
            "session_project_bindings",
            ["session_id", "bound_at"],
        )

    # ============================================================
    # 2. full_access_grants（独立 capability 授予；非 workspace 别名）
    # ============================================================
    op.create_table(
        "full_access_grants",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("session_id", mysql.BIGINT(), nullable=False),
        sa.Column("project_id", mysql.BIGINT(), nullable=False),
        sa.Column(
            "granted_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.Column("expires_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("revoked_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "revoke_reason",
            mysql.VARCHAR(64),
            nullable=True,
            comment="user_revoke/expired/app_exit/project_switch（低基数）",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_full_access_grant_session",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_full_access_grant_project",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_full_access_grants"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
        if_not_exists=True,
    )
    if not _index_exists(
        connection, "full_access_grants", "idx_full_access_grant_session"
    ):
        op.create_index(
            "idx_full_access_grant_session",
            "full_access_grants",
            ["session_id", "expires_at"],
        )
    if not _index_exists(
        connection, "full_access_grants", "idx_full_access_grant_expiry"
    ):
        op.create_index(
            "idx_full_access_grant_expiry",
            "full_access_grants",
            ["expires_at", "revoked_at"],
        )


def downgrade() -> None:
    # 仅用于开发库/克隆库验证；正式应用回退保留 schema（计划 §10）。
    connection = op.get_bind()
    for fk in (
        "fk_full_access_grant_session",
        "fk_full_access_grant_project",
    ):
        if _constraint_exists(connection, fk):
            op.drop_constraint(fk, "full_access_grants", type_="foreignkey")
    for idx in (
        "idx_full_access_grant_session",
        "idx_full_access_grant_expiry",
    ):
        if _index_exists(connection, "full_access_grants", idx):
            op.drop_index(idx, table_name="full_access_grants")
    op.drop_table("full_access_grants")

    for fk in (
        "fk_session_binding_session",
        "fk_session_binding_project",
        "fk_session_binding_workspace",
    ):
        if _constraint_exists(connection, fk):
            op.drop_constraint(
                fk, "session_project_bindings", type_="foreignkey"
            )
    if _index_exists(
        connection, "session_project_bindings", "idx_session_binding_session"
    ):
        op.drop_index(
            "idx_session_binding_session", table_name="session_project_bindings"
        )
    op.drop_table("session_project_bindings")
