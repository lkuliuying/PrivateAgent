"""v0.6.0 C0 契约迁移 1/2：ProjectWorkspace 与 session/run 运行上下文。

冻结依据：``docs/releases/v0.6.0/v0.6.0-c0-contracts-20260820.md`` §4.1。

变更：
- 新增 ``project_workspaces`` 表（root workspace；v0.6.0 只创建 root）。
- ``sessions`` 增加 project_id / workspace_id / kind / last_run_id / pinned_at / archived_at
  （全部 additive；kind 非空默认 ``legacy``，旧 session 不回填绑定）。
- ``agent_runs`` 增加 project_id / workspace_id / base_head_sha / base_branch_name /
  base_git_dirty / model_profile_id / reasoning_effort / permission_mode /
  permission_snapshot_json / client_request_id（全部 additive；client_request_id
  非空时全局唯一）。
- 升级回填：按 project id 分页，为每个现有 project 幂等补建一个 root workspace
  （不重写旧 session / 旧 run；中断后重跑不重复创建）。
- DDL 全部幂等（if_not_exists / 列与约束存在性检查）：MySQL DDL 隐式提交，
  迁移中断后重跑不会因表/列/索引/约束已存在而失败。

正式应用回退不执行本迁移的 downgrade；downgrade 仅用于开发库/克隆库验证。

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    """MySQL 列存在性检查（DDL 幂等重跑用）。"""
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row is not None


def _constraint_exists(conn, name: str) -> bool:
    """MySQL 约束存在性检查（DDL 幂等重跑用）。"""
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_schema = DATABASE() AND constraint_name = :n"
        ),
        {"n": name},
    ).fetchone()
    return row is not None


def _index_exists(conn, table: str, index: str) -> bool:
    """MySQL 索引存在性检查（MySQL 不支持 CREATE INDEX IF NOT EXISTS）。"""
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = :t AND index_name = :i"
        ),
        {"t": table, "i": index},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    connection = op.get_bind()
    # ============================================================
    # 1. project_workspaces
    # ============================================================
    op.create_table(
        "project_workspaces",
        sa.Column("id", mysql.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(), nullable=False),
        sa.Column(
            "kind",
            mysql.ENUM("root", "git_worktree", charset="utf8mb4"),
            nullable=False,
            server_default="root",
        ),
        sa.Column("root_path", mysql.VARCHAR(2048), nullable=False),
        sa.Column("root_path_sha256", mysql.CHAR(64), nullable=False),
        sa.Column("branch_name", mysql.VARCHAR(512), nullable=True),
        sa.Column("head_sha", mysql.VARCHAR(64), nullable=True),
        sa.Column(
            "status",
            mysql.ENUM(
                "active", "missing", "dirty", "archived", "conflict",
                charset="utf8mb4",
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column("last_used_at", mysql.DATETIME(fsp=3), nullable=True),
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
            onupdate=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_workspace_project",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_project_workspaces"),
        # Windows 路径大小写/分隔符变体防重复
        sa.UniqueConstraint(
            "project_id", "root_path_sha256", name="uk_workspace_project_path"
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
        if_not_exists=True,
    )
    if not _index_exists(connection, "project_workspaces", "idx_workspace_project_status"):
        op.create_index(
            "idx_workspace_project_status",
            "project_workspaces",
            ["project_id", "status", "last_used_at"],
        )

    # ============================================================
    # 2. sessions 新列（additive，kind 非空默认 legacy）
    # ============================================================
    if not _column_exists(connection, "sessions", "kind"):
        op.add_column(
            "sessions",
            sa.Column(
                "kind",
                mysql.VARCHAR(32),
                nullable=False,
                server_default="legacy",
            ),
        )
    if not _column_exists(connection, "sessions", "project_id"):
        op.add_column(
            "sessions",
            sa.Column("project_id", mysql.BIGINT(), nullable=True),
        )
    if not _column_exists(connection, "sessions", "workspace_id"):
        op.add_column(
            "sessions",
            sa.Column("workspace_id", mysql.BIGINT(), nullable=True),
        )
    if not _column_exists(connection, "sessions", "last_run_id"):
        op.add_column(
            "sessions",
            sa.Column("last_run_id", mysql.CHAR(36), nullable=True),
        )
    if not _column_exists(connection, "sessions", "pinned_at"):
        op.add_column(
            "sessions",
            sa.Column("pinned_at", mysql.DATETIME(fsp=3), nullable=True),
        )
    if not _column_exists(connection, "sessions", "archived_at"):
        op.add_column(
            "sessions",
            sa.Column("archived_at", mysql.DATETIME(fsp=3), nullable=True),
        )
    if not _index_exists(connection, "sessions", "idx_session_project"):
        op.create_index("idx_session_project", "sessions", ["project_id"])
    if not _index_exists(connection, "sessions", "idx_session_workspace"):
        op.create_index("idx_session_workspace", "sessions", ["workspace_id"])
    if not _constraint_exists(connection, "fk_session_project"):
        op.create_foreign_key(
            "fk_session_project",
            "sessions", "projects",
            ["project_id"], ["id"],
            ondelete="SET NULL",
        )
    if not _constraint_exists(connection, "fk_session_workspace"):
        op.create_foreign_key(
            "fk_session_workspace",
            "sessions", "project_workspaces",
            ["workspace_id"], ["id"],
            ondelete="SET NULL",
        )

    # ============================================================
    # 3. agent_runs 新列（additive；client_request_id 非空唯一）
    # ============================================================
    if not _column_exists(connection, "agent_runs", "project_id"):
        op.add_column(
            "agent_runs",
            sa.Column("project_id", mysql.BIGINT(), nullable=True),
        )
    if not _column_exists(connection, "agent_runs", "workspace_id"):
        op.add_column(
            "agent_runs",
            sa.Column("workspace_id", mysql.BIGINT(), nullable=True),
        )
    if not _column_exists(connection, "agent_runs", "base_head_sha"):
        op.add_column(
            "agent_runs",
            sa.Column("base_head_sha", mysql.VARCHAR(64), nullable=True),
        )
    if not _column_exists(connection, "agent_runs", "base_branch_name"):
        op.add_column(
            "agent_runs",
            sa.Column("base_branch_name", mysql.VARCHAR(512), nullable=True),
        )
    if not _column_exists(connection, "agent_runs", "base_git_dirty"):
        op.add_column(
            "agent_runs",
            sa.Column("base_git_dirty", mysql.BOOLEAN(), nullable=True),
        )
    if not _column_exists(connection, "agent_runs", "model_profile_id"):
        op.add_column(
            "agent_runs",
            sa.Column("model_profile_id", mysql.VARCHAR(128), nullable=True),
        )
    if not _column_exists(connection, "agent_runs", "reasoning_effort"):
        op.add_column(
            "agent_runs",
            sa.Column("reasoning_effort", mysql.VARCHAR(32), nullable=True),
        )
    if not _column_exists(connection, "agent_runs", "permission_mode"):
        op.add_column(
            "agent_runs",
            sa.Column("permission_mode", mysql.VARCHAR(32), nullable=True),
        )
    if not _column_exists(connection, "agent_runs", "permission_snapshot_json"):
        op.add_column(
            "agent_runs",
            sa.Column("permission_snapshot_json", mysql.JSON(), nullable=True),
        )
    if not _column_exists(connection, "agent_runs", "client_request_id"):
        op.add_column(
            "agent_runs",
            sa.Column(
                "client_request_id", mysql.VARCHAR(64), nullable=True, unique=True
            ),
        )
    if not _index_exists(connection, "agent_runs", "idx_agent_run_project_workspace"):
        op.create_index(
            "idx_agent_run_project_workspace",
            "agent_runs",
            ["project_id", "workspace_id", "created_at"],
        )
    if not _constraint_exists(connection, "fk_agent_run_project"):
        op.create_foreign_key(
            "fk_agent_run_project",
            "agent_runs", "projects",
            ["project_id"], ["id"],
            ondelete="SET NULL",
        )
    if not _constraint_exists(connection, "fk_agent_run_workspace"):
        op.create_foreign_key(
            "fk_agent_run_workspace",
            "agent_runs", "project_workspaces",
            ["workspace_id"], ["id"],
            ondelete="SET NULL",
        )

    # ============================================================
    # 4. 升级回填：为每个现有 project 幂等补建一个 root workspace。
    # 不重写旧 session / 旧 run；中断后重跑不重复创建。
    # ============================================================
    project_rows = connection.execute(
        sa.text("SELECT id, root_path FROM projects WHERE id IS NOT NULL ORDER BY id")
    ).fetchall()
    for project_id, root_path in project_rows:
        if not root_path:
            continue
        # 幂等：已存在 root workspace 的 project 跳过
        existing = connection.execute(
            sa.text(
                "SELECT id FROM project_workspaces "
                "WHERE project_id = :pid AND kind = 'root' LIMIT 1"
            ),
            {"pid": project_id},
        ).fetchone()
        if existing is not None:
            continue
        root_path_sha256 = _normalized_path_sha256(root_path)
        connection.execute(
            sa.text(
                "INSERT INTO project_workspaces "
                "(project_id, kind, root_path, root_path_sha256, status, created_at, updated_at) "
                "VALUES (:pid, 'root', :rp, :sha, 'active', NOW(3), NOW(3))"
            ),
            {"pid": project_id, "rp": root_path, "sha": root_path_sha256},
        )


def _normalized_path_sha256(root_path: str) -> str:
    """与 core/workspaces 的路径规范化哈希一致：Windows 大小写不敏感。"""
    import hashlib

    normalized = root_path.replace("\\", "/").rstrip("/")
    if not normalized:
        normalized = "/"
    return hashlib.sha256(normalized.casefold().encode("utf-8")).hexdigest()


def downgrade() -> None:
    # ============================================================
    # 仅用于开发库/克隆库验证。正式应用回退不执行本函数。
    # 全部 DDL 带存在性检查：与 upgrade 的幂等哲学对称，兼容
    # MySQL 自动创建的 FK 支撑索引命名差异与历史结构残留，
    # 保证中断/循环演练不因 "key/constraint does not exist" 失败。
    # ============================================================
    connection = op.get_bind()
    if _constraint_exists(connection, "fk_agent_run_workspace"):
        op.drop_constraint("fk_agent_run_workspace", "agent_runs", type_="foreignkey")
    if _constraint_exists(connection, "fk_agent_run_project"):
        op.drop_constraint("fk_agent_run_project", "agent_runs", type_="foreignkey")
    if _index_exists(connection, "agent_runs", "idx_agent_run_project_workspace"):
        op.drop_index("idx_agent_run_project_workspace", table_name="agent_runs")
    for column in (
        "client_request_id",
        "permission_snapshot_json",
        "permission_mode",
        "reasoning_effort",
        "model_profile_id",
        "base_git_dirty",
        "base_branch_name",
        "base_head_sha",
        "workspace_id",
        "project_id",
    ):
        if _column_exists(connection, "agent_runs", column):
            op.drop_column("agent_runs", column)

    if _constraint_exists(connection, "fk_session_workspace"):
        op.drop_constraint("fk_session_workspace", "sessions", type_="foreignkey")
    if _constraint_exists(connection, "fk_session_project"):
        op.drop_constraint("fk_session_project", "sessions", type_="foreignkey")
    if _index_exists(connection, "sessions", "idx_session_workspace"):
        op.drop_index("idx_session_workspace", table_name="sessions")
    if _index_exists(connection, "sessions", "idx_session_project"):
        op.drop_index("idx_session_project", table_name="sessions")
    for column in (
        "archived_at",
        "pinned_at",
        "last_run_id",
        "workspace_id",
        "project_id",
        "kind",
    ):
        if _column_exists(connection, "sessions", column):
            op.drop_column("sessions", column)

    if _index_exists(connection, "project_workspaces", "idx_workspace_project_status"):
        op.drop_index("idx_workspace_project_status", table_name="project_workspaces")
    op.drop_table("project_workspaces")
