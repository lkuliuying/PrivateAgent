"""本机联调入口的授权、隔离、凭据与实际 IPC 回归；供应商均为合成替身。"""
import errno
import getpass
import hashlib
import json
import os
import socket
import warnings
from argparse import Namespace
from pathlib import Path

import pytest
from coding_acceptance_catalog import load_catalog
from coding_acceptance_evidence import verify_ledger
from coding_acceptance_local import (
    ACCOUNT_MODE,
    LocalSession,
    local_config,
    secret_input,
    validate_secret,
)
from coding_acceptance_models import check_preflight
from coding_acceptance_transport import Fixture, RuntimeClient
from run_coding_local_probe import CATALOG, TEMPLATE, check, initialize, main

from private_agent_local.identity import LOCAL_AUTHORITY, LOCAL_OWNER_ID
from private_agent_local.model_catalog import ModelCatalog

SYNTHETIC_KEY = "S6_LOCAL_SYNTHETIC_PROVIDER_ONLY"


def config(**changes):
    data = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    data["provider"]["endpoint"] = "https://models.example.test/v1"
    data["model"] = "s6-fixture"
    data.update(changes)
    return data


def config_path(tmp_path, data):
    path = tmp_path / "local-probe.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def options(path, tmp_path, **changes):
    return Namespace(**({"mode": "probe", "tasks": "PY01", "repetitions": 1, "protocol": "openai",
                         "model_config": path, "bundle": None, "work_dir": tmp_path,
                         "isolation": "appcontainer", "catalog": CATALOG, "authorize_model_calls": True} | changes))


@pytest.mark.parametrize("changes", [
    {"api_key": SYNTHETIC_KEY}, {"endpoint": "https://account.test"}, {"model_settings_directory": "existing"},
    {"schema_version": True}, {"schema_version": 2}, {"account_mode": "server_account"},
    {"model": None}, {"model": ""}, {"supports_streaming": 1},
    {"tasks": []}, {"tasks": ["PY01", "PY01"]}, {"tasks": ["PY01", None]},
])
def test_local_configuration_rejects_secrets_and_ambiguous_scope(changes):
    with pytest.raises(ValueError):
        local_config(config(**changes))


@pytest.mark.parametrize("field,value", [
    ("provider.endpoint", "http://remote.example.test/v1"),
    ("provider.endpoint", "https://name:synthetic@models.test/v1"),
    ("provider.endpoint", "https://models.test/v1?key=synthetic"),
    ("provider.protocol", "ollama"),
    ("parameters.llm_context_length", 100000),
    ("parameters.llm_temperature", True),
    ("parameters.max_output_tokens", 0),
    ("budget.max_model_requests", 25),
    ("budget.max_total_tokens", 1),
    ("budget.cost_usd", 1),
])
def test_local_configuration_keeps_existing_provider_and_budget_contract(field, value):
    data = config()
    parent, name = field.split(".")
    data[parent][name] = value
    with pytest.raises(ValueError):
        local_config(data)


