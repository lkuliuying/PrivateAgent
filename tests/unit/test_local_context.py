"""计量必须来源于真实用量字段；不把累计计费量或字符数当成窗口占用。"""
import json

import pytest
from test_local_executor import TERMINAL, call, close, response, setup, until

from private_agent_local.context import average_cache_hit_percent, context_budget


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
async def test_model_identity_uses_selected_route_and_refreshes_between_turns(tmp_path, explicit):
    app, client, server, _, body = await setup(tmp_path)
    try:
        server.profiles = [
            {"id": "profile-a", "model_name": "deepseek-flash-v4-long-model-id", "context_tokens": 32000, "is_default": True, "enabled": True},
            {"id": "profile-b", "model_name": "another-model-2026-09", "context_tokens": 32000, "is_default": False, "enabled": True},
        ]
        body.update(message="你是什么模型？")
        for profile in (server.profiles[1], server.profiles[0]) if explicit else (server.profiles[0], server.profiles[1]):
            if explicit:
                body["model_profile_id"] = profile["id"]
            else:
                body.pop("model_profile_id", None)
                for item in server.profiles:
                    item["is_default"] = item["id"] == profile["id"]
            server.responses = [response(text="合成模型回答")]
            run = (await client.post("/agent-runs", json=body)).json()
            assert (await until(client, run["id"], TERMINAL))["status"] == "completed"
            request = json.loads([payload for path, payload in server.calls if path == "/desktop/model/complete"][-1])
            identity = [message["content"] for message in request["request"]["messages"]
                        if message["role"] == "system" and "当前请求的模型信息" in message["content"]]
            assert len(identity) == 1
            assert json.dumps({"model_id": profile["model_name"]}, ensure_ascii=False) in identity[0]
            assert "直接简短回答：我是 <model_id>。" in identity[0]
            assert "不要附加配置来源、字段名、版本边界、工具能力或其他说明" in identity[0]
            assert "实际请求标识，不证明" not in identity[0]
            assert request["model_profile_id"] == profile["id"]
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_missing_model_identity_is_unknown_without_using_profile_id(tmp_path):
    app, client, server, _, body = await setup(tmp_path)
    try:
        server.profiles[0].pop("model_name")
        server.responses = [response(text="合成模型回答")]
        run = (await client.post("/agent-runs", json={**body, "message": "当前模型 ID"})).json()
        await until(client, run["id"], TERMINAL)
        request = json.loads([payload for path, payload in server.calls if path == "/desktop/model/complete"][-1])["request"]
        identity = next(message["content"] for message in request["messages"] if "当前请求的模型信息" in message["content"])
        assert '"model_id": null' in identity and "test-profile" not in identity
        assert "ID 为空时只回答：无法确认当前模型。" in identity
    finally:
        await close(app, client)


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
