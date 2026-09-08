"""S1 本机完成闭环：使用真实 ASGI、SQLite 与磁盘，模型和命令可控。"""
import asyncio
import json
import os
from pathlib import Path

import pytest
from test_local_executor import call, close, response, setup, until

from private_agent_core.coding_contracts import RunOutcome
from private_agent_core.completion import interpret_execution
from private_agent_local.completion import LocalCompletionVerifier
from private_agent_local.executor import ExecutionFailure
from private_agent_local.runtime import TERMINAL

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def api(tmp_path):
    values = await setup(tmp_path)
    try:
        yield values
    finally:
        await close(values[0], values[1])


async def test_s1_t01_zero_tool_file_claim_is_unmet(api):
    app, client, server, root, body = api
    server.responses = [response(text="已创建 hello.py") for _ in range(3)]
    created = await client.post("/agent-runs", json={**body, "message": "创建 hello.py"})
    run_id = created.json()["id"]
    run = await until(client, run_id, TERMINAL)
    assert run["goal_outcome"] == "unmet"
    assert run["status"] == "failed" and run["tool_call_count"] == 0
    assert not (root / "hello.py").exists()
    assert run["run_outcome"]["unverified_items"]
    assert len([path for path, _ in server.calls if path == "/desktop/model/complete"]) == 3


async def test_s1_t02_failed_test_reaches_same_model_loop(api, monkeypatch):
    app, client, server, root, body = api

    async def fail_command(*args, **kwargs):
        return {"returncode": 1, "stdout": "1 failed", "stderr": "", "truncated": False}

    monkeypatch.setattr("private_agent_local.runtime.run_command", fail_command)
    server.responses = [response(call("run_project_command", {"command": "python -m pytest"})),
                        *[response(text="测试通过") for _ in range(3)]]
    created = await client.post("/agent-runs", json={**body, "message": "运行 python -m pytest", "permission_mode": "workspace"})
    run_id = created.json()["id"]
    run = await until(client, run_id, TERMINAL)
    execution = (await client.get(f"/agent-runs/{run_id}/executions")).json()[0]
    assert run["goal_outcome"] == "unmet"
    assert execution["execution_result"]["outcome"] == "exited"
    assert execution["execution_result"]["exit_code"] == 1
    assert execution["execution_result"]["validation_outcome"] == "failed"
    requests = [json.loads(data) for path, data in server.calls if path == "/desktop/model/complete"]
    result = next(item for item in requests[1]["request"]["messages"] if item["role"] == "tool")
    facts = json.loads(result["content"])
    assert facts["success"] is False
    assert facts["output"]["returncode"] == 1
    assert "1 failed" in facts["output"]["stdout"]


async def create_run(api, message, responses, **overrides):
    app, client, server, root, body = api
    server.responses = responses
    created = await client.post("/agent-runs", json={**body, "message": message, "permission_mode": "workspace", **overrides})
    assert created.status_code == 201, created.text
    return await until(client, created.json()["id"], TERMINAL)


async def test_s1_t03_search_empty_is_normal(api):
    result = interpret_execution(execution_id="e", operation_id="o", argv=["rg", "missing"], outcome="exited", exit_code=1)
    assert result.validation_outcome == "succeeded"
    failed = interpret_execution(execution_id="e", operation_id="o", argv=["rg", "missing"], outcome="exited", exit_code=2)
    assert failed.validation_outcome == "failed"
    run = await create_run(api, "解释搜索结果", [response(call("search_project_files", {"query": "missing"})), response(text="没有匹配")])
    execution = (await api[1].get(f"/agent-runs/{run['id']}/executions")).json()[0]
    assert execution["output"]["count"] == 0 and execution["status"] == "completed"
    assert run["goal_outcome"] == "answered"


async def test_s1_t04_fake_file_result_is_not_evidence(api, monkeypatch):
    monkeypatch.setattr("private_agent_local.patchsets.replace_one", lambda *args: {"applied": True, "verified": True})
    run = await create_run(api, "创建 hello.py", [response(call("write_project_file", {"rel_path": "hello.py", "content": "print('hello')"})),
                                               *[response(text="文件已经创建") for _ in range(3)]])
    assert run["goal_outcome"] == "unmet" and not (api[3] / "hello.py").exists()
    assert all(item["status"] != "passed" for item in run["run_outcome"]["verification_results"])


