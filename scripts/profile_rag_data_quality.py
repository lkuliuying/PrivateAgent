#!/usr/bin/env python3
"""Write a privacy-bounded RAG corpus quality profile under data/."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from personal_assistant.config import settings  # noqa: E402
from personal_assistant.core.rag_data_quality import (  # noqa: E402
    profile_rag_data_quality,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-chroma", action="store_true")
    parser.add_argument("--embedding-report", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    allowed_root = settings.data_dir.resolve()
    if output != allowed_root and allowed_root not in output.parents:
        print("profile output must stay inside the configured data directory", file=sys.stderr)
        return 2
    if output.exists():
        print("profile output already exists; refusing to overwrite", file=sys.stderr)
        return 2
    embedding_preflight = None
    if args.embedding_report:
        report_path = args.embedding_report.resolve()
        if report_path != allowed_root and allowed_root not in report_path.parents:
            print("embedding report must stay inside the configured data directory", file=sys.stderr)
            return 2
        embedding_preflight = json.loads(report_path.read_text(encoding="utf-8"))
    profile = profile_rag_data_quality(
        settings.db_url,
        data_dir=settings.data_dir,
        project_root=PROJECT_ROOT,
        include_chroma=not args.skip_chroma,
        embedding_preflight=embedding_preflight,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "document_rows": profile["grain"]["document_rows"],
                "legacy_chunk_rows": profile["grain"]["legacy_chunk_rows"],
                "logical_content_groups": profile["grain"]["logical_content_groups"],
                "raw_values_printed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
