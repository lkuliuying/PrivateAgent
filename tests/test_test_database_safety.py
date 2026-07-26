"""Pure safety tests for isolated MySQL URL selection and DROP authorization."""
from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import stat
import sys

import pytest
from sqlalchemy.engine import make_url

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import _test_database as test_db  # noqa: E402

BASE_URL = "mysql+aiomysql://developer:secret@127.0.0.1:3306/personal_assistant"


def test_generated_plan_never_reuses_development_database():
    plan = test_db.build_database_plan(
        BASE_URL,
        run_token="Run-ABC-123",
        worker_id="gw0",
    )

    assert plan.created_by_run is True
    assert plan.database_name.startswith("pa_test_")
    assert make_url(plan.database_url).database == plan.database_name
    assert make_url(plan.database_url).database != "personal_assistant"
    assert test_db.is_drop_authorized(plan) is True


@pytest.mark.parametrize(
    "name",
    [
        "personal_assistant",
        "pa-test-invalid",
        "PA_TEST_UPPERCASE",
        "pa_test_",
        "pa_test_valid_but_trailing-hyphen",
        "pa_test_" + "a" * 57,
    ],
)
def test_database_name_guard_rejects_unsafe_names(name):
    with pytest.raises(test_db.DatabaseSafetyError):
        test_db.validate_test_database_name(name)


def test_explicit_test_database_is_validated_and_never_drop_owned():
    explicit = BASE_URL.replace("personal_assistant", "pa_test_shared_ci")
    plan = test_db.build_database_plan(
        BASE_URL,
        explicit_test_url=explicit,
        run_token="caller-token",
    )

    assert plan.database_name == "pa_test_shared_ci"
    assert plan.created_by_run is False
    assert test_db.is_drop_authorized(plan) is False


def test_explicit_development_database_is_rejected():
    with pytest.raises(test_db.DatabaseSafetyError):
        test_db.build_database_plan(BASE_URL, explicit_test_url=BASE_URL)


def test_drop_authorization_rejects_tampered_name_or_token():
    plan = test_db.build_database_plan(
        BASE_URL,
        run_token="owned-run",
        worker_id="master",
    )

    assert test_db.is_drop_authorized(replace(plan, run_token="other-run")) is False
    assert test_db.is_drop_authorized(
        replace(plan, database_name="pa_test_other_safe_name")
    ) is False


def test_generated_names_are_deterministic_and_worker_scoped():
    first = test_db.generated_database_name("same-run", "gw0")
    second = test_db.generated_database_name("same-run", "gw0")
    other_worker = test_db.generated_database_name("same-run", "gw1")

    assert first == second
    assert first != other_worker
    assert len(first) <= 64


def test_pytest_runtime_is_bound_to_isolated_database_and_data_dir():
    from personal_assistant.config import settings

    database_name = make_url(settings.db_url).database
    assert test_db.validate_test_database_name(database_name) == database_name
    assert os.environ["PA_TEST_DATABASE_NAME"] == database_name
    assert Path(settings.data_dir).name.startswith("pa-test-data-")


def test_temp_cleanup_removes_readonly_files_inside_validated_subtree(tmp_path):
    temp_root = tmp_path / "cleanup-root"
    temp_root.mkdir()
    data_dir = temp_root / "pa-test-data-pa_test_cleanup-safe1234567"
    nested = data_dir / "git" / "objects"
    nested.mkdir(parents=True)
    readonly = nested / "object"
    readonly.write_bytes(b"test")
    os.chmod(readonly, stat.S_IREAD)

    test_db.remove_test_data_dir(data_dir, temp_root=temp_root)

    assert not data_dir.exists()
