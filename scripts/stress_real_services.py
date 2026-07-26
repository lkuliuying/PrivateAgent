#!/usr/bin/env python3
"""Opt-in endurance and large-document stress test against real local services.

This harness exercises the production import and RAG code paths with real
Ollama, MySQL and embedded Chroma.  It never reuses the configured application
schema: every invocation creates a unique ``pa_stress_*`` schema and a
marker-owned temporary data directory, then proves ownership again before
cleanup.

Examples:
    uv run python scripts/stress_real_services.py --confirm-real-services \
        --use-configured-mysql-credentials --duration-seconds 900

    # Credentials are read from the environment, never from command-line args.
    PA_STRESS_MYSQL_URL=mysql+aiomysql://... uv run python \
        scripts/stress_real_services.py --confirm-real-services
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import tracemalloc
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from _stress_environment import (  # noqa: E402
    StressEnvironment,
    StressProvisionError,
    StressSafetyError,
    drop_database,
    make_environment,
    provision_database,
    redact_url,
    remove_data_dir,
)

DEFAULT_THRESHOLDS_MS = {
    "document_import": 600_000.0,
    "mysql_query": 750.0,
    "ollama_embed": 30_000.0,
    "chroma_query": 2_000.0,
    "rag_retrieve": 60_000.0,
    "ollama_chat": 120_000.0,
}
DEFAULT_OUT_DIR = PROJECT_ROOT / "dist" / "stress"
_OPERATION_ORDER = (
    "mysql_query",
    "ollama_embed",
    "chroma_query",
    "rag_retrieve",
    "ollama_chat",
)


class StressRunError(RuntimeError):
    """A secret-free, actionable stress-run failure."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dt%H%M%S")
    return f"{stamp}_{uuid.uuid4().hex[:10]}"


def percentile(values: list[float], quantile: float) -> float | None:
    """Linear percentile suitable for stable latency summaries."""

    if not values:
        return None
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be between 0 and 1")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 2)
    weight = position - lower
    return round(ordered[lower] * (1.0 - weight) + ordered[upper] * weight, 2)


@dataclass(slots=True)
class MetricSeries:
    latencies_ms: list[float] = field(default_factory=list)
    succeeded: int = 0
    failed: int = 0
    error_types: Counter[str] = field(default_factory=Counter)
    first_started_at: float | None = None
    last_finished_at: float | None = None

    def record(
        self,
        elapsed_ms: float,
        error: BaseException | None = None,
        *,
        started_at: float | None = None,
        finished_at: float | None = None,
    ) -> None:
        self.latencies_ms.append(elapsed_ms)
        if started_at is not None:
            self.first_started_at = (
                started_at
                if self.first_started_at is None
                else min(self.first_started_at, started_at)
            )
        if finished_at is not None:
            self.last_finished_at = (
                finished_at
                if self.last_finished_at is None
                else max(self.last_finished_at, finished_at)
            )
        if error is None:
            self.succeeded += 1
        else:
            self.failed += 1
            self.error_types[type(error).__name__] += 1

    def summary(self, elapsed_seconds: float | None = None) -> dict[str, Any]:
        total = self.succeeded + self.failed
        if elapsed_seconds is None:
            if self.first_started_at is not None and self.last_finished_at is not None:
                elapsed_seconds = self.last_finished_at - self.first_started_at
            else:
                elapsed_seconds = sum(self.latencies_ms) / 1000.0
        return {
            "requests": total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "error_rate": round(self.failed / total, 6) if total else 1.0,
            "throughput_per_second": round(
                self.succeeded / max(elapsed_seconds, 0.001), 4
            ),
            "p50_ms": percentile(self.latencies_ms, 0.50),
            "p95_ms": percentile(self.latencies_ms, 0.95),
            "p99_ms": percentile(self.latencies_ms, 0.99),
            "max_ms": round(max(self.latencies_ms), 2) if self.latencies_ms else None,
            "error_types": dict(sorted(self.error_types.items())),
        }


class Metrics:
    def __init__(self) -> None:
        self._series: defaultdict[str, MetricSeries] = defaultdict(MetricSeries)

    async def measure(
        self,
        name: str,
        operation: Callable[[], Awaitable[Any]],
        *,
        timeout_seconds: float,
    ) -> Any:
        started = time.perf_counter()
        error: BaseException | None = None
        try:
            return await asyncio.wait_for(operation(), timeout=timeout_seconds)
        except BaseException as exc:
            error = exc
            raise
        finally:
            finished = time.perf_counter()
            self._series[name].record(
                (finished - started) * 1000.0,
                error,
                started_at=started,
                finished_at=finished,
            )

    def summarize(self) -> dict[str, dict[str, Any]]:
        return {
            name: self._series[name].summary()
            for name in sorted(self._series)
        }


def redact_diagnostic(value: str | None, *, limit: int = 500) -> str | None:
    """Keep actionable failure evidence without persisting credentials."""

    if not value:
        return None
    redacted = re.sub(
        r"([a-z][a-z0-9+.-]*://)[^/@\s:]+(?::[^/@\s]*)?@",
        r"\1<redacted>@",
        value,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"(?i)\b(password|passwd|token|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+",
        r"\1=<redacted>",
        redacted,
    )
    return redacted[:limit]


def safe_http_endpoint(raw_url: str) -> str:
    parts = urlsplit(raw_url)
    host = parts.hostname or "unknown"
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit((parts.scheme, f"{host}{port}", "", "", ""))