def test_initializer_preserves_user_file_and_requires_missing_information(tmp_path):
    path = tmp_path / "settings.json"
    initialize(path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        check(path)
    with pytest.raises(FileExistsError):
        initialize(path)
    assert path.read_bytes() == before


def test_configuration_check_never_opens_session_and_redacts_invalid_input(tmp_path, monkeypatch, capsys):
    import run_coding_acceptance as runner

    monkeypatch.setattr(runner, "secret_input", lambda: pytest.fail("检查不得读取凭据"))
    path = config_path(tmp_path, config())
    assert main(["check", "--config", str(path)]) == 0
    assert main(["probe", "--config", str(path)]) == 2
    path.write_text(json.dumps(config(api_key=SYNTHETIC_KEY)))
    assert main(["check", "--config", str(path)]) == 2
    output = capsys.readouterr()
    assert SYNTHETIC_KEY not in output.out + output.err
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("changes", [
    {"authorize_model_calls": False}, {"tasks": "PY02"}, {"isolation": "none"},
    {"mode": "quality", "repetitions": 3}, {"expected_config_sha256": "0" * 64},
])
def test_local_calls_require_bound_scope_before_credentials(tmp_path, monkeypatch, changes):
    import run_coding_acceptance as runner

    monkeypatch.setattr(runner, "secret_input", lambda: pytest.fail("范围无效时不得读取凭据"))
    path = config_path(tmp_path, config())
    with pytest.raises(ValueError):
        runner.run(options(path, tmp_path, **changes))
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("value", ["", "bad\nkey", "bad key", "\x00", "x" * 16385, None])
def test_secret_input_rejects_unsafe_values(value):
    with pytest.raises(ValueError):
        validate_secret(value)


def test_secret_input_refuses_pipe_and_getpass_echo_fallback(monkeypatch):
    import coding_acceptance_local as module

    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(module.getpass, "getpass", lambda *_: pytest.fail("非终端不得读取"))
    with pytest.raises(ValueError):
        secret_input()
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: True)

    def fallback(*_):
        warnings.warn("synthetic echo fallback", getpass.GetPassWarning)
        pytest.fail("检测到回显后不得继续读取")

    monkeypatch.setattr(module.getpass, "getpass", fallback)
    with pytest.raises(ValueError, match="隐藏"):
        secret_input()
    monkeypatch.setattr(module.getpass, "getpass", lambda *_: SYNTHETIC_KEY)
    assert secret_input() == SYNTHETIC_KEY


@pytest.mark.parametrize("mode", ["restricted", "trusted_project"])
def test_prompt_discloses_executable_approval_contract(mode):
    import run_coding_acceptance as runner

    task = load_catalog(CATALOG)["tasks"][0]
    task["_execution_mode"] = mode
    prompt = runner.task_prompt(task)
    arguments = json.loads(prompt.split("其余执行参数（JSON）：\n", 1)[1].splitlines()[0])
    assert "argv 必须按照题面验证命令的参数顺序传入数组，不得追加或省略参数" in prompt
    arguments["argv"] = task["validation_command"]
    assert prompt.startswith(task["files"]["README.md"])
    assert arguments["argv"] == ["python", "-m", "pytest"]
    assert arguments["timeout_ms"] == 60000 and arguments["cwd"] == "." and arguments["retention"] == "run"
    assert arguments["execution_mode"] == mode
    assert arguments["network_policy"] == ("none" if mode == "restricted" else "approved")
    assert "read_execution" in prompt
    assert runner.approved(task, {"tool_name": "exec_command"}, arguments)
    assert runner.approved(task, {"tool_name": "exec_command"}, {**arguments, "timeout_ms": 59999})
    assert not runner.approved(task, {"tool_name": "exec_command"}, {**arguments, "timeout_ms": 300000})


@pytest.mark.parametrize("change", [
    {"timeout_ms": 60001}, {"cwd": "src"}, {"retention": "session"},
    {"argv": ["python", "-m", "pytest", "--unapproved"]},
    {"execution_mode": "trusted_project", "network_policy": "approved"}, {"network_policy": "approved"},
])
def test_disclosed_command_keeps_out_of_scope_requests_rejected(change):
    import run_coding_acceptance as runner

    task = load_catalog(CATALOG)["tasks"][0]
    task["_execution_mode"] = "restricted"
    prompt = runner.task_prompt(task)
    arguments = json.loads(prompt.split("其余执行参数（JSON）：\n", 1)[1].splitlines()[0])
    arguments["argv"] = task["validation_command"]
    assert not runner.approved(task, {"tool_name": "exec_command"}, {**arguments, **change})


@pytest.mark.parametrize("task", load_catalog(CATALOG)["tasks"], ids=lambda task: task["id"])
def test_execution_instructions_preserve_public_task_requirements(task):
    import run_coding_acceptance as runner

    from private_agent_core.completion import task_requirements

    previous = task["files"]["README.md"] + "\n请完成上述修改并运行验证。只运行预定验证命令；不要安装依赖。"
    expected = task_requirements(previous)
    for mode in ("restricted", "trusted_project"):
        task["_execution_mode"] = mode
        assert task_requirements(runner.task_prompt(task)) == expected


