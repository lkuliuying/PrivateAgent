"""Run deployment regressions without loading environment files or connecting to a DB."""
from __future__ import annotations

import ast
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from alembic.config import Config


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))

    # Execute the actual URL assignment only, never Alembic's online migration path.
    tree = ast.parse((root / "alembic/env.py").read_text(encoding="utf-8"))
    statements = [
        node for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "config"
        and node.value.func.attr == "set_main_option"
    ]
    assert len(statements) == 1, "Could not identify Alembic URL configuration"
    assignment = compile(ast.Module(body=statements, type_ignores=[]), "alembic/env.py", "exec")
    # Synthetic values; no real credentials. Verify both percent and ordinary URLs.
    for url in ("mysql+aiomysql://test:fake%25%40%2F@localhost/test", "sqlite:///example.db"):
        config = Config()
        exec(assignment, {"config": config, "settings": SimpleNamespace(db_url=url)})
        assert config.get_main_option("sqlalchemy.url") == url
    print("Alembic URL round-trip: 2 cases passed (no database accessed).")

    config_module = types.ModuleType("personal_assistant.config")
    config_module.settings = SimpleNamespace()
    sys.modules[config_module.__name__] = config_module
    db = types.ModuleType("personal_assistant.core.db")
    db.engine = Mock()

    async def no_database_session():
        raise AssertionError("No real database access is permitted in this check")
        yield

    db.get_session = no_database_session
    db.async_session_factory = Mock(side_effect=AssertionError("Unexpected database access"))
    sys.modules[db.__name__] = db
    return pytest.main([
        "--noconftest", "-q", "-p", "no:cacheprovider",
        str(root / "tests/test_health_visibility.py"),
    ])


if __name__ == "__main__":
    raise SystemExit(main())
