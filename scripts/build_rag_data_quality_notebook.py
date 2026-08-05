#!/usr/bin/env python3
"""Build and execute the aggregate-only RAG data-quality audit notebook."""

from __future__ import annotations

import argparse
from pathlib import Path

import nbformat
from nbclient import NotebookClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile_path = args.profile.resolve()
    validation_path = args.validation.resolve()
    output_path = args.output.resolve()
    data_root = (PROJECT_ROOT / "data").resolve()
    docs_root = (PROJECT_ROOT / "docs" / "analysis").resolve()
    for label, path in (("profile", profile_path), ("validation", validation_path)):
        if path != data_root and data_root not in path.parents:
            raise SystemExit(f"{label} must stay inside {data_root}")
    if output_path != docs_root and docs_root not in output_path.parents:
        raise SystemExit(f"output must stay inside {docs_root}")

    profile_rel = profile_path.relative_to(PROJECT_ROOT).as_posix()
    validation_rel = validation_path.relative_to(PROJECT_ROOT).as_posix()
    cells = [
        nbformat.v4.new_markdown_cell(
            """# RAG Corpus Data Quality Audit

## tl;dr

**Decision: do not promote versioned hybrid RAG to the production corpus yet.** The legacy database has 1,117 document rows, but only 357 ready/enabled rows with chunks and just 4 distinct chunk-content groups. All 357 chunked rows belong to duplicate groups, Chroma contains no legacy vectors, and the embedding preflight is unavailable. The evidence supports a controlled cleanup/rebuild rehearsal, not production rollout.
"""
        ),
        nbformat.v4.new_markdown_cell(
            """## Context & Methods

This notebook consumes two privacy-bounded aggregate JSON files: an application-side profile and an independent database-side reconciliation. Neither source emits document names, paths, content, or opaque hashes.

### Key Assumptions

- A logical content group is defined by the SHA-256 hash of each document's chunks ordered by ordinal and row id.
- `ready` and enabled documents are the retrieval-eligible legacy population.
- Source-file availability means the current workspace can resolve the original file without exposing its path here.
- A production rollout requires schema revision 0020, usable embeddings, and a benchmark broader than four logical cases.
"""
        ),
        nbformat.v4.new_code_cell(
            f"""from pathlib import Path
import json

root = Path.cwd()
profile_path = root / {profile_rel!r}
validation_path = root / {validation_rel!r}
profile = json.loads(profile_path.read_text(encoding="utf-8"))
validation = json.loads(validation_path.read_text(encoding="utf-8"))

assert validation["all_checks_match"] is True
assert profile["grain"]["logical_content_groups"] == validation["sql_results"]["chunk_manifest_groups"]
print("Loaded aggregate-only sources; independent checks match.")
"""
        ),
        nbformat.v4.new_markdown_cell(
            """## Data

The analysis grain is a document row, a legacy chunk row, or a logical chunk-content group. Counts below are exact snapshots of the local `personal_assistant` schema; percentages use the ready/enabled population unless labeled otherwise.
"""
        ),
        nbformat.v4.new_code_cell(
            """grain = profile["grain"]
completeness = profile["completeness"]
uniqueness = profile["uniqueness"]
integrity = profile["integrity"]
vectors = profile["vector_integrity"]

funnel = [
    ("All document rows", grain["document_rows"]),
    ("Ready and enabled", grain["ready_enabled_documents"]),
    ("Ready/enabled with chunks", grain["ready_enabled_with_chunks"]),
    ("Source-resolvable with chunks", round(grain["ready_enabled_with_chunks"] * completeness["source_file_available_with_chunks_rate"])),
]
print("stage | rows | share of all rows")
print("--- | ---: | ---:")
for stage, rows in funnel:
    print(f"{stage} | {rows:,} | {rows / grain['document_rows']:.1%}")
"""
        ),
        nbformat.v4.new_markdown_cell(
            """## Results

The retrieval-eligible corpus is numerically large but logically tiny. The independent SQL path reproduces all five decision-critical counts and shows that every usable document contains exactly one chunk.
"""
        ),
        nbformat.v4.new_code_cell(
            """group_sizes = validation["sql_results"]["manifest_group_sizes"]
checks = validation["checks"]
print("metric | application profile | independent SQL | match")
print("--- | ---: | ---: | :---:")
for metric, values in checks.items():
    print(f"{metric.replace('_', ' ')} | {values['profile']:,} | {values['sql']:,} | {'yes' if values['matches'] else 'no'}")
print()
print("logical group rank | document rows")
print("---: | ---:")
for rank, size in enumerate(group_sizes, start=1):
    print(f"{rank} | {size:,}")
"""
        ),
        nbformat.v4.new_code_cell(
            """quality_rows = [
    ("Duplicate rate among chunked documents", f"{uniqueness['duplicate_document_rate_among_chunked']:.1%}"),
    ("Excess duplicate document rows", f"{uniqueness['excess_duplicate_documents']:,}"),
    ("BM25 rows missing", f"{integrity['bm25_missing_chunks']:,}"),
    ("Documents with chunk-count mismatch", f"{integrity['chunk_count_mismatch_documents']:,}"),
    ("Legacy vector coverage", f"{vectors['coverage_rate']:.1%}"),
    ("Valid declared hash coverage on chunked documents", f"{completeness['valid_content_hash_with_chunks_rate']:.1%}"),
]
print("quality signal | result")
print("--- | ---:")
for label, value in quality_rows:
    print(f"{label} | {value}")
"""
        ),
        nbformat.v4.new_markdown_cell(
            """## Takeaways

1. **Hold production rollout.** Schema revision 0012, zero vector coverage, unavailable embedding preflight, and four logical cases cannot support a defensible hybrid-RAG promotion gate.
2. **Preserve before cleaning.** Keep the verified pre-upgrade clone and perform any deduplication only as a dry-run or on an isolated clone.
3. **Rebuild by logical content.** Select one canonical document per chunk manifest, repair chunk metadata/BM25 text, and regenerate vectors after the embedding service passes preflight.
4. **Require human-reviewed breadth.** Expand the benchmark beyond the four generated logical cases before comparing legacy and versioned retrieval.

### Open Questions

- Are the four repeated content groups expected fixtures, accidental repeated imports, or the wrong database/data directory for production use?
- Should documents without resolvable source files be retained as legacy-only evidence, exported, or quarantined?

### Caveats

- The 357 chunked documents have no valid declared content hash, so declared hashes cannot independently validate the chunk-manifest partition.
- The report measures the local snapshot only; it does not infer user intent from private document contents.
- No production database rows were changed during this audit.
"""
        ),
    ]
    notebook = nbformat.v4.new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.12"},
        },
    )
    client = NotebookClient(
        notebook,
        timeout=120,
        kernel_name="python3",
        resources={"metadata": {"path": str(PROJECT_ROOT)}},
    )
    client.execute()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, output_path)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
