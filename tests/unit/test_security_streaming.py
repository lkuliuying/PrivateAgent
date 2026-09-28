"""公开模型输出在分片、正常结束和中断时保持脱敏与生命周期一致。"""
import asyncio
import json

import pytest
from test_local_executor import Server, close, response, setup, until

from private_agent_core.llm.contracts import ModelTextDelta
from private_agent_local.model_errors import CloudError
from private_agent_local.runtime import TERMINAL

pytestmark = pytest.mark.asyncio

SECRET = "synthetic-provider-credential-0123456789"


class PublicOutputServer(Server):
    def __init__(self, chunks, *, interrupt=False):
        super().__init__()
        self.profiles[0]["supports_streaming"] = True
        self.chunks = chunks
        self.interrupt = interrupt
        self.ready = asyncio.Event()
        self.release = asyncio.Event()

    async def model_stream(self, on_delta):
        for chunk in self.chunks:
            await on_delta(chunk)
        self.ready.set()
        if self.interrupt:
            await self.release.wait()
            raise CloudError(502, "测试供应商断流", code="model_stream_interrupted")
        return response(text="".join(self.chunks))


def public_text(events):
    return "".join(event["payload"]["delta"] for event in events if event["type"] == "model.output.delta")


def assert_public_records_safe(store, run_id, session_id):
    records = {
        "run": store.run(run_id),
        "events": store.events(run_id),
        "messages": store.list("message", session_id=session_id),
    }
    assert SECRET not in json.dumps(records, ensure_ascii=False)


@pytest.mark.parametrize("chunks,expected", [
    (["开始 ", "synthetic-provider-", "credential-", "0123456789", " 完成"], "开始 [REDACTED] 完成"),
    (list(SECRET), "[REDACTED]"),
    (["普通正文 ", "synthetic-pro"], "普通正文 [REDACTED]"),
])
async def test_completed_public_stream_matches_safe_final_response(tmp_path, chunks, expected):
    server = PublicOutputServer(chunks)
    app, client, _, _, body = await setup(tmp_path, server)
    app.state.desktop.cloud.secrets = {"provider": SECRET}
    try:
        created = await client.post("/agent-runs", json={**body, "permission_mode": "readonly"})
        assert created.status_code == 201, created.text
        run_id = created.json()["id"]
        final = await until(client, run_id, TERMINAL)
        assert final["status"] == "completed", final
        store = app.state.desktop.runtime.store
        events = store.events(run_id)
        assert final["output"] == public_text(events) == expected
        finished, = [event for event in events if event["type"] == "model.output.finished"]
        assert all(event["sequence"] < finished["sequence"] for event in events if event["type"] == "model.output.delta")
        assert not any(event["type"] == "model.output.interrupted" for event in events)
        messages = [item for item in store.list("message", session_id=body["session_id"]) if item["role"] == "assistant"]
        assert len(messages) == 1
        assert_public_records_safe(store, run_id, body["session_id"])
    finally:
        await close(app, client)


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("prefix", ["", "公开内容 "])
async def test_interruption_flushes_sensitive_tail_before_terminal(tmp_path, cancel, prefix):
    server = PublicOutputServer([prefix, "synthetic-pro"], interrupt=True)
    app, client, _, _, body = await setup(tmp_path, server)
    app.state.desktop.cloud.secrets = {"provider": SECRET}
    try:
        created = await client.post("/agent-runs", json={**body, "permission_mode": "readonly"})
        assert created.status_code == 201, created.text
        run_id = created.json()["id"]
        await asyncio.wait_for(server.ready.wait(), timeout=2)
        if cancel:
            assert (await client.post(f"/agent-runs/{run_id}/cancel")).status_code == 200
        else:
            server.release.set()
        final = await until(client, run_id, TERMINAL)
        assert final["status"] == ("cancelled" if cancel else "failed"), final
        store = app.state.desktop.runtime.store
        events = store.events(run_id)
        deltas = [event for event in events if event["type"] == "model.output.delta"]
        interrupted, = [event for event in events if event["type"] == "model.output.interrupted"]
        assert public_text(events) == prefix + "[REDACTED]"
        assert deltas and all(event["sequence"] < interrupted["sequence"] for event in deltas)
        assert all(event["payload"]["attempt_id"] == interrupted["payload"]["attempt_id"] for event in deltas)
        assert not any(event["type"] == "model.output.finished" for event in events)
        assert not [item for item in store.list("message", session_id=body["session_id"]) if item["role"] == "assistant"]
        assert_public_records_safe(store, run_id, body["session_id"])
    finally:
        server.release.set()
        await close(app, client)


