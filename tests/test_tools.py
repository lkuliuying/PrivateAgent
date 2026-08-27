"""第二阶段 M1 工具调用底座测试。

覆盖：
- 单测：ToolRegistry / 审批状态机 / is_trusted_path 越界。
- API：/tools/plan（提议/不提议）、approve read_file（授权/未授权）、reject 不执行、
  /chat/stream 注入 tool_result。

照 test_chat_rag_e2e 模式：client fixture 走 ASGITransport + 真实 MySQL，
OllamaProvider.chat 在集成缝处 monkeypatch。
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete

from personal_assistant.api import routes_tools
from personal_assistant.config import settings
from personal_assistant.core import approvals
from personal_assistant.core.compatibility import CompatibilityTelemetry
from personal_assistant.core.models import ChatSession, TrustedPath
from personal_assistant.core.permissions import is_trusted_path
from personal_assistant.core.provider import OllamaProvider
from personal_assistant.core.tools import _parse_plan, default_registry


def _parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line.removeprefix("data:").strip()))
    return events


async def _read_stream(response) -> list[dict]:
    body = await response.aread()
    return _parse_sse(body.decode("utf-8"))


# ============ 单测 ============

def test_registry_has_read_file():
    tool = default_registry.get("read_file")
    assert tool is not None
    assert tool.risk_level == "confirm"


def test_registry_for_planning_excludes_restricted():
    planning = default_registry.for_planning()
    assert planning
    assert all(t["risk_level"] != "restricted" for t in planning)
    assert any(t["name"] == "read_file" for t in planning)


def test_approval_state_machine_valid_transitions():
    approvals.assert_transition("pending_approval", "approved")
    approvals.assert_transition("approved", "running")
    approvals.assert_transition("running", "succeeded")
    approvals.assert_transition("running", "failed")
    approvals.assert_transition("pending_approval", "rejected")


def test_approval_state_machine_invalid_transitions():
    with pytest.raises(approvals.ApprovalError):
        approvals.assert_transition("rejected", "approved")
    with pytest.raises(approvals.ApprovalError):
        approvals.assert_transition("succeeded", "running")
    with pytest.raises(approvals.ApprovalError):
        approvals.assert_transition("pending_approval", "succeeded")


def test_is_trusted_path_authorized_directory(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    nested = sub / "b.txt"
    nested.write_text("y", encoding="utf-8")
    trusted = [str(tmp_path)]
    assert is_trusted_path(str(f), trusted)
    assert is_trusted_path(str(nested), trusted)
    assert is_trusted_path(str(tmp_path), trusted)


def test_is_trusted_path_unauthorized(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    assert not is_trusted_path(str(f), [])
    other = tmp_path.parent / "other_target.txt"
    assert not is_trusted_path(str(other), [str(tmp_path)])


def test_is_trusted_path_traversal_blocked(tmp_path):
    """通过 ``..`` 构造的越界路径不应被授权。"""
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    trusted = [str(tmp_path)]
    crafted = str(tmp_path / ".." / "outside.txt")
    assert not is_trusted_path(crafted, trusted)


# ============ API 测试 ============

@pytest.mark.asyncio
async def test_tools_plan_proposes_read_file(client, db, monkeypatch):
    async def fake_chat(self: OllamaProvider, messages: list[dict]) -> str:
        return json.dumps(
            {
                "use_tool": True,
                "tool": "read_file",
                "input": {"path": "C:/tmp/x.txt"},
                "reason": "用户要读取文件",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)
    sess = (await client.post("/sessions")).json()
    try:
        res = await client.post(
            "/tools/plan",
            json={"session_id": sess["id"], "message": "读取 C:/tmp/x.txt"},
        )
        assert res.status_code == 200
        assert res.headers["Deprecation"] == "true"
        tc = res.json()["tool_call"]
        assert tc is not None
        assert tc["tool_name"] == "read_file"
        assert tc["risk_level"] == "confirm"
        assert tc["status"] == "pending_approval"
        assert tc["input_json"]["path"] == "C:/tmp/x.txt"
    finally:
        await db.execute(delete(ChatSession).where(ChatSession.id == sess["id"]))
        await db.commit()


@pytest.mark.asyncio
async def test_tools_plan_no_tool(client, db, monkeypatch):
    async def fake_chat(self: OllamaProvider, messages: list[dict]) -> str:
        return '{"use_tool": false}'

    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)
    telemetry = CompatibilityTelemetry()
    monkeypatch.setattr(routes_tools, "compatibility_telemetry", telemetry)
    sess = (await client.post("/sessions")).json()
    try:
        res = await client.post(
            "/tools/plan", json={"session_id": sess["id"], "message": "你好"}
        )
        assert res.status_code == 200
        assert res.headers["Deprecation"] == "true"
        assert res.json()["tool_call"] is None

        async def unavailable_provider(_db):
            raise routes_tools.HTTPException(503, "provider unavailable")

        monkeypatch.setattr(routes_tools, "_provider", unavailable_provider)
        unavailable = await client.post(
            "/tools/plan", json={"session_id": sess["id"], "message": "你好"}
        )
        assert unavailable.status_code == 503
        assert unavailable.headers["Deprecation"] == "true"
        metric = telemetry.snapshot()["paths"]["/tools/plan"]
        assert metric["calls"] == 2
        assert metric["outcomes"]["not_planned"] == 1
        assert metric["outcomes"]["error"] == 1
    finally:
        await db.execute(delete(ChatSession).where(ChatSession.id == sess["id"]))
        await db.commit()


@pytest.mark.asyncio
async def test_legacy_planner_hides_runtime_owned_read_only_tools(
    client, db, monkeypatch
):
    seen_system_prompts: list[str] = []

    async def fake_chat(self: OllamaProvider, messages: list[dict]) -> str:
        del self
        seen_system_prompts.append(messages[0]["content"])
        return json.dumps(
            {
                "use_tool": True,
                "tool": "read_file",
                "input": {"path": "C:/tmp/should-not-be-planned.txt"},
                "reason": "stale planner choice",
            }
        )

    monkeypatch.setattr(settings, "chat_agent_runtime_enabled", True)
    monkeypatch.setattr(settings, "agent_run_read_only_tools_enabled", True)
    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)
    telemetry = CompatibilityTelemetry()
    monkeypatch.setattr(routes_tools, "compatibility_telemetry", telemetry)
    sess = (await client.post("/sessions")).json()
    try:
        res = await client.post(
            "/tools/plan",
            json={"session_id": sess["id"], "message": "inspect files"},
        )

        assert res.status_code == 200
        assert res.headers["Deprecation"] == "true"
        assert res.json()["tool_call"] is None
        assert len(seen_system_prompts) == 1
        prompt = seen_system_prompts[0]
        for native_tool in (
            "read_file",
            "list_directory",
            "search_files",
            "grep_code",
            "read_code_file",
            "get_git_status",
            "get_git_diff",
            "propose_patch",
        ):
            assert f'"name": "{native_tool}"' not in prompt
        assert '"name": "summarize_file"' in prompt
        metric = telemetry.snapshot()["paths"]["/tools/plan"]
        assert metric["calls"] == 1
        assert metric["modes"]["runtime_filtered"] == 1
        assert metric["outcomes"]["not_planned"] == 1
    finally:
        await db.execute(delete(ChatSession).where(ChatSession.id == sess["id"]))
        await db.commit()


@pytest.mark.asyncio
async def test_approve_read_file_succeeds(client, db, monkeypatch, tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("hello world 文件内容", encoding="utf-8")

    auth = await client.post(
        "/files/authorize", json={"path": str(f), "kind": "file"}
    )
    assert auth.status_code == 201

    async def fake_chat(self: OllamaProvider, messages: list[dict]) -> str:
        return json.dumps(
            {
                "use_tool": True,
                "tool": "read_file",
                "input": {"path": str(f)},
                "reason": "读取",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)
    telemetry = CompatibilityTelemetry()
    monkeypatch.setattr(routes_tools, "compatibility_telemetry", telemetry)
    sess = (await client.post("/sessions")).json()
    try:
        plan = await client.post(
            "/tools/plan", json={"session_id": sess["id"], "message": "读取文件"}
        )
        tc = plan.json()["tool_call"]

        res = await client.post(f"/tool-calls/{tc['id']}/approve")
        assert res.status_code == 200
        assert res.headers["Deprecation"] == "true"
        updated = res.json()
        assert updated["status"] == "succeeded"
        assert "hello world" in updated["output_json"]["content"]
        assert updated["output_json"]["size_bytes"] > 0
        metric = telemetry.snapshot()["paths"]["/tool-calls/:id/approve"]
        assert metric["calls"] == 1
        assert metric["outcomes"]["succeeded"] == 1
    finally:
        await db.execute(delete(ChatSession).where(ChatSession.id == sess["id"]))
        await db.execute(delete(TrustedPath).where(TrustedPath.path == str(f)))
        await db.commit()


@pytest.mark.asyncio
async def test_reject_does_not_execute(client, db, monkeypatch):
    async def fake_chat(self: OllamaProvider, messages: list[dict]) -> str:
        return json.dumps(
            {"use_tool": True, "tool": "read_file", "input": {"path": "C:/nope.txt"}, "reason": "x"}
        )

    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)
    telemetry = CompatibilityTelemetry()
    monkeypatch.setattr(routes_tools, "compatibility_telemetry", telemetry)
    sess = (await client.post("/sessions")).json()
    try:
        plan = await client.post(
            "/tools/plan", json={"session_id": sess["id"], "message": "读"}
        )
        tc = plan.json()["tool_call"]

        res = await client.post(f"/tool-calls/{tc['id']}/reject")
        assert res.status_code == 200
        assert res.headers["Deprecation"] == "true"
        assert res.json()["status"] == "rejected"

        listed = await client.get(
            "/tool-calls", params={"session_id": sess["id"]}
        )
        definitions = await client.get("/tools")
        detail = await client.get(f"/tool-calls/{tc['id']}")
        missing = await client.get("/tool-calls/0")
        assert listed.status_code == 200
        assert listed.headers["Deprecation"] == "true"
        assert [item["id"] for item in listed.json()] == [tc["id"]]
        assert definitions.status_code == 200
        assert definitions.headers["Deprecation"] == "true"
        assert any(item["name"] == "summarize_file" for item in definitions.json())
        assert detail.status_code == 200
        assert detail.headers["Deprecation"] == "true"
        assert missing.status_code == 404
        assert missing.headers["Deprecation"] == "true"

        # 拒绝后再批准 → 409（非法状态转换）
        again = await client.post(f"/tool-calls/{tc['id']}/approve")
        assert again.status_code == 409
        assert again.headers["Deprecation"] == "true"
        rejected = telemetry.snapshot()["paths"]["/tool-calls/:id/reject"]
        approve = telemetry.snapshot()["paths"]["/tool-calls/:id/approve"]
        listed_metric = telemetry.snapshot()["paths"]["/tool-calls"]
        detail_metric = telemetry.snapshot()["paths"]["/tool-calls/:id"]
        definitions_metric = telemetry.snapshot()["paths"]["/tools"]
        assert rejected["outcomes"]["rejected"] == 1
        assert approve["outcomes"]["conflict"] == 1
        assert listed_metric["modes"]["session_filtered"] == 1
        assert detail_metric["outcomes"]["found"] == 1
        assert detail_metric["outcomes"]["not_found"] == 1
        assert definitions_metric["outcomes"]["returned"] == 1
    finally:
        await db.execute(delete(ChatSession).where(ChatSession.id == sess["id"]))
        await db.commit()


@pytest.mark.asyncio
async def test_approve_unauthorized_path_fails(client, monkeypatch, tmp_path):
    f = tmp_path / "secret.txt"
    f.write_text("secret", encoding="utf-8")
    # 不授权该路径

    async def fake_chat(self: OllamaProvider, messages: list[dict]) -> str:
        return json.dumps(
            {"use_tool": True, "tool": "read_file", "input": {"path": str(f)}, "reason": "x"}
        )

    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)
    sess = (await client.post("/sessions")).json()
    plan = await client.post(
        "/tools/plan", json={"session_id": sess["id"], "message": "读"}
    )
    tc = plan.json()["tool_call"]

    res = await client.post(f"/tool-calls/{tc['id']}/approve")
    assert res.status_code == 400

    got = await client.get(f"/tool-calls/{tc['id']}")
    assert got.json()["status"] == "failed"
    assert "未授权" in got.json()["error_message"]


@pytest.mark.asyncio
async def test_files_authorize_dedup(client, tmp_path):
    f = tmp_path / "d.txt"
    f.write_text("x", encoding="utf-8")
    r1 = await client.post("/files/authorize", json={"path": str(f), "kind": "file"})
    r2 = await client.post("/files/authorize", json={"path": str(f), "kind": "file"})
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]  # 去重，返回同一条
    listed = (await client.get("/files/trusted")).json()
    assert sum(1 for t in listed if t["path"] == str(f)) == 1


@pytest.mark.asyncio
async def test_chat_stream_injects_tool_result(client, monkeypatch):
    seen: list[list[dict]] = []

    async def fake_chat_stream(
        self: OllamaProvider, messages: list[dict]
    ) -> AsyncIterator[str]:
        seen.append(messages)
        yield "基于文件内容"
        yield "的总结"

    async def fake_chat(self: OllamaProvider, messages: list[dict]) -> str:
        return "工具总结"

    monkeypatch.setattr(OllamaProvider, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)

    sess = (await client.post("/sessions")).json()
    async with client.stream(
        "POST",
        "/chat/stream",
        json={
            "session_id": sess["id"],
            "message": "总结一下",
            "knowledge_base": False,
            "tool_result": {
                "tool_name": "read_file",
                "output": {
                    "content": "文件内容XYZ",
                    "size_bytes": 10,
                    "truncated": False,
                },
            },
        },
    ) as response:
        assert response.status_code == 200
        events = await _read_stream(response)

    done = next(e for e in events if e["type"] == "done")
    assert "基于文件内容" in done["content"]
    prompt_text = "\n".join(m["content"] for m in seen[0])
    assert "文件内容XYZ" in prompt_text
    assert "read_file" in prompt_text


# ============ 审查修复回归测试 ============

def test_parse_plan_robustness():
    """_parse_plan 用括号配对，避免贪婪正则吞掉尾部多余 '}'。"""
    assert _parse_plan('{"use_tool": false}') == {"use_tool": False}
    # 尾部多余花括号：贪婪正则会失败，括号配对可恢复
    assert _parse_plan(
        '{"use_tool": true, "tool": "read_file", "input": {"path": "x"}} see {1}'
    ) == {"use_tool": True, "tool": "read_file", "input": {"path": "x"}}
    # 两个 JSON 对象：返回首个平衡对象
    assert _parse_plan('{"use_tool": false} {"use_tool": true}') == {
        "use_tool": False
    }
    # markdown 围栏
    assert _parse_plan('```json\n{"use_tool": false}\n```') == {"use_tool": False}
    # 无 JSON
    assert _parse_plan("no json here") is None


@pytest.mark.asyncio
async def test_authorize_rejects_relative_path(client):
    """相对路径必须被拒绝，避免按后端 CWD 解析授权到非预期位置。"""
    for bad in ["notes", ".", "..", "C:foo"]:
        res = await client.post(
            "/files/authorize", json={"path": bad, "kind": "file"}
        )
        assert res.status_code == 422, bad


@pytest.mark.asyncio
async def test_approve_after_succeeded_returns_409(client, monkeypatch, tmp_path):
    """已成功的工具调用再次 approve 应 409（状态机/原子 claim 拒绝）。"""
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    await client.post("/files/authorize", json={"path": str(f), "kind": "file"})

    async def fake_chat(self: OllamaProvider, messages: list[dict]) -> str:
        return json.dumps(
            {"use_tool": True, "tool": "read_file", "input": {"path": str(f)}, "reason": "x"}
        )

    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)
    sess = (await client.post("/sessions")).json()
    plan = await client.post(
        "/tools/plan", json={"session_id": sess["id"], "message": "读"}
    )
    tc = plan.json()["tool_call"]

    first = await client.post(f"/tool-calls/{tc['id']}/approve")
    assert first.status_code == 200
    assert first.json()["status"] == "succeeded"

    second = await client.post(f"/tool-calls/{tc['id']}/approve")
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_activity_started_at_set_on_running(db):
    """工具调用进入 running 时，活动记录应补 started_at（非 NULL）。"""
    from personal_assistant.core.activities import ActivityService
    from personal_assistant.core.models import ChatSession
    from personal_assistant.core.repo_tools import (
        ActivityRepository,
        ToolCallRepository,
    )

    sess = ChatSession(title="t")
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    try:
        repo = ToolCallRepository(db)
        tc = await repo.create(
            session_id=sess.id,
            tool_name="read_file",
            risk_level="confirm",
            status="pending_approval",
            input_json={"path": "x"},
        )
        svc = ActivityService(db)
        await svc.sync_tool_call(tc)  # waiting_approval，无 started_at

        await repo.update_status(tc.id, status="running")
        tc_running = await repo.get_fresh(tc.id)
        await svc.sync_tool_call(tc_running)  # running 应补 started_at

        act = await ActivityRepository(db).get_by_ref("tool_call", tc.id)
        assert act is not None
        assert act.status == "running"
        assert act.started_at is not None
    finally:
        await db.execute(
            __import__("sqlalchemy").text("DELETE FROM activities WHERE ref_id=:i"),
            {"i": tc.id},
        )
        await db.execute(
            __import__("sqlalchemy").text("DELETE FROM tool_calls WHERE id=:i"),
            {"i": tc.id},
        )
        await db.delete(sess)
        await db.commit()
