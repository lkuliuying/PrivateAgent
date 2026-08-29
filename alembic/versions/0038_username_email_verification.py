"""唯一用户名与注册邮箱验证码。

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-29
"""
from __future__ import annotations

import re
import unicodedata
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(conn, table: str, index: str) -> bool:
    return any(item["name"] == index for item in sa.inspect(conn).get_indexes(table))


def _legacy_username(display_name: str | None, user_id: int, used: set[str]) -> str:
    raw = (display_name or "").strip()
    raw = re.sub(r"[\s@]+", "-", raw)
    raw = "".join(
        character
        for character in raw
        if not unicodedata.category(character).startswith("C")
    ).strip("-")
    base = raw[:100] if len(raw) >= 2 else f"user-{user_id}"
    candidate = base
    if candidate.casefold() in used:
        suffix = f"-{user_id}"
        candidate = f"{base[: 100 - len(suffix)]}{suffix}"
    used.add(candidate.casefold())
    return candidate


def upgrade() -> None:
    conn = op.get_bind()
    op.add_column(
        "users",
        sa.Column("username", mysql.VARCHAR(length=100), nullable=True),
    )

    used: set[str] = set()
    rows = conn.execute(
        sa.text("SELECT id, display_name FROM users ORDER BY id")
    ).mappings().all()
    for row in rows:
        username = _legacy_username(row["display_name"], int(row["id"]), used)
        conflict = conn.execute(
            sa.text("SELECT 1 FROM users WHERE username = :username LIMIT 1"),
            {"username": username},
        ).first()
        if conflict is not None:
            username = f"user-{row['id']}"
            counter = 1
            while conn.execute(
                sa.text("SELECT 1 FROM users WHERE username = :username LIMIT 1"),
                {"username": username},
            ).first() is not None:
                username = f"user-{row['id']}-{counter}"
                counter += 1
        conn.execute(
            sa.text("UPDATE users SET username = :username WHERE id = :user_id"),
            {"username": username, "user_id": row["id"]},
        )

    op.alter_column(
        "users",
        "username",
        existing_type=mysql.VARCHAR(length=100),
        nullable=False,
    )
    op.create_unique_constraint("uk_users_username", "users", ["username"])

    op.create_table(
        "email_verification_codes",
        sa.Column("id", mysql.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("email", mysql.VARCHAR(length=320), nullable=False),
        sa.Column(
            "purpose",
            mysql.VARCHAR(length=32),
            nullable=False,
            server_default="registration",
        ),
        sa.Column("code_hash", mysql.CHAR(length=64), nullable=False),
        sa.Column("code_salt", mysql.CHAR(length=32), nullable=False),
        sa.Column("attempts", mysql.INTEGER(), nullable=False, server_default="0"),
        sa.Column("expires_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("consumed_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.Column("owner_user_id", mysql.BIGINT(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_email_verification_lookup",
        "email_verification_codes",
        ["email", "purpose", "created_at"],
    )
    op.create_index(
        "idx_email_verification_expiry",
        "email_verification_codes",
        ["expires_at", "consumed_at"],
    )
    op.create_index(
        "ix_email_verification_codes_owner_user_id",
        "email_verification_codes",
        ["owner_user_id"],
    )


def downgrade() -> None:
    conn = op.get_bind()
    if _index_exists(
        conn,
        "email_verification_codes",
        "ix_email_verification_codes_owner_user_id",
    ):
        op.drop_index(
            "ix_email_verification_codes_owner_user_id",
            table_name="email_verification_codes",
        )
    op.drop_index(
        "idx_email_verification_expiry",
        table_name="email_verification_codes",
    )
    op.drop_index(
        "idx_email_verification_lookup",
        table_name="email_verification_codes",
    )
    op.drop_table("email_verification_codes")
    op.drop_constraint("uk_users_username", "users", type_="unique")
    op.drop_column("users", "username")
