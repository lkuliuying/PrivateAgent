from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import stress_real_services as stress  # noqa: E402
from _stress_environment import (  # noqa: E402
    StressSafetyError,
    generated_database_name,
    is_cleanup_authorized,
    make_environment,
    redact_url,
    remove_data_dir,
    validate_database_name,
)


MYSQL_URL = "mysql+aiomysql://stress_user:secret@127.0.0.1:3306/application"


def test_stress_environment_is_unique_owned_and_redacted(tmp_path: Path) -> None:
    environment = make_environment(
        MYSQL_URL, run_id="20260726t120000_abcdef1234", temp_root=tmp_path
    )
    try:
        assert environment.database_name.startswith("pa_stress_")
        assert environment.database_name == generated_database_name(environment.run_id)
        assert len(environment.ownership_nonce) == 64
        assert is_cleanup_authorized(environment)
        assert "secret" not in redact_url(environment.database_url)
        assert "stress_user" not in redact_url(environment.database_url)
        assert redact_url(environment.database_url).endswith("/<isolated>")
    finally:
        remove_data_dir(environment, temp_root=tmp_path)


def test_cleanup_rejects_tampered_ownership_marker(tmp_path: Path) -> None:
    environment = make_environment(
        MYSQL_URL, run_id="20260726t120001_abcdef1234", temp_root=tmp_path
    )
    marker = environment.data_dir / ".pa-stress-run.json"
    original = marker.read_text(encoding="utf-8")
    marker.write_text(json.dumps({"run_id": "somebody_else"}), encoding="utf-8")
    assert not is_cleanup_authorized(environment)
    with pytest.raises(StressSafetyError):
        remove_data_dir(environment, temp_root=tmp_path)
    marker.write_text(original, encoding="utf-8")
    remove_data_dir(environment, temp_root=tmp_path)


def test_cleanup_rejects_tampered_ownership_nonce(tmp_path: Path) -> None:
    environment = make_environment(
        MYSQL_URL, run_id="20260726t120003_abcdef1234", temp_root=tmp_path
    )
    marker = environment.data_dir / ".pa-stress-run.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["ownership_nonce"] = "0" * 64
    marker.write_text(json.dumps(payload), encoding="utf-8")
    assert not is_cleanup_authorized(environment)


def test_cleanup_binds_admin_url_to_the_owned_database_server(tmp_path: Path) -> None:
    environment = make_environment(
        MYSQL_URL, run_id="20260726t120004_abcdef1234", temp_root=tmp_path
    )
    try:
        assert not is_cleanup_authorized(
            replace(
                environment,
                admin_url="mysql+aiomysql://stress_user:secret@127.0.0.1:3307/mysql",
            )
        )
        assert not is_cleanup_authorized(
            replace(environment, admin_url=environment.admin_url.replace("/mysql", "/other"))
        )
    finally:
        remove_data_dir(environment, temp_root=tmp_path)


@pytest.mark.parametrize(
    "name",
    ["personal_assistant", "pa_test_x", "pa_stress_UPPER", "pa_stress_"],
)
def test_database_name_validation_is_fail_closed(name: str) -> None:
    with pytest.raises(StressSafetyError):
        validate_database_name(name)


def test_remote_mysql_requires_explicit_opt_in(tmp_path: Path) -> None:
    with pytest.raises(StressSafetyError, match="remote MySQL"):
        make_environment(
            "mysql+aiomysql://user:secret@db.example.test:3306/app",
            run_id="20260726t120002_abcdef1234",
            temp_root=tmp_path,
        )


def test_percentiles_and_metric_summary() -> None:
    series = stress.MetricSeries()
    for latency in (10.0, 20.0, 30.0, 40.0, 50.0):
        series.record(latency)
    series.record(100.0, RuntimeError("not persisted"))
    summary = series.summary(2.0)
    assert summary["requests"] == 6
    assert summary["failed"] == 1
    assert summary["throughput_per_second"] == 2.5
    assert summary["p50_ms"] == 35.0
    assert summary["p95_ms"] == 87.5
    assert summary["error_types"] == {"RuntimeError": 1}


def test_large_markdown_generation_is_bounded(tmp_path: Path) -> None:
    target = tmp_path / "large.md"
    written = stress.generate_large_markdown(target, 64 * 1024, "safe-marker")
    assert written == 64 * 1024
    assert target.stat().st_size == written
    content = target.read_text(encoding="utf-8")
    assert "safe-marker" in content
    assert "pa stress retrieval" in content


def test_process_rss_is_reported_on_windows() -> None:
    rss = stress.process_rss_bytes()
    if sys.platform == "win32":
        assert rss is not None
        assert rss > 0


def test_threshold_override_rejects_unknown_operations(tmp_path: Path) -> None:
    path = tmp_path / "thresholds.json"
    path.write_text('{"unknown": 1}', encoding="utf-8")
    with pytest.raises(StressSafetyError, match="unknown threshold"):
        stress.load_thresholds(path)


