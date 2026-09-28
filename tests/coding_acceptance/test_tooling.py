"""测试入口的隔离守卫，以及固定任务判定器的正反对照。"""
import importlib
import subprocess
import sys
from collections import Counter

import pytest
from coding_task_baseline import judge, load_catalog, materialize
from coding_validation_process import managed_process
from run_coding_validation import isolated_environment

from private_agent_local.entry import parent_alive


def test_isolated_environment_drops_credentials_and_pytest_injection(tmp_path, monkeypatch):
    for key in ("PA_DB_URL", "PA_TEST_DB_URL", "OPENAI_API_KEY", "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONSTARTUP", "NODE_OPTIONS"):
        monkeypatch.setenv(key, "fixture-do-not-forward")
    environment = isolated_environment(tmp_path)
    assert not any(value == "fixture-do-not-forward" for value in environment.values())
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert environment["TMP"] == str(tmp_path / "tmp")


def test_configuration_import_is_blocked_and_directory_supports_io(tmp_path):
    for module in ("personal_assistant.config", "personal_assistant.core.db", "personal_assistant.main_api"):
        with pytest.raises(ImportError, match="隔离测试禁止"):
            importlib.import_module(module)
    target = tmp_path / "write.txt"
    target.write_text("中文", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "中文"
    target.unlink()
    assert not target.exists()


def test_catalog_split_and_budget_are_fixed():
    catalog = load_catalog()
    assert Counter(task["repository"] for task in catalog["tasks"]) == {"python": 10, "node": 10, "mixed": 10}
    assert Counter(task["split"] for task in catalog["tasks"]) == {"development": 24, "holdout": 6}
    assert catalog["budget"]["real_model_status"] == "not_run"


def test_judge_rejects_changes_made_during_candidate_execution(tmp_path):
    task = load_catalog()["tasks"][0]
    directory = tmp_path / "candidate"
    materialize(task, directory)
    target = directory / task["editable_files"][0]
    target.write_text("from pathlib import Path\nPath('user-notes.txt').write_text('changed')\n" + task["reference"], encoding="utf-8")
    assert judge(task, directory)["reason"] == "user_work_changed"


def test_validation_watchdog_reaps_child_tree(tmp_path):
    code = ("import subprocess,sys,time; from pathlib import Path; "
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            "Path('child.pid').write_text(str(p.pid)); time.sleep(30)")
    with pytest.raises(subprocess.TimeoutExpired):
        with managed_process([sys.executable, "-B", "-c", code], cwd=tmp_path,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as process:
            process.wait(timeout=1)
    assert not parent_alive(int((tmp_path / "child.pid").read_text()))


@pytest.mark.parametrize("task", load_catalog()["tasks"], ids=lambda task: task["id"])
def test_task_seed_fails_and_reference_passes(tmp_path, task):
    directory = tmp_path / task["id"]
    materialize(task, directory)
    initial = judge(task, directory)
    assert initial["reason"] == "assertion_failed", initial
    assert initial["passed"] is False
    with pytest.raises(ValueError, match="全新"):
        materialize(task, directory)
    (directory / task["editable_files"][0]).write_text(task["reference"], encoding="utf-8", newline="\n")
    accepted = judge(task, directory)
    assert accepted["passed"] is True, accepted
    (directory / "user-notes.txt").write_text("覆盖用户修改", encoding="utf-8")
    assert judge(task, directory)["reason"] == "user_work_changed"
