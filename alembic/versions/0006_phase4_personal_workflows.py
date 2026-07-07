"""phase4 M0: personal workflows — memory / reviews / patch sets / collections / extractions

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-06

对齐 docs/phase4-plan.md §3.3 与 docs/phase4-requirements.md §6（M0 范围）：
- memory_items / memory_events：长期记忆与事件流，覆盖偏好/学习/项目/文档/工作流/笔记。
- learning_cards 增列（due_at/interval_days/ease_factor/review_count/lapse_count）：间隔重复调度字段。
- learning_reviews：复习记录，rating 驱动 SM-2 调度。
- project_command_profiles：项目命令模板（test/build/lint/format/typecheck/custom）。
- patch_sets / patch_files：补丁集与文件级补丁，支持审批/应用/回滚状态机。
- document_collections / document_collection_items：文档集合与成员。
- document_extractions：文档/集合的结构化抽取（术语/表格摘要/行动项/论断/代码/模板报告）。
域内父子关系用 CASCADE 外键（memory_events→memory_items、patch_files→patch_sets、
document_collection_items→document_collections、learning_reviews→learning_cards/learning_topics）；
跨域引用（project_id/topic_id/doc_id/task_id）为软引用（纯 BIGINT，不建外键），
避免跨业务域级联删除与循环依赖。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- memory_items ----
    op.create_table(
        "memory_items",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column(
            "kind",
            mysql.ENUM(
                "preference",
                "learning",
                "project",
                "document",
                "workflow",
                "note",
                name="memory_kind_enum",
            ),
            nullable=False,
        ),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column("content_md", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("summary", mysql.VARCHAR(1024), nullable=True),
        sa.Column("source_type", mysql.VARCHAR(64), nullable=True),
        sa.Column("source_id", mysql.BIGINT(), nullable=True),
        # 跨域软引用：projects / learning_topics 在另一域，不建外键。
        sa.Column("project_id", mysql.BIGINT(), nullable=True),
        sa.Column("topic_id", mysql.BIGINT(), nullable=True),
        sa.Column("tags_json", mysql.JSON(), nullable=True),
        sa.Column("confidence", mysql.FLOAT(), nullable=True),
        sa.Column(
            "enabled",
            mysql.BOOLEAN(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "sensitive",
            mysql.BOOLEAN(),
            nullable=False,
            server_default=sa.text("0"),
        ),
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
    op.create_index("idx_memory_kind_enabled", "memory_items", ["kind", "enabled"])
    op.create_index("idx_memory_project", "memory_items", ["project_id"])
    op.create_index("idx_memory_topic", "memory_items", ["topic_id"])

    # ---- memory_events ----
    op.create_table(
        "memory_events",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("memory_id", mysql.BIGINT(), nullable=False),
        sa.Column(
            "event_type",
            mysql.ENUM(
                "created",
                "used",
                "edited",
                "disabled",
                "deleted",
                name="memory_event_type_enum",
            ),
            nullable=False,
        ),
        sa.Column("ref_type", mysql.VARCHAR(64), nullable=True),
        sa.Column("ref_id", mysql.BIGINT(), nullable=True),
        sa.Column("detail_json", mysql.JSON(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"], ["memory_items.id"], ondelete="CASCADE", name="fk_memory_event_memory"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_memory_event_memory", "memory_events", ["memory_id", "created_at"])

    # ---- learning_cards 增列（间隔重复调度）----
    op.add_column("learning_cards", sa.Column("due_at", mysql.DATETIME(fsp=3), nullable=True))
    op.add_column(
        "learning_cards",
        sa.Column("interval_days", mysql.INTEGER(), nullable=False, server_default="0"),
    )
    op.add_column(
        "learning_cards",
        sa.Column("ease_factor", mysql.FLOAT(), nullable=False, server_default="2.5"),
    )
    op.add_column(
        "learning_cards",
        sa.Column("review_count", mysql.INTEGER(), nullable=False, server_default="0"),
    )
    op.add_column(
        "learning_cards",
        sa.Column("lapse_count", mysql.INTEGER(), nullable=False, server_default="0"),
    )
    op.create_index("idx_learning_card_due", "learning_cards", ["topic_id", "due_at"])

    # ---- learning_reviews ----
    op.create_table(
        "learning_reviews",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("card_id", mysql.BIGINT(), nullable=False),
        sa.Column("topic_id", mysql.BIGINT(), nullable=False),
        sa.Column(
            "rating",
            mysql.ENUM("again", "hard", "good", "easy", name="learning_review_rating_enum"),
            nullable=False,
        ),
        sa.Column("previous_due_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("next_due_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["learning_cards.id"], ondelete="CASCADE", name="fk_review_card"
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"], ["learning_topics.id"], ondelete="CASCADE", name="fk_review_topic"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_review_topic_time", "learning_reviews", ["topic_id", "created_at"])
    op.create_index("idx_review_card_time", "learning_reviews", ["card_id", "created_at"])

    # ---- project_command_profiles ----
    op.create_table(
        "project_command_profiles",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        # 跨域软引用：projects 在另一域，不建外键。
        sa.Column("project_id", mysql.BIGINT(), nullable=False),
        sa.Column("name", mysql.VARCHAR(128), nullable=False),
        sa.Column("command_json", mysql.JSON(), nullable=False),
        sa.Column(
            "kind",
            mysql.ENUM(
                "test",
                "build",
                "lint",
                "format",
                "typecheck",
                "custom",
                name="command_profile_kind_enum",
            ),
            nullable=False,
        ),
        sa.Column(
            "timeout_seconds", mysql.INTEGER(), nullable=False, server_default="120"
        ),
        sa.Column(
            "enabled",
            mysql.BOOLEAN(),
            nullable=False,
            server_default=sa.text("1"),
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
        "idx_command_profile_project", "project_command_profiles", ["project_id", "enabled"]
    )

    # ---- patch_sets ----
    op.create_table(
        "patch_sets",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        # 跨域软引用：projects / agent_tasks 在另一域，不建外键。
        sa.Column("project_id", mysql.BIGINT(), nullable=False),
        sa.Column("task_id", mysql.BIGINT(), nullable=True),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column(
            "status",
            mysql.ENUM(
                "draft",
                "waiting_approval",
                "applied",
                "rejected",
                "rolled_back",
                name="patch_set_status_enum",
            ),
            nullable=False,
            server_default="draft",
        ),
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
    op.create_index("idx_patch_set_project", "patch_sets", ["project_id", "created_at"])

    # ---- patch_files ----
    op.create_table(
        "patch_files",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("patch_set_id", mysql.BIGINT(), nullable=False),
        sa.Column("rel_path", mysql.VARCHAR(2048), nullable=False),
        sa.Column("old_sha256", mysql.CHAR(64), nullable=True),
        sa.Column("new_sha256", mysql.CHAR(64), nullable=True),
        sa.Column("diff_text", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("old_content", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column("new_content", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column(
            "status",
            mysql.ENUM(
                "draft",
                "applied",
                "rejected",
                "rolled_back",
                name="patch_file_status_enum",
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.ForeignKeyConstraint(
            ["patch_set_id"], ["patch_sets.id"], ondelete="CASCADE", name="fk_patch_file_set"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_patch_file_set", "patch_files", ["patch_set_id"])

    # ---- document_collections ----
    op.create_table(
        "document_collections",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("title", mysql.VARCHAR(255), nullable=False),
        sa.Column("goal", mysql.TEXT(), nullable=True),
        sa.Column("tags_json", mysql.JSON(), nullable=True),
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

    # ---- document_collection_items ----
    op.create_table(
        "document_collection_items",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("collection_id", mysql.BIGINT(), nullable=False),
        # 跨域软引用：documents 在另一域，不建外键。
        sa.Column("doc_id", mysql.BIGINT(), nullable=False),
        sa.Column(
            "order_index", mysql.INTEGER(), nullable=False, server_default="0"
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["document_collections.id"],
            ondelete="CASCADE",
            name="fk_collection_item_collection",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "uk_collection_doc",
        "document_collection_items",
        ["collection_id", "doc_id"],
        unique=True,
    )

    # ---- document_extractions ----
    op.create_table(
        "document_extractions",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        # 跨域软引用：documents / document_collections 在另一域，不建外键。
        sa.Column("doc_id", mysql.BIGINT(), nullable=True),
        sa.Column("collection_id", mysql.BIGINT(), nullable=True),
        sa.Column(
            "kind",
            mysql.ENUM(
                "terms",
                "table_summary",
                "actions",
                "claims",
                "code",
                "template_report",
                name="extraction_kind_enum",
            ),
            nullable=False,
        ),
        sa.Column("content_json", mysql.JSON(), nullable=True),
        sa.Column("content_md", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column("source_refs_json", mysql.JSON(), nullable=True),
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
    op.create_index("idx_extraction_doc", "document_extractions", ["doc_id", "kind"])
    op.create_index(
        "idx_extraction_collection", "document_extractions", ["collection_id", "kind"]
    )


def downgrade() -> None:
    # document_extractions
    op.drop_index("idx_extraction_collection", table_name="document_extractions")
    op.drop_index("idx_extraction_doc", table_name="document_extractions")
    op.drop_table("document_extractions")
    # document_collection_items
    op.drop_index("uk_collection_doc", table_name="document_collection_items")
    op.drop_table("document_collection_items")
    # document_collections
    op.drop_table("document_collections")
    # patch_files
    op.drop_index("idx_patch_file_set", table_name="patch_files")
    op.drop_table("patch_files")
    # patch_sets
    op.drop_index("idx_patch_set_project", table_name="patch_sets")
    op.drop_table("patch_sets")
    # project_command_profiles
    op.drop_index("idx_command_profile_project", table_name="project_command_profiles")
    op.drop_table("project_command_profiles")
    # learning_reviews
    op.drop_index("idx_review_card_time", table_name="learning_reviews")
    op.drop_index("idx_review_topic_time", table_name="learning_reviews")
    op.drop_table("learning_reviews")
    # learning_cards 增列（逆序删除）
    op.drop_index("idx_learning_card_due", table_name="learning_cards")
    op.drop_column("learning_cards", "lapse_count")
    op.drop_column("learning_cards", "review_count")
    op.drop_column("learning_cards", "ease_factor")
    op.drop_column("learning_cards", "interval_days")
    op.drop_column("learning_cards", "due_at")
    # memory_events
    op.drop_index("idx_memory_event_memory", table_name="memory_events")
    op.drop_table("memory_events")
    # memory_items
    op.drop_index("idx_memory_topic", table_name="memory_items")
    op.drop_index("idx_memory_project", table_name="memory_items")
    op.drop_index("idx_memory_kind_enabled", table_name="memory_items")
    op.drop_table("memory_items")
