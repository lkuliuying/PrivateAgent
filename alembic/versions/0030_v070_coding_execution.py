"""v0.7.0 E0 契约迁移：可信编码执行（PatchSet / 模型 profile / 命令 profile 版本化）。

冻结依据：``docs/releases/v0.7.0/v0.7.0-e0-contracts-20260821.md`` §2/§5/§6。

变更：
- 新增 ``coding_patch_sets`` / ``coding_patch_set_files``：run 绑定的多文件
  PatchSet 与文件级操作（create/update/delete/rename），状态机含
  ``partial_unknown`` 人工处置态。与 M4 遗留 ``patch_sets`` 表分离，
  旧表不动（回退性）。
- 新增 ``model_profiles``：模型能力显式声明，不存任何 secret。
- ``project_command_profiles`` 增加版本化列（profile_version / cwd_rel /
  env_allowlist / allow_network / result_parser / risk_level / capability /
  max_output_bytes / description，全部 additive）。
- ``agent_run_artifacts.kind`` ENUM 扩展（v0.7.0 新增 6 种 kind，旧值保留；
  MySQL 8 支持 ENUM 成员追加，MySQL 5.7 需要整列重建——用条件判断兼容）。

DDL 全部幂等（if_not_exists / 存在性检查）：MySQL DDL 隐式提交，
迁移中断后重跑不会因表/列/索引/约束已存在而失败。

正式应用回退不执行本迁移的 downgrade；downgrade 仅用于开发库/克隆库验证。

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
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


def _index_exists(conn, table: str, index: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = :t AND index_name = :i"
        ),
        {"t": table, "i": index},
    ).fetchone()
    return row is not None


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
    # ============================================================
    # 1. coding_patch_sets
    # ============================================================
    op.create_table(
        "coding_patch_sets",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("run_id", mysql.CHAR(36), nullable=False),
        sa.Column("project_id", mysql.BIGINT(), nullable=False),
        sa.Column("workspace_id", mysql.BIGINT(), nullable=False),
        sa.Column("base_head_sha", mysql.VARCHAR(64), nullable=True),
        sa.Column("parameters_hash", mysql.CHAR(64), nullable=False),
        sa.Column("preview_version", mysql.INTEGER(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            mysql.ENUM(
                "previewed", "applied", "failed", "rolled_back",
                "partial_unknown", "rejected",
                charset="utf8mb4",
            ),
            nullable=False,
            server_default="previewed",
        ),
        sa.Column("file_count", mysql.INTEGER(), nullable=False, server_default="0"),
        sa.Column("additions", mysql.INTEGER(), nullable=False, server_default="0"),
        sa.Column("deletions", mysql.INTEGER(), nullable=False, server_default="0"),
        sa.Column("truncated", mysql.BOOLEAN(), nullable=False, server_default="0"),
        sa.Column("diff_total_bytes", mysql.INTEGER(), nullable=False, server_default="0"),
        sa.Column("error_code", mysql.VARCHAR(64), nullable=True),
        sa.Column("error_message", mysql.TEXT(), nullable=True),
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
            ["run_id"],
            ["agent_runs.id"],
            name="fk_coding_patch_set_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_coding_patch_set_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["project_workspaces.id"],
            name="fk_coding_patch_set_workspace",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_coding_patch_sets"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
        if_not_exists=True,
    )
    if not _index_exists(connection, "coding_patch_sets", "idx_coding_patch_set_run"):
        op.create_index(
            "idx_coding_patch_set_run",
            "coding_patch_sets",
            ["run_id", "created_at"],
        )
    if not _index_exists(
        connection, "coding_patch_sets", "idx_coding_patch_set_workspace"
    ):
        op.create_index(
            "idx_coding_patch_set_workspace",
            "coding_patch_sets",
            ["workspace_id", "status"],
        )

    # ============================================================
    # 2. coding_patch_set_files
    # ============================================================
    op.create_table(
        "coding_patch_set_files",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("patch_set_id", mysql.CHAR(36), nullable=False),
        sa.Column("ordinal", mysql.INTEGER(), nullable=False),
        sa.Column(
            "operation",
            mysql.ENUM("create", "update", "delete", "rename", charset="utf8mb4"),
            nullable=False,
        ),
        sa.Column("rel_path", mysql.VARCHAR(2048), nullable=False),
        sa.Column("new_rel_path", mysql.VARCHAR(2048), nullable=True),
        sa.Column("old_sha256", mysql.CHAR(64), nullable=True),
        sa.Column("new_sha256", mysql.CHAR(64), nullable=True),
        sa.Column(
            "new_content",
            mysql.MEDIUMTEXT(),
            nullable=True,
            comment="预览时冻结的新内容（apply 事实源；delete 为 NULL）",
        ),
        sa.Column(
            "truncated",
            mysql.BOOLEAN(),
            nullable=False,
            server_default="0",
            comment="单文件 diff 是否被截断",
        ),
        sa.Column("diff_text", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column(
            "status",
            mysql.ENUM(
                "pending", "applied", "rolled_back", "unknown",
                charset="utf8mb4",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error_message", mysql.TEXT(), nullable=True),
        sa.ForeignKeyConstraint(
            ["patch_set_id"],
            ["coding_patch_sets.id"],
            name="fk_coding_patch_file_set",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_coding_patch_set_files"),
        sa.UniqueConstraint(
            "patch_set_id", "ordinal", name="uk_coding_patch_file_ordinal"
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
        if_not_exists=True,
    )
    if not _index_exists(
        connection, "coding_patch_set_files", "idx_coding_patch_file_set"
    ):
        op.create_index(
            "idx_coding_patch_file_set", "coding_patch_set_files", ["patch_set_id"]
        )

    if not _column_exists(connection, "coding_patch_set_files", "new_content"):
        op.add_column(
            "coding_patch_set_files",
            sa.Column(
                "new_content",
                mysql.MEDIUMTEXT(),
                nullable=True,
                comment="预览时冻结的新内容（apply 事实源；delete 为 NULL）",
            ),
        )

    if not _column_exists(connection, "coding_patch_set_files", "truncated"):
        op.add_column(
            "coding_patch_set_files",
            sa.Column(
                "truncated",
                mysql.BOOLEAN(),
                nullable=False,
                server_default="0",
                comment="单文件 diff 是否被截断",
            ),
        )

    # ============================================================
    # 3. model_profiles（不存 secret；能力显式声明）
    # ============================================================
    op.create_table(
        "model_profiles",
        sa.Column("id", mysql.VARCHAR(128), nullable=False),
        sa.Column("provider", mysql.VARCHAR(100), nullable=False),
        sa.Column("display_name", mysql.VARCHAR(200), nullable=False),
        sa.Column("is_local", mysql.BOOLEAN(), nullable=False, server_default="0"),
        sa.Column(
            "native_tool_calls", mysql.BOOLEAN(), nullable=False, server_default="1"
        ),
        sa.Column(
            "supports_streaming", mysql.BOOLEAN(), nullable=False, server_default="0"
        ),
        sa.Column(
            "supports_structured_output",
            mysql.BOOLEAN(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("supports_vision", mysql.BOOLEAN(), nullable=False, server_default="0"),
        sa.Column(
            "context_tokens", mysql.INTEGER(), nullable=False, server_default="8192"
        ),
        sa.Column("reasoning_efforts_json", mysql.JSON(), nullable=True),
        sa.Column(
            "usage_reporting", mysql.BOOLEAN(), nullable=False, server_default="0"
        ),
        sa.Column("enabled", mysql.BOOLEAN(), nullable=False, server_default="1"),
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
        sa.PrimaryKeyConstraint("id", name="pk_model_profiles"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
        if_not_exists=True,
    )
    if not _index_exists(connection, "model_profiles", "idx_model_profile_provider"):
        op.create_index(
            "idx_model_profile_provider",
            "model_profiles",
            ["provider", "enabled"],
        )

    # ============================================================
    # 4. project_command_profiles 版本化扩展（全部 additive）
    # ============================================================
    profile_columns = {
        "profile_version": sa.Column(
            "profile_version", mysql.INTEGER(), nullable=False, server_default="1"
        ),
        "cwd_rel": sa.Column("cwd_rel", mysql.VARCHAR(2048), nullable=True),
        "env_allowlist": sa.Column("env_allowlist", mysql.JSON(), nullable=True),
        "allow_network": sa.Column(
            "allow_network", mysql.BOOLEAN(), nullable=False, server_default="0"
        ),
        "result_parser": sa.Column("result_parser", mysql.VARCHAR(64), nullable=True),
        "risk_level": sa.Column(
            "risk_level", mysql.VARCHAR(16), nullable=False, server_default="confirm"
        ),
        "capability": sa.Column("capability", mysql.VARCHAR(64), nullable=True),
        "max_output_bytes": sa.Column("max_output_bytes", mysql.BIGINT(), nullable=True),
        "description": sa.Column("description", mysql.VARCHAR(512), nullable=True),
    }
    for column_name, column in profile_columns.items():
        if not _column_exists(connection, "project_command_profiles", column_name):
            op.add_column("project_command_profiles", column)

    # ============================================================
    # 5. agent_run_artifacts.kind ENUM 扩展（旧值保留；v0.7.0 新增 6 种）
    # ============================================================
    artifact_kinds = (
        "diff",
        "file",
        "command_output",
        "test_report",
        "summary",
        "patch_preview",
        "patch_applied",
        "command_result",
        "lint_report",
        "build_report",
        "final_report",
    )
    if not _enum_has_value(connection, "agent_run_artifacts", "kind", "final_report"):
        op.execute(
            "ALTER TABLE agent_run_artifacts "
            f"MODIFY COLUMN kind ENUM({','.join(repr(k) for k in artifact_kinds)}) "
            "NOT NULL"
        )


def downgrade() -> None:
    # 仅用于开发库/克隆库验证；正式应用回退不执行本函数。
    # 先删子表再删父表；FK 约束/索引带存在性检查，循环演练不中断。
    connection = op.get_bind()
    if _constraint_exists(connection, "fk_coding_patch_file_set"):
        op.drop_constraint(
            "fk_coding_patch_file_set", "coding_patch_set_files", type_="foreignkey"
        )
    if _index_exists(connection, "coding_patch_set_files", "idx_coding_patch_file_set"):
        op.drop_index("idx_coding_patch_file_set", table_name="coding_patch_set_files")
    op.drop_table("coding_patch_set_files")

    if _constraint_exists(connection, "fk_coding_patch_set_run"):
        op.drop_constraint(
            "fk_coding_patch_set_run", "coding_patch_sets", type_="foreignkey"
        )
    if _constraint_exists(connection, "fk_coding_patch_set_project"):
        op.drop_constraint(
            "fk_coding_patch_set_project", "coding_patch_sets", type_="foreignkey"
        )
    if _constraint_exists(connection, "fk_coding_patch_set_workspace"):
        op.drop_constraint(
            "fk_coding_patch_set_workspace", "coding_patch_sets", type_="foreignkey"
        )
    if _index_exists(connection, "coding_patch_sets", "idx_coding_patch_set_run"):
        op.drop_index("idx_coding_patch_set_run", table_name="coding_patch_sets")
    if _index_exists(
        connection, "coding_patch_sets", "idx_coding_patch_set_workspace"
    ):
        op.drop_index(
            "idx_coding_patch_set_workspace", table_name="coding_patch_sets"
        )
    op.drop_table("coding_patch_sets")

    if _index_exists(connection, "model_profiles", "idx_model_profile_provider"):
        op.drop_index("idx_model_profile_provider", table_name="model_profiles")
    op.drop_table("model_profiles")

    for column_name in (
        "description",
        "max_output_bytes",
        "capability",
        "risk_level",
        "result_parser",
        "allow_network",
        "env_allowlist",
        "cwd_rel",
        "profile_version",
    ):
        if _column_exists(connection, "project_command_profiles", column_name):
            op.drop_column("project_command_profiles", column_name)

    # artifact kind ENUM 回退到 v0.6.0 集合（仅开发库验证用）
    legacy_kinds = ("diff", "file", "command_output", "test_report", "summary")
    if not _enum_has_value(connection, "agent_run_artifacts", "kind", "final_report"):
        op.execute(
            "ALTER TABLE agent_run_artifacts "
            f"MODIFY COLUMN kind ENUM({','.join(repr(k) for k in legacy_kinds)}) "
            "NOT NULL"
        )
