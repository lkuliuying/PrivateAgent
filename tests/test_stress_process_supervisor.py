from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import stress_process_supervisor as supervisor  # noqa: E402
import stress_real_services as stress  # noqa: E402
from _stress_environment import make_environment  # noqa: E402


def test_batch_entrypoint_always_uses_process_supervisor() -> None:
    batch = (SCRIPTS / "stress-real-services.bat").read_text(encoding="utf-8")
    assert "stress_process_supervisor.py" in batch
    assert '"%UV_EXE%" run python' in batch


def test_supervisor_option_is_not_forwarded_to_worker() -> None:
    deadline, worker_args = supervisor._parse_supervisor_args(
        [
            "--confirm-real-services",
            "--supervisor-timeout-seconds",
            "123",
            "--duration-seconds",
            "5",
        ]
    )
    assert deadline == 123.0
    assert "--supervisor-timeout-seconds" not in worker_args
    parsed = stress.parse_args(worker_args)
    assert parsed.confirm_real_services is True
    assert parsed.duration_seconds == 5.0


def test_automatic_supervisor_deadline_covers_all_declared_phases() -> None:
    args = stress.parse_args(
        [
            "--duration-seconds",
            "900",
            "--import-timeout-seconds",
            "1800",
            "--operation-timeout-seconds",
            "30",
            "--cleanup-timeout-seconds",
            "10",
            "--document-count",
            "2",
        ]
    )
    deadline = supervisor._automatic_deadline(args)
    assert deadline > args.duration_seconds + args.import_timeout_seconds
    assert deadline >= args.duration_seconds + args.import_timeout_seconds + 300


def test_supervisor_recovery_is_noop_when_worker_created_no_data(tmp_path: Path) -> None:
    result = asyncio.run(
        supervisor._recover_owned_resources(
            mysql_url=(
                "mysql+aiomysql://stress_user:secret@127.0.0.1:3306/application"
            ),
            run_id="20260726t120010_abcdef1234",
            allow_remote_mysql=False,
            temp_root=tmp_path,
            cleanup_timeout_seconds=1.0,
        )
    )
    assert result["database_cleanup_verified"] is False
    assert result["data_removed"] is True
    assert result["errors"] == []


def test_owned_data_removal_runs_in_bounded_helper_process(tmp_path: Path) -> None:
    environment = make_environment(
        "mysql+aiomysql://stress_user:secret@127.0.0.1:3306/application",
        run_id="20260726t120011_abcdef1234",
        temp_root=tmp_path,
    )
    supervisor._remove_data_dir_bounded(
        environment,
        temp_root=tmp_path,
        timeout_seconds=5.0,
    )
    assert not environment.data_dir.exists()


def test_worker_termination_falls_back_when_taskkill_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProcess:
        pid = 12345

        def __init__(self) -> None:
            self.killed = False

        def poll(self) -> int | None:
            return -9 if self.killed else None

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout: float | None = None) -> int:
            assert timeout is not None
            if not self.killed:
                raise subprocess.TimeoutExpired("worker", timeout)
            return -9

    monkeypatch.setattr(supervisor.os, "name", "nt")
    monkeypatch.setattr(
        supervisor.subprocess,
        "run",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("taskkill", 10)
        ),
    )
    process = FakeProcess()
    supervisor._terminate_worker(process)  # type: ignore[arg-type]
    assert process.killed is True
    assert process.poll() is not None


def test_keyboard_interrupt_still_recovers_and_writes_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class InterruptedProcess:
        pid = 12346

        def __init__(self) -> None:
            self.wait_calls = 0
            self.killed = False

        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise KeyboardInterrupt
            self.killed = True
            return -9

        def poll(self) -> int | None:
            return -9 if self.killed else None

        def kill(self) -> None:
            self.killed = True

    process = InterruptedProcess()
    monkeypatch.setattr(
        supervisor.subprocess, "Popen", lambda *_a, **_kw: process
    )
    monkeypatch.setattr(supervisor, "_terminate_worker", lambda item: item.kill())
    monkeypatch.setattr(
        stress,
        "_resolve_configuration",
        lambda _args: (
            "mysql+aiomysql://stress_user:secret@127.0.0.1:3306/application",
            "http://127.0.0.1:11434",
            "qwen2",
            "bge-m3",
        ),
    )
    recovery_calls: list[dict[str, Any]] = []

    async def recover(**kwargs: Any) -> dict[str, object]:
        recovery_calls.append(kwargs)
        return {
            "database_created": True,
            "database_dropped": True,
            "database_cleanup_verified": True,
            "data_removed": True,
            "errors": [],
        }

    written: list[dict[str, Any]] = []
    monkeypatch.setattr(supervisor, "_recover_owned_resources", recover)
    monkeypatch.setattr(
        supervisor,
        "_write_supervisor_failure_report",
        lambda **kwargs: (
            written.append(kwargs) or (tmp_path / "a.json", tmp_path / "a.md")
        ),
    )

    code = supervisor.main(
        [
            "--confirm-real-services",
            "--use-configured-mysql-credentials",
            "--out",
            str(tmp_path),
        ]
    )

    assert code == 130
    assert process.killed is True
    assert len(recovery_calls) == 1
    assert written[0]["blocker"]["check"] == "interrupted"
