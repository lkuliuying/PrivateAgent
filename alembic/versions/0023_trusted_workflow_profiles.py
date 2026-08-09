"""Add non-sensitive HTTP/SQL workflow profiles.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-09

v0.5.0 B0 决策（docs/v0.5.0-b0-contracts-20260809.md §6）：0014–0016 已
承载 approvals / checkpoints / executions，Patch 与命令工作流直接复用；
HTTP 与只读 SQL 工作流需要持久化非敏感 profile，新增本 additive 迁移：

- ``http_endpoint_profiles``：endpoint 目标/方法/Schema/大小/超时/非敏感头
  + secret reference（明文 key 只进 OS keyring，数据库只保存引用）；
- ``sql_readonly_profiles``：连接元数据（driver/host/port/database/
  username）+ password secret reference；不保存 DSN、密码或明文凭据。

两表均不可通过 SQL 或 header 字段保存明文 secret；备份导出按
``core/backup.py`` 的 secret 清理策略只保留"已配置"状态。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "http_endpoint_profiles",
        sa.Column("id", mysql.INTEGER(), primary_key=True, autoincrement=True),
        sa.Column("name", mysql.VARCHAR(64), nullable=False),
        sa.Column("scheme", mysql.VARCHAR(8), nullable=False, server_default="https"),
        sa.Column("host", mysql.VARCHAR(255), nullable=False),
        sa.Column("port", mysql.INTEGER(), nullable=False),
        sa.Column(
            "path_prefix", mysql.VARCHAR(1024), nullable=False, server_default="/"
        ),
        sa.Column("allowed_methods_json", mysql.JSON(), nullable=False),
        sa.Column("request_schema_json", mysql.JSON(), nullable=True),
        sa.Column("response_schema_json", mysql.JSON(), nullable=True),
        sa.Column(
            "max_request_bytes",
            mysql.INTEGER(),
            nullable=False,
            server_default="65536",
        ),
        sa.Column(
            "max_response_bytes",
            mysql.INTEGER(),
            nullable=False,
            server_default="1048576",
        ),
        sa.Column(
            "timeout_ms", mysql.INTEGER(), nullable=False, server_default="30000"
        ),
        # 仅允许非敏感固定请求头；敏感头只能通过 secret_refs_json 引用 keyring。
        sa.Column("headers_json", mysql.JSON(), nullable=False),
        sa.Column("secret_refs_json", mysql.JSON(), nullable=False),
        # 非敏感重试策略（max_attempts / backoff 秒），不包含任何凭据。
        sa.Column("retry_policy_json", mysql.JSON(), nullable=True),
        sa.Column("enabled", mysql.TINYINT(1), nullable=False, server_default="0"),
        sa.Column("version", mysql.INTEGER(), nullable=False, server_default="1"),
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
        sa.UniqueConstraint("name", name="uk_http_endpoint_profile_name"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_http_endpoint_profile_enabled",
        "http_endpoint_profiles",
        ["enabled"],
    )
    op.create_table(
        "sql_readonly_profiles",
        sa.Column("id", mysql.INTEGER(), primary_key=True, autoincrement=True),
        sa.Column("name", mysql.VARCHAR(64), nullable=False),
        sa.Column("dialect", mysql.VARCHAR(16), nullable=False),
        sa.Column("host", mysql.VARCHAR(255), nullable=False),
        sa.Column("port", mysql.INTEGER(), nullable=False),
        sa.Column("database", mysql.VARCHAR(255), nullable=False),
        # username 属非敏感连接元数据；password 只走 keyring，见 password_secret_ref。
        sa.Column("username", mysql.VARCHAR(255), nullable=True),
        sa.Column("password_secret_ref", mysql.VARCHAR(512), nullable=False),
        # 仅非敏感连接选项（ssl 开关、字符集等），禁止凭据。
        sa.Column("connect_args_json", mysql.JSON(), nullable=True),
        sa.Column("max_rows", mysql.INTEGER(), nullable=False, server_default="1000"),
        sa.Column(
            "max_bytes", mysql.INTEGER(), nullable=False, server_default="1048576"
        ),
        sa.Column(
            "timeout_ms", mysql.INTEGER(), nullable=False, server_default="30000"
        ),
        sa.Column("enabled", mysql.TINYINT(1), nullable=False, server_default="0"),
        sa.Column("version", mysql.INTEGER(), nullable=False, server_default="1"),
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
        sa.UniqueConstraint("name", name="uk_sql_readonly_profile_name"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_sql_readonly_profile_enabled",
        "sql_readonly_profiles",
        ["enabled"],
    )


def downgrade() -> None:
    op.drop_table("sql_readonly_profiles")
    op.drop_table("http_endpoint_profiles")
