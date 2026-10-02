"""凭据范围、私有应答、超时与 HTTP 会话边界；仅使用内存宿主替身。"""
import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest

from private_agent_local.mcp_credentials import (
    CredentialTransport,
    McpCredentialError,
    McpCredentials,
    credential_reference,
    get_broker,
    validate_binding,
)

IDENTITY, SERVICE, VERSION = "a" * 64, "b" * 32, "c" * 32
BINDING = {"identity": IDENTITY, "service_id": SERVICE, "version": VERSION, "slot": "static"}


@pytest.mark.parametrize("change", [
    {"identity": "../other"}, {"service_id": "model-provider.test"}, {"version": "C" * 32},
    {"slot": "refresh_token"}, {"slot": {}}, {"account": "arbitrary"}, {"identity": None},
])
def test_binding_rejects_arbitrary_account_and_invalid_scope(change):
    with pytest.raises(McpCredentialError, match="范围无效"):
        validate_binding({**BINDING, **change})


def test_reference_binds_every_namespace_dimension():
    base = credential_reference(BINDING)
    assert base.startswith("secret://os-keyring/mcp/")
    for key, value in (("identity", "d" * 64), ("service_id", "e" * 32), ("version", "f" * 32), ("slot", "oauth")):
        assert credential_reference({**BINDING, key: value}) != base


@pytest.mark.asyncio
async def test_http_mode_never_falls_back_for_static_secrets_and_oauth_is_session_only(tmp_path):
    first, second = McpCredentials(IDENTITY), McpCredentials(IDENTITY)
    assert not first.persistent
    for operation in (first.binding(SERVICE, VERSION, "static"), first.get(SERVICE, VERSION, "static"),
                      first.set(SERVICE, VERSION, "static", "synthetic-static"), first.delete(SERVICE, VERSION, "static")):
        with pytest.raises(McpCredentialError) as error:
            await operation
        assert error.value.code == "persistent_credentials_unavailable"
    reference = await first.set(SERVICE, VERSION, "oauth", "synthetic-oauth")
    assert reference.startswith("secret://session/")
    assert await first.get(SERVICE, VERSION, "oauth") == "synthetic-oauth"
    assert await second.get(SERVICE, VERSION, "oauth") is None
    await first.delete(SERVICE, VERSION, "oauth")
    assert await first.get(SERVICE, VERSION, "oauth") is None
    await first.set(SERVICE, VERSION, "oauth", "synthetic-oauth")
    first.close()
    assert first._session == {}
    with pytest.raises(McpCredentialError, match="已关闭"):
        await first.get(SERVICE, VERSION, "oauth")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_private_transport_roundtrip_only_uses_bound_references():
    frames, values = [], {}

    async def send(frame):
        frames.append(frame)
        params = frame["params"]
        reference = credential_reference(params["binding"])
        result = {}
        if params["operation"] == "set":
            values[reference] = params["value"]
            result = {"reference": reference}
        elif params["operation"] == "get":
            result = {"value": values.get(reference)}
        elif params["operation"] == "delete":
            values.pop(reference, None)
        bridge.receive({"id": frame["id"], "method": "mcp_credential_result", "result": result})

    bridge = CredentialTransport(send)
    broker = McpCredentials(IDENTITY, bridge)
    assert broker.persistent
    assert await broker.binding(SERVICE, VERSION, "static") == BINDING
    reference = await broker.set(SERVICE, VERSION, "static", "synthetic-value")
    assert reference == credential_reference(BINDING)
    assert await broker.get(SERVICE, VERSION, "static") == "synthetic-value"
    assert await broker.get(SERVICE, "d" * 32, "static") is None
    await broker.delete(SERVICE, VERSION, "static")
    assert await broker.get(SERVICE, VERSION, "static") is None
    assert all(frame["method"] == "mcp_credential" for frame in frames)
    assert bridge.pending == {}