@pytest.mark.parametrize("message,goal", [("创建 hello.py", "unmet"), ("只给 hello.py 的补丁预览，不写入", "answered")])
async def test_s1_t05_preview_respects_user_scope(api, message, goal):
    run = await create_run(api, message, [response(text="```diff\n+print('hello')\n```") for _ in range(3)])
    assert run["goal_outcome"] == goal
    assert not (api[3] / "hello.py").exists()


async def test_s1_t06_test_evidence_expires_after_write(api, monkeypatch):
    async def passed(*args, **kwargs):
        return {"returncode": 0, "stdout": "1 passed", "stderr": "", "truncated": False}

    monkeypatch.setattr("private_agent_local.runtime.run_command", passed)
    run = await create_run(api, "创建 hello.py 并运行 python -m pytest", [
        response(call("run_project_command", {"command": "python -m pytest"})),
        response(call("write_project_file", {"rel_path": "hello.py", "content": "print('hello')"})),
        *[response(text="修改和测试完成") for _ in range(3)]])
    assert run["goal_outcome"] == "unmet"
    assert any("过期" in item for item in run["run_outcome"]["unverified_items"])
    assert (api[3] / "hello.py").exists()


@pytest.mark.parametrize("retry", [
    call("write_project_file", {"rel_path": "hello.py", "content": "different", "require_approval": False}),
    call("run_project_command", {"command": "python writer.py"}),
    call("run_powershell_command", {"command": "Set-Content", "arguments": ["-LiteralPath", "hello.py", "-Value", "different"]}),
])
async def test_s1_t07_denial_cannot_be_bypassed(api, monkeypatch, retry):
    from private_agent_local.runtime import TOOLS
    if retry["name"] not in TOOLS:
        pytest.skip("本平台未提供 PowerShell 工具")
    app, client, server, root, body = api
    invoked = []

    async def forbidden(*args, **kwargs):
        invoked.append(args)
        raise AssertionError("拒绝后不应进入宿主")

    monkeypatch.setattr("private_agent_local.runtime.run_command", forbidden)
    server.responses = [response(call("write_project_file", {"rel_path": "hello.py", "content": "original"})),
                        response({**retry, "id": "retry-via-another-tool"}), response(text="等待用户处理")]
    run_id = (await client.post("/agent-runs", json={**body, "message": "创建 hello.py"})).json()["id"]
    await until(client, run_id, {"waiting_approval"})
    approval = (await client.get(f"/agent-runs/{run_id}/approvals")).json()[0]
    await client.post(f"/agent-runs/{run_id}/approvals/{approval['id']}/reject")
    run = await until(client, run_id, TERMINAL)
    assert run["goal_outcome"] == "blocked"
    assert not invoked and not (root / "hello.py").exists()
    executions = (await client.get(f"/agent-runs/{run_id}/executions")).json()
    assert executions[-1]["error_code"] == "operation_denied"
    assert len((await client.get(f"/agent-runs/{run_id}/approvals")).json()) == 1
    assert approval["operation_id"] == executions[0]["operation_id"]


async def test_s1_t08_explanation_needs_no_tools(api):
    run = await create_run(api, "解释这个函数为什么返回 None", [response(text="函数没有显式返回值时返回 None。")])
    assert run["status"] == "completed" and run["goal_outcome"] == "answered"
    assert run["tool_call_count"] == 0 and run["run_outcome"]["evidence_ids"] == []


@pytest.mark.parametrize("failure,outcome,goal", [
    (TimeoutError(), "timed_out", "blocked"),
    (ValueError("本机尚未安装该命令所需的开发工具"), "failed", "blocked"),
    (ExecutionFailure("宿主失联", outcome="unknown", output={"stdout": "partial"}), "unknown", "unknown"),
])
async def test_s1_t09_execution_failure_keeps_reason(api, monkeypatch, failure, outcome, goal):
    async def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr("private_agent_local.runtime.run_command", fail)
    run = await create_run(api, "运行 pytest", [response(call("run_project_command", {"command": "pytest"})), response(text="未完成")])
    execution = (await api[1].get(f"/agent-runs/{run['id']}/executions")).json()[0]
    assert execution["execution_result"]["outcome"] == outcome
    assert execution["execution_result"]["exit_code"] is None
    assert run["goal_outcome"] == goal
    if outcome == "unknown":
        assert execution["output"]["stdout"] == "partial"