def test_evaluate_thresholds_detects_latency_errors_memory_and_drift() -> None:
    operations = {
        name: {
            "requests": 10,
            "error_rate": 0.0,
            "p95_ms": 1.0,
        }
        for name in stress.DEFAULT_THRESHOLDS_MS
    }
    operations["ollama_chat"]["error_rate"] = 0.2
    operations["mysql_query"]["p95_ms"] = 1_000.0
    blockers = stress.evaluate_thresholds(
        operations,
        thresholds_ms=stress.DEFAULT_THRESHOLDS_MS,
        max_error_rate=0.01,
        max_rss_mb=128.0,
        max_steady_rss_growth_mb=32.0,
        resource_summary={
            "max_rss_bytes": 256 * 1024 * 1024,
            "steady_rss_growth_bytes": 64 * 1024 * 1024,
        },
        integrity={"mysql_chunks": 10, "chroma_vectors": 9},
    )
    checks = {item["check"] for item in blockers}
    assert {
        "ollama_chat",
        "mysql_query",
        "process_rss",
        "steady_rss_growth",
        "index_integrity",
    } <= checks


def test_evaluate_thresholds_blocks_missing_rss_sample() -> None:
    operations = {
        name: {"requests": 1, "error_rate": 0.0, "p95_ms": 1.0}
        for name in stress.DEFAULT_THRESHOLDS_MS
    }
    blockers = stress.evaluate_thresholds(
        operations,
        thresholds_ms=stress.DEFAULT_THRESHOLDS_MS,
        max_error_rate=0.01,
        max_rss_mb=128.0,
        max_steady_rss_growth_mb=32.0,
        resource_summary={
            "max_rss_bytes": None,
            "steady_rss_growth_bytes": None,
        },
        integrity={"mysql_chunks": 1, "chroma_vectors": 1},
    )
    assert any(item["check"] == "process_rss" for item in blockers)


def test_resource_summary_separates_import_growth_from_steady_state() -> None:
    mib = 1024 * 1024
    summary = stress._resource_summary(
        [
            {"phase": "document_import", "elapsed_seconds": 0, "rss_bytes": 100 * mib},
            {"phase": "document_import", "elapsed_seconds": 60, "rss_bytes": 300 * mib},
            {"phase": "steady", "elapsed_seconds": 61, "rss_bytes": 301 * mib},
            {"phase": "steady", "elapsed_seconds": 121, "rss_bytes": 303 * mib},
        ]
    )
    assert summary["rss_growth_mb"] == 203.0
    assert summary["steady_rss_samples"] == 2
    assert summary["steady_rss_growth_mb"] == 2.0
    assert summary["steady_rss_growth_mb_per_hour"] == 120.0


def test_diagnostic_redaction_removes_url_and_token_secrets() -> None:
    value = (
        "mysql+aiomysql://user:password@127.0.0.1/db "
        "token=top-secret failure"
    )
    redacted = stress.redact_diagnostic(value)
    assert redacted is not None
    assert "password" not in redacted
    assert "top-secret" not in redacted
    assert "<redacted>" in redacted


def test_invalid_ollama_port_is_rejected_during_validation() -> None:
    with pytest.raises(StressSafetyError, match="invalid port"):
        stress.validate_http_endpoint(
            "http://127.0.0.1:99999", allow_remote=False
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://user:password@127.0.0.1:11434",
        "http://127.0.0.1:11434?token=secret",
        "http://127.0.0.1:11434#credential",
    ],
)
def test_ollama_endpoint_rejects_command_line_secret_surfaces(url: str) -> None:
    with pytest.raises(StressSafetyError):
        stress.validate_http_endpoint(url, allow_remote=False)


@pytest.mark.asyncio
async def test_await_bounded_reports_dependency_timeout() -> None:
    with pytest.raises(TimeoutError, match="test dependency timed out"):
        await stress.await_bounded(
            asyncio.sleep(60), timeout_seconds=0.01, label="test dependency"
        )


@pytest.mark.asyncio
async def test_execute_requires_explicit_real_service_confirmation() -> None:
    args = stress.parse_args([])
    with pytest.raises(StressSafetyError, match="opt-in"):
        await stress.execute(args)


@pytest.mark.asyncio
async def test_execute_never_drops_database_when_provisioning_did_not_complete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args = stress.parse_args(
        [
            "--confirm-real-services",
            "--use-configured-mysql-credentials",
            "--out",
            str(tmp_path / "reports"),
            "--temp-root",
            str(tmp_path),
        ]
    )
    monkeypatch.setattr(
        stress,
        "_resolve_configuration",
        lambda _args: (MYSQL_URL, "http://127.0.0.1:11434", "qwen2", "bge-m3"),
    )

    async def refuse_provision(_environment, **_kwargs):
        raise stress.StressProvisionError("schema already exists")

    drop_called = False

    async def forbidden_drop(_environment, **_kwargs):
        nonlocal drop_called
        drop_called = True
        raise AssertionError("pre-existing schema must not be dropped")

    monkeypatch.setattr(stress, "provision_database", refuse_provision)
    monkeypatch.setattr(stress, "drop_database", forbidden_drop)

    report, _, _ = await stress.execute(args)

    assert report["status"] == "failed"
    assert report["cleanup"]["database_created"] is False
    assert report["cleanup"]["data_removed"] is True
    assert drop_called is False
