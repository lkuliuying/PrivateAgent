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
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from coding_acceptance_evidence import digest, write_json
from coding_acceptance_schema import plain_path
from run_coding_validation import isolated_environment, new_directory


async def verify(bundle: Path, work: Path, model_mode: str = "service") -> dict:
    bundle, work = plain_path(bundle), plain_path(work, must_exist=False)
    work.mkdir(parents=True, exist_ok=True)
    area = new_directory(work, "packaged-runtime")
    staged, project = area / "binaries", area / "project"
    staged.mkdir()
    project.mkdir()
    for name in ("private-agent-local.exe", "exec-host.exe", "exec-host.sha256"):
        shutil.copyfile(plain_path(bundle / name), staged / name)
    host_digest = hashlib.sha256((staged / "exec-host.exe").read_bytes()).hexdigest()
    assert (staged / "exec-host.sha256").read_text().strip() == host_digest
    (project / "tests").mkdir()
    (project / "tests" / "test_fixture.py").write_text('from pathlib import Path\ndef test_file():\n    assert Path("result.txt").read_text(encoding="utf-8") == "本机验证"\n', encoding="utf-8")
    (project / "fixture.py").write_text('print("full-access-script-ok")\n', encoding="utf-8")
    # 测试配置随独立项目提供，pytest 不应向沙箱外搜索仓库配置和 conftest。
    (project / "pytest.ini").write_text("[pytest]\ntestpaths = tests\naddopts = --noconftest --confcutdir=tests --import-mode=importlib -p no:cacheprovider\n", encoding="utf-8")
    replies: list[dict] = []

    fixture_token = secrets.token_urlsafe(48)
    active = True
    server_calls = []
    protocol = "ollama" if model_mode == "ollama" else "openai"
    correlations, run_ids = [], []

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
            elif self.path in {"/agent-model-profiles?enabled_only=true", "/model-providers"}:
                self.reply({"detail": "account server does not provide models"}, 410)
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
            elif self.path.startswith("/desktop/model/"):
                self.reply({"detail": "server model execution disabled"}, 410)
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
    env = isolated_environment(area)
    for key, relative in (("USERPROFILE", "home"), ("HOME", "home"),
                          ("APPDATA", "home/AppData/Roaming"), ("LOCALAPPDATA", "home/AppData/Local")):
        directory = area / relative
        directory.mkdir(parents=True, exist_ok=True)
        env[key] = str(directory)
    if os.name == "nt":
        from private_agent_local.windows_process import profile_environment

        # AppContainer 临时目录需要系统位置；仅定位，不读取该目录中的用户设置。
        env["LOCALAPPDATA"] = profile_environment()["LOCALAPPDATA"]
    (area / "tmp").mkdir()
    env.update(PATH=str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", ""), PRIVATEAGENT_LOCAL_NONCE=secrets.token_urlsafe(48))
    model_endpoint = server_origin + ("/v1" if protocol == "openai" else "")
    # service 保留历史标签，实际使用本机目录和直连 OpenAI 回环替身。
    model_config = {"inference_mode": "auto"}
    process = None
    job = None
    token = None
    result = {"passed": False, "evidence_kind": "packaged_ipc_fixture", "real_model_called": False,
              "native_desktop_verified": False, "installed_copy_verified": False, "work_dir": str(area),
              "model_mode": model_mode, "wire_protocol": protocol, "connection_mode": "fixture",
              "artifacts_sha256": {name: digest(staged / name) for name in ("private-agent-local.exe", "exec-host.exe")}}
    try:
        process = await asyncio.create_subprocess_exec(str(staged / "private-agent-local.exe"), "--stdio", "--data-dir", str(area / "records"),
            "--model-json", json.dumps(model_config), cwd=area, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0))
        if os.name == "nt":
            from private_agent_local.windows_process import ProcessJob

            job = ProcessJob()
            job.assign(process.pid)
        result["process_id"] = process.pid

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
            value = json.loads("".join(chunks))
            if method not in {"GET", "HEAD"}:
                correlations.append({"ipc_request_id": identity, "path": path, "method": method, "status": status,
                                     "result_ids": {key: value[key] for key in ("id", "run_id", "result_run_id")
                                                    if isinstance(value, dict) and key in value}})
            if path == "/agent-runs" and method == "POST" and isinstance(value, dict) and "id" in value:
                run_ids.append(value["id"])
            return value

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
        token = (await request("/identity/local", "POST"))["access_token"]
        provider = await request("/model-providers/fixture-provider", "PUT", {"name": "合成打包验证", "protocol": protocol,
            "base_url": model_endpoint, "api_format": "ollama_chat" if protocol == "ollama" else "chat_completions",
            "models": [{"model_id": "fixture-model", "context_tokens": 65536}]})
        profile_id = provider["models"][0]["profile_id"]
        configured = await request(f"/agent-model-profiles/{profile_id}")
        await request(f"/agent-model-profiles/{profile_id}", "PUT", {"provider": protocol, "display_name": "合成",
            "model_name": "fixture-model", "is_local": configured["is_local"], "context_tokens": 65536,
            "supports_streaming": False, "native_tool_calls": True})
        await request("/model-settings", "PUT", {"llm_temperature": 0.7, "llm_context_length": 65536, "kb_enabled_by_default": False})
        discovered = await request("/model-providers/discover/models", "POST", {"provider_id": "fixture-provider", "protocol": protocol, "base_url": model_endpoint})
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
        assert budget["source"] == "provider_usage" and budget["used_tokens"] == 1000 and budget["max_context_tokens"] == 65536
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
        assert execution["status"] == "failed" and "SHA-256" in execution["error_message"]
        assert execution["error_code"] == "environment_unavailable"
        assert execution["execution_result"]["outcome"] == "failed" and execution["execution_result"]["exit_code"] is None
        assert not execution["output"].get("stdout") and execution["output"].get("returncode") is None
        assert (await request(f"/full-access-grants/{grant['grant_id']}", "DELETE"))["revoked"]
        exported = await request("/local-history/export")
        assert len(exported["records"]["runs"]) == 4 and exported["records"]["run_steps"]
        assert not replies
        await request("/identity/clear", "POST")
        await request("/projects", expected_status=401)
        assert not any(path.startswith("/auth/") for path in server_calls)
        model_path = "/api/chat" if model_mode == "ollama" else "/v1/chat/completions"
        assert model_path in server_calls
        assert not any(path.startswith(("/desktop/model/", "/model-providers", "/agent-model-profiles")) for path in server_calls)
        result.update({"inference_mode": "auto", "api_key_only": True, "local_session": True, "platform_account_removed": True,"passed": True, "file_write": True, "workspace_auto_approval": True, "manual_command_approval": True, "powershell_command": True,
                "full_access_script": True, "context_usage": budget["used_tokens"], "tampered_host_blocked": True,
                "history_export_runs": 4, "sandbox_available": command_output["sandbox_available"]})
        return result
    except BaseException as error:
        import traceback

        result["failure"] = {"type": type(error).__name__, "errno": getattr(error, "errno", None),
                             "frames": [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                                        for frame in traceback.extract_tb(error.__traceback__)]}
        raise
    finally:
        try:
            if process is not None:
                if process.returncode is None:
                    process.stdin.write(b'{"method":"shutdown"}\n')
                    await process.stdin.drain()
                    await asyncio.wait_for(process.wait(), 15)
                assert process.returncode == 0, "打包运行时异常退出"
        except BaseException:
            result.update(passed=False, cleanup_failed=True)
            raise
        finally:
            if job:
                job.close()
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            result.update(ipc_requests=correlations, run_ids=run_ids, fixture_paths=server_calls)
            write_json(area / "verification.json", result)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--model-mode", choices=["service", "ollama", "openai"], default="service")
    parser.add_argument("--s6", action="store_true", help="完整候选另行追加 S6 公开题 AppContainer 校准")
    args = parser.parse_args()
    result = asyncio.run(verify(args.bundle.resolve(), args.work_dir.resolve(), args.model_mode))
    if args.s6:
        from run_coding_acceptance import ROOT, run

        result["s6_exit_code"] = run(argparse.Namespace(mode="control", tasks="PY01,PY10", protocol=args.model_mode,
            repetitions=1, bundle=args.bundle.resolve(), model_config=None, work_dir=args.work_dir.resolve(),
            catalog=ROOT / "tests/coding_acceptance/external_public/catalog.json", isolation="appcontainer"))
        result["passed"] = result["passed"] and result["s6_exit_code"] == 0
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
