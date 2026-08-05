from __future__ import annotations

import pytest

from personal_assistant import server_entry


def test_project_base_finds_resources_outside_installed_package(
    monkeypatch, tmp_path
):
    (tmp_path / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    (tmp_path / "alembic").mkdir()
    installed_module = (
        tmp_path
        / ".venv"
        / "lib"
        / "python3.13"
        / "site-packages"
        / "personal_assistant"
        / "server_entry.py"
    )

    monkeypatch.setattr(server_entry, "__file__", str(installed_module))
    monkeypatch.setattr(server_entry.sys, "executable", str(tmp_path / ".venv" / "bin" / "python"))
    monkeypatch.setattr(server_entry.sys, "frozen", False, raising=False)
    monkeypatch.chdir(tmp_path)

    assert server_entry._project_base() == tmp_path


def test_run_migrations_rejects_missing_resources(monkeypatch, tmp_path):
    monkeypatch.setattr(server_entry, "_project_base", lambda: tmp_path)

    with pytest.raises(FileNotFoundError, match="Alembic resources"):
        server_entry._run_migrations()


def test_packaged_server_refuses_to_start_after_migration_failure(
    monkeypatch, capsys
):
    monkeypatch.delenv("PA_SKIP_MIGRATIONS", raising=False)
    monkeypatch.setattr(server_entry, "_ensure_data_dirs", lambda: None)
    monkeypatch.setattr(server_entry, "_start_parent_watchdog", lambda: None)

    def fail_migration() -> None:
        raise RuntimeError("secret-dsn-should-not-be-logged")

    monkeypatch.setattr(server_entry, "_run_migrations", fail_migration)

    with pytest.raises(SystemExit) as exc_info:
        server_entry.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "refusing to start" in captured.err
    assert "RuntimeError" in captured.err
    assert "secret-dsn-should-not-be-logged" not in captured.err
