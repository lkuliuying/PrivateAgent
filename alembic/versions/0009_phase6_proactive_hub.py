"""phase6 M1: proactive hub - inbox / reminders / goals / briefings / provider audits

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-08

对齐 docs/archive/phases/phase6-plan.md §3 M1 与 docs/archive/phases/phase6-requirements.md §6：
- inbox_items：统一收件箱，聚合聊天/任务/学习/活动/记忆等待处理项。
- reminders：通用提醒（一次性/重复），due_at + recurrence_rule + next_fire_at。
- personal_goals / goal_links / goal_checkins：跨模块长期目标层 + 关联对象 + 周回顾。
- briefings：主动简报（today/weekly/learning/project/goal），sources_json 只存摘要与 id。
- provider_call_audits：远程 Provider 请求级审计，只存类别与估算大小，不存完整 prompt。

关联策略（phase6 §6）：
- 跨模块/跨域关联一律 target_type/target_id 或 source_type/source_id 软引用（纯 BIGINT，不建外键）。
- goal_links.goal_id / goal_checkins.goal_id 虽同域，但遵循「不自动级联删除用户数据」原则，
  亦不建 FK CASCADE——目标删除时由应用层显式处理链接/回顾，避免用户数据静默消失。
- meta_json / sources_json / context_types_json 只保存摘要与 id，不保存大段原文；
  provider_call_audits 不保存完整 prompt，只保存类别、估算大小与状态。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- inbox_items ----
    op.create_table(
        "inbox_items",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column("body_md", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column(
            "item_type",
            mysql.ENUM(
                "todo",
                "reminder",
                "review",
                "approval",
                "failure",
                "memory",
                "note",
                "system",
                name="inbox_item_type_enum",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            mysql.ENUM(
                "open",
                "snoozed",
                "done",
                "ignored",
                "archived",
                name="inbox_item_status_enum",
            ),
            nullable=False,
            server_default="open",
        ),
        sa.Column(
            "priority",
            mysql.ENUM(
                "low",
                "normal",
                "high",
                "urgent",
                name="inbox_item_priority_enum",
            ),
            nullable=False,
            server_default="normal",
        ),
        sa.Column("due_at", mysql.DATETIME(fsp=3), nullable=True),
        # 跨模块软引用：来源对象（如 chat_message / agent_task / activity / memory）。
        sa.Column("source_type", mysql.VARCHAR(64), nullable=True),
        sa.Column("source_id", mysql.BIGINT(), nullable=True),
        # 跨模块软引用：转化的目标对象（如 reminder / agent_task / memory）。
        sa.Column("target_type", mysql.VARCHAR(64), nullable=True),
        sa.Column("target_id", mysql.BIGINT(), nullable=True),
        sa.Column("meta_json", mysql.JSON(), nullable=True),
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
    op.create_index("idx_inbox_status_due", "inbox_items", ["status", "due_at"])
    op.create_index("idx_inbox_source", "inbox_items", ["source_type", "source_id"])

    # ---- reminders ----
    op.create_table(
        "reminders",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column("body_md", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column(
            "status",
            mysql.ENUM(
                "active",
                "snoozed",
                "done",
                "cancelled",
                name="reminder_status_enum",
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column("due_at", mysql.DATETIME(fsp=3), nullable=False),
        # 轻量重复规则：{freq: none/daily/weekly/monthly, interval: N, ...}。
        sa.Column("recurrence_rule", mysql.JSON(), nullable=True),
        sa.Column("next_fire_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("last_fired_at", mysql.DATETIME(fsp=3), nullable=True),
        # 跨模块软引用：来源对象（如 chat_message / inbox_item）。
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
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_reminder_next", "reminders", ["status", "next_fire_at"])
    op.create_index("idx_reminder_source", "reminders", ["source_type", "source_id"])

    # ---- personal_goals ----
    op.create_table(
        "personal_goals",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column("description", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column(
            "domain", mysql.VARCHAR(64), nullable=False, server_default="custom"
        ),
        sa.Column(
            "status",
            mysql.ENUM(
                "active",
                "paused",
                "done",
                "archived",
                name="personal_goal_status_enum",
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "priority",
            mysql.ENUM("low", "normal", "high", name="personal_goal_priority_enum"),
            nullable=False,
            server_default="normal",
        ),
        sa.Column("start_date", mysql.DATE(), nullable=True),
        sa.Column("target_date", mysql.DATE(), nullable=True),
        sa.Column("success_criteria_md", mysql.MEDIUMTEXT(), nullable=True),
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
    op.create_index("idx_goal_status", "personal_goals", ["status", "priority"])

    # ---- goal_links ----
    op.create_table(
        "goal_links",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        # 同域软引用：遵循「不自动级联删除用户数据」，不建 FK CASCADE。
        sa.Column("goal_id", mysql.BIGINT(), nullable=False),
        # 跨模块软引用：learning_topic / project / agent_task / document_collection 等。
        sa.Column("target_type", mysql.VARCHAR(64), nullable=False),
        sa.Column("target_id", mysql.BIGINT(), nullable=False),
        sa.Column(
            "relation", mysql.VARCHAR(64), nullable=False, server_default="supports"
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "uk_goal_target",
        "goal_links",
        ["goal_id", "target_type", "target_id", "relation"],
        unique=True,
    )
    op.create_index("idx_goal_links_goal", "goal_links", ["goal_id"])

    # ---- goal_checkins ----
    op.create_table(
        "goal_checkins",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        # 同域软引用：不建 FK CASCADE，目标删除时回顾保留为历史。
        sa.Column("goal_id", mysql.BIGINT(), nullable=False),
        sa.Column("checkin_date", mysql.DATE(), nullable=False),
        sa.Column("progress_note_md", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column("confidence", mysql.FLOAT(), nullable=True),
        sa.Column("blockers_json", mysql.JSON(), nullable=True),
        sa.Column("next_actions_json", mysql.JSON(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_goal_checkins_goal_date", "goal_checkins", ["goal_id", "checkin_date"]
    )

    # ---- briefings ----
    op.create_table(
        "briefings",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column(
            "kind",
            mysql.ENUM(
                "today",
                "weekly",
                "learning",
                "project",
                "goal",
                name="briefing_kind_enum",
            ),
            nullable=False,
        ),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column("body_md", mysql.MEDIUMTEXT(), nullable=False),
        # sources_json 只存摘要与 id，不存大段原文（phase6 §6）。
        sa.Column("sources_json", mysql.JSON(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_briefing_kind_time", "briefings", ["kind", "created_at"])

    # ---- provider_call_audits ----
    op.create_table(
        "provider_call_audits",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("provider_type", mysql.VARCHAR(64), nullable=False),
        sa.Column("model", mysql.VARCHAR(255), nullable=True),
        sa.Column("purpose", mysql.VARCHAR(64), nullable=False),
        sa.Column(
            "remote", mysql.BOOLEAN(), nullable=False, server_default=sa.text("0")
        ),
        # context_types_json：发送的上下文类别（如 chat_messages/kb_chunks/memories），
        # 不存完整 prompt（phase6 §6 隐私要求）。
        sa.Column("context_types_json", mysql.JSON(), nullable=True),
        sa.Column("estimated_input_chars", mysql.INTEGER(), nullable=True),
        sa.Column("estimated_output_chars", mysql.INTEGER(), nullable=True),
        sa.Column(
            "status",
            mysql.ENUM(
                "planned",
                "sent",
                "succeeded",
                "failed",
                "cancelled",
                name="provider_audit_status_enum",
            ),
            nullable=False,
            server_default="planned",
        ),
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
    op.create_index("idx_provider_audit_time", "provider_call_audits", ["created_at"])
    op.create_index(
        "idx_provider_audit_remote", "provider_call_audits", ["remote", "created_at"]
    )


def downgrade() -> None:
    # provider_call_audits
    op.drop_index("idx_provider_audit_remote", table_name="provider_call_audits")
    op.drop_index("idx_provider_audit_time", table_name="provider_call_audits")
    op.drop_table("provider_call_audits")
    # briefings
    op.drop_index("idx_briefing_kind_time", table_name="briefings")
    op.drop_table("briefings")
    # goal_checkins
    op.drop_index("idx_goal_checkins_goal_date", table_name="goal_checkins")
    op.drop_table("goal_checkins")
    # goal_links
    op.drop_index("idx_goal_links_goal", table_name="goal_links")
    op.drop_index("uk_goal_target", table_name="goal_links")
    op.drop_table("goal_links")
    # personal_goals
    op.drop_index("idx_goal_status", table_name="personal_goals")
    op.drop_table("personal_goals")
    # reminders
    op.drop_index("idx_reminder_source", table_name="reminders")
    op.drop_index("idx_reminder_next", table_name="reminders")
    op.drop_table("reminders")
    # inbox_items
    op.drop_index("idx_inbox_source", table_name="inbox_items")
    op.drop_index("idx_inbox_status_due", table_name="inbox_items")
    op.drop_table("inbox_items")
