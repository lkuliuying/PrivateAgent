"""v1.0 CT-3（专项计划 §8.2）：模型工具能力探测快照表。

变更（additive）：
- 新增 ``model_tool_profile_snapshots``：profile_id/provider/model_name/
  model_digest/status/error_code/sample_count/pass_count/results_json/
  requirements_json/probed_at。工具面门禁取 profile 最新一条有效快照；
  无有效快照时失败关闭到最小工具面（§8.2 末条）。

不改动既有表；DDL 幂等；正式应用回退不执行本迁移的 downgrade。

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-26
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = :t"
        ),
        {"t": table},
    ).fetchone()
    return bool(row and row[0])


def upgrade() -> None:
    connection = op.get_bind()
    if not _table_exists(connection, "model_tool_profile_snapshots"):
        op.execute(
            """
            CREATE TABLE model_tool_profile_snapshots (
                id CHAR(36) NOT NULL,
                profile_id VARCHAR(128) NOT NULL,
                provider VARCHAR(100) NOT NULL,
                model_name VARCHAR(200) NOT NULL,
                model_digest VARCHAR(128) NOT NULL,
                status VARCHAR(16) NOT NULL,
                error_code VARCHAR(64) NULL,
                sample_count INTEGER NOT NULL DEFAULT 1,
                pass_count INTEGER NOT NULL DEFAULT 0,
                results_json JSON NULL,
                requirements_json JSON NULL,
                probed_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
                created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
                PRIMARY KEY (id),
                INDEX idx_model_tool_probe_profile_created (profile_id, created_at)
            )
            """
        )


def downgrade() -> None:
    # 仅开发库验证；正式回退保留 schema（上位计划 §10）
    connection = op.get_bind()
    if _table_exists(connection, "model_tool_profile_snapshots"):
        op.execute("DROP TABLE model_tool_profile_snapshots")
