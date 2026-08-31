"""真实子进程验证私有管道、鉴权和流式关闭；不调用真实模型。"""
import asyncio
import json
import os
import sys
import uuid
from contextlib import asynccontextmanager

import pytest

from private_agent_local.ipc import request_scope

NONCE = "isolated-pipe-fixture-" * 3


@asynccontextmanager
async def runtime_pipe(tmp_path):
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "private_agent_local.entry", "--stdio",
        "--connection-json", '{"mode":"local"}', "--data-dir", str(tmp_path / "records"),
        cwd=tmp_path, env={**os.environ, "PRIVATEAGENT_LOCAL_NONCE": NONCE},
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        yield process
    finally:
        if process.returncode is None:
            process.stdin.write(b'{"method":"shutdown"}\n')
            await process.stdin.drain()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                process.kill()
                await process.wait()
                raise
        assert process.returncode == 0, (await process.stderr.read()).decode(errors="replace")


async def request(process, path, *, method="GET", body=None, token=None):
    request_id = str(uuid.uuid4())
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    frame = {"id": request_id, "method": "request", "params": {"path": path, "method": method,
             "headers": headers, "body": json.dumps(body, ensure_ascii=False) if body is not None else ""}}
    process.stdin.write((json.dumps(frame, ensure_ascii=False) + "\n").encode())
    await process.stdin.drain()
    frames = []
    async with asyncio.timeout(10):
        while True:
            data = await process.stdout.readline()
            assert data, (await process.stderr.read()).decode(errors="replace")
            item = json.loads(data)
            assert item["id"] == request_id
            frames.append(item)
            if item.get("done") or item.get("error"):
                break
    return frames


def content(frames):
    assert frames[-1].get("done"), frames
    return json.loads("".join(f.get("data", "") for f in frames))


@pytest.mark.asyncio
async def test_private_pipe_auth_unicode_and_run_event_stream(tmp_path):
    async with runtime_pipe(tmp_path) as process:
        health = await request(process, "/health")
        assert health[0]["status"] == 200
        assert content(health)["mode"] == "desktop-local"
        assert (await request(process, "/projects"))[0]["status"] == 401
        auth = content(await request(process, "/auth/local", method="POST"))
        token = auth["access_token"]
        root = tmp_path / "项目"
        root.mkdir()
        project = content(await request(process, "/projects", method="POST", body={"name": "管道项目", "root_path": str(root)}, token=token))
        workspace = content(await request(process, f"/projects/{project['id']}/workspaces", token=token))[0]
        binding = {"project_id": project["id"], "workspace_id": workspace["id"]}
        session = content(await request(process, "/sessions", method="POST", body={**binding, "title": "测试中文"}, token=token))
        run = content(await request(process, "/agent-runs", method="POST", body={**binding, "session_id": session["id"], "message": "无模型配置", "permission_mode": "readonly"}, token=token))
        frames = await request(process, f"/agent-runs/{run['id']}/events/stream", token=token)
        assert frames[0]["status"] == 200, frames
        text = "".join(f.get("data", "") for f in frames)
        assert "run.failed" in text and "run.terminal" in text
        assert frames[-1]["done"]
        assert len(list((tmp_path / "records").glob("*/projects.sqlite3"))) == 1


@pytest.mark.parametrize("params", [
    {"path": "https://server.example/projects"}, {"path": "//server/projects"},
    {"path": "/internal/shutdown"}, {"path": "/health", "headers": {"host": "other"}},
    {"path": "/health", "headers": {"authorization": "x\r\nHost: other"}},
    {"path": "/health", "method": "CONNECT"}, {"path": "/projects", "body": "文" * 800000},
])
def test_pipe_rejects_untrusted_request_boundaries(params):
    with pytest.raises(ValueError):
        request_scope({"params": params}, NONCE)
