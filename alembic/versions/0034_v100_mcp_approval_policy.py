"""v1.0.0 CT-7 MCP 逐工具审批策略与 discovery 缓存（专项计划 §12.1/§12.2）。

变更（additive）：
- ``mcp_servers.approval_policy_json`` JSON NULL：server 默认审批模式与
  逐工具覆盖 ``{"default": "<mode>", "tools": {"<name>": "<mode>"}}``，
  mode ∈ auto|prompt|writes|always|deny。NULL 等价 ``{"default": "prompt"}``
  （现状语义：逐次审批）。
- ``mcp_servers.discovery_config_hash`` CHAR(64) NULL：保存该份 discovery
  时的连接身份规范化哈希；与当前配置不一致或超出 TTL 即视为过期，
  工具面失败关闭（§12.1：不静默替换、不静默使用过期目录）。

不改动既有列与数据；DDL 幂等；正式应用回退不执行本迁移的 downgrade。

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-26
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0034"
down_revision: Union[str, None] = "0033"
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
    if not _column_exists(connection, "mcp_servers", "approval_policy_json"):
        op.execute("ALTER TABLE mcp_servers ADD COLUMN approval_policy_json JSON NULL")
    if not _column_exists(connection, "mcp_servers", "discovery_config_hash"):
        op.execute(
            "ALTER TABLE mcp_servers ADD COLUMN discovery_config_hash CHAR(64) NULL"
        )


def downgrade() -> None:
    # 仅开发库验证；正式回退保留 schema（上位计划 §10）
    connection = op.get_bind()
    if _column_exists(connection, "mcp_servers", "discovery_config_hash"):
        op.execute("ALTER TABLE mcp_servers DROP COLUMN discovery_config_hash")
    if _column_exists(connection, "mcp_servers", "approval_policy_json"):
        op.execute("ALTER TABLE mcp_servers DROP COLUMN approval_policy_json")
