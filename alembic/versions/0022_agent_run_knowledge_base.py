"""Persist whether an Agent run was created for a knowledge-base chat.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-08

0.3.0 A3：RAG 引用验证器（带 strict JSON output_schema）只应对知识库聊天
注入；普通聊天注入后模型被强制 JSON 输出并抑制工具调用，真实模型审批
（read_file 等 CONFIRM 工具）无法触发。本迁移为 ``agent_runs`` 增加
``knowledge_base`` 列（additive，默认 false），使创建与审批恢复路径能按
同一持久化事实决定是否注入 RAG 引用验证器。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column(
            "knowledge_base",
            mysql.TINYINT(1),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "knowledge_base")