def validate_http_endpoint(raw_url: str, *, allow_remote: bool) -> str:
    parts = urlsplit(raw_url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise StressSafetyError("Ollama URL must be an absolute http(s) URL")
    loopback = parts.hostname.casefold() == "localhost" or parts.hostname in {
        "127.0.0.1",
        "::1",
    }
    if not allow_remote and not loopback:
        raise StressSafetyError(
            "remote Ollama is disabled; pass --allow-remote-ollama explicitly"
        )
    return raw_url.rstrip("/")


def load_thresholds(path: Path | None) -> dict[str, float]:
    thresholds = dict(DEFAULT_THRESHOLDS_MS)
    if path is None:
        return thresholds
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise StressSafetyError("threshold JSON must be an object")
    unknown = set(payload) - set(DEFAULT_THRESHOLDS_MS)
    if unknown:
        raise StressSafetyError(f"unknown threshold operations: {sorted(unknown)}")
    for key, raw_value in payload.items():
        value = float(raw_value)
        if not math.isfinite(value) or value <= 0:
            raise StressSafetyError(f"threshold {key} must be positive and finite")
        thresholds[key] = value
    return thresholds


def generate_large_markdown(path: Path, size_bytes: int, marker: str) -> int:
    """Generate deterministic, valid UTF-8 markdown without retaining it in RAM."""

    if size_bytes < 1024:
        raise ValueError("large document must be at least 1024 bytes")
    header = (
        f"# Real service stress document {marker}\n\n"
        f"Search anchor: pa stress retrieval {marker}.\n\n"
    ).encode()
    paragraph = (
        "## Reliability section\n\n"
        "This generated document validates large document parsing, deterministic "
        "chunking, Ollama embeddings, MySQL full text retrieval, and Chroma vector "
        f"recall. Search anchor pa stress retrieval {marker}.\n\n"
    ).encode()
    written = 0
    with path.open("wb") as handle:
        handle.write(header)
        written += len(header)
        while written + len(paragraph) <= size_bytes:
            handle.write(paragraph)
            written += len(paragraph)
        if written < size_bytes:
            padding = b"x" * (size_bytes - written)
            handle.write(padding)
            written += len(padding)
    return written


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def repository_provenance() -> dict[str, Any]:
    """Bind a report to source and dependency-lock bytes without exposing diffs."""

    commit: str | None = None
    dirty: bool | None = None
    try:
        commit_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
        )
        if commit_result.returncode == 0:
            commit = commit_result.stdout.strip() or None
        status_result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
        )
        if status_result.returncode == 0:
            dirty = bool(status_result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass

    lockfiles: dict[str, str] = {}
    for relative in (
        "uv.lock",
        "apps/desktop/package-lock.json",
        "scripts/windows/updater-signature-verifier/Cargo.lock",
    ):
        path = PROJECT_ROOT / relative
        if path.is_file():
            lockfiles[relative] = sha256_file(path)
    return {
        "git_commit": commit,
        "git_dirty": dirty,
        "lockfile_sha256": lockfiles,
    }


def process_rss_bytes() -> int | None:
    """Best-effort resident set measurement without an extra dependency."""

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = (
                wintypes.HANDLE,
                ctypes.POINTER(ProcessMemoryCounters),
                wintypes.DWORD,
            )
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            process = kernel32.GetCurrentProcess()
            ok = psapi.GetProcessMemoryInfo(
                process, ctypes.byref(counters), counters.cb
            )
            return int(counters.WorkingSetSize) if ok else None
        except (AttributeError, OSError):
            return None
    try:
        import resource

        maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(maximum * (1 if sys.platform == "darwin" else 1024))
    except (ImportError, OSError):
        return None


def directory_size(path: Path) -> int:
    total = 0
    for candidate in path.rglob("*"):
        try:
            if candidate.is_file():
                total += candidate.stat().st_size
        except OSError:
            continue
    return total


def migrate_database() -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("prepend_sys_path", str(PROJECT_ROOT / "src"))
    command.upgrade(config, "head")


def evaluate_thresholds(
    operations: dict[str, dict[str, Any]],
    *,
    thresholds_ms: dict[str, float],
    max_error_rate: float,
    max_rss_mb: float,
    max_steady_rss_growth_mb: float,
    resource_summary: dict[str, Any],
    integrity: dict[str, Any],
    min_steady_throughput_per_second: float = 0.0,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for name, threshold in thresholds_ms.items():
        result = operations.get(name)
        if result is None or result["requests"] == 0:
            blockers.append({"check": name, "reason": "operation was not exercised"})
            continue
        if result["error_rate"] > max_error_rate:
            blockers.append(
                {
                    "check": name,
                    "reason": "error_rate",
                    "actual": result["error_rate"],
                    "threshold": max_error_rate,
                }
            )
        if result["p95_ms"] is not None and result["p95_ms"] > threshold:
            blockers.append(
                {
                    "check": name,
                    "reason": "p95_ms",
                    "actual": result["p95_ms"],
                    "threshold": threshold,
                }
            )
        if (
            name in _OPERATION_ORDER
            and result.get("throughput_per_second", 0.0)
            < min_steady_throughput_per_second
        ):
            blockers.append(
                {
                    "check": name,
                    "reason": "throughput_per_second",
                    "actual": result.get("throughput_per_second", 0.0),
                    "threshold": min_steady_throughput_per_second,
                }
            )
    maximum_rss = resource_summary.get("max_rss_bytes")
    if maximum_rss is None:
        blockers.append(
            {
                "check": "process_rss",
                "reason": "RSS sampling produced no usable value",
            }
        )
    elif maximum_rss > max_rss_mb * 1024 * 1024:
        blockers.append(
            {
                "check": "process_rss",
                "reason": "max_rss_mb",
                "actual": round(maximum_rss / 1024 / 1024, 2),
                "threshold": max_rss_mb,
            }
        )
    steady_growth = resource_summary.get("steady_rss_growth_bytes")
    if steady_growth is None:
        blockers.append(
            {
                "check": "steady_rss_growth",
                "reason": "steady-state RSS sampling produced fewer than two usable values",
            }
        )
    elif steady_growth > max_steady_rss_growth_mb * 1024 * 1024:
        blockers.append(
            {
                "check": "steady_rss_growth",
                "reason": "max_steady_rss_growth_mb",
                "actual": round(steady_growth / 1024 / 1024, 2),
                "threshold": max_steady_rss_growth_mb,
            }
        )
    if integrity.get("mysql_chunks") != integrity.get("chroma_vectors"):
        blockers.append(
            {
                "check": "index_integrity",
                "reason": "MySQL chunk and Chroma vector counts differ",
                "actual": integrity,
            }
        )
    if integrity.get("chunk_id_sets_equal") is not True:
        blockers.append(
            {
                "check": "index_identity",
                "reason": "MySQL and Chroma chunk ID sets differ",
            }
        )
    if integrity.get("all_document_markers_verified") is not True:
        blockers.append(
            {
                "check": "document_retrieval_integrity",
                "reason": "one or more document markers were not stored and retrieved",
                "actual": {
                    "mysql_marker_checks": integrity.get("mysql_marker_checks"),
                    "rag_marker_checks": integrity.get("rag_marker_checks"),
                },
            }
        )
    return blockers


def write_reports(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"real-services-{report['run_id']}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Real-service stress report",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Status: **{report['status']}**",
        f"- Started: {report['started_at']}",
        f"- Finished: {report['finished_at']}",
        f"- Duration: {report['elapsed_seconds']} seconds",
        f"- Git commit: `{report.get('provenance', {}).get('git_commit')}` "
        f"(dirty={report.get('provenance', {}).get('git_dirty')})",
        f"- MySQL: `{report['services'].get('mysql_endpoint', 'not reached')}`",
        f"- Ollama: `{report['services'].get('ollama_endpoint', 'not reached')}`",
        f"- LLM digest: `{report['services'].get('llm_model_digest')}`",
        f"- Embedding digest: `{report['services'].get('embed_model_digest')}`",
        "",
        "## Workload",
        "",
        f"- Documents: {report['parameters']['document_count']} × "
        f"{report['parameters']['document_size_mb']} MiB",
        f"- Concurrency: {report['parameters']['concurrency']}",
        f"- Steady-state target: {report['parameters']['duration_seconds']} seconds",
        "",
        "## Latency and throughput",
        "",
        "| Operation | Requests | Errors | Error rate | Throughput/s | p50 ms | p95 ms | p99 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in report.get("operations", {}).items():
        lines.append(
            f"| {name} | {item['requests']} | {item['failed']} | "
            f"{item['error_rate']:.4%} | {item['throughput_per_second']} | "
            f"{item['p50_ms']} | {item['p95_ms']} | {item['p99_ms']} |"
        )
    resources = report.get("resources", {}).get("summary", {})
    lines.extend(
        [
            "",
            "## Resources and integrity",
            "",
            f"- Peak process RSS: {resources.get('max_rss_mb')} MiB",
            f"- Process RSS growth: {resources.get('rss_growth_mb')} MiB "
            f"({resources.get('rss_growth_mb_per_hour')} MiB/hour over the sampled window)",
            f"- Steady-state RSS growth: {resources.get('steady_rss_growth_mb')} MiB "
            f"({resources.get('steady_rss_growth_mb_per_hour')} MiB/hour; "
            f"{resources.get('steady_rss_samples')} samples)",
            f"- Peak traced Python allocation: {resources.get('max_python_peak_mb')} MiB",
            f"- Peak isolated data directory: {resources.get('max_data_dir_mb')} MiB",
            f"- Maximum application queue/running: "
            f"{resources.get('max_background_queued')}/{resources.get('max_background_running')}",
            f"- MySQL chunks / Chroma vectors: "
            f"{report.get('integrity', {}).get('mysql_chunks')} / "
            f"{report.get('integrity', {}).get('chroma_vectors')}",
            f"- Exact chunk ID sets equal: "
            f"{report.get('integrity', {}).get('chunk_id_sets_equal')}",
            f"- Every document marker stored and retrieved: "
            f"{report.get('integrity', {}).get('all_document_markers_verified')}",
            "",
            "## Threshold result",
            "",
        ]
    )
    blockers = report.get("blockers", [])
    if blockers:
        lines.extend(f"- BLOCKER: `{json.dumps(item, ensure_ascii=False)}`" for item in blockers)
    else:
        lines.append("- All configured thresholds passed.")
    lines.extend(
        [
            "",
            "## Cleanup",
            "",
            f"- Database created by this run: "
            f"{report.get('cleanup', {}).get('database_created')}",
            f"- Database dropped: {report.get('cleanup', {}).get('database_dropped')}",
            f"- Database cleanup verified: "
            f"{report.get('cleanup', {}).get('database_cleanup_verified')}",
            f"- Temporary data removed: {report.get('cleanup', {}).get('data_removed')}",
            f"- Cleanup errors: {report.get('cleanup', {}).get('errors', [])}",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def _resource_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    def maximum(key: str) -> int | None:
        values = [sample[key] for sample in samples if sample.get(key) is not None]
        return max(values) if values else None

    rss = maximum("rss_bytes")
    python_peak = maximum("python_peak_bytes")
    data_size = maximum("data_dir_bytes")
    rss_samples = [
        (float(sample.get("elapsed_seconds", 0.0)), int(sample["rss_bytes"]))
        for sample in samples
        if sample.get("rss_bytes") is not None
    ]
    steady_rss_samples = [
        (float(sample.get("elapsed_seconds", 0.0)), int(sample["rss_bytes"]))
        for sample in samples
        if sample.get("phase") == "steady" and sample.get("rss_bytes") is not None
    ]

    def growth(values: list[tuple[float, int]]) -> tuple[int | None, float | None]:
        if len(values) < 2:
            return None, None
        elapsed = values[-1][0] - values[0][0]
        delta = values[-1][1] - values[0][1]
        if elapsed > 0:
            return delta, delta / 1024 / 1024 / elapsed * 3600
        return delta, None

    rss_growth, rss_growth_per_hour = growth(rss_samples)
    steady_rss_growth, steady_rss_growth_per_hour = growth(steady_rss_samples)
    return {
        "samples": len(samples),
        "max_rss_bytes": rss,
        "max_rss_mb": round(rss / 1024 / 1024, 2) if rss is not None else None,
        "rss_growth_mb": (
            round(rss_growth / 1024 / 1024, 2) if rss_growth is not None else None
        ),
        "rss_growth_mb_per_hour": (
            round(rss_growth_per_hour, 2)
            if rss_growth_per_hour is not None
            else None
        ),
        "steady_rss_samples": len(steady_rss_samples),
        "steady_rss_growth_bytes": steady_rss_growth,
        "steady_rss_growth_mb": (
            round(steady_rss_growth / 1024 / 1024, 2)
            if steady_rss_growth is not None
            else None
        ),
        "steady_rss_growth_mb_per_hour": (
            round(steady_rss_growth_per_hour, 2)
            if steady_rss_growth_per_hour is not None
            else None
        ),
        "max_python_peak_mb": (
            round(python_peak / 1024 / 1024, 2) if python_peak is not None else None
        ),
        "max_data_dir_mb": (
            round(data_size / 1024 / 1024, 2) if data_size is not None else None
        ),
        "max_background_queued": maximum("background_queued"),
        "max_background_running": maximum("background_running"),
        "max_db_pool_checked_out": maximum("db_pool_checked_out"),
    }


async def run_workload(
    args: argparse.Namespace,
    environment: StressEnvironment,
    metrics: Metrics,
    report: dict[str, Any],
) -> None:
    from personal_assistant.config import settings
    from personal_assistant.core.background import background_tasks
    from personal_assistant.core.db import async_session_factory, engine
    from personal_assistant.core.hybrid_retrieval import HybridRetriever
    from personal_assistant.core.models import DocChunk
    from personal_assistant.core.provider import OllamaProvider
    from personal_assistant.core.repo import DocumentRepository
    from personal_assistant.core.store_chroma import chroma_store
    from personal_assistant.workers.importer import import_document

    provider = OllamaProvider(
        base_url=args.ollama_url,
        llm_model=args.llm_model,
        embed_model=args.embed_model,
    )
    health = await provider.health()
    if not health.get("ok"):
        raise StressRunError("Ollama health check failed")
    if not health.get("llm_model_available"):
        raise StressRunError(f"configured LLM model is unavailable: {args.llm_model}")
    if not health.get("embed_model_available"):
        raise StressRunError(
            f"configured embedding model is unavailable: {args.embed_model}"
        )
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{args.ollama_url}/api/version")
        response.raise_for_status()
        ollama_version = response.json().get("version", "unknown")
        tags_response = await client.get(f"{args.ollama_url}/api/tags")
        tags_response.raise_for_status()
        ollama_models = {
            str(item.get("name") or item.get("model")): str(item.get("digest") or "")
            for item in tags_response.json().get("models", [])
            if item.get("name") or item.get("model")
        }

    def model_digest(requested: str) -> str | None:
        requested_base = requested.split(":", 1)[0]
        for name, digest in ollama_models.items():
            if name == requested or name.split(":", 1)[0] == requested_base:
                return digest or None
        return None
    import chromadb

    report["services"].update(
        {
            "ollama_endpoint": safe_http_endpoint(args.ollama_url),
            "ollama_version": ollama_version,
            "llm_model": args.llm_model,
            "llm_model_digest": model_digest(args.llm_model),
            "embed_model": args.embed_model,
            "embed_model_digest": model_digest(args.embed_model),
            "chroma_version": chromadb.__version__,
            "chroma_path": "run-owned temporary directory",
        }
    )

    samples: list[dict[str, Any]] = []
    stop_sampling = asyncio.Event()
    workload_started = time.monotonic()
    resource_phase = "document_import"
    sample_lock = asyncio.Lock()

    async def capture_resource_sample() -> None:
        async with sample_lock:
            current, peak = tracemalloc.get_traced_memory()
            pool = engine.pool
            stats = background_tasks.stats()
            samples.append(
                {
                    "phase": resource_phase,
                    "elapsed_seconds": round(time.monotonic() - workload_started, 2),
                    "rss_bytes": process_rss_bytes(),
                    "python_allocated_bytes": current,
                    "python_peak_bytes": peak,
                    "cpu_seconds": round(time.process_time(), 3),
                    "data_dir_bytes": await asyncio.to_thread(
                        directory_size, settings.data_dir
                    ),
                    "chroma_vectors": await chroma_store.count(),
                    "db_pool_checked_out": getattr(pool, "checkedout", lambda: None)(),
                    "db_pool_size": getattr(pool, "size", lambda: None)(),
                    "background_queued": stats["queued"],
                    "background_running": stats["running"],
                }
            )

    async def capture_resource_sample_bounded() -> None:
        await asyncio.wait_for(
            capture_resource_sample(),
            timeout=args.operation_timeout_seconds,
        )

    async def sample_resources() -> None:
        while not stop_sampling.is_set():
            await capture_resource_sample_bounded()
            try:
                await asyncio.wait_for(
                    stop_sampling.wait(), timeout=args.sample_interval_seconds
                )
            except TimeoutError:
                pass
    sampler = asyncio.create_task(sample_resources(), name="stress-resource-sampler")
    failure: BaseException | None = None
    sampler_failure: BaseException | None = None
    provider_close_failure: BaseException | None = None
    try:
        document_dir = settings.data_dir / "stress-documents"
        document_dir.mkdir(parents=True, exist_ok=True)
        size_bytes = int(args.document_size_mb * 1024 * 1024)
        documents: list[tuple[int, Path, str]] = []
        for index in range(args.document_count):
            marker = f"{environment.run_id}-document-{index}"
            path = document_dir / f"stress-{index}.md"
            actual_size = await asyncio.to_thread(
                generate_large_markdown, path, size_bytes, marker
            )
            content_hash = await asyncio.to_thread(sha256_file, path)
            async with async_session_factory() as db:
                document = await DocumentRepository(db).create(
                    name=path.name,
                    source_path=str(path),
                    mime_type="text/markdown",
                    size_bytes=actual_size,
                    content_hash=content_hash,
                    embedding_model=args.embed_model,
                    doc_type="markdown",
                )
            documents.append((document.id, path, marker))

        semaphore = asyncio.Semaphore(args.concurrency)

        async def import_one(document_id: int, path: Path) -> None:
            async with semaphore:
                await import_document(document_id, str(path))
                async with async_session_factory() as db:
                    document = await DocumentRepository(db).get(document_id)
                if document is None or document.status != "ready":
                    status = document.status if document is not None else "missing"
                    detail = redact_diagnostic(
                        document.error_message if document is not None else None
                    )
                    report.setdefault("diagnostics", {}).setdefault(
                        "document_import_failures", []
                    ).append(
                        {
                            "document_id": document_id,
                            "status": status,
                            "detail": detail,
                        }
                    )
                    raise StressRunError(
                        f"document import ended as {status}: {detail or 'no diagnostic'}"
                    )

        import_results = await asyncio.gather(
            *(
                metrics.measure(
                    "document_import",
                    lambda document_id=document_id, path=path: import_one(
                        document_id, path
                    ),
                    timeout_seconds=args.import_timeout_seconds,
                )
                for document_id, path, _marker in documents
            ),
            return_exceptions=True,
        )
        import_failures = [
            result for result in import_results if isinstance(result, BaseException)
        ]
        if import_failures:
            kinds = sorted({type(item).__name__ for item in import_failures})
            raise StressRunError(
                f"{len(import_failures)} document import(s) failed: {', '.join(kinds)}"
            )

        query = "pa stress retrieval reliability"
        cached_embedding = await provider.embed_one(query)

        async def mysql_query() -> None:
            async with async_session_factory() as db:
                matches = (
                    await db.execute(
                        text(
                            "SELECT id, MATCH(bm25_text) AGAINST "
                            "(:query IN NATURAL LANGUAGE MODE) AS score "
                            "FROM doc_chunks WHERE MATCH(bm25_text) AGAINST "
                            "(:query IN NATURAL LANGUAGE MODE) > 0 LIMIT 5"
                        ),
                        {"query": query},
                    )
                ).all()
            if not matches:
                raise StressRunError("MySQL FULLTEXT returned no matching chunks")

        async def ollama_embed() -> None:
            embedding = await provider.embed_one(query)
            if not embedding:
                raise StressRunError("Ollama returned an empty embedding")

        async def chroma_query() -> None:
            ids = await chroma_store.query(cached_embedding, top_k=5)
            if not ids:
                raise StressRunError("Chroma returned no vector matches")

        async def rag_retrieve() -> None:
            async with async_session_factory() as db:
                results = await HybridRetriever(db, provider=provider).retrieve(
                    query, top_k=5
                )
            if not results:
                raise StressRunError("hybrid RAG returned no results")
            paths = {source for item in results for source in item.matched_via}
            if not {"vector", "bm25"}.issubset(paths):
                raise StressRunError(
                    "hybrid RAG did not prove both vector and BM25 recall paths"
                )
            if len(results) > 1 and any(
                item.rerank_score is None for item in results
            ):
                raise StressRunError("hybrid RAG reranking was not applied")

        async def ollama_chat() -> None:
            answer = await provider.chat(
                [
                    {
                        "role": "user",
                        "content": "Reply with the single word OK. This is a local stress probe.",
                    }
                ]
            )
            if not answer.strip():
                raise StressRunError("Ollama returned an empty chat response")

        operations: dict[str, Callable[[], Awaitable[None]]] = {
            "mysql_query": mysql_query,
            "ollama_embed": ollama_embed,
            "chroma_query": chroma_query,
            "rag_retrieve": rag_retrieve,
            "ollama_chat": ollama_chat,
        }

        # Guarantee every real dependency/path is covered even for a tiny smoke.
        for name in _OPERATION_ORDER:
            try:
                await metrics.measure(
                    name,
                    operations[name],
                    timeout_seconds=args.operation_timeout_seconds,
                )
            except Exception:  # noqa: BLE001 - thresholds retain the failure
                pass

        counter = 0
        counter_lock = asyncio.Lock()
        resource_phase = "steady"
        await capture_resource_sample_bounded()
        steady_started = time.monotonic()
        deadline = steady_started + args.duration_seconds

        async def worker() -> None:
            nonlocal counter
            while time.monotonic() < deadline:
                async with counter_lock:
                    name = _OPERATION_ORDER[counter % len(_OPERATION_ORDER)]
                    counter += 1
                try:
                    await metrics.measure(
                        name,
                        operations[name],
                        timeout_seconds=args.operation_timeout_seconds,
                    )
                except Exception:  # noqa: BLE001 - aggregate and continue
                    continue

        await asyncio.gather(*(worker() for _ in range(args.concurrency)))
        steady_elapsed = time.monotonic() - steady_started
        await capture_resource_sample()
        resource_phase = "integrity"

        document_ids = [document_id for document_id, _path, _marker in documents]
        marker_checks: dict[str, bool] = {}
        async with async_session_factory() as db:
            mysql_rows = (
                await db.execute(
                    select(DocChunk.id, DocChunk.doc_id).where(
                        DocChunk.doc_id.in_(document_ids)
                    )
                )
            ).all()
            mysql_chunk_ids = {int(row.id) for row in mysql_rows}
            mysql_chunks = len(mysql_chunk_ids)
            for document_id, _path, marker in documents:
                marker_count = int(
                    await db.scalar(
                        select(func.count(DocChunk.id)).where(
                            DocChunk.doc_id == document_id,
                            DocChunk.content.contains(marker),
                        )
                    )
                    or 0
                )
                marker_checks[str(document_id)] = marker_count > 0
            selected_database = str(await db.scalar(text("SELECT DATABASE()")))
        if selected_database != environment.database_name:
            raise StressSafetyError(
                "application connected to an unexpected MySQL schema"
            )
        chroma_chunk_ids = set(await chroma_store.list_ids())
        chroma_vectors = len(chroma_chunk_ids)
        retrieval_checks: dict[str, bool] = {}
        for document_id, _path, marker in documents:
            async with async_session_factory() as db:
                marker_results = await HybridRetriever(db, provider=provider).retrieve(
                    f"pa stress retrieval {marker}", top_k=max(5, len(documents))
                )
            retrieval_checks[str(document_id)] = any(
                item.doc_id == document_id for item in marker_results
            )
        report["steady_state_elapsed_seconds"] = round(steady_elapsed, 3)
        report["integrity"] = {
            "documents": len(documents),
            "mysql_chunks": mysql_chunks,
            "chroma_vectors": chroma_vectors,
            "chunk_id_sets_equal": mysql_chunk_ids == chroma_chunk_ids,
            "mysql_marker_checks": marker_checks,
            "rag_marker_checks": retrieval_checks,
            "all_document_markers_verified": all(marker_checks.values())
            and all(retrieval_checks.values()),
        }
    except BaseException as exc:  # noqa: BLE001 - sample/close before re-raise
        failure = exc
    finally:
        stop_sampling.set()
        try:
            await asyncio.wait_for(
                asyncio.shield(sampler),
                timeout=max(1.0, min(10.0, args.operation_timeout_seconds)),
            )
        except TimeoutError:
            sampler.cancel()
            try:
                await asyncio.wait_for(sampler, timeout=5.0)
            except asyncio.CancelledError:
                pass
            except BaseException as exc:  # noqa: BLE001
                sampler_failure = exc
            if sampler_failure is None:
                sampler_failure = StressRunError(
                    "resource sampler did not stop within its cleanup deadline"
                )
        except BaseException as exc:  # noqa: BLE001
            sampler_failure = exc
        try:
            await provider.aclose()
        except BaseException as exc:  # noqa: BLE001
            provider_close_failure = exc
        report["resources"] = {
            "summary": _resource_summary(samples),
            "samples": samples,
        }
        if sampler_failure is not None:
            report.setdefault("diagnostics", {})["resource_sampler_error"] = type(
                sampler_failure
            ).__name__
        if provider_close_failure is not None:
            report.setdefault("diagnostics", {})["provider_close_error"] = type(
                provider_close_failure
            ).__name__

    if failure is not None:
        raise failure.with_traceback(failure.__traceback__)
    if sampler_failure is not None:
        raise StressRunError("resource sampler failed") from sampler_failure
    if provider_close_failure is not None:
        raise StressRunError("Ollama provider cleanup failed") from provider_close_failure


def _resolve_configuration(args: argparse.Namespace) -> tuple[str, str, str, str]:
    configured = None
    stress_url = os.environ.get("PA_STRESS_MYSQL_URL", "").strip()
    if args.use_configured_mysql_credentials or not (
        args.ollama_url and args.llm_model and args.embed_model
    ):
        from personal_assistant.config import Settings

        configured = Settings()  # type: ignore[call-arg]
    if args.use_configured_mysql_credentials:
        assert configured is not None
        if stress_url:
            raise StressSafetyError(
                "choose either PA_STRESS_MYSQL_URL or --use-configured-mysql-credentials"
            )
        stress_url = configured.db_url
    if not stress_url:
        raise StressSafetyError(
            "set PA_STRESS_MYSQL_URL or pass --use-configured-mysql-credentials"
        )
    ollama_url = args.ollama_url or (
        configured.ollama_base_url if configured else "http://127.0.0.1:11434"
    )
    llm_model = args.llm_model or (
        configured.llm_model if configured else "qwen2.5:14b-instruct-q4_K_M"
    )
    embed_model = args.embed_model or (
        configured.embed_model if configured else "bge-m3"
    )
    return stress_url, ollama_url, llm_model, embed_model


def _activate_application(
    environment: StressEnvironment,
    *,
    ollama_url: str,
    llm_model: str,
    embed_model: str,
) -> None:
    if "personal_assistant.core.db" in sys.modules:
        raise StressSafetyError("application database engine was initialized before isolation")
    os.environ.update(
        {
            "PA_DB_URL": environment.database_url,
            "PA_DATA_DIR": str(environment.data_dir),
            "PA_OLLAMA_BASE_URL": ollama_url,
            "PA_LLM_MODEL": llm_model,
            "PA_EMBED_MODEL": embed_model,
            "PA_STRESS_RUN_ID": environment.run_id,
        }
    )
    # ``Settings`` may already be cached because configured credentials were
    # explicitly requested. Mutate only before the global DB engine exists.
    from personal_assistant.config import settings

    settings.db_url = environment.database_url
    settings.data_dir = environment.data_dir
    settings.ollama_base_url = ollama_url
    settings.llm_model = llm_model
    settings.embed_model = embed_model


async def execute(args: argparse.Namespace) -> tuple[dict[str, Any], Path, Path]:
    if not args.confirm_real_services:
        raise StressSafetyError(
            "real-service stress is opt-in; pass --confirm-real-services"
        )
    stress_url, ollama_url, llm_model, embed_model = _resolve_configuration(args)
    args.ollama_url = validate_http_endpoint(
        ollama_url, allow_remote=args.allow_remote_ollama
    )
    args.llm_model = llm_model
    args.embed_model = embed_model
    thresholds = load_thresholds(args.thresholds_json)
    run_id = new_run_id()
    environment = make_environment(
        stress_url,
        run_id=run_id,
        allow_remote=args.allow_remote_mysql,
        temp_root=args.temp_root,
    )
    report: dict[str, Any] = {
        "schema_version": 2,
        "run_id": run_id,
        "status": "running",
        "started_at": utc_now(),
        "finished_at": None,
        "elapsed_seconds": None,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
        },
        "provenance": repository_provenance(),
        "parameters": {
            "duration_seconds": args.duration_seconds,
            "concurrency": args.concurrency,
            "document_count": args.document_count,
            "document_size_mb": args.document_size_mb,
            "operation_timeout_seconds": args.operation_timeout_seconds,
            "import_timeout_seconds": args.import_timeout_seconds,
            "sample_interval_seconds": args.sample_interval_seconds,
            "max_error_rate": args.max_error_rate,
            "max_rss_mb": args.max_rss_mb,
            "max_steady_rss_growth_mb": args.max_steady_rss_growth_mb,
            "min_steady_throughput_per_second": args.min_steady_throughput_per_second,
            "thresholds_ms": thresholds,
        },
        "services": {
            "mysql_endpoint": redact_url(environment.database_url),
            "mysql_database": environment.database_name,
            "ollama_endpoint": safe_http_endpoint(args.ollama_url),
        },
        "operations": {},
        "resources": {"summary": {}, "samples": []},
        "integrity": {},
        "blockers": [],
        "cleanup": {
            "database_created": False,
            "database_dropped": False,
            "database_cleanup_verified": False,
            "data_removed": False,
            "errors": [],
        },
    }
    started = time.monotonic()
    metrics = Metrics()
    database_created = False
    application_activated = False
    try:
        raw_document_bytes = int(
            args.document_count * args.document_size_mb * 1024 * 1024
        )
        required_free_bytes = max(512 * 1024 * 1024, raw_document_bytes * 4)
        free_bytes = shutil.disk_usage(environment.data_dir.parent).free
        report["platform"]["disk_free_bytes_before_run"] = free_bytes
        report["parameters"]["required_free_bytes"] = required_free_bytes
        if free_bytes < required_free_bytes:
            raise StressSafetyError(
                "insufficient free disk space for document and index amplification"
            )
        mysql_version = await provision_database(environment)
        database_created = True
        report["cleanup"]["database_created"] = True
        report["services"]["mysql_version"] = mysql_version
        _activate_application(
            environment,
            ollama_url=args.ollama_url,
            llm_model=args.llm_model,
            embed_model=args.embed_model,
        )
        application_activated = True
        await asyncio.to_thread(migrate_database)
        tracemalloc.start()
        await run_workload(args, environment, metrics, report)
    except (StressSafetyError, StressProvisionError, StressRunError) as exc:
        if isinstance(exc, StressProvisionError) and exc.database_created:
            database_created = True
            report["cleanup"]["database_created"] = True
        report["blockers"].append(
            {"check": "run", "reason": type(exc).__name__, "detail": str(exc)}
        )
    except BaseException as exc:  # noqa: BLE001 - cleanup/report before propagating
        report["blockers"].append(
            {"check": "run", "reason": type(exc).__name__}
        )
        if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
            report["blockers"].append({"check": "run", "reason": "interrupted"})
    finally:
        report["operations"] = metrics.summarize()
        if report["integrity"]:
            report["blockers"].extend(
                evaluate_thresholds(
                    report["operations"],
                    thresholds_ms=thresholds,
                    max_error_rate=args.max_error_rate,
                    max_rss_mb=args.max_rss_mb,
                    max_steady_rss_growth_mb=args.max_steady_rss_growth_mb,
                    resource_summary=report["resources"]["summary"],
                    integrity=report["integrity"],
                    min_steady_throughput_per_second=args.min_steady_throughput_per_second,
                )
            )
        if application_activated:
            try:
                from personal_assistant.core.background import background_tasks

                await background_tasks.cancel_all()
                remaining = background_tasks.stats()
                if remaining["queued"] or remaining["running"]:
                    raise StressRunError("background tasks remained after cancellation")
            except Exception as exc:  # noqa: BLE001
                report["cleanup"]["errors"].append(
                    {"target": "background_tasks", "reason": type(exc).__name__}
                )
            try:
                from personal_assistant.core.store_chroma import chroma_store

                await chroma_store.close()
            except Exception as exc:  # noqa: BLE001
                report["cleanup"]["errors"].append(
                    {"target": "chroma", "reason": type(exc).__name__}
                )
            try:
                from personal_assistant.core.db import engine

                await engine.dispose()
            except Exception as exc:  # noqa: BLE001
                report["cleanup"]["errors"].append(
                    {"target": "sqlalchemy", "reason": type(exc).__name__}
                )
        # A schema is removable only after CREATE completed in this process.
        # In particular, never drop a pre-existing schema when the generated
        # name collides or was deliberately reserved by another actor.
        if database_created:
            try:
                dropped = await drop_database(environment)
                report["cleanup"]["database_dropped"] = dropped
                report["cleanup"]["database_cleanup_verified"] = True
            except Exception as exc:  # noqa: BLE001
                report["cleanup"]["errors"].append(
                    {"target": "mysql", "reason": type(exc).__name__}
                )
        # Preserve the ownership marker when MySQL cleanup fails; it is the
        # evidence required for a safe, targeted manual retry.
        if not database_created or report["cleanup"]["database_cleanup_verified"]:
            try:
                remove_data_dir(environment, temp_root=args.temp_root)
                report["cleanup"]["data_removed"] = True
            except Exception as exc:  # noqa: BLE001
                report["cleanup"]["errors"].append(
                    {"target": "data_dir", "reason": type(exc).__name__}
                )
        if database_created and not report["cleanup"]["database_cleanup_verified"]:
            report["blockers"].append(
                {"check": "cleanup", "reason": "isolated database was not dropped"}
            )
        if not report["cleanup"]["data_removed"]:
            report["blockers"].append(
                {"check": "cleanup", "reason": "temporary data was not removed"}
            )
        if report["cleanup"]["errors"]:
            report["blockers"].append(
                {"check": "cleanup", "reason": "cleanup errors occurred"}
            )
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["finished_at"] = utc_now()
        report["status"] = "failed" if report["blockers"] else "passed"
        json_path, md_path = write_reports(report, args.out)
    return report, json_path, md_path


def bounded_float(minimum: float, maximum: float) -> Callable[[str], float]:
    def parse(raw: str) -> float:
        value = float(raw)
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise argparse.ArgumentTypeError(
                f"value must be between {minimum} and {maximum}"
            )
        return value

    return parse


def bounded_int(minimum: int, maximum: int) -> Callable[[str], int]:
    def parse(raw: str) -> int:
        value = int(raw)
        if not minimum <= value <= maximum:
            raise argparse.ArgumentTypeError(
                f"value must be between {minimum} and {maximum}"
            )
        return value

    return parse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--confirm-real-services", action="store_true")
    parser.add_argument(
        "--use-configured-mysql-credentials",
        action="store_true",
        help="reuse configured credentials, but never its database name",
    )
    parser.add_argument("--allow-remote-mysql", action="store_true")
    parser.add_argument("--allow-remote-ollama", action="store_true")
    parser.add_argument("--ollama-url")
    parser.add_argument("--llm-model")
    parser.add_argument("--embed-model")
    parser.add_argument(
        "--duration-seconds", type=bounded_float(0.0, 86_400.0), default=900.0
    )
    parser.add_argument("--concurrency", type=bounded_int(1, 32), default=4)
    parser.add_argument("--document-count", type=bounded_int(1, 32), default=2)
    parser.add_argument(
        "--document-size-mb", type=bounded_float(0.01, 256.0), default=4.0
    )
    parser.add_argument(
        "--operation-timeout-seconds",
        type=bounded_float(1.0, 1_800.0),
        default=180.0,
    )
    parser.add_argument(
        "--import-timeout-seconds",
        type=bounded_float(1.0, 7_200.0),
        default=1_800.0,
    )
    parser.add_argument(
        "--sample-interval-seconds",
        type=bounded_float(0.1, 300.0),
        default=5.0,
    )
    parser.add_argument(
        "--max-error-rate", type=bounded_float(0.0, 1.0), default=0.01
    )
    parser.add_argument(
        "--max-rss-mb", type=bounded_float(64.0, 131_072.0), default=8_192.0
    )
    parser.add_argument(
        "--max-steady-rss-growth-mb",
        type=bounded_float(0.0, 65_536.0),
        default=256.0,
    )
    parser.add_argument(
        "--min-steady-throughput-per-second",
        type=bounded_float(0.0, 10_000.0),
        default=0.01,
    )
    parser.add_argument("--thresholds-json", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--temp-root", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report, json_path, md_path = asyncio.run(execute(args))
    except (StressSafetyError, StressProvisionError) as exc:
        print(f"[stress] blocked: {exc}", file=sys.stderr)
        return 2
    print(f"[stress] status: {report['status']}")
    print(f"[stress] JSON: {json_path}")
    print(f"[stress] Markdown: {md_path}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
