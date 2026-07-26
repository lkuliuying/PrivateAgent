#!/usr/bin/env python3
"""Hard process watchdog for the real-service stress worker.

The workload already applies cooperative asyncio deadlines. This outer process
exists for native libraries and executor threads that cannot be cancelled by
Python. On a hard deadline it terminates only the worker process tree, then
uses the run-owned marker and database nonce to attempt bounded recovery.
"""
from __future__ import annotations

import argparse
import asyncio
import multiprocessing
import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import stress_real_services as stress  # noqa: E402
from _stress_environment import (  # noqa: E402
    DatabaseTimeouts,
    STRESS_DATA_PREFIX,
    StressEnvironment,
    drop_database,
    load_environment_for_cleanup,
    redact_url,
    remove_data_dir,
)


class WorkerTerminationError(RuntimeError):
    """The supervisor could not prove that its worker process exited."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_supervisor_args(argv: Sequence[str]) -> tuple[float | None, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--supervisor-timeout-seconds",
        type=stress.bounded_float(60.0, 100_000.0),
    )
    known, worker_args = parser.parse_known_args(list(argv))
    return known.supervisor_timeout_seconds, worker_args


def _automatic_deadline(args: argparse.Namespace) -> float:
    # Import/migration, steady-state work, warm-up operations, per-document
    # integrity checks and cleanup all receive room before the hard kill.
    dependency_windows = len(stress._OPERATION_ORDER) + args.document_count + 8
    return max(
        300.0,
        args.import_timeout_seconds
        + args.duration_seconds
        + args.operation_timeout_seconds * dependency_windows
        + args.cleanup_timeout_seconds * 5
        + 300.0,
    )


def _terminate_worker(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    capture_output=True,
                    timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        if process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
    if process.poll() is None:
        raise WorkerTerminationError(
            "stress worker did not exit within the supervisor termination deadline"
        )


def _remove_data_dir_worker(
    environment: StressEnvironment, temp_root: Path | None
) -> None:
    try:
        remove_data_dir(environment, temp_root=temp_root)
    except BaseException:  # noqa: BLE001 - child must not print credential-bearing repr
        raise SystemExit(1) from None


def _remove_data_dir_bounded(
    environment: StressEnvironment,
    *,
    temp_root: Path | None,
    timeout_seconds: float,
) -> None:
    """Run recursive deletion in a killable helper process, never a stuck thread."""

    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_remove_data_dir_worker,
        args=(environment, temp_root),
        name=f"stress-data-cleanup-{environment.run_id}",
    )
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(5)
    if process.is_alive():
        process.kill()
        process.join(5)
    if process.is_alive():
        raise TimeoutError("stress data cleanup process did not terminate")
    if process.exitcode != 0 or environment.data_dir.exists():
        raise RuntimeError("stress data cleanup process failed")


async def _recover_owned_resources(
    *,
    mysql_url: str,
    run_id: str,
    allow_remote_mysql: bool,
    temp_root: Path | None,
    cleanup_timeout_seconds: float,
) -> dict[str, object]:
    result: dict[str, object] = {
        "database_created": None,
        "database_dropped": False,
        "database_cleanup_verified": False,
        "data_removed": False,
        "errors": [],
    }
    root = (temp_root or Path(tempfile.gettempdir())).resolve()
    expected_data_dir = root / f"{STRESS_DATA_PREFIX}{run_id}"
    if not expected_data_dir.exists():
        result["data_removed"] = True
        return result
    try:
        environment = load_environment_for_cleanup(
            mysql_url,
            run_id=run_id,
            allow_remote=allow_remote_mysql,
            temp_root=temp_root,
        )
    except Exception as exc:  # noqa: BLE001 - preserve untrusted residue
        result["errors"].append(
            {"target": "ownership_marker", "reason": type(exc).__name__}
        )
        return result
    try:
        dropped = await drop_database(
            environment,
            timeouts=DatabaseTimeouts(
                connect_seconds=min(10.0, cleanup_timeout_seconds),
                operation_seconds=cleanup_timeout_seconds,
                cleanup_seconds=cleanup_timeout_seconds,
            ),
        )
        result["database_created"] = dropped
        result["database_dropped"] = dropped
        result["database_cleanup_verified"] = True
    except Exception as exc:  # noqa: BLE001 - marker is kept for manual retry
        result["errors"].append(
            {"target": "mysql", "reason": type(exc).__name__}
        )
        return result
    try:
        _remove_data_dir_bounded(
            environment,
            temp_root=temp_root,
            timeout_seconds=cleanup_timeout_seconds,
        )
        result["data_removed"] = True
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(
            {"target": "data_dir", "reason": type(exc).__name__}
        )
    return result


def _write_supervisor_failure_report(
    *,
    args: argparse.Namespace,
    run_id: str,
    started_at: str,
    started_monotonic: float,
    deadline_seconds: float,
    mysql_url: str,
    ollama_url: str,
    cleanup: dict[str, object],
    blocker: dict[str, object],
) -> tuple[Path, Path]:
    report = {
        "schema_version": 2,
        "run_id": run_id,
        "status": "failed",
        "started_at": started_at,
        "finished_at": _utc_now(),
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
            "machine": platform.machine(),
            "logical_cpu_count": os.cpu_count(),
        },
        "provenance": stress.repository_provenance(),
        "parameters": {
            "duration_seconds": args.duration_seconds,
            "concurrency": args.concurrency,
            "document_count": args.document_count,
            "document_size_mb": args.document_size_mb,
            "operation_timeout_seconds": args.operation_timeout_seconds,
            "import_timeout_seconds": args.import_timeout_seconds,
            "cleanup_timeout_seconds": args.cleanup_timeout_seconds,
            "supervisor_timeout_seconds": deadline_seconds,
        },
        "services": {
            "mysql_endpoint": redact_url(mysql_url),
            "ollama_endpoint": stress.safe_http_endpoint(ollama_url),
        },
        "operations": {},
        "resources": {"summary": {}, "samples": []},
        "integrity": {},
        "blockers": [blocker],
        "cleanup": cleanup,
    }
    if cleanup.get("errors"):
        report["blockers"].append(
            {"check": "cleanup", "reason": "supervisor recovery was incomplete"}
        )
    return stress.write_reports(report, args.out)


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(argv if argv is not None else sys.argv[1:])
    explicit_deadline, worker_args = _parse_supervisor_args(raw_args)
    args = stress.parse_args(worker_args)
    if not args.confirm_real_services:
        # Preserve the worker's opt-in behavior without starting a subprocess.
        return stress.main(worker_args)
    mysql_url, ollama_url, _llm_model, _embed_model = stress._resolve_configuration(args)
    ollama_url = stress.validate_http_endpoint(
        ollama_url, allow_remote=args.allow_remote_ollama
    )
    deadline_seconds = explicit_deadline or _automatic_deadline(args)
    run_id = stress.new_run_id()
    child_environment = os.environ.copy()
    child_environment["PA_STRESS_SUPERVISOR_RUN_ID"] = run_id
    command = [sys.executable, str(SCRIPT_DIR / "stress_real_services.py"), *worker_args]
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    started_at = _utc_now()
    started_monotonic = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=child_environment,
        creationflags=creation_flags,
    )
    exit_code: int
    blocker: dict[str, object]
    try:
        return process.wait(timeout=deadline_seconds)
    except subprocess.TimeoutExpired:
        exit_code = 124
        blocker = {
            "check": "supervisor_timeout",
            "reason": "stress worker exceeded its hard process deadline",
            "timeout_seconds": deadline_seconds,
        }
    except KeyboardInterrupt:
        exit_code = 130
        blocker = {
            "check": "interrupted",
            "reason": "stress worker was interrupted by the operator",
        }
    try:
        _terminate_worker(process)
    except WorkerTerminationError as exc:
        print(f"[stress] supervisor termination failed: {exc}", file=sys.stderr)
        return 125

    cleanup = asyncio.run(
        _recover_owned_resources(
            mysql_url=mysql_url,
            run_id=run_id,
            allow_remote_mysql=args.allow_remote_mysql,
            temp_root=args.temp_root,
            cleanup_timeout_seconds=args.cleanup_timeout_seconds,
        )
    )
    json_path, markdown_path = _write_supervisor_failure_report(
        args=args,
        run_id=run_id,
        started_at=started_at,
        started_monotonic=started_monotonic,
        deadline_seconds=deadline_seconds,
        mysql_url=mysql_url,
        ollama_url=ollama_url,
        cleanup=cleanup,
        blocker=blocker,
    )
    print("[stress] status: failed", file=sys.stderr)
    print(f"[stress] supervisor JSON: {json_path}", file=sys.stderr)
    print(f"[stress] supervisor Markdown: {markdown_path}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
