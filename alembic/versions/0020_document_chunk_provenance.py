"""Add source provenance for immutable versioned RAG chunks.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_index_chunk_provenance",
        sa.Column(
            "chunk_id",
            mysql.BIGINT(),
            sa.ForeignKey("document_index_chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "doc_id",
            mysql.BIGINT(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_kind", mysql.VARCHAR(32), nullable=False),
        sa.Column("parser_version", mysql.VARCHAR(64), nullable=False),
        sa.Column("page_start", mysql.INTEGER(), nullable=True),
        sa.Column("page_end", mysql.INTEGER(), nullable=True),
        sa.Column("char_start", mysql.INTEGER(), nullable=True),
        sa.Column("char_end", mysql.INTEGER(), nullable=True),
        sa.Column("line_start", mysql.INTEGER(), nullable=True),
        sa.Column("line_end", mysql.INTEGER(), nullable=True),
        sa.Column("heading_path_json", mysql.JSON(), nullable=True),
        sa.Column("provenance_sha256", mysql.CHAR(64), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.func.current_timestamp(3),
        ),
        sa.CheckConstraint(
            "(page_start IS NULL AND page_end IS NULL) OR "
            "(page_start >= 1 AND page_end >= page_start)",
            name="ck_index_chunk_provenance_page_range",
        ),
        sa.CheckConstraint(
            "(char_start IS NULL AND char_end IS NULL) OR "
            "(char_start >= 0 AND char_end >= char_start)",
            name="ck_index_chunk_provenance_char_range",
        ),
        sa.CheckConstraint(
            "(line_start IS NULL AND line_end IS NULL) OR "
            "(line_start >= 1 AND line_end >= line_start)",
            name="ck_index_chunk_provenance_line_range",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_document_index_chunk_provenance_page",
        "document_index_chunk_provenance",
        ["doc_id", "page_start", "page_end"],
    )

    # Existing 0019 chunks have no recoverable source coordinates. Backfill a
    # complete, explicit unknown record so every versioned chunk keeps the
    # one-to-one invariant without inventing page or line numbers.
    op.execute(
        sa.text(
            "INSERT INTO document_index_chunk_provenance "
            "(chunk_id, doc_id, source_kind, parser_version, provenance_sha256) "
            "SELECT id, doc_id, 'unspecified', 'legacy-index:v1', "
            "'14d020f8806aeb5b78ba925ba8186e708d324ff629d77c2fc2d18e54d57acf2b' "
            "FROM document_index_chunks"
        )
    )


def downgrade() -> None:
    # MySQL may reuse the composite page index for the doc_id foreign key.
    # Dropping the table releases both constraints and indexes atomically.
    op.drop_table("document_index_chunk_provenance")
