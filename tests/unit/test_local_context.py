"""计量必须来源于真实用量字段；不把累计计费量或字符数当成窗口占用。"""
import pytest
from test_local_executor import TERMINAL, call, close, response, setup, until

from private_agent_local.context import average_cache_hit_percent, context_budget


def test_unknown_capacity_and_missing_usage_do_not_fabricate_percent():
    unknown = context_budget(None, {"context_usage": {"input_tokens": 20}})
    assert unknown["source"] == "unavailable" and unknown["usage_percent"] is None
    pending = context_budget({"context_tokens": 32000}, None)
    assert pending["max_context_tokens"] == 32000 and pending["usage_percent"] is None
    assert pending["error_code"] == "context_usage_unavailable"
    for invalid in [True, -1, 1.5, "10"]:
        assert context_budget({"context_tokens": 32000}, {"context_usage": {"input_tokens": invalid}})["usage_percent"] is None


@pytest.mark.asyncio
async def test_context_endpoint_uses_latest_request_instead_of_accumulated_tokens(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        server.responses = [response(call("list_project_directory", {"rel_path": "."})), response(text="完成")]
        server.responses[0]["usage"] = {"input_tokens": 8000, "cached_tokens": 2000}
        server.responses[1]["usage"] = {"input_tokens": 12000, "cached_tokens": 6000}
        run = (await client.post("/agent-runs", json=body)).json()
        final = await until(client, run["id"], TERMINAL)
        assert final["input_tokens"] == 20000
        budget = (await client.get(f"/sessions/{body['session_id']}/context-budget?model_profile_id=test-profile")).json()
        assert budget["used_tokens"] == 12000
        assert budget["max_context_tokens"] == 32000
        assert budget["source"] == "provider_usage"
        assert budget["usage_percent"] == 38
        assert budget["cache_hit_percent"] == 40
        assert budget["cache_hit_scope"] == "session"
        server.responses = [response(text="下一轮")]
        server.responses[0]["usage"] = {"input_tokens": 5000, "cached_tokens": 5000}
        second = (await client.post("/agent-runs", json=body)).json()
        await until(client, second["id"], TERMINAL)
        budget = (await client.get(f"/sessions/{body['session_id']}/context-budget?model_profile_id=test-profile")).json()
        assert budget["cache_hit_percent"] == 52
        assert budget["used_tokens"] == 5000
        unknown = (await client.get(f"/sessions/{body['session_id']}/context-budget?model_profile_id=missing")).json()
        assert unknown["usage_percent"] is None
        assert unknown["cache_hit_percent"] is None
    finally:
        await close(app, client)


def test_average_cache_ignores_invalid_usage_and_other_models():
    profile = {"id": "chosen", "model_name": "fixture"}
    base = {"model_profile_id": "chosen", "model": "fixture"}
    runs = [
        {**base, "cache_usage": {"input_tokens": 100, "cached_tokens": 25}},
        {**base, "cache_usage": {"input_tokens": 300, "cached_tokens": 225}},
        {**base, "model_profile_id": "other", "cache_usage": {"input_tokens": 500, "cached_tokens": 500}},
        {**base, "model": "other", "cache_usage": {"input_tokens": 500, "cached_tokens": 500}},
    ]
    for used, cached in [(0, 0), (True, 0), (50, None), (50, 51), (50, -1), (50, True), ("50", 10)]:
        runs.append({**base, "cache_usage": {"input_tokens": used, "cached_tokens": cached}})
    assert average_cache_hit_percent(profile, runs) == 62.5
    assert average_cache_hit_percent(profile, []) is None
    assert average_cache_hit_percent(None, runs) is None
    assert average_cache_hit_percent(profile, [{**base, "context_usage": {"input_tokens": 100, "cached_tokens": 50}}]) == 50
