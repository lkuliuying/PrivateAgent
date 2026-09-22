"""模型直连的分帧工具、断流和本机唯一事件源。"""
import asyncio
import json

import httpx
import pytest
from test_direct_models import configuration, desktop
from test_local_executor import Server, call, close, response, setup, until
from test_responses_adapter import OPAQUE, message, reasoning, sse
from test_responses_adapter import response as responses_body

from private_agent_local.connections import ModelConfig
from private_agent_local.local_models import LocalInference
from private_agent_local.model_errors import CloudError
from private_agent_local.runtime import TERMINAL

pytestmark = pytest.mark.asyncio


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks, gate=None):
        self.chunks, self.gate, self.closed = chunks, gate, False

    async def __aiter__(self):
        for index, chunk in enumerate(self.chunks):
            yield chunk
            if index == 0 and self.gate:
                await self.gate.wait()

    async def aclose(self):
        self.closed = True






@pytest.mark.parametrize("valid", [True, False])
async def test_local_provider_assembles_tool_json_only_after_finish(valid):
    gate, deltas = asyncio.Event(), []
    frames = [
        {"choices": [{"delta": {"content": "检查文件", "reasoning_content": "不可公开", "tool_calls": [{"index": 0, "id": "tool-one", "function": {"name": "read_code_file", "arguments": '{"rel_path":'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"main.py"}' if valid else '"main.py"'}}]}, "finish_reason": "tool_calls"}]},
    ]
    stream = Stream([(f"data: {json.dumps(frame)}\n\n").encode() for frame in frames] + [b"data: [DONE]\n\n"], gate)
    async def handle(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
    models = LocalInference(ModelConfig(inference_mode="local", model_protocol="openai", model_endpoint="http://127.0.0.1:9999/v1", model_name="fixture", context_tokens=32000), transport=httpx.MockTransport(handle))
    async def delta(value):
        deltas.append(value)
    task = asyncio.create_task(models.complete_stream(None, {"messages": [{"role": "user", "content": "inspect"}]}, on_delta=delta))
    try:
        for _ in range(100):
            if deltas:
                break
            await asyncio.sleep(.005)
        assert deltas == ["检查文件"] and not task.done()
        gate.set()
        if valid:
            result = await task
            assert result["tool_calls"][0]["arguments"] == {"rel_path": "main.py"}
            assert result["usage"] == {}
        else:
            with pytest.raises(CloudError):
                await task
        assert stream.closed
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await models.close()


class StreamingServer(Server):
    def __init__(self):
        super().__init__()
        self.profiles[0]["supports_streaming"] = True
        self.release = asyncio.Event()
        self.stream = None

    async def model_stream(self, on_delta):
        self.stream = Stream([b"first", b"last"], self.release)
        try:
            async for chunk in self.stream:
                if chunk == b"first":
                    await on_delta("公开内容🙂")
            return {**response(text="公开内容🙂"), "usage": {}}
        finally:
            await self.stream.aclose()


@pytest.mark.parametrize("cancel", [False, True])
async def test_local_run_persists_partial_then_only_one_final_message(tmp_path, cancel):
    server = StreamingServer()
    app, client, _, root, body = await setup(tmp_path, server)
    try:
        created = (await client.post("/agent-runs", json={**body, "message": "你好"})).json()
        run_id = created["id"]
        for _ in range(200):
            events = (await client.get(f"/agent-runs/{run_id}/events")).json()["items"]
            if any(event["type"] == "model.output.delta" for event in events):
                break
            await asyncio.sleep(.01)
        assert any(event["type"] == "model.output.delta" for event in events)
        assert (await client.get(f"/agent-runs/{run_id}")).json()["status"] == "running"
        assert not [message for message in app.state.desktop.runtime.store.list("message", session_id=body["session_id"]) if message["role"] == "assistant"]
        if cancel:
            await client.post(f"/agent-runs/{run_id}/cancel")
        else:
            server.release.set()
        final = await until(client, run_id, TERMINAL)
        assert final["usage_complete"] is False and final["cost_usd"] is None
        events = app.state.desktop.runtime.store.events(run_id)
        deltas = [event for event in events if event["type"] == "model.output.delta"]
        assert [event["payload"]["delta"] for event in deltas] == ["公开内容🙂"]
        requested = next(event for event in events if event["type"] == "model.requested")
        terminal = next(event for event in events if event["type"] == (
            "model.output.interrupted" if cancel else "model.output.finished"
        ))
        assert deltas[0]["payload"]["attempt_id"] == requested["payload"]["attempt_id"] == terminal["payload"]["attempt_id"]
        assert deltas[0]["payload"]["message_id"] == requested["payload"]["attempt_id"] + ":default"
        assert deltas[0]["payload"]["phase"] is None
        messages = app.state.desktop.runtime.store.list("message", session_id=body["session_id"])
        assert len([item for item in messages if item["role"] == "assistant"]) == (0 if cancel else 1)
        assert server.stream.closed
        if not cancel:
            assert final["goal_outcome"] == "answered"
            assert terminal["payload"]["messages"] == [{"message_id": deltas[0]["payload"]["message_id"], "phase": "final_answer"}]
            completed = [event for event in app.state.desktop.runtime.store.events(run_id) if event["type"] == "model.completed"]
            assert completed[0]["payload"]["usage_complete"] is False
            assert completed[0]["payload"]["input_tokens"] is None
            stream = await client.get(f"/agent-runs/{run_id}/events/stream")
            frames = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
            assert frames[-1]["sequence"] == frames[-2]["sequence"] == final["last_event_sequence"]
    finally:
        await close(app, client)


class LegacyServer(Server):
    async def handle(self, request):
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(404)
        return await super().handle(request)


@pytest.mark.parametrize("supports_streaming", [False, True])
@pytest.mark.parametrize("progress", ["准备读取文件🙂", ""])
async def test_complete_response_publishes_public_text_once_per_attempt(tmp_path, supports_streaming, progress):
    server = LegacyServer()
    server.profiles[0]["supports_streaming"] = supports_streaming
    server.responses = [
        response(call("read_code_file", {"rel_path": "note.txt"}), text=progress),
        response(text="已完成只读检查"),
    ]
    app, client, _, root, body = await setup(tmp_path, server)
    try:
        (root / "note.txt").write_text("内容", encoding="utf-8")
        created = (await client.post("/agent-runs", json={**body, "permission_mode": "readonly"})).json()
        run_id = created["id"]
        final = await until(client, run_id, TERMINAL)
        assert final["status"] == "completed" and final["output"] == "已完成只读检查"
        events = app.state.desktop.runtime.store.events(run_id)
        attempts = [event["payload"]["attempt_id"] for event in events if event["type"] == "model.requested"]
        assert len(attempts) == len(set(attempts)) == 2
        for attempt, expected, has_tools in zip(attempts, (progress, "已完成只读检查"), (True, False), strict=True):
            output = [event for event in events if event["payload"].get("attempt_id") == attempt]
            deltas = [event for event in output if event["type"] == "model.output.delta"]
            assert [event["payload"]["delta"] for event in deltas] == ([expected] if expected else [])
            finished, = [event for event in output if event["type"] == "model.output.finished"]
            assert finished["payload"]["has_tool_calls"] is has_tools
            assert all(event["sequence"] < finished["sequence"] for event in deltas)
        replay = (await client.get(f"/agent-runs/{run_id}/events")).json()["items"]
        assert [event for event in replay if event["type"].startswith("model.output.")] == [
            event for event in events if event["type"].startswith("model.output.")
        ]
        assert sum(path == "/desktop/model/complete" for path, _ in server.calls) == 2
    finally:
        await close(app, client)


@pytest.mark.parametrize("invalid", ["oversized", "malformed", "too_many_tools"])
async def test_invalid_complete_response_never_publishes_public_text(tmp_path, invalid):
    server = Server()
    if invalid == "oversized":
        # 多字节正文验证 UTF-8 字节上限，不能只按字符数放行。
        raw = response(text="界" * (1024 * 1024 // 3 + 1))
    elif invalid == "malformed":
        raw = response(text=["不是字符串"])
    else:
        raw = response(*[
            {"id": f"read-{index}", "name": "read_code_file", "arguments": {"rel_path": "note.txt"}}
            for index in range(9)
        ], text="不应公开的无效响应")
    server.responses = [raw]
    app, client, _, _, body = await setup(tmp_path, server)
    try:
        created = (await client.post("/agent-runs", json={**body, "permission_mode": "readonly"})).json()
        run_id = created["id"]
        final = await until(client, run_id, TERMINAL)
        assert final["status"] == "failed" and final["error_code"] == "model_invalid_response"
        events = app.state.desktop.runtime.store.events(run_id)
        assert not any(event["type"] in {"model.output.delta", "model.output.finished", "tool.started"} for event in events)
        assert sum(event["type"] == "model.output.interrupted" for event in events) == 1
        assert sum(path == "/desktop/model/complete" for path, _ in server.calls) == 1
    finally:
        await close(app, client)


@pytest.mark.parametrize("invalid", ["oversized", "malformed"])
async def test_message_protocol_still_bounds_legacy_text_callback(tmp_path, invalid):
    server = Server()
    server.profiles[0]["supports_streaming"] = True
    app, client, _, _, body = await setup(tmp_path, server)

    async def broken_stream(token, profile, request, *, on_delta, on_message_delta):
        await on_delta("界" * (1024 * 1024 // 3 + 1) if invalid == "oversized" else ["无效正文"])
        raise AssertionError("无效正文应在回调边界被拒绝")

    app.state.desktop.cloud.complete_stream_messages = broken_stream
    try:
        created = await client.post("/agent-runs", json={**body, "permission_mode": "readonly"})
        run = await until(client, created.json()["id"], TERMINAL)
        assert run["status"] == "failed" and run["error_code"] == "model_invalid_response"
        events = app.state.desktop.runtime.store.events(run["id"])
        assert not any(event["type"] in {"model.output.delta", "model.output.finished", "tool.started"} for event in events)
        assert not app.state.desktop.runtime.store.run(run["id"]).get("response_attempt_id")
    finally:
        await close(app, client)


@pytest.mark.parametrize("cancel", [False, True])
async def test_direct_responses_preserves_message_phases_before_terminal(tmp_path, cancel):
    gate = asyncio.Event()
    commentary, final = message("正在检查", "commentary", "progress"), message("检查完成")
    stream = Stream([
        sse({"type": "response.output_item.added", "item": commentary},
            {"type": "response.output_text.delta", "item_id": "progress", "delta": "正在检查"},
            {"type": "response.reasoning_text.delta", "delta": "不应公开的推理"}),
        sse({"type": "response.output_item.added", "item": final},
            {"type": "response.output_text.delta", "item_id": "msg_1", "delta": "检查完成"},
            {"type": "response.completed", "response": responses_body(reasoning(), commentary, final)}),
    ], gate)
    async with desktop(tmp_path, handle=lambda _: httpx.Response(200, stream=stream)) as (models, app, client, accounts, calls):
        saved = await client.put("/model-providers/provider", json=configuration(api_format="responses"))
        assert saved.status_code == 200
        identifier = saved.json()["models"][0]["profile_id"]
        assert (await client.put("/model-providers/provider/runtime-secret", json={"secret": "fixture-provider-secret"})).status_code == 200
        models.catalog.data["profiles"][identifier]["supports_streaming"] = True
        models.catalog.save()
        root = tmp_path / "project"
        root.mkdir()
        project = (await client.post("/projects", json={"name": "阶段测试", "root_path": str(root)})).json()
        workspace = (await client.get(f"/projects/{project['id']}/workspaces")).json()[0]
        binding = {"project_id": project["id"], "workspace_id": workspace["id"]}
        session = (await client.post("/sessions", json={**binding, "title": "阶段测试", "kind": "coding"})).json()
        created = await client.post("/agent-runs", json={**binding, "session_id": session["id"], "message": "你好", "permission_mode": "readonly"})
        assert created.status_code == 201, created.text
        run_id = created.json()["id"]
        store = app.state.desktop.runtime.store
        try:
            for _ in range(100):
                events = store.events(run_id)
                deltas = [event["payload"] for event in events if event["type"] == "model.output.delta"]
                if deltas:
                    break
                await asyncio.sleep(.01)
            assert len(deltas) == 1 and deltas[0]["delta"] == "正在检查" and deltas[0]["phase"] == "commentary"
            attempt_id = deltas[0]["attempt_id"]
            assert deltas[0]["message_id"] == f"{attempt_id}:progress"
            assert store.run(run_id)["status"] == "running"
            if cancel:
                await client.post(f"/agent-runs/{run_id}/cancel")
            else:
                gate.set()
            result = await until(client, run_id, TERMINAL)
            events = store.events(run_id)
            assert len(calls) == 1 and accounts == [] and stream.closed
            assert OPAQUE not in json.dumps(events) and "不应公开的推理" not in json.dumps(events, ensure_ascii=False)
            if cancel:
                assert result["status"] == "cancelled" and result["output"] is None
                assert not store.run(run_id).get("response_attempt_id")
                assert any(event["type"] == "model.output.interrupted" and event["payload"]["attempt_id"] == attempt_id for event in events)
            else:
                assert result["status"] == "completed" and result["output"] == "检查完成"
                assert store.run(run_id)["response_attempt_id"] == attempt_id
                finished, = [event["payload"] for event in events if event["type"] == "model.output.finished"]
                assert finished["messages"] == [{"message_id": f"{attempt_id}:progress", "phase": "commentary"},
                                                  {"message_id": f"{attempt_id}:msg_1", "phase": "final_answer"}]
                assert [event["payload"]["delta"] for event in events if event["type"] == "model.output.delta"] == ["正在检查", "检查完成"]
        finally:
            gate.set()
