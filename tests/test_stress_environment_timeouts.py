from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _stress_environment as stress_env  # noqa: E402
from _stress_environment import (  # noqa: E402
    DatabaseTimeouts,
    StressEnvironment,
    StressProvisionError,
    StressSafetyError,
    load_environment_for_cleanup,
    make_environment,
    remove_data_dir,
)


MYSQL_URL = (
    "mysql+aiomysql://stress_user:supersecret@127.0.0.1:3306/application"
)
TINY_TIMEOUTS = DatabaseTimeouts(
    connect_seconds=0.01,
    operation_seconds=0.01,
    cleanup_seconds=0.01,
)


class FakeResult:
    def __init__(self, row: Any = None) -> None:
        self._row = row

    def one_or_none(self) -> Any:
        return self._row


class FakeConnection:
    def __init__(
        self,
        *,
        scalar_value: Any = None,
        scalar_delay: float = 0.0,
        execute_delay: float = 0.0,
        ownership_nonce: str | None = None,
        driver_delays: dict[str, float] | None = None,
        close_delay: float = 0.0,
    ) -> None:
        self.scalar_value = scalar_value
        self.scalar_delay = scalar_delay
        self.execute_delay = execute_delay
        self.ownership_nonce = ownership_nonce
        self.driver_delays = driver_delays or {}
        self.close_delay = close_delay
        self.closed = False
        self.driver_statements: list[str] = []

    async def scalar(self, *_args: Any, **_kwargs: Any) -> Any:
        if self.scalar_delay:
            await asyncio.sleep(self.scalar_delay)
        return self.scalar_value

    async def execute(self, *_args: Any, **_kwargs: Any) -> FakeResult:
        if self.execute_delay:
            await asyncio.sleep(self.execute_delay)
        row = (
            SimpleNamespace(ownership_nonce=self.ownership_nonce)
            if self.ownership_nonce is not None
            else None
        )
        return FakeResult(row)

    async def exec_driver_sql(self, statement: str) -> None:
        self.driver_statements.append(statement)
        for marker, delay in self.driver_delays.items():
            if marker in statement:
                await asyncio.sleep(delay)
                break

    async def close(self) -> None:
        if self.close_delay:
            await asyncio.sleep(self.close_delay)
        self.closed = True


class FakeEngine:
    def __init__(
        self,
        connection: FakeConnection | None = None,
        *,
        connect_delay: float = 0.0,
        dispose_delay: float = 0.0,
    ) -> None:
        self.connection = connection or FakeConnection()
        self.connect_delay = connect_delay
        self.dispose_delay = dispose_delay
        self.disposed = False

    async def connect(self) -> FakeConnection:
        if self.connect_delay:
            await asyncio.sleep(self.connect_delay)
        return self.connection

    async def dispose(self) -> None:
        if self.dispose_delay:
            await asyncio.sleep(self.dispose_delay)
        self.disposed = True


