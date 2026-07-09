"""phase8: release-quality & extension layer - test runs / release artifacts / upgrade smoke / integrations / extensions

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-09

对齐 docs/phase8-plan.md §6 与 docs/phase8-requirements.md §6/§7：
- test_runs：发布检查 / E2E / 性能基线 / 升级 smoke / 诊断包脱敏 smoke 的运行摘要。
  只保存摘要、状态、路径与 hash，不保存完整日志中的敏感内容。
- release_artifacts：安装包 / sidecar / latest.json / 签名 / 清单的 sha256、平台与签名状态。
  不保存证书或密钥。
- upgrade_smoke_runs：vN -> vN+1 升级 smoke 的前后版本、样本数据摘要、数据保留与 schema 检查结果。
  样本数据必须可重建，不依赖用户真实隐私数据。
- integration_sources：本地集成源配置与状态。第八阶段只做本地文件型集成，config_json 不得保存敏感凭据。
- integration_imports：单次集成导入的来源、解析摘要、目标对象引用与可撤销信息（reversal_info_json）。
- extension_registry_items：扩展注册项持久化启用状态。描述符在内存注册表定义，本表只持久化 enabled 覆盖。

关联策略延续 phase6/7：跨域一律软引用（纯 BIGINT，不建外键）；测试/发布/集成记录只存摘要与路径，
不存敏感正文；集成源不存凭据；扩展启用/禁用不得绕过审批状态机。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- test_runs ----
    op.create_table(
        "test_runs",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column(
            "kind",
            mysql.ENUM(
                "release_check",
                "e2e",
                "performance",
                "upgrade_smoke",
                "diagnostic_smoke",
                name="test_run_kind_enum",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            mysql.ENUM(
                "running", "passed", "failed", "skipped", name="test_run_status_enum"
            ),
            nullable=False,
            server_default="running",
        ),
        sa.Column("version", mysql.VARCHAR(64), nullable=True),
        sa.Column("git_commit", mysql.VARCHAR(64), nullable=True),
        sa.Column("schema_head", mysql.VARCHAR(64), nullable=True),
        sa.Column("summary_json", mysql.JSON(), nullable=True),
        sa.Column("artifact_path", mysql.VARCHAR(2048), nullable=True),
        sa.Column("started_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("finished_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_test_run_kind_created", "test_runs", ["kind", "created_at"])

    # ---- release_artifacts ----
    op.create_table(
        "release_artifacts",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("version", mysql.VARCHAR(64), nullable=False),
        sa.Column(
            "kind",
            mysql.ENUM(
                "installer",
                "sidecar",
                "latest_json",
                "signature",
                "manifest",
                name="release_artifact_kind_enum",
            ),
            nullable=False,
        ),
        sa.Column("platform", mysql.VARCHAR(64), nullable=False),
        sa.Column("path", mysql.VARCHAR(2048), nullable=True),
        sa.Column("sha256", mysql.CHAR(64), nullable=True),
        sa.Column("size_bytes", mysql.BIGINT(), nullable=True),
        sa.Column(
            "code_signed",
            mysql.BOOLEAN(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_release_artifact_version", "release_artifacts", ["version", "kind"]
    )
    op.create_index("idx_release_artifact_platform", "release_artifacts", ["platform"])

    # ---- upgrade_smoke_runs ----
    op.create_table(
        "upgrade_smoke_runs",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("from_version", mysql.VARCHAR(64), nullable=False),
        sa.Column("to_version", mysql.VARCHAR(64), nullable=False),
        sa.Column(
            "platform",
            mysql.VARCHAR(64),
            nullable=False,
            server_default="windows-x86_64",
        ),
        sa.Column(
            "result",
            mysql.ENUM(
                "passed", "failed", "blocked", name="upgrade_smoke_result_enum"
            ),
            nullable=False,
            server_default="blocked",
        ),
        sa.Column("data_preserved", mysql.BOOLEAN(), nullable=True),
        sa.Column("schema_ok", mysql.BOOLEAN(), nullable=True),
        sa.Column("sample_summary_json", mysql.JSON(), nullable=True),
        sa.Column("notes_md", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column("artifact_path", mysql.VARCHAR(2048), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_upgrade_smoke_created", "upgrade_smoke_runs", ["created_at"])

    # ---- integration_sources ----
    op.create_table(
        "integration_sources",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column(
            "kind",
            mysql.ENUM(
                "ics_calendar",
                "bookmarks_html",
                "eml_mail",
                "folder_watch",
                name="integration_source_kind_enum",
            ),
            nullable=False,
        ),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        # config_json 只存文件路径与选项，严禁保存凭据（第八阶段仅本地文件型集成）。
        sa.Column("config_json", mysql.JSON(), nullable=True),
        sa.Column(
            "enabled",
            mysql.BOOLEAN(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("last_run_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "last_status",
            mysql.ENUM(
                "pending",
                "succeeded",
                "failed",
                "reverted",
                name="integration_source_status_enum",
            ),
            nullable=True,
        ),
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
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_integration_source_kind", "integration_sources", ["kind", "enabled"]
    )

    # ---- integration_imports ----
    op.create_table(
        "integration_imports",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        # 跨域软引用：integration_sources 同域但不级联删除（保留可撤销记录）。
        sa.Column("source_id", mysql.BIGINT(), nullable=True),
        sa.Column("source_kind", mysql.VARCHAR(64), nullable=False),
        sa.Column("summary_json", mysql.JSON(), nullable=True),
        # 目标对象软引用（reminder / inbox / capture / document）。
        sa.Column("target_type", mysql.VARCHAR(64), nullable=True),
        sa.Column("target_id", mysql.BIGINT(), nullable=True),
        sa.Column(
            "reversible",
            mysql.BOOLEAN(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        # reversal_info_json 记录本次导入创建的所有目标对象 id，供撤销使用。
        sa.Column("reversal_info_json", mysql.JSON(), nullable=True),
        sa.Column(
            "status",
            mysql.ENUM(
                "previewed",
                "imported",
                "reverted",
                "failed",
                name="integration_import_status_enum",
            ),
            nullable=False,
            server_default="previewed",
        ),
        sa.Column("error_message", mysql.TEXT(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.Column("reverted_at", mysql.DATETIME(fsp=3), nullable=True),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_integration_import_source", "integration_imports", ["source_id", "status"]
    )
    op.create_index(
        "idx_integration_import_created", "integration_imports", ["created_at"]
    )

    # ---- extension_registry_items ----
    op.create_table(
        "extension_registry_items",
        sa.Column("ext_id", mysql.VARCHAR(128), primary_key=True),
        sa.Column("kind", mysql.VARCHAR(64), nullable=False),
        sa.Column("title", mysql.VARCHAR(255), nullable=True),
        sa.Column(
            "risk_level",
            mysql.ENUM(
                "safe", "confirm", "restricted", name="extension_risk_enum"
            ),
            nullable=True,
        ),
        sa.Column(
            "enabled",
            mysql.BOOLEAN(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_extension_registry_kind", "extension_registry_items", ["kind", "enabled"]
    )


def downgrade() -> None:
    # extension_registry_items
    op.drop_index(
        "idx_extension_registry_kind", table_name="extension_registry_items"
    )
    op.drop_table("extension_registry_items")
    # integration_imports
    op.drop_index(
        "idx_integration_import_created", table_name="integration_imports"
    )
    op.drop_index(
        "idx_integration_import_source", table_name="integration_imports"
    )
    op.drop_table("integration_imports")
    # integration_sources
    op.drop_index(
        "idx_integration_source_kind", table_name="integration_sources"
    )
    op.drop_table("integration_sources")
    # upgrade_smoke_runs
    op.drop_index("idx_upgrade_smoke_created", table_name="upgrade_smoke_runs")
    op.drop_table("upgrade_smoke_runs")
    # release_artifacts
    op.drop_index("idx_release_artifact_platform", table_name="release_artifacts")
    op.drop_index(
        "idx_release_artifact_version", table_name="release_artifacts"
    )
    op.drop_table("release_artifacts")
    # test_runs
    op.drop_index("idx_test_run_kind_created", table_name="test_runs")
    op.drop_table("test_runs")
