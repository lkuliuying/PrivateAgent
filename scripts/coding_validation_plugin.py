"""隔离测试专用插件：拒绝业务配置导入，保留证据并使用继承 ACL 的目录。"""
from __future__ import annotations

import importlib.abc
import json
import os
import platform
import sys
import uuid
from pathlib import Path

import pytest

BLOCKED = ("personal_assistant.config", "personal_assistant.core.db", "personal_assistant.main_api")


class NoBusinessConfiguration(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in BLOCKED):
            raise ImportError(f"隔离测试禁止加载业务配置或数据库：{fullname}")
        return None


def pytest_configure(config):
    root = Path(os.environ["CODING_VALIDATION_DIR"]).resolve(strict=True)
    if root != Path.cwd().resolve() or (root / ".env").exists():
        raise pytest.UsageError("测试必须从不含 .env 的专用隔离目录启动")
    if any(name in sys.modules for name in BLOCKED):
        raise pytest.UsageError("业务模块在隔离守卫安装前已被导入")
    sys.meta_path.insert(0, NoBusinessConfiguration())


@pytest.fixture
def tmp_path():
    root = Path(os.environ["CODING_VALIDATION_DIR"]).resolve(strict=True)
    path = root / "tmp" / uuid.uuid4().hex
    path.mkdir(mode=0o777)
    if not path.resolve().is_relative_to(root):
        raise pytest.UsageError("测试临时目录越界")
    return path


def pytest_sessionfinish(session, exitstatus):
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    counts = {key: len(value) for key, value in reporter.stats.items() if key}
    evidence = {
        "python": platform.python_version(), "platform": platform.platform(),
        "exit_code": int(exitstatus), "counts": counts,
        "business_modules_loaded": [name for name in BLOCKED if name in sys.modules],
        "tests": {key: [item.nodeid for item in value if hasattr(item, "nodeid")]
                  for key, value in reporter.stats.items() if key in {"failed", "error", "xfailed", "xpassed", "skipped"}},
    }
    root = Path(os.environ["CODING_VALIDATION_DIR"])
    (root / "pytest-result.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
