#!/usr/bin/env python3
"""Create and verify a full pre-upgrade clone of the configured MySQL database.

This command never overwrites a database.  It requires ``--yes``, creates a
source-specific ``*_preupgrade_<UTC timestamp>`` database, and compares every
base table and exact row count before reporting success.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy.engine import make_url  # noqa: E402

from personal_assistant.config import settings  # noqa: E402
from personal_assistant.core.database_clone import (  # noqa: E402
    DatabaseCloneError,
    build_clone_name,
    create_verified_database_clone,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="确认创建完整克隆数据库")
    parser.add_argument("--name", help="可选的严格 *_preupgrade_<UTC timestamp> 名称")
    parser.add_argument("--mysqldump", type=Path)
    parser.add_argument("--mysql", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    source_name = make_url(settings.db_url).database or ""
    clone_name = args.name or build_clone_name(source_name)
    if not args.yes:
        print(
            json.dumps(
                {
                    "mode": "preview",
                    "source_database": source_name,
                    "clone_database": clone_name,
                    "requires_yes": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    result = await create_verified_database_clone(
        settings.db_url,
        clone_database=clone_name,
        mysqldump_executable=args.mysqldump,
        mysql_executable=args.mysql,
        timeout_seconds=args.timeout_seconds,
    )
    manifest_dir = settings.data_dir / "backups"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{result.clone.database}.json"
    manifest_path.write_text(
        json.dumps(result.to_manifest(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output = {
        "verified": result.verified,
        "source_database": result.source.database,
        "clone_database": result.clone.database,
        "schema_head": result.clone.schema_head,
        "tables": len(result.clone.table_counts),
        "total_rows": result.clone.total_rows,
        "counts_sha256": result.clone.counts_sha256,
        "manifest_path": str(manifest_path),
        "rollback": "Point the application database configuration at the verified clone.",
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    try:
        return asyncio.run(run(parse_args()))
    except DatabaseCloneError as exc:
        print(f"database clone refused: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"database clone failed: {type(exc).__name__}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