async def test_s1_t09_cancel_is_persisted_without_exit_code(api, monkeypatch):
    app, client, server, root, body = api
    entered = asyncio.Event()

    async def wait(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("private_agent_local.runtime.run_command", wait)
    server.responses = [response(call("run_project_command", {"command": "pytest"}))]
    run_id = (await client.post("/agent-runs", json={**body, "message": "运行 pytest", "permission_mode": "workspace"})).json()["id"]
    await asyncio.wait_for(entered.wait(), 2)
    await client.post(f"/agent-runs/{run_id}/cancel")
    run = await until(client, run_id, TERMINAL)
    execution = (await client.get(f"/agent-runs/{run_id}/executions")).json()[0]
    assert run["status"] == "cancelled"
    assert execution["execution_result"]["outcome"] == "cancelled"
    assert execution["execution_result"]["exit_code"] is None


async def test_s1_t10_verifier_exception_fails_closed(api, monkeypatch):
    async def fail(*args):
        raise RuntimeError("private-error-body")

    monkeypatch.setattr(LocalCompletionVerifier, "load_outcome", fail)
    run = await create_run(api, "解释这个函数", [response(text="全部通过")])
    assert run["status"] == "failed" and run["goal_outcome"] == "unknown"
    assert "verification_error" in run["output"]
    assert "private-error-body" not in json.dumps(run)


async def test_s1_t10_correction_uses_original_budget_and_can_pass(api):
    run = await create_run(api, "创建 hello.py", [response(text="已完成"),
        response(call("write_project_file", {"rel_path": "hello.py", "content": "print('hello')"})), response(text="文件已创建")])
    assert run["status"] == "completed" and run["goal_outcome"] == "verified"
    assert run["input_tokens"] == 9 and run["tool_call_count"] == 1
    events = (await api[1].get(f"/agent-runs/{run['id']}/events")).json()["items"]
    assert sum(event["type"] == "run.started" for event in events) == 1
    assert [event["payload"]["attempt"] for event in events if event["type"] == "output.validation_started"] == [1, 2]
    assert events[-1]["payload"]["run_outcome"] == run["run_outcome"]


@pytest.mark.parametrize("fail_at", ["message", "terminal"])
async def test_s1_t11_final_transaction_never_publishes_early_success(api, monkeypatch, fail_at):
    app, client, server, root, body = api
    store = app.state.desktop.runtime.store
    create, emit = store.create, store.emit

    def fail_message(kind, data):
        if kind == "message" and data.get("role") == "assistant":
            raise OSError("fixture message failure")
        return create(kind, data)

    def fail_terminal(run, event_type, payload, **options):
        emit(run, event_type, payload, **options)
        if event_type == "run.completed":
            raise OSError("fixture terminal failure after insert")

    monkeypatch.setattr(store, "create" if fail_at == "message" else "emit", fail_message if fail_at == "message" else fail_terminal)
    run = await create_run(api, "创建 hello.py", [response(call("write_project_file", {"rel_path": "hello.py", "content": "hello"})), response(text="已创建")])
    assert run["status"] == "failed" and run["goal_outcome"] == "unknown" and run["output"] is None
    assert (root / "hello.py").read_text() == "hello"
    events = store.events(run["id"])
    assert not any(event["type"] == "run.completed" for event in events)
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert [item["role"] for item in store.list("message", session_id=body["session_id"])] == ["user"]


async def test_s1_t12_legacy_mapping_does_not_invent_evidence(api):
    app, client, server, root, body = api
    store = app.state.desktop.runtime.store
    store.save_run({"id": "legacy-run", "status": "completed", "output": "已完成", "session_id": body["session_id"]})
    result = (await client.get("/agent-runs/legacy-run")).json()
    assert result["goal_outcome"] == "unknown" and result["run_outcome"]["evidence_ids"] == []
    assert "run_outcome" not in store.run_state("legacy-run")


async def test_user_forbids_commands_preserves_test_requirement(api):
    run = await create_run(api, "修复 hello.py 并测试，但暂时不允许运行命令", [
        response(call("write_project_file", {"rel_path": "hello.py", "content": "fixed"})), response(text="已修改，测试尚未运行")])
    assert run["goal_outcome"] == "blocked"
    assert any(item["kind"] == "test" for item in run["run_outcome"]["requirements"])
    assert any("不运行命令" in item for item in run["run_outcome"]["unverified_items"])


async def test_user_cannot_remove_inferred_requirements_or_send_unknown_version(api):
    app, client, server, root, body = api
    rejected = await client.post("/agent-runs", json={**body, "completion_contract_version": "2.0"})
    assert rejected.status_code == 422
    run = await create_run(api, "创建 hello.py", [response(text="完成") for _ in range(3)], completion_requirements=[])
    assert run["goal_outcome"] == "unmet"


async def test_disk_change_after_test_is_detected_without_tool_version_bump(api, monkeypatch):
    async def passed(*args, **kwargs):
        return {"returncode": 0, "stdout": "1 passed", "stderr": ""}

    monkeypatch.setattr("private_agent_local.runtime.run_command", passed)
    original = LocalCompletionVerifier.load_outcome

    async def external_edit(verifier, output):
        (verifier.root / "external.py").write_text("changed", encoding="utf-8")
        return await original(verifier, output)

    monkeypatch.setattr(LocalCompletionVerifier, "load_outcome", external_edit)
    run = await create_run(api, "运行 pytest", [response(call("run_project_command", {"command": "pytest"})), *[response(text="通过") for _ in range(3)]])
    assert run["goal_outcome"] == "unmet"


async def test_version_query_does_not_satisfy_tests(api, monkeypatch):
    async def version(*args, **kwargs):
        return {"returncode": 0, "stdout": "pytest 8", "stderr": ""}

    monkeypatch.setattr("private_agent_local.runtime.run_command", version)
    run = await create_run(api, "运行测试", [response(call("run_project_command", {"command": "pytest --version"})),
                                           *[response(text="已通过") for _ in range(3)]])
    assert run["goal_outcome"] == "unmet"
    assert not any(item["status"] == "passed" for item in run["run_outcome"]["verification_results"])


async def test_artifact_exists_and_manual_requirement_is_not_fabricated(api):
    (api[3] / "artifact.txt").write_text("artifact", encoding="utf-8")
    run = await create_run(api, "检查产物", [response(text="产物可用，外观仍需人工确认")], completion_requirements=[
        {"requirement_id": "artifact", "kind": "artifact", "scope": "artifact.txt", "description": "产物存在", "evidence_policy": "disk"},
        {"requirement_id": "manual", "kind": "manual", "description": "人工检查视觉效果"}])
    assert run["goal_outcome"] == "unknown"
    results = run["run_outcome"]["verification_results"]
    assert [item["status"] for item in results] == ["passed", "unverified"]
    assert run["run_outcome"]["evidence_refs"][0]["execution_id"] is None


async def test_fix_and_explain_still_requires_actual_change(api):
    run = await create_run(api, "修复 hello.py 并解释原因", [response(text="已修复，原因如下") for _ in range(3)])
    assert run["goal_outcome"] == "unmet"


async def test_empty_answer_does_not_become_verified(api):
    run = await create_run(api, "解释函数", [response() for _ in range(3)])
    assert run["status"] == "failed" and run["goal_outcome"] == "unknown"
    assert "未提供" in run["output"]


async def test_preview_can_finish_after_blocked_write_attempt(api):
    run = await create_run(api, "只给 hello.py 的补丁预览，不写入", [
        response(call("write_project_file", {"rel_path": "hello.py", "content": "unexpected"})), response(text="这是补丁预览")])
    assert run["goal_outcome"] == "answered" and not (api[3] / "hello.py").exists()


async def test_readonly_manual_check_is_unverified_not_permission_failure(api):
    run = await create_run(api, "说明界面状态", [response(text="需要人工检查")], permission_mode="readonly",
                           completion_requirements=[{"requirement_id": "manual", "description": "人工验收"}])
    assert run["goal_outcome"] == "unknown"


async def test_unknown_command_is_not_automatically_replayed(api, monkeypatch):
    attempts = []

    async def lost(*args, **kwargs):
        attempts.append(kwargs["execution_id"])
        raise ExecutionFailure("失联", outcome="unknown", output={})

    monkeypatch.setattr("private_agent_local.runtime.run_command", lost)
    run = await create_run(api, "运行 pytest", [response(call("run_project_command", {"command": "pytest"})),
        response({"id": "retry", "name": "run_project_command", "arguments": {"command": "pytest -q"}}), response(text="结果未知")])
    assert run["goal_outcome"] == "unknown" and len(attempts) == 1


async def test_verification_retries_cannot_reset_step_budget():
    from private_agent_core.contracts import AgentRunLimits, ModelMessage, ModelResponse
    from private_agent_core.runtime import AgentRuntime
    from private_agent_core.verification import OutputVerification

    class Model:
        calls = 0

        async def complete(self, request, *, cancellation):
            self.calls += 1
            return ModelResponse(text="未执行")

        async def execute(self, call, *, cancellation):
            raise AssertionError("不应调用工具")

    class Verifier:
        name, output_schema = "budget_test", None

        async def verify(self, output, *, attempt):
            return OutputVerification(passed=False, code="missing_evidence", message="缺少执行证据")

    model = Model()
    result = await AgentRuntime(model, model, output_verifier=Verifier(), max_verification_retries=2).run(
        [ModelMessage(role="user", content="创建文件")], limits=AgentRunLimits(max_steps=2))
    assert result.status.value == "limit_exceeded" and model.calls == 2
    assert result.events[-1].payload["error_code"] == "max_steps"


@pytest.mark.parametrize("case", ["answered", "verified", "unmet", "test_failed", "blocked", "unknown"])
async def test_s1_wire_examples_from_real_api(api, monkeypatch, case):
    async def command(*args, **kwargs):
        return {"returncode": 1, "stdout": "1 failed", "stderr": "", "truncated": False}

    monkeypatch.setattr("private_agent_local.runtime.run_command", command)
    message = "解释函数的返回值"
    responses = [response(text="函数返回一个数字")]
    overrides = {}
    if case == "verified":
        message = "创建 hello.py"
        responses = [response(call("write_project_file", {"rel_path": "hello.py", "content": "print('hello')"})), response(text="文件已创建并回读")]
    elif case == "unmet":
        message, responses = "创建 hello.py", [response(text="已创建") for _ in range(3)]
    elif case == "test_failed":
        message = "运行 pytest"
        responses = [response(call("run_project_command", {"command": "pytest"})), *[response(text="测试通过") for _ in range(3)]]
    elif case == "blocked":
        message, responses = "运行测试，但不允许运行命令", [response(text="测试受阻")]
    elif case == "unknown":
        overrides = {"completion_requirements": [{"requirement_id": "manual", "description": "人工验收界面"}]}
    run = await create_run(api, message, responses, **overrides)
    expected = "unmet" if case == "test_failed" else case
    assert run["goal_outcome"] == expected
    RunOutcome.model_validate(run["run_outcome"])
    if case == "verified":
        assert (api[3] / "hello.py").read_text() == "print('hello')"
    elif case == "unmet":
        assert not (api[3] / "hello.py").exists()
    events = (await api[1].get(f"/agent-runs/{run['id']}/events")).json()["items"]
    assert events[-1]["payload"]["run_outcome"] == run["run_outcome"]
    sample = {"snapshot": run, "events": [event for event in events if not event["type"].startswith("tool.")],
              "executions": (await api[1].get(f"/agent-runs/{run['id']}/executions")).json()}
    directory = Path(os.environ["CODING_VALIDATION_DIR"]) / "s1-wire"
    directory.mkdir(exist_ok=True)
    (directory / f"{case}.json").write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
