"""RAG lexical recall: MySQL FULLTEXT ngram index on doc_chunks.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-13

Backfill historical chunks before creating the index. MySQL's ngram parser
supports Chinese text while retaining recall for identifiers and error strings.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE doc_chunks SET bm25_text = content "
        "WHERE bm25_text IS NULL OR bm25_text = ''"
    )
    op.create_index(
        "ft_chunk_bm25",
        "doc_chunks",
        ["bm25_text"],
        unique=False,
        mysql_prefix="FULLTEXT",
        mysql_with_parser="ngram",
    )


def downgrade() -> None:
    op.drop_index("ft_chunk_bm25", table_name="doc_chunks")
