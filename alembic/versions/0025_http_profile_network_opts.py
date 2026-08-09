"""Add explicit local/private network opt-ins for HTTP endpoint profiles.

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-09

v0.5.0 B3（HTTP/API 可信工作流）：``http_endpoint_profiles`` 增加两个
显式 opt-in 标志（默认 false，与 MCP 语义一致）：

- ``allow_insecure_local``：仅当目标为环回地址时才允许 http scheme
  （本地开发/测试服务用；环回默认仍拒绝）；
- ``allow_private_network``：允许私网/链路本地等非全局地址
  （内部服务显式配置用；默认拒绝，DNS 解析结果同样受此约束）。

两个标志均可独立关闭；关闭后对应目标在配置校验与 DNS 校验两层均被拒绝。
additive 迁移：旧版应用可读取原表。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "http_endpoint_profiles",
        sa.Column(
            "allow_insecure_local",
            mysql.TINYINT(1),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "http_endpoint_profiles",
        sa.Column(
            "allow_private_network",
            mysql.TINYINT(1),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("http_endpoint_profiles", "allow_private_network")
    op.drop_column("http_endpoint_profiles", "allow_insecure_local")
