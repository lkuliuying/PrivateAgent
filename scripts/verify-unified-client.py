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


async def verify(bundle: Path, work: Path) -> dict:
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

    class ModelFixture(BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers.get("content-length", "0"))
            if self.path != "/v1/chat/completions" or not 0 < size <= 2 * 1024 * 1024 or not replies:
                self.send_error(400)
                return
            json.loads(self.rfile.read(size))
            message = replies.pop(0)
            body = json.dumps({"id": "fixture", "model": "fixture-model", "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 25, "prompt_tokens_details": {"cached_tokens": 200}}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    def tool(name, arguments):
        return {"role": "assistant", "content": "", "tool_calls": [{"id": str(uuid.uuid4()), "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]}

    def finish():
        return {"role": "assistant", "content": "fixture complete"}

    server = ThreadingHTTPServer(("127.0.0.1", 0), ModelFixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    profile = {"mode": "local", "model_protocol": "openai", "model_endpoint": f"http://127.0.0.1:{server.server_port}/v1",
               "model_name": "fixture-model", "context_tokens": 4096}
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(PATH=str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", ""), PRIVATEAGENT_LOCAL_NONCE=secrets.token_urlsafe(48))
    process = None
    token = None
    try:
        process = await asyncio.create_subprocess_exec(str(staged / "private-agent-local.exe"), "--stdio", "--data-dir", str(area / "records"),
            "--connection-json", json.dumps(profile), cwd=area, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0))

        async def request(path, method="GET", body=None):
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
            assert status is not None and 200 <= status < 300, f"本机接口失败：{path}，状态 {status}"
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
        token = (await request("/auth/local", "POST"))["access_token"]
        created = await request("/projects", "POST", {"name": "打包隔离验证", "root_path": str(project)})
        workspace = (await request(f"/projects/{created['id']}/workspaces"))[0]
        binding = {"project_id": created["id"], "workspace_id": workspace["id"]}
        session = await request("/sessions", "POST", {**binding, "title": "隔离验收"})
        binding.update(session_id=session["id"], message="fixture", model_profile_id="local-model")
        replies.extend([tool("write_project_file", {"rel_path": "result.txt", "content": "本机验证"}),
            tool("run_project_command", {"command": "python -m pytest"}), finish()])
        run = await request("/agent-runs", "POST", {**binding, "permission_mode": "workspace"})
        assert (await terminal(run["id"], approve=True))["status"] == "completed"
        executions = await request(f"/agent-runs/{run['id']}/executions")
        assert len(executions) == 2 and all(e["status"] == "completed" for e in executions)
        assert (project / "result.txt").read_text(encoding="utf-8") == "本机验证"
        command_output = executions[1]["output"]
        assert command_output["returncode"] == 0 and "1 passed" in command_output["stdout"]
        assert command_output["execution_host_sha256"] == host_digest
        approvals = await request(f"/agent-runs/{run['id']}/approvals")
        assert len(approvals) == 1 and approvals[0]["status"] == "consumed"
        budget = await request(f"/sessions/{session['id']}/context-budget?model_profile_id=local-model")
        assert budget["source"] == "provider_usage" and budget["used_tokens"] == 1000 and budget["max_context_tokens"] == 4096
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
        assert len(exported["records"]["runs"]) == 3 and exported["records"]["run_steps"]
        assert not replies
        return {"passed": True, "work_dir": str(area), "file_write": True, "manual_command_approval": True,
                "full_access_script": True, "context_usage": budget["used_tokens"], "tampered_host_blocked": True,
                "history_export_runs": 3, "sandbox_available": command_output["sandbox_available"], "real_model_called": False}
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
    args = parser.parse_args()
    print(json.dumps(asyncio.run(verify(args.bundle.resolve(), args.work_dir.resolve())), ensure_ascii=False, indent=2))
