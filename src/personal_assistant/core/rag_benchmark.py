"""Deterministic, local-only candidate generation for RAG rollout benchmarks."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

_LATIN_TERM = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9_.:/-]{2,47}")
_CJK_RUN = re.compile(r"[\u3400-\u9fff]{4,32}")
_SPACE = re.compile(r"\s+")
_GENERIC_HEADINGS = {
    "摘要",
    "概述",
    "介绍",
    "目录",
    "结论",
    "总结",
    "前言",
    "appendix",
    "conclusion",
    "contents",
    "introduction",
    "overview",
    "summary",
}
_LATIN_STOP = {
    "about",
    "after",
    "before",
    "between",
    "document",
    "from",
    "into",
    "other",
    "that",
    "their",
    "there",
    "these",
    "this",
    "those",
    "using",
    "with",
}


@dataclass(frozen=True, slots=True)
class BenchmarkChunk:
    doc_id: int
    chunk_id: int
    ordinal: int
    content: str
    heading: str | None = None
    keywords: tuple[str, ...] = ()


def load_benchmark_case_rows(
    path: Path, *, allow_unreviewed: bool = False
) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    global_review_status = "reviewed"
    if isinstance(payload, dict):
        global_review_status = str(payload.get("review_status") or "").strip()
        payload = payload.get("cases")
    if not isinstance(payload, list) or not payload:
        raise ValueError("evaluation case file must contain a non-empty cases array")
    rows: list[dict] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise TypeError(f"case #{index + 1} must be an object")
        case_id = str(row.get("id") or "").strip()
        query = str(row.get("query") or "").strip()
        names = row.get("relevant_doc_names")
        ids = row.get("relevant_doc_ids")
        clean_names = (
            [str(name).strip() for name in names if str(name).strip()]
            if isinstance(names, list)
            else []
        )
        clean_ids = (
            [int(doc_id) for doc_id in ids if isinstance(doc_id, int) and doc_id > 0]
            if isinstance(ids, list)
            else []
        )
        evidence = row.get("evidence_terms") or []
        clean_evidence = (
            [str(term).strip() for term in evidence if str(term).strip()]
            if isinstance(evidence, list)
            else []
        )
        review_status = str(
            row.get("review_status") or global_review_status or ""
        ).strip()
        relevance_mode = str(row.get("relevance_mode") or "all").strip()
        expect_empty = bool(row.get("expect_empty") or False)
        if relevance_mode not in {"all", "any"}:
            raise ValueError(f"case #{index + 1} has invalid relevance_mode")
        if review_status != "reviewed" and not allow_unreviewed:
            raise ValueError(
                f"case #{index + 1} is not reviewed; use --allow-unreviewed only for characterization"
            )
        if (
            not case_id
            or not query
            or (not clean_names and not clean_ids and not expect_empty)
        ):
            raise ValueError(
                f"case #{index + 1} requires id, query and relevant document names or ids"
            )
        if expect_empty and (clean_names or clean_ids):
            raise ValueError(
                f"case #{index + 1} declares expect_empty together with relevant documents"
            )
        rows.append(
            {
                "id": case_id,
                "query": query,
                "relevant_doc_names": clean_names,
                "relevant_doc_ids": clean_ids,
                "evidence_terms": clean_evidence,
                "relevance_mode": relevance_mode,
                "expect_empty": expect_empty,
                "review_status": review_status,
            }
        )
    case_ids = [row["id"] for row in rows]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("evaluation case ids must be unique")
    return rows


def resolve_document_source_path(
    *,
    doc_id: int,
    name: str,
    source_path: str | None,
    data_dir: Path,
    project_root: Path,
) -> Path | None:
    candidates: list[Path] = []
    if source_path:
        candidates.append(Path(source_path))
    suffix = Path(name).suffix
    candidates.extend(
        [
            data_dir / "uploads" / f"{doc_id}{suffix}",
            project_root / "data" / "uploads" / f"{doc_id}{suffix}",
        ]
    )
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def build_benchmark_candidates(
    chunks: Sequence[BenchmarkChunk],
    *,
    limit: int = 50,
    equivalent_doc_ids: Mapping[int, Sequence[int]] | None = None,
) -> list[dict]:
    """Build one grounded candidate per document without emitting source text.

    Queries are derived from headings or rare lexical anchors.  Every evidence
    term is verified against the exact source chunk and provenance stores only
    a SHA-256, never chunk text.
    """
    limit = max(1, min(int(limit), 500))
    grouped: dict[int, list[BenchmarkChunk]] = defaultdict(list)
    document_terms: dict[int, set[str]] = defaultdict(set)
    terms_by_chunk: dict[int, tuple[str, ...]] = {}
    for chunk in chunks:
        if not chunk.content.strip():
            continue
        grouped[chunk.doc_id].append(chunk)
        terms = _candidate_terms(chunk)
        terms_by_chunk[chunk.chunk_id] = terms
        document_terms[chunk.doc_id].update(term.casefold() for term in terms)
    document_frequency = Counter(
        term for terms in document_terms.values() for term in terms
    )

    candidates: list[dict] = []
    seen_logical_groups: set[tuple[int, ...]] = set()
    seen_queries: set[str] = set()
    for doc_id in sorted(grouped):
        logical_group = tuple(
            sorted(
                {
                    int(item)
                    for item in (equivalent_doc_ids or {}).get(doc_id, (doc_id,))
                    if int(item) > 0
                }
            )
        )
        if logical_group in seen_logical_groups:
            continue
        ranked_chunks = sorted(
            grouped[doc_id],
            key=lambda item: (
                -_chunk_quality(item, terms_by_chunk.get(item.chunk_id, ())),
                item.ordinal,
                item.chunk_id,
            ),
        )
        selected: tuple[BenchmarkChunk, tuple[str, ...], str] | None = None
        for chunk in ranked_chunks:
            available = terms_by_chunk.get(chunk.chunk_id, ())
            anchors = tuple(
                sorted(
                    available,
                    key=lambda term: (
                        document_frequency[term.casefold()],
                        -len(term),
                        term.casefold(),
                    ),
                )[:2]
            )
            if not anchors:
                continue
            heading = _clean_heading(chunk.heading)
            if heading and any(anchor.casefold() in heading.casefold() for anchor in anchors):
                query = f"资料中“{heading}”部分涉及哪些要点？"
            elif len(anchors) >= 2:
                query = f"哪些资料同时涉及“{anchors[0]}”和“{anchors[1]}”？"
            else:
                query = f"哪份资料详细讨论了“{anchors[0]}”？"
            selected = (chunk, anchors, query[:256])
            break
        if selected is None:
            continue
        chunk, anchors, query = selected
        normalized_query = query.casefold()
        if normalized_query in seen_queries:
            continue
        content_folded = chunk.content.casefold()
        if not all(anchor.casefold() in content_folded for anchor in anchors):
            continue
        candidates.append(
            {
                "id": f"doc-{doc_id}-chunk-{chunk.chunk_id}",
                "query": query,
                "relevant_doc_ids": sorted(
                    logical_group
                ),
                "evidence_terms": list(anchors),
                "relevance_mode": "any",
                "review_status": "generated",
                "provenance": {
                    "chunk_id": chunk.chunk_id,
                    "chunk_ordinal": chunk.ordinal,
                    "content_sha256": hashlib.sha256(
                        chunk.content.encode("utf-8")
                    ).hexdigest(),
                },
            }
        )
        seen_logical_groups.add(logical_group)
        seen_queries.add(normalized_query)
        if len(candidates) >= limit:
            break
    return candidates


def _candidate_terms(chunk: BenchmarkChunk) -> tuple[str, ...]:
    content_folded = chunk.content.casefold()
    terms: list[str] = []
    for keyword in chunk.keywords:
        clean = _clean_term(keyword)
        if clean and clean.casefold() in content_folded:
            terms.append(clean)
    heading = _clean_heading(chunk.heading)
    if heading:
        for term in _extract_terms(heading):
            if term.casefold() in content_folded:
                terms.append(term)
    terms.extend(_extract_terms(chunk.content[:8_000]))
    unique: dict[str, str] = {}
    for term in terms:
        unique.setdefault(term.casefold(), term)
    return tuple(unique.values())


def _extract_terms(text: str) -> Iterable[str]:
    for match in _LATIN_TERM.finditer(text):
        term = match.group(0).strip("._:/-")
        if term.casefold() not in _LATIN_STOP and not term.isdigit():
            yield term
    for match in _CJK_RUN.finditer(text):
        run = match.group(0)
        # A full punctuation-bounded clause is far more reviewable than an
        # arbitrary ngram such as “理硬件资”. MySQL's ngram parser can still
        # match the phrase while the benchmark remains human meaningful.
        yield run


def _clean_heading(value: str | None) -> str | None:
    if not value:
        return None
    clean = _SPACE.sub(" ", value).strip().strip("#*-—–:： ")
    if not 2 <= len(clean) <= 120 or clean.casefold() in _GENERIC_HEADINGS:
        return None
    return clean


def _clean_term(value: str) -> str | None:
    clean = _SPACE.sub(" ", str(value)).strip().strip("#*`'\".,，。:：;；()（）[]【】 ")
    if not 2 <= len(clean) <= 48 or "\n" in clean or "\r" in clean:
        return None
    return clean


def _chunk_quality(chunk: BenchmarkChunk, terms: Sequence[str]) -> int:
    return (
        10 * int(_clean_heading(chunk.heading) is not None)
        + 3 * min(len(chunk.keywords), 4)
        + min(len(terms), 8)
    )
