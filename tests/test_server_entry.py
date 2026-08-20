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


def test_run_migrations_skips_unknown_future_revision(monkeypatch, capsys):
    """第 7 节：DB revision 不在本应用迁移链内（新版升级后回退安装）时跳过迁移。

    不得执行破坏性 downgrade，也不得拒绝启动；旧版回退应用必须可用。
    """
    from pathlib import Path

    calls: list[str] = []

    def fake_upgrade(cfg, revision):  # noqa: ANN001
        calls.append(str(revision))

    monkeypatch.setattr("alembic.command.upgrade", fake_upgrade)
    monkeypatch.setattr(server_entry, "_read_db_revision", lambda: "9999")
    monkeypatch.setattr(
        server_entry,
        "_project_base",
        lambda: Path(__file__).resolve().parents[1],
    )

    server_entry._run_migrations()

    captured = capsys.readouterr()
    assert calls == []
    assert "skipping migrations" in captured.err
    assert "9999" in captured.err


def test_run_migrations_upgrades_when_revision_known(monkeypatch):
    """DB revision 在本应用迁移链内时仍执行正常 upgrade head。"""
    from pathlib import Path

    calls: list[str] = []

    def fake_upgrade(cfg, revision):  # noqa: ANN001
        calls.append(str(revision))

    monkeypatch.setattr("alembic.command.upgrade", fake_upgrade)
    monkeypatch.setattr(server_entry, "_read_db_revision", lambda: "0029")
    monkeypatch.setattr(
        server_entry,
        "_project_base",
        lambda: Path(__file__).resolve().parents[1],
    )

    server_entry._run_migrations()

    assert calls == ["head"]


def test_read_db_revision_returns_none_on_failure(monkeypatch):
    """读 revision 失败（连接/表异常）时返回 None，交由 upgrade 路径处理。"""
    import sqlalchemy.engine
    import sqlalchemy.ext.asyncio

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise RuntimeError("connection refused")

    monkeypatch.setattr(sqlalchemy.engine, "make_url", boom)
    monkeypatch.setattr(
        sqlalchemy.ext.asyncio, "create_async_engine", boom, raising=False
    )

    assert server_entry._read_db_revision() is None


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
