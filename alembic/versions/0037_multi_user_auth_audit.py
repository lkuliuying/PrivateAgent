"""多用户认证、租户归属与操作审计。

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-29
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TENANT_COLUMN_TABLES = (
    "sessions",
    "messages",
    "documents",
    "doc_chunks",
    "document_index_versions",
    "document_index_chunks",
    "document_index_chunk_provenance",
    "document_index_heads",
    "settings",
    "tool_calls",
    "trusted_paths",
    "activities",
    "projects",
    "project_workspaces",
    "project_files",
    "learning_topics",
    "learning_nodes",
    "learning_notes",
    "learning_cards",
    "learning_quizzes",
    "learning_quiz_attempts",
    "agent_tasks",
    "agent_task_steps",
    "agent_evidence",
    "memory_items",
    "memory_revisions",
    "memory_conflicts",
    "conversation_summaries",
    "memory_events",
    "learning_reviews",
    "project_command_profiles",
    "patch_sets",
    "patch_files",
    "coding_patch_sets",
    "coding_patch_set_files",
    "model_profiles",
    "model_tool_profile_snapshots",
    "document_collections",
    "document_collection_items",
    "document_extractions",
    "inbox_items",
    "reminders",
    "personal_goals",
    "goal_links",
    "goal_checkins",
    "briefings",
    "provider_call_audits",
    "app_notifications",
    "capture_items",
    "ocr_jobs",
    "diagnostic_runs",
    "data_integrity_findings",
    "search_recent_items",
    "test_runs",
    "release_artifacts",
    "upgrade_smoke_runs",
    "integration_sources",
    "integration_imports",
    "extension_registry_items",
    "agent_runs",
    "run_steps",
    "agent_run_events",
    "tool_approvals",
    "agent_run_checkpoints",
    "agent_tool_executions",
    "tool_execution_output",
    "http_endpoint_profiles",
    "sql_readonly_profiles",
    "mcp_servers",
    "mcp_call_logs",
    "compatibility_telemetry",
    "run_plan_items",
    "agent_run_artifacts",
    "session_project_bindings",
    "full_access_grants",
)


def _table_exists(conn, table: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = :table"
            ),
            {"table": table},
        ).scalar()
    )


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = :table "
                "AND column_name = :column"
            ),
            {"table": table, "column": column},
        ).scalar()
    )


def _index_exists(conn, table: str, index: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = :table "
                "AND index_name = :index"
            ),
            {"table": table, "index": index},
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "users"):
        op.create_table(
            "users",
            sa.Column("id", mysql.BIGINT(), autoincrement=True, nullable=False),
            sa.Column("email", mysql.VARCHAR(length=320), nullable=False),
            sa.Column("display_name", mysql.VARCHAR(length=100), nullable=False),
            sa.Column("password_hash", mysql.VARCHAR(length=512), nullable=False),
            sa.Column("role", mysql.VARCHAR(length=16), server_default="user", nullable=False),
            sa.Column("status", mysql.VARCHAR(length=16), server_default="active", nullable=False),
            sa.Column("last_login_at", mysql.DATETIME(fsp=3), nullable=True),
            sa.Column(
                "created_at",
                mysql.DATETIME(fsp=3),
                server_default=sa.text("CURRENT_TIMESTAMP(3)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                mysql.DATETIME(fsp=3),
                server_default=sa.text("CURRENT_TIMESTAMP(3)"),
                nullable=False,
            ),
            sa.Column("owner_user_id", mysql.BIGINT(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email", name="uk_users_email"),
            mysql_charset="utf8mb4",
        )
        op.create_index("idx_users_role_status", "users", ["role", "status"])
        op.create_index("idx_users_created_at", "users", ["created_at"])
        op.create_index("ix_users_owner_user_id", "users", ["owner_user_id"])

    if not _table_exists(conn, "auth_sessions"):
        op.create_table(
            "auth_sessions",
            sa.Column("id", mysql.CHAR(length=36), nullable=False),
            sa.Column("user_id", mysql.BIGINT(), nullable=False),
            sa.Column("token_hash", mysql.CHAR(length=64), nullable=False),
            sa.Column("expires_at", mysql.DATETIME(fsp=3), nullable=False),
            sa.Column("revoked_at", mysql.DATETIME(fsp=3), nullable=True),
            sa.Column("last_used_at", mysql.DATETIME(fsp=3), nullable=True),
            sa.Column(
                "created_at",
                mysql.DATETIME(fsp=3),
                server_default=sa.text("CURRENT_TIMESTAMP(3)"),
                nullable=False,
            ),
            sa.Column("owner_user_id", mysql.BIGINT(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash", name="uk_auth_sessions_token_hash"),
            mysql_charset="utf8mb4",
        )
        op.create_index(
            "idx_auth_sessions_user_expiry", "auth_sessions", ["user_id", "expires_at"]
        )
        op.create_index(
            "idx_auth_sessions_expiry", "auth_sessions", ["expires_at", "revoked_at"]
        )
        op.create_index(
            "ix_auth_sessions_owner_user_id", "auth_sessions", ["owner_user_id"]
        )

    if not _table_exists(conn, "audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("id", mysql.BIGINT(), autoincrement=True, nullable=False),
            sa.Column("request_id", mysql.CHAR(length=36), nullable=False),
            sa.Column("actor_user_id", mysql.BIGINT(), nullable=True),
            sa.Column("actor_type", mysql.VARCHAR(length=16), server_default="anonymous", nullable=False),
            sa.Column("method", mysql.VARCHAR(length=10), nullable=False),
            sa.Column("path", mysql.VARCHAR(length=512), nullable=False),
            sa.Column("status_code", mysql.INTEGER(), nullable=False),
            sa.Column("duration_ms", mysql.BIGINT(), nullable=False),
            sa.Column("client_ip", mysql.VARCHAR(length=64), nullable=True),
            sa.Column("user_agent", mysql.VARCHAR(length=512), nullable=True),
            sa.Column(
                "created_at",
                mysql.DATETIME(fsp=3),
                server_default=sa.text("CURRENT_TIMESTAMP(3)"),
                nullable=False,
            ),
            sa.Column("owner_user_id", mysql.BIGINT(), nullable=True),
            sa.ForeignKeyConstraint(
                ["actor_user_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("request_id", name="uk_audit_logs_request_id"),
            mysql_charset="utf8mb4",
        )
        op.create_index("idx_audit_logs_created", "audit_logs", ["created_at"])
        op.create_index(
            "idx_audit_logs_actor_created",
            "audit_logs",
            ["actor_user_id", "created_at"],
        )
        op.create_index(
            "idx_audit_logs_status_created",
            "audit_logs",
            ["status_code", "created_at"],
        )
        op.create_index("ix_audit_logs_owner_user_id", "audit_logs", ["owner_user_id"])

    for table in TENANT_COLUMN_TABLES:
        if not _table_exists(conn, table):
            continue
        if not _column_exists(conn, table, "owner_user_id"):
            op.add_column(
                table,
                sa.Column("owner_user_id", mysql.BIGINT(), nullable=True),
            )
        index_name = f"ix_{table}_owner_user_id"
        if not _index_exists(conn, table, index_name):
            op.create_index(index_name, table, ["owner_user_id"])


def downgrade() -> None:
    conn = op.get_bind()
    for table in reversed(TENANT_COLUMN_TABLES):
        if not _table_exists(conn, table) or not _column_exists(
            conn, table, "owner_user_id"
        ):
            continue
        index_name = f"ix_{table}_owner_user_id"
        if _index_exists(conn, table, index_name):
            op.drop_index(index_name, table_name=table)
        op.drop_column(table, "owner_user_id")
    for table in ("audit_logs", "auth_sessions", "users"):
        if _table_exists(conn, table):
            op.drop_table(table)