async def test_rich_public_stream_filters_each_message_before_its_terminal(tmp_path):
    server = PublicOutputServer([])
    app, client, _, _, body = await setup(tmp_path, server)
    app.state.desktop.cloud.secrets = {"provider": SECRET}

    async def model_stream(token, profile, request, *, on_delta, on_message_delta):
        for chunk in ["检查 ", "synthetic-provider-", "credential-0123456789"]:
            await on_message_delta(ModelTextDelta("progress", "commentary", chunk))
        for chunk in ["完成 ", "synthetic-provider-", "credential-0123456789"]:
            await on_message_delta(ModelTextDelta("answer", "final_answer", chunk))
            await on_delta(chunk)
        return response(text="完成 " + SECRET)

    app.state.desktop.cloud.complete_stream_messages = model_stream
    try:
        created = await client.post("/agent-runs", json={**body, "permission_mode": "readonly"})
        assert created.status_code == 201, created.text
        run_id = created.json()["id"]
        final = await until(client, run_id, TERMINAL)
        assert final["status"] == "completed" and final["output"] == "完成 [REDACTED]", final
        store = app.state.desktop.runtime.store
        events = store.events(run_id)
        finished, = [event for event in events if event["type"] == "model.output.finished"]
        deltas = [event for event in events if event["type"] == "model.output.delta"]
        for phase, expected in [("commentary", "检查 [REDACTED]"), ("final_answer", "完成 [REDACTED]")]:
            assert "".join(event["payload"]["delta"] for event in deltas if event["payload"]["phase"] == phase) == expected
        assert all(event["sequence"] < finished["sequence"] for event in deltas)
        assert [item["phase"] for item in finished["payload"]["messages"]] == ["commentary", "final_answer"]
        assert_public_records_safe(store, run_id, body["session_id"])
    finally:
        await close(app, client)


@pytest.mark.parametrize("kind", ["commentary", "summary"])
async def test_sensitive_native_public_state_is_not_persisted(tmp_path, kind):
    server = PublicOutputServer([])
    app, client, _, _, body = await setup(tmp_path, server)
    app.state.desktop.cloud.secrets = {"provider": SECRET}

    async def model_stream(token, profile, request, *, on_delta):
        await on_delta("已完成")
        native = ({"type": "message", "phase": "commentary",
                   "content": [{"type": "output_text", "text": SECRET}]}
                  if kind == "commentary" else {"type": "reasoning",
                   "summary": [{"type": "summary_text", "text": SECRET}], "encrypted_content": "opaque-test"})
        return {**response(text="已完成"), "provider_state": {
            "api_format": "responses", "route": "a" * 64, "output_json": json.dumps([native])}}

    app.state.desktop.cloud.complete_stream = model_stream
    try:
        created = await client.post("/agent-runs", json={**body, "permission_mode": "readonly"})
        assert created.status_code == 201, created.text
        run_id = created.json()["id"]
        final = await until(client, run_id, TERMINAL)
        assert final["status"] == "completed" and final["output"] == "已完成", final
        store = app.state.desktop.runtime.store
        assert_public_records_safe(store, run_id, body["session_id"])
        assert SECRET not in json.dumps(store.context.items(body["session_id"]), ensure_ascii=False)
    finally:
        await close(app, client)


@pytest.mark.parametrize("field", ["tool_id", "tool_name", "message_id", "provider", "model", "request_id"])
async def test_sensitive_protocol_identifiers_are_rejected_without_persistence(tmp_path, field):
    server = PublicOutputServer([])
    app, client, _, _, body = await setup(tmp_path, server)
    app.state.desktop.cloud.secrets = {"provider": SECRET}

    async def model_stream(token, profile, request, *, on_delta, on_message_delta):
        value = response(text="公开回复")
        if field == "message_id":
            await on_message_delta(ModelTextDelta(SECRET, "final_answer", "公开回复"))
        elif field.startswith("tool_"):
            value["tool_calls"] = [{"id": SECRET if field == "tool_id" else "normal-call",
                                    "name": SECRET if field == "tool_name" else "list_project_directory",
                                    "arguments": {"rel_path": "."}}]
        else:
            value[field] = SECRET
        await on_delta("公开回复")
        return value

    app.state.desktop.cloud.complete_stream_messages = model_stream
    try:
        created = await client.post("/agent-runs", json={**body, "permission_mode": "readonly"})
        assert created.status_code == 201, created.text
        run_id = created.json()["id"]
        final = await until(client, run_id, TERMINAL)
        assert final["status"] == "failed", final
        store = app.state.desktop.runtime.store
        assert not store.run(run_id)["executions"]
        assert_public_records_safe(store, run_id, body["session_id"])
    finally:
        await close(app, client)
