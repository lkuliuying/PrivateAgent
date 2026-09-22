"""直连评测的严格配置、真实 IPC 交接与冻结验证；凭据全部为合成值。"""
import hashlib
import json
from argparse import Namespace
from pathlib import Path

import pytest
from coding_acceptance_metrics import process_metrics
from coding_acceptance_models import ProductSession, direct_config
from coding_acceptance_transport import Fixture, RuntimeClient
from test_s6_models import budgets, config, event

from private_agent_local.identity import LOCAL_AUTHORITY, LOCAL_OWNER_ID
from private_agent_local.model_catalog import (
    ModelCatalog,
    ModelParameters,
    ProviderInput,
)


def direct_data(directory):
    data = config()
    data.update(schema_version=2, connection_mode="direct_provider", model_settings_directory=str(directory),
                credential_namespace="candidate", provider={"id": "test", "protocol": "openai", "endpoint": "https://models.example.test/v1"})
    data["parameters"].update(ModelParameters().model_dump())
    return data


def prepare_direct_evaluation(tmp_path, fixture, monkeypatch):
    import coding_acceptance_transport as transport

    root = tmp_path / "client-models"
    scope = hashlib.sha256(f"{LOCAL_AUTHORITY}\0{LOCAL_OWNER_ID}".encode()).hexdigest()
    source = ModelCatalog(root / scope / "model-settings.sqlite3", scope)
    provider = source.upsert("test", ProviderInput.model_validate({"name": "专用测试模型", "protocol": fixture.protocol,
        "base_url": fixture.endpoint, "api_format": "chat_completions" if fixture.protocol == "openai" else "ollama_chat",
        "models": [{"model_id": fixture.model_name, "context_tokens": 131072}]}))
    identifier = provider["models"][0]["profile_id"]
    source.data["parameters"] = ModelParameters(llm_context_length=131072).model_dump()
    source.data["profiles"][identifier]["supports_streaming"] = not fixture.legacy_stream
    source.save()
    reference = source.reference("test")["reference"]
    source.close()
    original = transport.isolated_environment
    if fixture.protocol != "ollama":
        fixture.provider_authorization = "Bearer S6_SYNTHETIC_PROVIDER_VALUE"
        monkeypatch.setattr(transport, "isolated_environment", lambda area: {
            **original(area), "PA_MODEL_PROVIDER_SECRETS_JSON": json.dumps({reference: "S6_SYNTHETIC_PROVIDER_VALUE"})})
    data = direct_data(root)
    data.update(profile_id=identifier, model=fixture.model_name)
    data["provider"].update(protocol=fixture.protocol, endpoint=fixture.endpoint)
    data["parameters"]["llm_context_length"] = 131072
    data["budget"].update(max_model_requests=12, max_tool_calls=12, max_attempt_tokens=10000, max_total_tokens=20000,
                          max_total_model_requests=24, max_total_tool_calls=24, max_active_seconds=60, max_total_active_seconds=120)
    path = tmp_path / "direct.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, direct_config(data)


@pytest.mark.parametrize("change", [
    {"schema_version": 1}, {"schema_version": True}, {"connection_mode": "local_unbilled"}, {"api_key": "synthetic"},
    {"credential_namespace": []}, {"model_settings_directory": "relative"}, {"model_settings_directory": []},
    {"provider": {"id": [], "protocol": "openai", "endpoint": "https://test.invalid"}},
    {"provider": {"id": "x", "protocol": [], "endpoint": "https://test.invalid"}},
    {"provider": {"id": "x", "protocol": "ollama", "endpoint": "https://test.invalid"}},
    {"provider": {"id": "x", "protocol": "openai", "endpoint": "https://u:synthetic@test.invalid"}},
])
def test_direct_config_requires_explicit_version_and_no_credentials(tmp_path, change):
    with pytest.raises(ValueError):
        direct_config(direct_data(tmp_path) | change)


def test_direct_generation_settings_are_strict_and_complete(tmp_path):
    data = direct_data(tmp_path)
    assert direct_config(data)["connection_mode"] == "direct_provider"
    for value in (True, "0.7", -1, float("nan")):
        data["parameters"]["llm_temperature"] = value
        with pytest.raises(ValueError):
            direct_config(data)


def test_old_proxy_execution_is_explicitly_rejected_before_login(tmp_path, monkeypatch):
    import run_coding_acceptance as runner

    path = tmp_path / "old.json"
    path.write_text(json.dumps(config()))
    monkeypatch.setattr(runner, "ProductSession", lambda *_: pytest.fail("旧入口不得绑定模型"))
    with pytest.raises(ValueError, match="product_proxy 执行已停用"):
        runner.model_config(path)


@pytest.mark.parametrize("protocol,stream", [("openai", True), ("openai", False), ("ollama", True)])
def test_direct_ipc_preflight_uses_product_snapshot_without_inference(tmp_path, monkeypatch, protocol, stream):
    with Fixture(protocol, legacy_stream=not stream) as fixture:
        _, model = prepare_direct_evaluation(tmp_path, fixture, monkeypatch)
        account = ProductSession(model)
        area = tmp_path / "agent"
        area.mkdir()
        with RuntimeClient(area, account) as client:
            client.request("/identity/local", "POST")
            description = client.request("/model-evaluation/preflight?profile_id=" + model["profile_id"])
            from coding_acceptance_models import check_preflight

            assert not check_preflight(description, model, client.request("/capabilities"))
            assert description["route"] == "direct_provider"
            assert description["profile"]["supports_streaming"] is stream
            assert description["parameters"]["llm_context_length"] == 131072
            assert description["version_unknown_reason"] and description["model_version"] is None
            assert fixture.calls == []
            assert client.request("/agent-model-profiles/x/tool-probe", "POST", expected=409)["error_code"] == "evaluation_configuration_frozen"
            assert fixture.calls == []


def test_direct_probe_requires_authorization_before_model_binding(tmp_path, monkeypatch):
    import run_coding_acceptance as runner

    path = tmp_path / "direct.json"
    path.write_text(json.dumps(direct_data(tmp_path)))
    monkeypatch.setattr(runner, "ProductSession", lambda *_: pytest.fail("未授权不得绑定模型"))
    with pytest.raises(ValueError, match="未授权"):
        runner.run(Namespace(mode="probe", tasks="PY01", repetitions=1, model_config=path, isolation="appcontainer",
                             catalog=Path(__file__).parent / "external_public/catalog.json", authorize_model_calls=False))


@pytest.mark.parametrize("ids", [["a", "a"], ["a", "wrong"], [None, "b"]])
def test_transport_counters_require_unique_request_correlations(ids):
    history = [event("model.requested", 0, attempt_id="a"), event("model.requested", 1, attempt_id="b")]
    history += [event("model.transport", 2, attempt_id=i, call_id=i, provider_requests=1, provider_retries=0) for i in ids]
    assert process_metrics(history, {})["provider_requests"] is None


def test_budget_does_not_settle_failed_or_cancelled_requests_as_free():
    from coding_acceptance_budget import ExperimentBudget

    ledger = ExperimentBudget(budgets(), 2)
    ledger.settle({"attempt_id": "failed", "started": True, "model_requests": 1, "tool_calls": 0, "active_seconds": 2})
    assert ledger.snapshot()["usage"]["model_requests"] == 1
    assert ledger.snapshot()["usage"]["tokens"] is None
    with pytest.raises(ValueError, match="unknown"):
        ledger.allocate(budgets())
