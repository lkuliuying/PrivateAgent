#!/usr/bin/env python3
"""Write a non-mutating legacy RAG canonicalization plan under data/."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from personal_assistant.config import settings  # noqa: E402
from personal_assistant.core.rag_canonicalization import (  # noqa: E402
    build_rag_canonicalization_plan,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    allowed_root = settings.data_dir.resolve()
    if output != allowed_root and allowed_root not in output.parents:
        print("plan output must stay inside the configured data directory", file=sys.stderr)
        return 2
    if output.exists():
        print("plan output already exists; refusing to overwrite", file=sys.stderr)
        return 2
    plan = build_rag_canonicalization_plan(
        settings.db_url,
        data_dir=settings.data_dir,
        project_root=PROJECT_ROOT,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                **plan["summary"],
                "mutations_performed": False,
                "private_values_printed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
