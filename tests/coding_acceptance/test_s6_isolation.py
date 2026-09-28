"""阶段 B 隔离后端使用真实令牌及合成材料验证，不把公开样例计作盲评。"""
import json
import os
from pathlib import Path

import pytest
from coding_acceptance_catalog import judge, load_catalog, rebuild
from coding_acceptance_isolation import WindowsIsolation, read_live_journal
from coding_acceptance_schema import assessment_for
from run_coding_validation import ROOT, new_directory


def test_live_journal_disappearance_after_path_validation_is_not_a_manifest_error(tmp_path, monkeypatch):
    import coding_acceptance_schema as schema

    journal = tmp_path / "released-lease.json"
    journal.write_text('{"paths":[]}', encoding="utf-8")
    original = schema.plain_path

    def released_after_validation(path, **kwargs):
        checked = original(path, **kwargs)
        # 只删除本用例新建的夹具，复现租约校验后、元数据读取前的正常清理。
        if path == journal:
            journal.unlink()
        return checked

    monkeypatch.setattr(schema, "plain_path", released_after_validation)
    with pytest.raises(FileNotFoundError):
        read_live_journal(journal)


@pytest.mark.parametrize("kind", ["directory", "oversized", "invalid_json"])
def test_live_journal_invalid_existing_input_is_still_rejected(tmp_path, kind):
    from coding_acceptance_schema import LIMIT

    journal = tmp_path / "invalid-lease.json"
    if kind == "directory":
        journal.mkdir()
    elif kind == "oversized":
        with journal.open("wb") as stream:
            stream.truncate(LIMIT + 1)
    else:
        journal.write_text('{"paths":', encoding="utf-8")
    with pytest.raises(ValueError):
        read_live_journal(journal)


@pytest.fixture(scope="module")
def isolated_backend():
    area = new_directory(Path(os.environ["CODING_VALIDATION_DIR"]), "b-isolation")
    backend = WindowsIsolation(area / "tools")
    yield backend
    backend.verify()
    assert not list((backend.directory / "leases").glob("*.json"))


def test_scoped_appcontainer_denies_private_material(isolated_backend, tmp_path):
    protected = tmp_path / "assessment.json"
    protected.write_text('{"marker":"SYNTHETIC_PRIVATE_ASSESSMENT"}', encoding="utf-8")
    evidence = isolated_backend.probe([protected], tmp_path / "probe")
    assert evidence["verified"], evidence
    assert evidence["observation"]["appcontainer"] == 1
    assert evidence["observation"]["targets"] == [{"read": False, "write": False}]
    assert "SYNTHETIC_PRIVATE_ASSESSMENT" not in json.dumps(evidence)
    (tmp_path / "isolation.json").write_text(json.dumps(evidence), encoding="utf-8")


def test_actual_agent_ipc_restricted_material_boundary(isolated_backend, tmp_path):
    private = tmp_path / "assessment-canary.txt"
    private.write_text("SYNTHETIC_ISOLATED_ASSESSMENT", encoding="utf-8")
    observer = isolated_backend.observer_directory("python") / "hidden-input.txt"
    observer.write_text("SYNTHETIC_HIDDEN_JUDGE_INPUT", encoding="utf-8")
    isolated_backend.seal_observer("python", observer)
    evidence = isolated_backend.agent_probe([private, observer], tmp_path / "agent")
    (tmp_path / "ipc-isolation.json").write_text(json.dumps(evidence), encoding="utf-8")
    assert evidence["verified"], evidence
    assert "SYNTHETIC_ISOLATED_ASSESSMENT" not in json.dumps(evidence)
    assert "SYNTHETIC_HIDDEN_JUDGE_INPUT" not in json.dumps(evidence)
    assert not isolated_backend.runtime("python")["root"].is_relative_to(isolated_backend.agent_runtime("python")["root"])


@pytest.mark.parametrize("source,timeout,limit,reason", [
    ("print('x'*20000)", 10, 1024, "judge_output_quota"),
    ("import time; time.sleep(10)", 0.1, 64000, "judge_timeout"),
])
def test_isolated_execution_limits(isolated_backend, tmp_path, source, timeout, limit, reason):
    runtime = isolated_backend.runtime("python")
    script = tmp_path / "candidate.py"
    script.write_text(source, encoding="utf-8")
    result = isolated_backend.execute("python", [str(runtime["executable"]), "-I", "-B", str(script)], tmp_path,
                                      timeout=timeout, output_limit=limit)
    assert result["passed"] is False and result["reason"] == reason, result
    assert len(result["output"].encode("utf-8")) <= limit


