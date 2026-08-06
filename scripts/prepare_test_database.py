"""Create and migrate the dedicated MySQL test database.

The script derives ``<PA_DB_URL database>_test`` unless ``PA_TEST_DB_URL`` is
set.  It never prints credentials and requires an explicit ``--yes`` flag.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from pathlib import Path

from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from personal_assistant.config import settings
from personal_assistant.testing import (
    display_database_target,
    resolve_test_database_url,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MYSQL_IDENTIFIER = re.compile(r"^[A-Za-z0-9_$]+$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认创建专用测试数据库并升级到 Alembic head",
    )
    parser.add_argument(
        "--verify-reversible",
        action="store_true",
        help="升级后回退一个版本并再次升级（仅专用测试数据库）",
    )
    return parser.parse_args()


async def create_database(test_url: str) -> None:
    target = make_url(test_url)
    database_name = target.database or ""
    if not _MYSQL_IDENTIFIER.fullmatch(database_name):
        raise ValueError("测试数据库名只能包含字母、数字、下划线和 $ 字符")

    admin_url = target.set(database="mysql")
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
    finally:
        await engine.dispose()


def migrate_database(test_url: str, *, verify_reversible: bool = False) -> None:
    # alembic/env.py reads the already-created Settings singleton.
    settings.db_url = test_url
    alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(alembic_config, "head")
    if verify_reversible:
        command.downgrade(alembic_config, "-1")
        command.upgrade(alembic_config, "head")


def main() -> int:
    args = parse_args()
    test_url = resolve_test_database_url(
        settings.db_url,
        os.environ.get("PA_TEST_DB_URL"),
    )
    target = display_database_target(test_url)
    if not args.yes:
        raise SystemExit(
            f"拒绝修改数据库：目标为 {target}。确认后使用 --yes 重新运行。"
        )

    print(f"准备专用测试数据库：{target}")
    asyncio.run(create_database(test_url))
    migrate_database(test_url, verify_reversible=args.verify_reversible)
    if args.verify_reversible:
        print("专用测试数据库已完成 downgrade/upgrade 可逆性验证。")
    print("测试数据库已升级到 Alembic head。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
