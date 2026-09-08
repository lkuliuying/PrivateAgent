"""S4 模型增量协议：旧服务协商、分帧工具、断流和本机唯一事件源。"""
import asyncio
import json

import httpx
import pytest
from test_local_executor import Server, close, response, setup, until

from private_agent_local.cloud import Cloud, CloudError
from private_agent_local.connections import ModelConfig
from private_agent_local.local_models import LocalInference
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


async def test_old_server_selects_complete_before_any_delta():
    paths, deltas = [], []

    async def handle(request):
        paths.append(request.url.path)
        if request.url.path.endswith("capabilities"):
            return httpx.Response(404)
        return httpx.Response(200, json=response(text="旧服务回答"))

    cloud = Cloud("https://fixture.test", transport=httpx.MockTransport(handle))
    try:
        async def delta(value):
            deltas.append(value)
        result = await cloud.complete_stream("fixture", None, {"messages": []}, on_delta=delta)
        assert result["text"] == "旧服务回答" and deltas == []
        assert paths == ["/desktop/model/capabilities", "/desktop/model/complete"]
    finally:
        await cloud.close()


@pytest.mark.parametrize("failure", ["missing_terminal", "wrong_attempt", "wrong_sequence", "wrong_text", "error"])
async def test_published_stream_failure_never_replays(failure):
    calls, deltas, streams = [], [], []

    async def handle(request):
        calls.append(request.url.path)
        if request.url.path.endswith("capabilities"):
            return httpx.Response(200, json={"stream_protocol": "1.0"})
        attempt = json.loads(request.content)["attempt_id"]
        frames = [{"type": "text.delta", "sequence": 1, "attempt_id": attempt, "delta": "公开🙂"}]
        if failure != "missing_terminal":
            frames.append({"type": "completed", "sequence": 3 if failure == "wrong_sequence" else 2,
                           "attempt_id": "wrong" if failure == "wrong_attempt" else attempt,
                           "response": response(text="错误" if failure == "wrong_text" else "公开🙂")})
        if failure == "error":
            frames[-1] = {"type": "error", "sequence": 2, "attempt_id": attempt, "code": "provider_unavailable"}
        raw = b"".join((json.dumps(frame, ensure_ascii=False) + "\n").encode() for frame in frames)
        stream = Stream([raw[:9], raw[9:31], raw[31:]])
        streams.append(stream)
        return httpx.Response(200, headers={"content-type": "application/x-ndjson"}, stream=stream)

    cloud = Cloud("https://fixture.test", transport=httpx.MockTransport(handle))
    async def delta(value):
        deltas.append(value)
    try:
        with pytest.raises(CloudError, match="中断"):
            await cloud.complete_stream("fixture", "model", {}, on_delta=delta)
        assert deltas == ["公开🙂"]
        assert calls.count("/desktop/model/stream") == 1 and "/desktop/model/complete" not in calls
        assert streams[0].closed
    finally:
        await cloud.close()


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

    async def handle(self, request):
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(200, json={"stream_protocol": "1.0"})
        if request.url.path.endswith("/stream"):
            attempt = json.loads(request.content)["attempt_id"]
            frames = [{"type": "text.delta", "attempt_id": attempt, "sequence": 1, "delta": "公开内容🙂"},
                      {"type": "completed", "attempt_id": attempt, "sequence": 2, "response": {**response(text="公开内容🙂"), "usage": {}}}]
            self.stream = Stream([(json.dumps(frame, ensure_ascii=False) + "\n").encode() for frame in frames], self.release)
            return httpx.Response(200, headers={"content-type": "application/x-ndjson"}, stream=self.stream)
        return await super().handle(request)


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
        messages = app.state.desktop.runtime.store.list("message", session_id=body["session_id"])
        assert len([item for item in messages if item["role"] == "assistant"]) == (0 if cancel else 1)
        assert server.stream.closed
        if not cancel:
            assert final["goal_outcome"] == "answered"
            completed = [event for event in app.state.desktop.runtime.store.events(run_id) if event["type"] == "model.completed"]
            assert completed[0]["payload"]["usage_complete"] is False
            assert completed[0]["payload"]["input_tokens"] is None
            stream = await client.get(f"/agent-runs/{run_id}/events/stream")
            frames = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
            assert frames[-1]["sequence"] == frames[-2]["sequence"] == final["last_event_sequence"]
    finally:
        await close(app, client)
