"""phase7: reliable daily layer - notifications / capture / OCR / diagnostics / integrity / search

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-08

对齐 docs/archive/phases/phase7-plan.md §6 与 docs/archive/phases/phase7-requirements.md §6/§7：
- app_notifications：统一通知中心，记录异步操作结果与可跳转来源（只存摘要，不存敏感正文）。
- capture_items：快速捕获草稿，保存来源、候选类型、处理状态与转化目标。
- ocr_jobs：OCR 队列，记录文档/文件、状态、引擎、输出与错误。
- diagnostic_runs：诊断包生成记录，保存路径、状态、脱敏摘要。
- data_integrity_findings：数据体检发现项，支持 ignored/resolved 避免重复打扰。
- search_recent_items：最近打开/搜索对象，供全局搜索排序。

ENUM 扩展：
- activities.kind 增加 'ocr'（OCR worker 写活动流）。
- documents.status 增加 'needs_ocr'（扫描件不再 hard fail，改入 OCR 路径）。

provider_call_audits 扩展（M6 生产化治理）：
- started_at / duration_ms：调用开始与耗时。
- estimated_input_tokens / estimated_output_tokens：token 估算（与现有 chars 并存）。
- error_code：失败分类（missing_api_key/unauthorized/network_error/timeout/rate_limited/model_not_found/provider_error）。
- fallback_used：是否回退本地 Ollama。

关联策略延续 phase6：跨域一律软引用（纯 BIGINT，不建外键）；通知/诊断/体检只存摘要，
不存敏感正文；OCR 输出进入文档前可追溯来源；integrity finding 支持 ignored/resolved；
repair plan 不自动执行破坏性操作。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- ENUM 扩展：activities.kind 增加 'ocr' ----
    op.alter_column(
        "activities",
        "kind",
        existing_type=mysql.ENUM(
            "tool", "document_import", "reindex", "system", name="activity_kind"
        ),
        type_=mysql.ENUM(
            "tool", "document_import", "reindex", "system", "ocr", name="activity_kind"
        ),
        existing_nullable=False,
    )

    # ---- ENUM 扩展：documents.status 增加 'needs_ocr' ----
    op.alter_column(
        "documents",
        "status",
        existing_type=mysql.ENUM(
            "pending", "processing", "ready", "failed", "deleting", name="doc_status"
        ),
        type_=mysql.ENUM(
            "pending",
            "processing",
            "ready",
            "failed",
            "deleting",
            "needs_ocr",
            name="doc_status",
        ),
        existing_nullable=False,
        existing_server_default=sa.text("'pending'"),
    )

    # ---- provider_call_audits 增加 M6 审计列 ----
    op.add_column(
        "provider_call_audits",
        sa.Column("started_at", mysql.DATETIME(fsp=3), nullable=True),
    )
    op.add_column(
        "provider_call_audits",
        sa.Column("duration_ms", mysql.INTEGER(), nullable=True),
    )
    op.add_column(
        "provider_call_audits",
        sa.Column("estimated_input_tokens", mysql.INTEGER(), nullable=True),
    )
    op.add_column(
        "provider_call_audits",
        sa.Column("estimated_output_tokens", mysql.INTEGER(), nullable=True),
    )
    op.add_column(
        "provider_call_audits",
        sa.Column("error_code", mysql.VARCHAR(64), nullable=True),
    )
    op.add_column(
        "provider_call_audits",
        sa.Column(
            "fallback_used",
            mysql.BOOLEAN(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # ---- app_notifications ----
    op.create_table(
        "app_notifications",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column(
            "level",
            mysql.ENUM(
                "info", "success", "warning", "error", name="notification_level_enum"
            ),
            nullable=False,
            server_default="info",
        ),
        sa.Column("kind", mysql.VARCHAR(64), nullable=False),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column("message", mysql.TEXT(), nullable=True),
        sa.Column(
            "status",
            mysql.ENUM(
                "unread", "read", "archived", name="notification_status_enum"
            ),
            nullable=False,
            server_default="unread",
        ),
        # 跨模块软引用：来源对象供跳转（如 document/agent_task/briefing）。
        sa.Column("source_type", mysql.VARCHAR(64), nullable=True),
        sa.Column("source_id", mysql.BIGINT(), nullable=True),
        sa.Column("action_type", mysql.VARCHAR(64), nullable=True),
        sa.Column("action_payload_json", mysql.JSON(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.Column("read_at", mysql.DATETIME(fsp=3), nullable=True),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_notification_status_created", "app_notifications", ["status", "created_at"]
    )
    op.create_index("idx_notification_kind", "app_notifications", ["kind"])

    # ---- capture_items ----
    op.create_table(
        "capture_items",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("title", mysql.VARCHAR(255), nullable=True),
        sa.Column("content_md", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column(
            "source",
            mysql.ENUM(
                "manual",
                "clipboard",
                "chat_message",
                "document_extraction",
                "file",
                "web",
                name="capture_source_enum",
            ),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("source_ref_json", mysql.JSON(), nullable=True),
        sa.Column(
            "candidate_type",
            mysql.ENUM(
                "inbox",
                "reminder",
                "memory",
                "learning_note",
                "document_note",
                "task_draft",
                name="capture_candidate_enum",
            ),
            nullable=True,
        ),
        sa.Column(
            "status",
            mysql.ENUM(
                "pending", "handled", "discarded", name="capture_status_enum"
            ),
            nullable=False,
            server_default="pending",
        ),
        # 转化目标软引用（inbox/reminder/memory 等）。
        sa.Column("target_type", mysql.VARCHAR(64), nullable=True),
        sa.Column("target_id", mysql.BIGINT(), nullable=True),
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
        sa.Column("handled_at", mysql.DATETIME(fsp=3), nullable=True),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_capture_status_created", "capture_items", ["status", "created_at"]
    )

    # ---- ocr_jobs ----
    op.create_table(
        "ocr_jobs",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        # 跨域软引用：documents 在另一域，不建外键。
        sa.Column("doc_id", mysql.BIGINT(), nullable=True),
        sa.Column("file_path", mysql.VARCHAR(2048), nullable=True),
        sa.Column(
            "source",
            mysql.ENUM(
                "document_import",
                "manual",
                "capture",
                name="ocr_source_enum",
            ),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "status",
            mysql.ENUM(
                "pending",
                "processing",
                "succeeded",
                "failed",
                "unavailable",
                "cancelled",
                name="ocr_status_enum",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("engine", mysql.VARCHAR(64), nullable=True),
        sa.Column("output_text", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column("error_message", mysql.TEXT(), nullable=True),
        sa.Column("source_type", mysql.VARCHAR(64), nullable=True),
        sa.Column("source_id", mysql.BIGINT(), nullable=True),
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
        sa.Column("started_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("finished_at", mysql.DATETIME(fsp=3), nullable=True),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_ocr_status", "ocr_jobs", ["status"])
    op.create_index("idx_ocr_doc", "ocr_jobs", ["doc_id"])

    # ---- diagnostic_runs ----
    op.create_table(
        "diagnostic_runs",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column(
            "status",
            mysql.ENUM(
                "pending", "succeeded", "failed", name="diag_run_status_enum"
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("output_path", mysql.VARCHAR(2048), nullable=True),
        sa.Column("summary_json", mysql.JSON(), nullable=True),
        sa.Column("error_message", mysql.TEXT(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.Column("finished_at", mysql.DATETIME(fsp=3), nullable=True),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_diag_run_created", "diagnostic_runs", ["created_at"])

    # ---- data_integrity_findings ----
    op.create_table(
        "data_integrity_findings",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("check_name", mysql.VARCHAR(64), nullable=False),
        sa.Column(
            "severity",
            mysql.ENUM(
                "info", "warning", "error", name="integrity_severity_enum"
            ),
            nullable=False,
            server_default="warning",
        ),
        sa.Column("ref_type", mysql.VARCHAR(64), nullable=True),
        sa.Column("ref_id", mysql.BIGINT(), nullable=True),
        sa.Column("detail_json", mysql.JSON(), nullable=True),
        sa.Column("suggested_action", mysql.VARCHAR(64), nullable=True),
        sa.Column(
            "status",
            mysql.ENUM(
                "open", "ignored", "resolved", name="integrity_finding_status_enum"
            ),
            nullable=False,
            server_default="open",
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
    op.create_index("idx_integrity_status", "data_integrity_findings", ["status"])
    op.create_index(
        "idx_integrity_check", "data_integrity_findings", ["check_name", "status"]
    )

    # ---- search_recent_items ----
    op.create_table(
        "search_recent_items",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("object_type", mysql.VARCHAR(64), nullable=False),
        sa.Column("object_id", mysql.BIGINT(), nullable=False),
        sa.Column("title", mysql.VARCHAR(255), nullable=True),
        sa.Column(
            "last_opened_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.Column(
            "open_count", mysql.INTEGER(), nullable=False, server_default=sa.text("1")
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "uk_search_recent",
        "search_recent_items",
        ["object_type", "object_id"],
        unique=True,
    )
    op.create_index(
        "idx_search_recent_opened", "search_recent_items", ["last_opened_at"]
    )


def downgrade() -> None:
    # search_recent_items
    op.drop_index("idx_search_recent_opened", table_name="search_recent_items")
    op.drop_index("uk_search_recent", table_name="search_recent_items")
    op.drop_table("search_recent_items")
    # data_integrity_findings
    op.drop_index("idx_integrity_check", table_name="data_integrity_findings")
    op.drop_index("idx_integrity_status", table_name="data_integrity_findings")
    op.drop_table("data_integrity_findings")
    # diagnostic_runs
    op.drop_index("idx_diag_run_created", table_name="diagnostic_runs")
    op.drop_table("diagnostic_runs")
    # ocr_jobs
    op.drop_index("idx_ocr_doc", table_name="ocr_jobs")
    op.drop_index("idx_ocr_status", table_name="ocr_jobs")
    op.drop_table("ocr_jobs")
    # capture_items
    op.drop_index("idx_capture_status_created", table_name="capture_items")
    op.drop_table("capture_items")
    # app_notifications
    op.drop_index("idx_notification_kind", table_name="app_notifications")
    op.drop_index("idx_notification_status_created", table_name="app_notifications")
    op.drop_table("app_notifications")
    # provider_call_audits M6 列
    op.drop_column("provider_call_audits", "fallback_used")
    op.drop_column("provider_call_audits", "error_code")
    op.drop_column("provider_call_audits", "estimated_output_tokens")
    op.drop_column("provider_call_audits", "estimated_input_tokens")
    op.drop_column("provider_call_audits", "duration_ms")
    op.drop_column("provider_call_audits", "started_at")
    # documents.status 回退（移除 'needs_ocr'）
    op.alter_column(
        "documents",
        "status",
        existing_type=mysql.ENUM(
            "pending",
            "processing",
            "ready",
            "failed",
            "deleting",
            "needs_ocr",
            name="doc_status",
        ),
        type_=mysql.ENUM(
            "pending", "processing", "ready", "failed", "deleting", name="doc_status"
        ),
        existing_nullable=False,
        existing_server_default=sa.text("'pending'"),
    )
    # activities.kind 回退（移除 'ocr'）
    op.alter_column(
        "activities",
        "kind",
        existing_type=mysql.ENUM(
            "tool", "document_import", "reindex", "system", "ocr", name="activity_kind"
        ),
        type_=mysql.ENUM(
            "tool", "document_import", "reindex", "system", name="activity_kind"
        ),
        existing_nullable=False,
    )
