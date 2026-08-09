"""Persist optional workflow completion conditions on Agent runs.

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-09

v0.5.0 B5（多步骤工作流）：``agent_runs`` 增加 ``completion_conditions_json``
（可选），持久化创建时注入的可信完成条件，使审批恢复/sidecar 重启后的
续跑路径与创建路径使用同一组完成条件验证。additive：旧版应用可读取原表。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("completion_conditions_json", mysql.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "completion_conditions_json")