@pytest.fixture
def environment(tmp_path: Path) -> Iterator[StressEnvironment]:
    value = make_environment(
        MYSQL_URL,
        run_id="20260726t160000_timeout1234",
        temp_root=tmp_path,
    )
    try:
        yield value
    finally:
        marker = value.data_dir / ".pa-stress-run.json"
        if value.data_dir.exists():
            marker.write_text(
                json.dumps(
                    {
                        "run_id": value.run_id,
                        "database_name": value.database_name,
                        "ownership_nonce": value.ownership_nonce,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            remove_data_dir(value, temp_root=tmp_path)


@pytest.mark.asyncio
async def test_exists_connection_timeout_is_secret_free_and_disposes(
    monkeypatch: pytest.MonkeyPatch, environment: StressEnvironment
) -> None:
    engine = FakeEngine(connect_delay=1.0)
    captured: dict[str, Any] = {}

    def factory(_url: str, **kwargs: Any) -> FakeEngine:
        captured.update(kwargs)
        return engine

    monkeypatch.setattr(stress_env, "create_async_engine", factory)

    with pytest.raises(StressSafetyError) as exc_info:
        await stress_env._database_exists(environment, timeouts=TINY_TIMEOUTS)

    assert "supersecret" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert captured["connect_args"] == {"connect_timeout": 0.01}
    assert engine.disposed is True


@pytest.mark.asyncio
async def test_exists_operation_timeout_closes_connection_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch, environment: StressEnvironment
) -> None:
    connection = FakeConnection(scalar_delay=1.0)
    engine = FakeEngine(connection)
    monkeypatch.setattr(stress_env, "create_async_engine", lambda *_a, **_kw: engine)

    with pytest.raises(StressSafetyError, match="configured deadlines"):
        await stress_env._database_exists(environment, timeouts=TINY_TIMEOUTS)

    assert connection.closed is True
    assert engine.disposed is True


@pytest.mark.asyncio
async def test_engine_dispose_timeout_is_bounded_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch, environment: StressEnvironment
) -> None:
    connection = FakeConnection(scalar_value=None)
    engine = FakeEngine(connection, dispose_delay=1.0)
    monkeypatch.setattr(stress_env, "create_async_engine", lambda *_a, **_kw: engine)
    started = asyncio.get_running_loop().time()

    with pytest.raises(StressSafetyError, match="configured deadlines"):
        await stress_env._database_exists(environment, timeouts=TINY_TIMEOUTS)

    assert asyncio.get_running_loop().time() - started < 0.5
    assert connection.closed is True


@pytest.mark.asyncio
async def test_provision_timeout_after_create_attempt_requests_cleanup(
    monkeypatch: pytest.MonkeyPatch, environment: StressEnvironment
) -> None:
    async def database_absent(
        _environment: StressEnvironment, *, timeouts: DatabaseTimeouts
    ) -> bool:
        return False

    connection = FakeConnection(driver_delays={"CREATE TABLE": 1.0})
    engine = FakeEngine(connection)
    monkeypatch.setattr(stress_env, "_database_exists", database_absent)
    monkeypatch.setattr(stress_env, "create_async_engine", lambda *_a, **_kw: engine)

    with pytest.raises(StressProvisionError) as exc_info:
        await stress_env.provision_database(environment, timeouts=TINY_TIMEOUTS)

    assert exc_info.value.database_created is True
    assert "supersecret" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert any("CREATE DATABASE" in item for item in connection.driver_statements)
    assert connection.closed is True
    assert engine.disposed is True


@pytest.mark.asyncio
async def test_provision_cancellation_after_create_attempt_preserves_cleanup_state(
    monkeypatch: pytest.MonkeyPatch, environment: StressEnvironment
) -> None:
    async def database_absent(
        _environment: StressEnvironment, *, timeouts: DatabaseTimeouts
    ) -> bool:
        return False

    connection = FakeConnection(driver_delays={"CREATE TABLE": 60.0})
    engine = FakeEngine(connection)
    monkeypatch.setattr(stress_env, "_database_exists", database_absent)
    monkeypatch.setattr(stress_env, "create_async_engine", lambda *_a, **_kw: engine)

    task = asyncio.create_task(
        stress_env.provision_database(
            environment,
            timeouts=DatabaseTimeouts(
                connect_seconds=1.0,
                operation_seconds=120.0,
                cleanup_seconds=1.0,
            ),
        )
    )
    while not any("CREATE TABLE" in item for item in connection.driver_statements):
        await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(StressProvisionError) as exc_info:
        await task

    assert exc_info.value.database_created is True
    assert connection.closed is True
    assert engine.disposed is True


@pytest.mark.asyncio
async def test_ownership_timeout_never_reaches_drop(
    monkeypatch: pytest.MonkeyPatch, environment: StressEnvironment
) -> None:
    async def database_present(
        _environment: StressEnvironment, *, timeouts: DatabaseTimeouts
    ) -> bool:
        return True

    ownership_connection = FakeConnection(execute_delay=1.0)
    ownership_engine = FakeEngine(ownership_connection)
    created_engines: list[FakeEngine] = []

    def factory(*_args: Any, **_kwargs: Any) -> FakeEngine:
        created_engines.append(ownership_engine)
        return ownership_engine

    monkeypatch.setattr(stress_env, "_database_exists", database_present)
    monkeypatch.setattr(stress_env, "create_async_engine", factory)

    with pytest.raises(StressSafetyError, match="ownership proof") as exc_info:
        await stress_env.drop_database(environment, timeouts=TINY_TIMEOUTS)

    assert "supersecret" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert created_engines == [ownership_engine]
    assert ownership_connection.driver_statements == []
    assert ownership_connection.closed is True
    assert ownership_engine.disposed is True


@pytest.mark.asyncio
async def test_drop_operation_timeout_is_bounded_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch, environment: StressEnvironment
) -> None:
    async def database_present(
        _environment: StressEnvironment, *, timeouts: DatabaseTimeouts
    ) -> bool:
        return True

    ownership_connection = FakeConnection(
        ownership_nonce=environment.ownership_nonce
    )
    drop_connection = FakeConnection(driver_delays={"DROP DATABASE": 1.0})
    engines = [FakeEngine(ownership_connection), FakeEngine(drop_connection)]
    monkeypatch.setattr(stress_env, "_database_exists", database_present)
    monkeypatch.setattr(
        stress_env, "create_async_engine", lambda *_a, **_kw: engines.pop(0)
    )

    with pytest.raises(StressSafetyError, match="configured deadlines"):
        await stress_env.drop_database(environment, timeouts=TINY_TIMEOUTS)

    assert any("DROP DATABASE" in item for item in drop_connection.driver_statements)
    assert ownership_connection.closed is True
    assert drop_connection.closed is True


