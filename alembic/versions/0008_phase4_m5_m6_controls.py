"""phase4 M5/M6: task plan controls and provider settings

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-07
"""
from __future__ import annotations

from alembic import op


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


TASK_STATUSES = (
    "'plan_draft','plan_approved','planned','waiting_approval','paused',"
    "'running','succeeded','failed','cancelled'"
)
OLD_TASK_STATUSES = (
    "'planned','waiting_approval','running','succeeded','failed','cancelled'"
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_tasks MODIFY status "
        f"ENUM({TASK_STATUSES}) NOT NULL DEFAULT 'planned'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE agent_tasks SET status='planned' "
        "WHERE status IN ('plan_draft','plan_approved','paused')"
    )
    op.execute(
        "ALTER TABLE agent_tasks MODIFY status "
        f"ENUM({OLD_TASK_STATUSES}) NOT NULL DEFAULT 'planned'"
    )