@pytest.mark.parametrize("code", [5, 32, 33])
def test_lease_journal_retries_only_transient_windows_conflicts(tmp_path, monkeypatch, code):
    import coding_acceptance_isolation as module

    failure = PermissionError("synthetic")
    failure.winerror = code
    reads = []

    def read(_path):
        reads.append(True)
        if len(reads) == 1:
            raise failure
        return {"paths": ["observed"]}

    monkeypatch.setattr(module, "read_json", read)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    assert module.read_live_journal(tmp_path / "lease.json") == {"paths": ["observed"]}
    assert len(reads) == 2


@pytest.mark.parametrize("code", [None, 5])
def test_lease_journal_persistent_denial_remains_a_failure(tmp_path, monkeypatch, code):
    import coding_acceptance_isolation as module

    failure = PermissionError("synthetic")
    failure.winerror = code
    times = iter([0, 0.1, 1.1])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    def read(_path):
        raise failure

    monkeypatch.setattr(module, "read_json", read)
    with pytest.raises(PermissionError):
        module.read_live_journal(tmp_path / "lease.json")


@pytest.mark.parametrize("persistent", [False, True])
def test_lease_journal_handles_windows_errno_without_winerror(tmp_path, monkeypatch, persistent):
    import coding_acceptance_isolation as module

    failure = PermissionError(errno.EACCES, "synthetic")
    reads = []
    times = iter([0, 0.1, 1.1])
    path = tmp_path / "lease.json"
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    def read(_path):
        reads.append(True)
        if persistent or len(reads) == 1:
            raise failure
        return {"paths": ["observed"]}

    monkeypatch.setattr(module, "read_json", read)
    if persistent:
        with pytest.raises(PermissionError) as caught:
            module.read_live_journal(path)
        assert caught.value is failure
    else:
        assert module.read_live_journal(path) == {"paths": ["observed"]}
    assert len(reads) == 2


@pytest.mark.parametrize("platform_name,code", [("posix", errno.EACCES), ("nt", errno.EPERM)])
def test_lease_journal_does_not_retry_other_errno_failures(tmp_path, monkeypatch, platform_name, code):
    import coding_acceptance_isolation as module

    path = tmp_path / "lease.json"
    failure = PermissionError(code, "synthetic")
    monkeypatch.setattr(module.os, "name", platform_name)
    monkeypatch.setattr(module.time, "sleep", lambda _: pytest.fail("此错误不得重读"))

    def read(_path):
        raise failure

    monkeypatch.setattr(module, "read_json", read)
    with pytest.raises(PermissionError) as caught:
        module.read_live_journal(path)
    assert caught.value is failure


@pytest.mark.parametrize("protocol,stream", [("openai", True), ("openai", False), ("claude", True)])
def test_local_ipc_preflight_freezes_config_without_provider_requests(tmp_path, monkeypatch, protocol, stream):
    data = config(supports_streaming=stream)
    data["provider"].update(protocol=protocol)
    model = local_config(data)
    monkeypatch.setattr(socket.socket, "bind", lambda *_: pytest.fail("本机模型配置不得启动账号服务"))
    session = LocalSession(model, tmp_path, SYNTHETIC_KEY)
    assert session.identity()["account_service_started"] is False
    assert not hasattr(session, "token")
    try:
        area = tmp_path / "ipc"
        area.mkdir()
        client = RuntimeClient(area, session)
        assert client.startup_environment["PA_EVALUATION_SYNTHETIC_ONLY"] == "1"
        with client:
            assert "PA_MODEL_PROVIDER_SECRETS_JSON" not in client.startup_environment
            client.request("/identity/local", "POST")
            token = client.token
            url = "/model-evaluation/preflight?profile_id=" + model["profile_id"]
            description = client.request(url)
            assert not check_preflight(description, model, client.request("/capabilities"))
            assert description["profile"]["supports_streaming"] is stream
            assert client.request("/model-settings", "PUT", {}, expected=409)["error_code"] == "evaluation_configuration_frozen"
            scope = hashlib.sha256(f"{LOCAL_AUTHORITY}\0{LOCAL_OWNER_ID}".encode()).hexdigest()
            catalog = ModelCatalog(Path(session.model["model_settings_directory"]) / scope / "model-settings.sqlite3", scope)
            try:
                catalog.data["parameters"]["llm_temperature"] = 0.1
                catalog.save()
            finally:
                catalog.close()
            assert client.request(url, expected=409)["error_code"] == "evaluation_configuration_changed"
        assert client.process.poll() == 0
    finally:
        session.close()
    assert session._secret == ""
    with pytest.raises(ValueError):
        session.runtime_credentials()
    for path in tmp_path.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert SYNTHETIC_KEY.encode() not in content and token.encode() not in content


