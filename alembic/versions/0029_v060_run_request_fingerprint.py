"""v0.6.0 C2: agent_runs 增加请求指纹列（幂等冲突检测）。

冻结依据：``docs/releases/v0.6.0/v0.6.0-c0-contracts-20260820.md`` §5.2。
契约要求重复请求的 session/project/workspace/message hash 不一致时返回
``client_request_conflict``；``agent_runs`` 需持久化请求指纹以做跨进程比对。

变更：
- ``agent_runs`` 增加 ``request_payload_sha256`` VARCHAR(64) 可空（additive；
  旧客户端可忽略；旧 run 为 NULL，不参与冲突比对）。

正式应用回退不执行本迁移的 downgrade；downgrade 仅用于开发库/克隆库验证。

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
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


def upgrade() -> None:
    connection = op.get_bind()
    if not _column_exists(connection, "agent_runs", "request_payload_sha256"):
        op.add_column(
            "agent_runs",
            sa.Column("request_payload_sha256", mysql.VARCHAR(64), nullable=True),
        )


def downgrade() -> None:
    # 仅用于开发库/克隆库验证；正式应用回退不执行本函数。
    connection = op.get_bind()
    if _column_exists(connection, "agent_runs", "request_payload_sha256"):
        op.drop_column("agent_runs", "request_payload_sha256")
