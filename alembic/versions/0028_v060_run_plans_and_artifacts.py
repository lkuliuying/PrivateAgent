"""v0.6.0 C0 契约迁移 2/2：RunPlan 与 Artifact 最小契约。

冻结依据：``docs/releases/v0.6.0/v0.6.0-c0-contracts-20260820.md`` §4.2。

变更：
- 新增 ``run_plan_items``：持久化 run 计划（C0-D08，独立表，不复用 run_steps）。
  同一 plan version 的 item_key/ordinal 唯一；状态限定为 pending/in_progress/
  completed/blocked/failed/cancelled；evidence_json 只放有界引用。
- 新增 ``agent_run_artifacts``：产物引用契约（v0.6.0 不提供文件下载/外部上传）。

正式应用回退不执行本迁移的 downgrade；downgrade 仅用于开发库/克隆库验证
（先删本迁移的表，再回退 0027 的列）。

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================================
    # 1. run_plan_items
    # ============================================================
    op.create_table(
        "run_plan_items",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("run_id", mysql.CHAR(36), nullable=False),
        sa.Column("plan_version", mysql.INTEGER(), nullable=False),
        sa.Column("item_key", mysql.VARCHAR(128), nullable=False),
        sa.Column("ordinal", mysql.INTEGER(), nullable=False),
        sa.Column("title", mysql.VARCHAR(512), nullable=False),
        sa.Column("detail", mysql.TEXT(), nullable=True),
        sa.Column(
            "status",
            mysql.ENUM(
                "pending", "in_progress", "completed", "blocked",
                "failed", "cancelled",
                charset="utf8mb4",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("evidence_json", mysql.JSON(), nullable=True),
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
            name="fk_run_plan_item_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_run_plan_items"),
        sa.UniqueConstraint(
            "run_id", "plan_version", "item_key", name="uk_run_plan_item_key"
        ),
        sa.UniqueConstraint(
            "run_id", "plan_version", "ordinal", name="uk_run_plan_item_ordinal"
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "idx_run_plan_run", "run_plan_items", ["run_id", "plan_version"]
    )

    # ============================================================
    # 2. agent_run_artifacts（只冻结产物引用）
    # ============================================================
    op.create_table(
        "agent_run_artifacts",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("run_id", mysql.CHAR(36), nullable=False),
        sa.Column("step_id", mysql.CHAR(36), nullable=True),
        sa.Column(
            "kind",
            mysql.ENUM(
                "diff", "file", "command_output", "test_report", "summary",
                charset="utf8mb4",
            ),
            nullable=False,
        ),
        sa.Column("title", mysql.VARCHAR(512), nullable=False),
        sa.Column("rel_path", mysql.VARCHAR(2048), nullable=True),
        sa.Column("content_sha256", mysql.CHAR(64), nullable=True),
        sa.Column("metadata_json", mysql.JSON(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name="fk_run_artifact_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["run_steps.id"],
            name="fk_run_artifact_step",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_run_artifacts"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "idx_run_artifact_run", "agent_run_artifacts", ["run_id", "created_at"]
    )


def downgrade() -> None:
    # 仅用于开发库/克隆库验证；正式应用回退不执行本函数。
    op.drop_index("idx_run_artifact_run", table_name="agent_run_artifacts")
    op.drop_table("agent_run_artifacts")
    op.drop_index("idx_run_plan_run", table_name="run_plan_items")
    op.drop_table("run_plan_items")
