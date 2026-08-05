#!/usr/bin/env python3
"""Rehearse head upgrade and rollback on a verified pre-upgrade clone only."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from personal_assistant.config import settings  # noqa: E402
from personal_assistant.core.database_clone import (  # noqa: E402
    DatabaseCloneError,
    compare_snapshots,
    snapshot_database,
    validate_clone_name,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="确认只修改指定预升级克隆")
    parser.add_argument("--clone", required=True, help="已核验的 *_preupgrade_<UTC timestamp> 库")
    parser.add_argument("--base-revision", default="0012")
    return parser.parse_args()


def _assert_upgrade_preserved_source_tables(source, upgraded) -> list[str]:
    issues: list[str] = []
    for table, before in sorted(source.table_counts.items()):
        after = upgraded.table_counts.get(table)
        if after is None:
            issues.append(f"source table missing after upgrade: {table}")
        elif after != before:
            issues.append(f"source row count changed after upgrade: {table}")
    return issues


def run(args: argparse.Namespace) -> int:
    source_url = make_url(settings.db_url)
    source_database = source_url.database or ""
    validate_clone_name(source_database, args.clone)
    if not args.yes:
        print(
            json.dumps(
                {
                    "mode": "preview",
                    "source_database": source_database,
                    "clone_database": args.clone,
                    "sequence": [args.base_revision, "head", args.base_revision],
                    "requires_yes": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    clone_url = source_url.set(database=args.clone)
    source_before = asyncio.run(snapshot_database(source_url))
    clone_before = asyncio.run(snapshot_database(clone_url))
    initial_issues = compare_snapshots(source_before, clone_before)
    if initial_issues:
        raise DatabaseCloneError(
            "clone no longer matches source before rehearsal: " + "; ".join(initial_issues[:10])
        )
    if clone_before.schema_head != args.base_revision:
        raise DatabaseCloneError(
            f"clone must start at {args.base_revision}, found {clone_before.schema_head}"
        )

    alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
    original_url = settings.db_url
    try:
        settings.db_url = clone_url.render_as_string(hide_password=False)
        command.upgrade(alembic_config, "head")
        upgraded = asyncio.run(snapshot_database(clone_url))
        upgrade_issues = _assert_upgrade_preserved_source_tables(source_before, upgraded)
        if upgraded.schema_head == args.base_revision:
            upgrade_issues.append("upgrade did not advance Alembic head")
        if upgrade_issues:
            raise DatabaseCloneError(
                "clone upgrade verification failed: " + "; ".join(upgrade_issues[:10])
            )
        command.downgrade(alembic_config, args.base_revision)
        rolled_back = asyncio.run(snapshot_database(clone_url))
    finally:
        settings.db_url = original_url

    rollback_issues = compare_snapshots(source_before, rolled_back)
    if rollback_issues:
        raise DatabaseCloneError(
            "clone rollback verification failed: " + "; ".join(rollback_issues[:10])
        )
    print(
        json.dumps(
            {
                "verified": True,
                "source_database": source_database,
                "clone_database": args.clone,
                "sequence": [
                    clone_before.schema_head,
                    upgraded.schema_head,
                    rolled_back.schema_head,
                ],
                "source_tables_preserved_at_head": len(source_before.table_counts),
                "rollback_tables": len(rolled_back.table_counts),
                "rollback_total_rows": rolled_back.total_rows,
                "rollback_counts_sha256": rolled_back.counts_sha256,
                "primary_database_modified": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    try:
        return run(parse_args())
    except DatabaseCloneError as exc:
        print(f"database upgrade rehearsal refused: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"database upgrade rehearsal failed: {type(exc).__name__}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