@pytest.mark.asyncio
async def test_cancel_timeout_close_and_late_reply_do_not_leak_pending_requests():
    frames = []

    async def send(frame):
        frames.append(frame)

    bridge = CredentialTransport(send, timeout=0.02)
    with pytest.raises(McpCredentialError) as error:
        await bridge.request("get", BINDING)
    assert error.value.code == "credential_timeout" and not bridge.pending
    assert bridge.receive({"id": frames[-1]["id"], "method": "mcp_credential_result", "result": {"value": "late-secret"}})
    task = asyncio.create_task(bridge.request("get", BINDING))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not bridge.pending
    task = asyncio.create_task(bridge.request("get", BINDING))
    await asyncio.sleep(0)
    bridge.close()
    with pytest.raises(McpCredentialError) as error:
        await task
    assert error.value.code == "credential_transport_closed" and not bridge.pending


@pytest.mark.asyncio
async def test_native_error_and_invalid_reply_never_echo_a_secret():
    async def send(frame):
        bridge.receive({"id": frame["id"], "method": "mcp_credential_result", "error": "synthetic-secret-in-error"})

    bridge = CredentialTransport(send)
    with pytest.raises(McpCredentialError) as error:
        await bridge.request("get", BINDING)
    assert error.value.code == "credential_store_failed"
    assert "synthetic-secret" not in str(error.value)
    assert not bridge.receive({"id": "ordinary-request", "done": True})


def test_lazy_broker_is_identity_bound_and_reused(tmp_path):
    owner = SimpleNamespace(authority="fixture://local", owner_id=1, store=SimpleNamespace(path=tmp_path / "state.sqlite3"))
    broker = get_broker(owner)
    assert get_broker(owner) is broker
    other = SimpleNamespace(authority="fixture://local", owner_id=2, store=owner.store)
    assert get_broker(other).identity != broker.identity


@pytest.mark.asyncio
async def test_real_private_pipe_keeps_oauth_exchange_out_of_public_response(tmp_path):
    script = '''
import asyncio,json,sys
from types import SimpleNamespace
from fastapi import FastAPI
from private_agent_local.ipc import serve
from private_agent_local.mcp_credentials import McpCredentials
app=FastAPI()
app.state.desktop=SimpleNamespace()
@app.get('/work')
async def work():
    broker=McpCredentials('a'*64, app.state.desktop.mcp_credential_transport)
    await broker.set('b'*32,'c'*32,'oauth','synthetic-private-token')
    value=await broker.get('b'*32,'c'*32,'oauth')
    await broker.delete('b'*32,'c'*32,'oauth')
    return {'configured':value=='synthetic-private-token'}
asyncio.run(serve(app,'fixture-nonce-'*4,sys.stdin.buffer,sys.stdout.buffer))
'''
    process = await asyncio.create_subprocess_exec(sys.executable, "-B", "-c", script, cwd=tmp_path,
        env=dict(os.environ), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    public, private, values = [], [], {}
    try:
        process.stdin.write(json.dumps({"id": "public-1", "method": "request", "params": {"path": "/work"}}).encode() + b"\n")
        await process.stdin.drain()
        async with asyncio.timeout(15):
            while True:
                raw = await process.stdout.readline()
                assert raw
                frame = json.loads(raw)
                if frame.get("method") == "mcp_credential":
                    private.append(frame)
                    params = frame["params"]
                    key = credential_reference(params["binding"])
                    result = {}
                    if params["operation"] == "set":
                        values[key] = params["value"]
                        result = {"reference": key}
                    elif params["operation"] == "get":
                        result = {"value": values.get(key)}
                    else:
                        values.pop(key, None)
                    process.stdin.write(json.dumps({"id": frame["id"], "method": "mcp_credential_result", "result": result}).encode() + b"\n")
                    await process.stdin.drain()
                else:
                    public.append(frame)
                    if frame.get("done"):
                        break
        assert [frame["params"]["operation"] for frame in private] == ["set", "get", "delete"]
        assert not values
        assert "synthetic-private-token" not in json.dumps(public)
        assert json.loads("".join(frame.get("data", "") for frame in public)) == {"configured": True}
    finally:
        process.stdin.write(b'{"method":"shutdown"}\n')
        await process.stdin.drain()
        try:
            await asyncio.wait_for(process.wait(), 10)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        assert process.returncode == 0, (await process.stderr.read()).decode(errors="replace")
