"""Add side-by-side, atomically activated RAG index versions.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_index_versions",
        sa.Column("id", mysql.CHAR(36), primary_key=True),
        sa.Column("doc_id", mysql.BIGINT(), nullable=False),
        sa.Column("version_number", mysql.INTEGER(), nullable=False),
        sa.Column("status", mysql.VARCHAR(32), nullable=False),
        sa.Column("source_sha256", mysql.CHAR(64), nullable=False),
        sa.Column("chunker_version", mysql.VARCHAR(64), nullable=False),
        sa.Column("embedding_model", mysql.VARCHAR(128), nullable=False),
        sa.Column("embedding_dimensions", mysql.INTEGER(), nullable=True),
        sa.Column("chunk_count", mysql.INTEGER(), nullable=False, server_default="0"),
        sa.Column("vector_count", mysql.INTEGER(), nullable=False, server_default="0"),
        sa.Column("manifest_sha256", mysql.CHAR(64), nullable=True),
        sa.Column("failure_code", mysql.VARCHAR(64), nullable=True),
        sa.Column("error_message", mysql.TEXT(), nullable=True),
        sa.Column("build_started_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("validated_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("activated_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("retired_at", mysql.DATETIME(fsp=3), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.id"],
            name="fk_document_index_version_doc",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "doc_id",
            "version_number",
            name="uk_document_index_version_number",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_document_index_version_status",
        "document_index_versions",
        ["doc_id", "status", "version_number"],
    )

    op.create_table(
        "document_index_chunks",
        sa.Column("id", mysql.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("index_version_id", mysql.CHAR(36), nullable=False),
        sa.Column("doc_id", mysql.BIGINT(), nullable=False),
        sa.Column("ordinal", mysql.INTEGER(), nullable=False),
        sa.Column("content", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("content_sha256", mysql.CHAR(64), nullable=False),
        sa.Column("token_count", mysql.INTEGER(), nullable=True),
        sa.Column("heading", mysql.VARCHAR(512), nullable=True),
        sa.Column("keywords_json", mysql.JSON(), nullable=True),
        sa.Column("bm25_text", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.ForeignKeyConstraint(
            ["index_version_id"],
            ["document_index_versions.id"],
            name="fk_document_index_chunk_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.id"],
            name="fk_document_index_chunk_doc",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "index_version_id",
            "ordinal",
            name="uk_document_index_chunk_ordinal",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_document_index_chunk_doc",
        "document_index_chunks",
        ["doc_id", "index_version_id", "ordinal"],
    )
    op.create_index(
        "ft_document_index_chunk_bm25",
        "document_index_chunks",
        ["bm25_text"],
        unique=False,
        mysql_prefix="FULLTEXT",
        mysql_with_parser="ngram",
    )

    op.create_table(
        "document_index_heads",
        sa.Column("doc_id", mysql.BIGINT(), primary_key=True),
        sa.Column("active_version_id", mysql.CHAR(36), nullable=True),
        sa.Column("previous_version_id", mysql.CHAR(36), nullable=True),
        sa.Column("lock_version", mysql.INTEGER(), nullable=False, server_default="0"),
        sa.Column("switched_at", mysql.DATETIME(fsp=3), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.id"],
            name="fk_document_index_head_doc",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["active_version_id"],
            ["document_index_versions.id"],
            name="fk_document_index_head_active",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["previous_version_id"],
            ["document_index_versions.id"],
            name="fk_document_index_head_previous",
            ondelete="SET NULL",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_document_index_head_active",
        "document_index_heads",
        ["active_version_id"],
    )


def downgrade() -> None:
    op.drop_table("document_index_heads")
    op.drop_table("document_index_chunks")
    op.drop_table("document_index_versions")