@pytest.mark.parametrize("task_id", ["PY01", "VT01", "RS01"])
def test_three_language_isolated_judges(isolated_backend, tmp_path, task_id):
    catalog = load_catalog(ROOT / "tests/coding_acceptance/external_public/catalog.json")
    task = next(task for task in catalog["tasks"] if task["id"] == task_id)
    runtime = isolated_backend.runtime(task["family"])
    project = tmp_path / "project"
    before = rebuild(task, project, runtime=runtime)
    assert not judge(task, project, tmp_path, before, isolation=isolated_backend)["passed"]
    for name, content in assessment_for(task)["reference_files"].items():
        (project / name).write_text(content, encoding="utf-8")
    result = judge(task, project, tmp_path, before, isolation=isolated_backend)
    assert result["passed"], result
    assert result["isolation_verified"] and result["execution_profile"].startswith("pa.execution.")
    entry = {"python": "python.cmd", "vue-typescript": "npm.cmd", "rust": "cargo.cmd"}[task["family"]]
    public = isolated_backend.execute(task["family"], [str(runtime["root"] / entry), *task["validation_command"][1:]],
                                      project, timeout=20)
    assert public["passed"], public


def test_candidate_cannot_read_assessment_or_change_observer(isolated_backend, tmp_path):
    task = load_catalog(ROOT / "tests/coding_acceptance/external_public/catalog.json")["tasks"][0]
    project = tmp_path / "project"
    before = rebuild(task, project)
    private = tmp_path / "private.txt"
    private.write_text("SYNTHETIC_HIDDEN_VALUE", encoding="utf-8")
    for name, content in assessment_for(task)["reference_files"].items():
        (project / name).write_text(content, encoding="utf-8")
    program = (
        "\nimport sys\nfrom pathlib import Path\n"
        f"for path,mode in [(Path({str(private)!r}),'r'),(Path(sys.argv[0]),'r+')]:\n"
        "    try:\n        with path.open(mode): pass\n"
        "    except PermissionError: pass\n"
        "    else: raise AssertionError('isolation_failed')\n"
    )
    path = project / task["editable_files"][0]
    path.write_text(path.read_text(encoding="utf-8") + program, encoding="utf-8")
    result = judge(task, project, tmp_path, before, isolation=isolated_backend)
    assert result["passed"], result
    assert "SYNTHETIC_HIDDEN_VALUE" not in json.dumps(result)


def test_public_pytest_keeps_root_conftest_and_failing_tests(isolated_backend, tmp_path):
    runtime = isolated_backend.runtime("python")
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "conftest.py").write_text(
        "import pytest\n@pytest.fixture\ndef from_root():\n    return 42\n", encoding="utf-8")
    test = tmp_path / "tests/test_public.py"
    test.write_text("def test_public(from_root):\n    assert from_root == 42\n", encoding="utf-8")
    command = [str(runtime["root"] / "python.cmd"), "-m", "pytest"]
    result = isolated_backend.execute("python", command, tmp_path, timeout=10)
    assert result["passed"] and "1 passed" in result["output"], result
    test.write_text("def test_public(from_root):\n    assert from_root == 0\n", encoding="utf-8")
    result = isolated_backend.execute("python", command, tmp_path, timeout=10)
    assert result["reason"] == "candidate_failed" and "1 failed" in result["output"], result


def test_runtime_grant_never_contains_assessment(isolated_backend, tmp_path):
    marker = isolated_backend.observer_directory("python") / "private.txt"
    marker.write_text("SYNTHETIC_SCOPE", encoding="utf-8")
    isolated_backend.seal_observer("python", marker)
    try:
        with pytest.raises(ValueError, match="授权范围"):
            isolated_backend.probe([marker], tmp_path / "probe")
    finally:
        isolated_backend.protected.remove(marker)


def test_isolated_approval_refuses_trusted_downgrade():
    from run_coding_acceptance import approved, command_reply
    task = {"scenario": "normal", "validation_command": ["python", "-m", "pytest"], "_execution_mode": "restricted"}
    arguments = command_reply(task)["tool_calls"][0]["arguments"]
    preview = {**arguments, "cwd": ".", "retention": "run"}
    assert approved(task, {"tool_name": "exec_command"}, preview)
    assert not approved(task, {"tool_name": "exec_command"}, {**preview, "execution_mode": "trusted_project", "network_policy": "approved"})