def test_load_environment_for_cleanup_restores_exact_owned_target(
    environment: StressEnvironment, tmp_path: Path
) -> None:
    restored = load_environment_for_cleanup(
        MYSQL_URL,
        run_id=environment.run_id,
        temp_root=tmp_path,
    )

    assert restored == environment
    assert stress_env.is_cleanup_authorized(restored)


def test_remove_data_dir_rejects_link_to_marker_bearing_sibling(
    tmp_path: Path,
) -> None:
    environment = make_environment(
        MYSQL_URL,
        run_id="20260726t160010_timeout1234",
        temp_root=tmp_path,
    )
    sibling = tmp_path / "unrelated-sibling"
    environment.data_dir.rename(sibling)
    try:
        try:
            environment.data_dir.symlink_to(sibling, target_is_directory=True)
        except OSError:
            if sys.platform != "win32":
                pytest.skip("directory symlink creation is unavailable on this host")
            completed = subprocess.run(
                [
                    "cmd.exe",
                    "/d",
                    "/c",
                    "mklink",
                    "/J",
                    str(environment.data_dir),
                    str(sibling),
                ],
                check=False,
                capture_output=True,
            )
            assert completed.returncode == 0
        with pytest.raises(StressSafetyError, match="linked or unexpected"):
            remove_data_dir(environment, temp_root=tmp_path)
        assert sibling.is_dir()
        assert (sibling / ".pa-stress-run.json").is_file()
    finally:
        if environment.data_dir.is_symlink():
            environment.data_dir.unlink()
        elif getattr(environment.data_dir, "is_junction", lambda: False)():
            os.rmdir(environment.data_dir)
        if sibling.exists():
            sibling.rename(environment.data_dir)
        if environment.data_dir.exists():
            remove_data_dir(environment, temp_root=tmp_path)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(ownership_nonce="not-a-valid-nonce"),
        lambda payload: payload.update(database_name="pa_stress_somebody_else"),
        lambda payload: payload.update(run_id="20260726t160001_somebodyelse"),
        lambda payload: payload.update(unexpected="field"),
    ],
)
def test_load_environment_for_cleanup_rejects_tampered_marker(
    environment: StressEnvironment,
    tmp_path: Path,
    mutation: Any,
) -> None:
    marker = environment.data_dir / ".pa-stress-run.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    mutation(payload)
    marker.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(StressSafetyError):
        load_environment_for_cleanup(
            MYSQL_URL,
            run_id=environment.run_id,
            temp_root=tmp_path,
        )


@pytest.mark.asyncio
async def test_restored_tampered_nonce_cannot_authorize_database_drop(
    monkeypatch: pytest.MonkeyPatch,
    environment: StressEnvironment,
    tmp_path: Path,
) -> None:
    original_nonce = environment.ownership_nonce
    marker = environment.data_dir / ".pa-stress-run.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["ownership_nonce"] = "0" * 64
    marker.write_text(json.dumps(payload), encoding="utf-8")
    restored = load_environment_for_cleanup(
        MYSQL_URL,
        run_id=environment.run_id,
        temp_root=tmp_path,
    )

    async def database_present(
        _environment: StressEnvironment, *, timeouts: DatabaseTimeouts
    ) -> bool:
        return True

    ownership_connection = FakeConnection(ownership_nonce=original_nonce)
    ownership_engine = FakeEngine(ownership_connection)
    monkeypatch.setattr(stress_env, "_database_exists", database_present)
    monkeypatch.setattr(
        stress_env, "create_async_engine", lambda *_a, **_kw: ownership_engine
    )

    with pytest.raises(StressSafetyError, match="nonce does not match"):
        await stress_env.drop_database(restored, timeouts=TINY_TIMEOUTS)

    assert ownership_connection.driver_statements == []