@pytest.mark.parametrize("outcome", ["pass", "request_limit", "bad_key"])
def test_local_probe_uses_actual_agent_and_bounded_cloud_adapter(tmp_path, monkeypatch, outcome):
    import run_coding_acceptance as runner

    task = load_catalog(CATALOG)["tasks"][0]
    task["_execution_mode"] = "restricted"
    monkeypatch.setattr(runner, "ProductSession", lambda *_: pytest.fail("本机联调应只使用隔离模型配置"))
    monkeypatch.setattr(runner, "secret_input", lambda: SYNTHETIC_KEY)
    with Fixture("openai") as provider:
        data = config()
        data["provider"]["endpoint"] = provider.endpoint
        if outcome == "request_limit":
            data["budget"].update(max_model_requests=1, max_total_model_requests=1)
        provider.provider_authorization = "Bearer " + (SYNTHETIC_KEY if outcome != "bad_key" else "OTHER_SYNTHETIC")
        provider.responses.extend(runner.script(task))
        path = config_path(tmp_path, data)
        parent_environment = os.environ.get("PA_MODEL_PROVIDER_SECRETS_JSON")
        result = runner.run(options(path, tmp_path))
        assert os.environ.get("PA_MODEL_PROVIDER_SECRETS_JSON") == parent_environment
        directory = next(tmp_path.glob("probe-*"))
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in (directory / "attempts.jsonl").read_text(encoding="utf-8").splitlines()]
        assert manifest["model_preflight"]["passed"], manifest
        assert manifest["model_preflight"]["inference_performed"] is False
        assert manifest["account_mode"] == ACCOUNT_MODE
        assert manifest["local_account"]["real_server_account_verified"] is False
        assert manifest["local_account"]["account_service_model_routes"] is False
        assert len(rows) == 1 and rows[0]["started"], (rows, manifest.get("runner_exception"))
        row = rows[0]
        assert row["account_mode"] == ACCOUNT_MODE and row["isolation_verified"]
        assert row["effective_budget"]["max_model_requests"] == data["budget"]["max_model_requests"]
        assert row["cost_usd"] is None
        if outcome == "pass":
            assert result == 0 and row["system_behavior_passed"] and row["within_budget"], row
            assert row["validation_passed"] and row["process_metrics"]["tool_seconds"] > 0
            assert 1 < len(provider.calls) <= 8
            artifact = json.loads((directory / "artifacts/openai-PY01-1.json").read_text(encoding="utf-8"))
            assert "timeout_ms" in artifact["run"]["goal"] and "60000" in artifact["run"]["goal"]
            assert "read_execution" in artifact["run"]["goal"]
        else:
            assert result == 1 and not row["system_behavior_passed"]
            assert row["model_requests"] == 1
            assert len(provider.calls) == (1 if outcome == "request_limit" else 0)
        assert row["process_metrics"]["provider_requests"] == row["model_requests"]
        assert manifest["experiment_budget"]["usage"]["model_requests"] == row["model_requests"]
        assert manifest["experiment_budget"]["usage"]["tokens"] == row["tokens"]
        verify_ledger(directory, manifest, rows)
        assert json.loads((directory / "metrics.json").read_text(encoding="utf-8"))["delivery_decision"] == "blocked"
        for artifact in directory.rglob("*"):
            if artifact.is_file() and not artifact.is_symlink() and artifact.suffix not in {".exe", ".dll", ".pyd"}:
                assert SYNTHETIC_KEY.encode() not in artifact.read_bytes()
