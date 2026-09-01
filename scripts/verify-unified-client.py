"""在独立目录验证打包运行时；模型是回环测试替身，不读取真实账号或项目。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import shutil
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx


async def verify(bundle: Path, work: Path, model_mode: str = "service") -> dict:
    work.mkdir(parents=True, exist_ok=True)
    area = Path(tempfile.mkdtemp(prefix="packaged-runtime-", dir=work)).resolve()
    staged, project = area / "binaries", area / "project"
    staged.mkdir()
    project.mkdir()
    for name in ("private-agent-local.exe", "exec-host.exe", "exec-host.sha256"):
        shutil.copyfile(bundle / name, staged / name)
    host_digest = hashlib.sha256((staged / "exec-host.exe").read_bytes()).hexdigest()
    assert (staged / "exec-host.sha256").read_text().strip() == host_digest
    (project / "test_fixture.py").write_text('from pathlib import Path\ndef test_file():\n    assert Path("result.txt").read_text(encoding="utf-8") == "本机验证"\n', encoding="utf-8")
    (project / "fixture.py").write_text('print("full-access-script-ok")\n', encoding="utf-8")
    replies: list[dict] = []

    fixture_token = secrets.token_urlsafe(48)
    active = False
    server_calls = []
    profile_id = "server-profile" if model_mode == "service" else "local-model"
    protocol = "ollama" if model_mode == "ollama" else "openai"

    class AccountFixture(BaseHTTPRequestHandler):
        def reply(self, data, status=200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            return active and self.headers.get("Authorization") == "Bearer " + fixture_token

        def do_GET(self):
            server_calls.append(self.path)
            if self.path in {"/api/tags", "/v1/models"}:
                assert active and self.headers.get("Authorization") is None, "模型发现不得发送账号令牌"
                self.reply({"models": [{"name": "fixture-model"}]} if self.path == "/api/tags"
                           else {"data": [{"id": "fixture-model"}]})
            elif not self.authorized():
                self.reply({"detail": "fixture unauthorized"}, 401)
            elif self.path == "/auth/me":
                self.reply({"id": 7, "username": "fixture"})
            elif self.path == "/agent-model-profiles?enabled_only=true":
                self.reply([{"id": profile_id, "model_name": "fixture-model", "context_tokens": 4096,
                             "provider": protocol, "provider_id": "fixture-provider", "is_local": model_mode != "service",
                             "enabled": True, "is_default": True}])
            elif self.path == "/model-providers":
                self.reply([{"id": "fixture-provider", "protocol": protocol, "enabled": True,
                             "api_format": "ollama_chat" if protocol == "ollama" else "chat_completions",
                             "base_url": "https://model.example.invalid/v1" if model_mode == "service" else model_endpoint,
                             "api_key_configured": model_mode == "service",
                             "models": [{"profile_id": profile_id, "model_id": "fixture-model"}]}])
            else:
                self.reply({"detail": "fixture route missing"}, 404)

        def do_POST(self):
            nonlocal active
            server_calls.append(self.path)
            size = int(self.headers.get("content-length", "0"))
            if not 0 < size <= 2 * 1024 * 1024:
                self.reply({"detail": "fixture invalid body"}, 400)
                return
            payload = json.loads(self.rfile.read(size))
            if self.path == "/auth/login":
                if payload != {"identifier": "fixture", "password": "fixture-password"}:
                    self.reply({"detail": "fixture invalid credentials"}, 401)
                    return
                active = True
                self.reply({"access_token": fixture_token, "user": {"id": 7}, "token_type": "bearer"})
            elif self.path in {"/api/chat", "/v1/chat/completions"}:
                assert active and self.headers.get("Authorization") is None, "账号令牌不得发送到本机模型"
                assert replies and payload["model"] == "fixture-model"
                result = replies.pop(0)
                calls = result["tool_calls"]
                if self.path == "/api/chat":
                    self.reply({"model": "fixture-model", "message": {"role": "assistant", "content": result["text"],
                        "tool_calls": [{"id": c["id"], "function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls]},
                        "done": True, "prompt_eval_count": 1000, "eval_count": 25})
                else:
                    self.reply({"model": "fixture-model", "choices": [{"message": {"role": "assistant", "content": result["text"],
                        "tool_calls": [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}} for c in calls]},
                        "finish_reason": "tool_calls" if calls else "stop"}], "usage": {"prompt_tokens": 1000, "completion_tokens": 25,
                        "prompt_tokens_details": {"cached_tokens": 200}}})
            elif not self.authorized():
                self.reply({"detail": "fixture unauthorized"}, 401)
            elif self.path == "/auth/logout":
                active = False
                self.reply({"logged_out": True})
            elif self.path == "/desktop/model/complete" and replies:
                assert payload["model_profile_id"] == "server-profile"
                assert "messages" in payload["request"]
                self.reply(replies.pop(0))
            else:
                self.reply({"detail": "fixture route missing"}, 404)

        def log_message(self, *_args):
            pass

    def model_reply(text="", calls=None):
        return {"provider": "fixture-server", "model": "fixture-model", "text": text, "tool_calls": calls or [],
                "usage": {"input_tokens": 1000, "output_tokens": 25, "cached_tokens": 200}}

    def tool(name, arguments):
        return model_reply(calls=[{"id": str(uuid.uuid4()), "name": name, "arguments": arguments}])

    def finish():
        return model_reply(text="fixture complete")

    server = ThreadingHTTPServer(("127.0.0.1", 0), AccountFixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server_origin = f"http://127.0.0.1:{server.server_port}"
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(PATH=str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", ""), PRIVATEAGENT_LOCAL_NONCE=secrets.token_urlsafe(48))
    model_endpoint = server_origin + ("/v1" if model_mode == "openai" else "")
    # 与桌面入口一致，仅通过服务器模型配置自动决定推理位置。
    model_config = {"inference_mode": "auto"}
    process = None
    token = None
    try:
        process = await asyncio.create_subprocess_exec(str(staged / "private-agent-local.exe"), "--stdio", "--data-dir", str(area / "records"),
            "--server", server_origin, "--model-json", json.dumps(model_config), cwd=area, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0))

        async def request(path, method="GET", body=None, expected_status=None):
            identity = str(uuid.uuid4())
            headers = {"content-type": "application/json"}
            if token:
                headers["authorization"] = f"Bearer {token}"
            frame = {"id": identity, "method": "request", "params": {"path": path, "method": method, "headers": headers,
                "body": json.dumps(body, ensure_ascii=False) if body is not None else ""}}
            process.stdin.write((json.dumps(frame, ensure_ascii=False) + "\n").encode())
            await process.stdin.drain()
            status, chunks = None, []
            async with asyncio.timeout(45):
                while True:
                    line = await process.stdout.readline()
                    assert line, "打包进程意外退出"
                    event = json.loads(line)
                    assert event.get("id") == identity and not event.get("error"), "私有协议错误"
                    status = event.get("status", status)
                    chunks.append(event.get("data", ""))
                    if event.get("done"):
                        break
            assert status is not None and (status == expected_status if expected_status else 200 <= status < 300), f"本机接口失败：{path}，状态 {status}"
            return json.loads("".join(chunks))

        async def terminal(run_id, *, approve=False):
            async with asyncio.timeout(90):
                while True:
                    run = await request(f"/agent-runs/{run_id}")
                    if run["status"] == "waiting_approval" and approve:
                        approvals = await request(f"/agent-runs/{run_id}/approvals")
                        for approval in approvals:
                            if approval["status"] == "pending":
                                await request(f"/agent-runs/{run_id}/approvals/{approval['id']}/approve", "POST")
                    if run["status"] not in {"created", "running", "waiting_approval"}:
                        return run
                    await asyncio.sleep(0.1)

        assert (await request("/health"))["mode"] == "desktop-local"
        await request("/auth/local", "POST", expected_status=404)
        await request("/auth/login", "POST", expected_status=404)
        await request("/projects", expected_status=401)
        async with httpx.AsyncClient(base_url=server_origin, timeout=15, trust_env=False) as account:
            login = await account.post("/auth/login", json={"identifier": "fixture", "password": "fixture-password"})
            assert login.status_code == 200
            token = login.json()["access_token"]
        assert (await request("/identity", "POST"))["ready"]
        if model_mode != "service":
            discovered = await request("/local-models/discover", "POST", {"protocol": protocol, "base_url": model_endpoint})
            assert discovered["models"][0]["model_id"] == "fixture-model"
        created = await request("/projects", "POST", {"name": "打包隔离验证", "root_path": str(project)})
        workspace = (await request(f"/projects/{created['id']}/workspaces"))[0]
        binding = {"project_id": created["id"], "workspace_id": workspace["id"]}
        session = await request("/sessions", "POST", {**binding, "title": "隔离验收"})
        binding.update(session_id=session["id"], message="fixture", model_profile_id=profile_id)
        replies.extend([tool("write_project_file", {"rel_path": "result.txt", "content": "本机验证"}),
            tool("run_project_command", {"command": "python -m pytest"}),
            tool("run_powershell_command", {"command": "Get-ChildItem", "arguments": ["-LiteralPath", ".", "-Name"]}),
            finish()])
        run = await request("/agent-runs", "POST", {**binding, "permission_mode": "workspace"})
        assert (await terminal(run["id"], approve=True))["status"] == "completed"
        executions = await request(f"/agent-runs/{run['id']}/executions")
        assert len(executions) == 3 and all(e["status"] == "completed" for e in executions)
        assert (project / "result.txt").read_text(encoding="utf-8") == "本机验证"
        command_output = executions[1]["output"]
        assert command_output["returncode"] == 0 and "1 passed" in command_output["stdout"]
        assert command_output["execution_host_sha256"] == host_digest
        powershell_output = executions[2]["output"]
        assert powershell_output["returncode"] == 0 and "fixture.py" in powershell_output["stdout"]
        assert powershell_output["args"] == ["powershell", "Get-ChildItem", "-LiteralPath", ".", "-Name"]
        assert not await request(f"/agent-runs/{run['id']}/approvals")
        replies.extend([tool("run_project_command", {"command": "python -m pytest"}), finish()])
        confirm_run = await request("/agent-runs", "POST", {**binding, "permission_mode": "confirm"})
        assert (await terminal(confirm_run["id"], approve=True))["status"] == "completed"
        approvals = await request(f"/agent-runs/{confirm_run['id']}/approvals")
        assert len(approvals) == 1 and approvals[0]["status"] == "consumed"
        budget = await request(f"/sessions/{session['id']}/context-budget?model_profile_id={profile_id}")
        assert budget["source"] == "provider_usage" and budget["used_tokens"] == 1000 and budget["max_context_tokens"] == 4096
        assert budget["cache_hit_scope"] == "session"
        if model_mode != "ollama":
            assert budget["cache_hit_percent"] == 20.0
        grant = await request(f"/sessions/{session['id']}/full-access-grant", "POST", {})
        replies.extend([tool("run_project_command", {"command": "python fixture.py"}), finish()])
        run = await request("/agent-runs", "POST", {**binding, "permission_mode": "full_access"})
        assert (await terminal(run["id"]))["status"] == "completed"
        execution = (await request(f"/agent-runs/{run['id']}/executions"))[0]
        assert execution["status"] == "completed" and execution["output"]["stdout"].strip() == "full-access-script-ok"
        assert not await request(f"/agent-runs/{run['id']}/approvals")
        # 只破坏隔离副本的校验文件，验证打包宿主校验失败时不会执行命令。
        (staged / "exec-host.sha256").write_text("0" * 64, encoding="ascii")
        replies.extend([tool("run_project_command", {"command": "python fixture.py"}), finish()])
        run = await request("/agent-runs", "POST", {**binding, "permission_mode": "full_access"})
        await terminal(run["id"])
        execution = (await request(f"/agent-runs/{run['id']}/executions"))[0]
        assert execution["status"] == "failed" and "SHA-256" in execution["error_message"] and execution["output"] is None
        assert (await request(f"/full-access-grants/{grant['grant_id']}", "DELETE"))["revoked"]
        exported = await request("/local-history/export")
        assert len(exported["records"]["runs"]) == 4 and exported["records"]["run_steps"]
        assert not replies
        await request("/identity/clear", "POST")
        async with httpx.AsyncClient(base_url=server_origin, timeout=15, trust_env=False) as account:
            logout = await account.post("/auth/logout", json={}, headers={"Authorization": "Bearer " + token})
            assert logout.status_code == 200
        await request("/projects", expected_status=401)
        assert server_calls.count("/auth/login") == 1 and server_calls.count("/auth/logout") == 1
        assert "/auth/me" in server_calls
        model_path = "/desktop/model/complete" if model_mode == "service" else "/api/chat" if model_mode == "ollama" else "/v1/chat/completions"
        assert model_path in server_calls
        assert "/model-providers" in server_calls and "/agent-model-profiles?enabled_only=true" in server_calls
        if model_mode != "service":
            assert "/desktop/model/complete" not in server_calls
        return {"model_mode": model_mode, "inference_mode": "auto", "server_login": True, "server_logout": True, "local_account_removed": True,"passed": True, "work_dir": str(area), "file_write": True, "workspace_auto_approval": True, "manual_command_approval": True, "powershell_command": True,
                "full_access_script": True, "context_usage": budget["used_tokens"], "tampered_host_blocked": True,
                "history_export_runs": 4, "sandbox_available": command_output["sandbox_available"], "real_model_called": False}
    finally:
        if process is not None:
            if process.returncode is None:
                process.stdin.write(b'{"method":"shutdown"}\n')
                await process.stdin.drain()
                try:
                    await asyncio.wait_for(process.wait(), 15)
                except TimeoutError:
                    process.kill()
                    await process.wait()
                    raise AssertionError("打包运行时未能正常关闭") from None
            assert process.returncode == 0, "打包运行时异常退出"
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--model-mode", choices=["service", "ollama", "openai"], default="service")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(verify(args.bundle.resolve(), args.work_dir.resolve(), args.model_mode)), ensure_ascii=False, indent=2))
