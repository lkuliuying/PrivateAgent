"""v1.0.0 CT-9 路由级测试：工具快照诊断 API（脱敏、flag 门控）。

覆盖专项计划 §14.2/§7.3 与 ADR-008 退出条件：

- flag 关闭 → 404（不暴露诊断面）；
- flag 开启 → 返回每个工具的 direct/hidden 原因与四组 hash；
- intent tag 过滤生效（file.mutate 视角下写工具 direct）；
- 非法 intent tag → 422；视图条目不含 schema/描述全文。
"""

from __future__ import annotations

from personal_assistant.api import routes_agent_runs


async def test_diagnostics_404_when_flag_disabled(client):
    resp = await client.get("/agent-runs/tool-diagnostics")
    assert resp.status_code == 404


async def test_diagnostics_returns_redacted_snapshot(client, monkeypatch, db):
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(
        routes_agent_runs.cfg, "agent_v2_tool_snapshot_enabled", True
    )
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_run_read_only_tools_enabled", True)
    # 默认 answer.only 视角：带意图标签的工具全部 not_relevant（§9.2 第 7 层）。
    base = await client.get("/agent-runs/tool-diagnostics")
    assert base.status_code == 200
    assert base.json()["hidden_total"] >= 1

    resp = await client.get("/agent-runs/tool-diagnostics?intent_tags=code.inspect")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["direct_total"] >= 1
    assert body["hidden_total"] >= 1
    by_name = {item["canonical_name"]: item for item in body["tools"]}
    # read_only_tools 开启 → search_files 可见。
    assert by_name["search_files"]["exposure"] == "direct"
    # patch_workflow 未开启 → apply_patch_to_workspace 隐藏且原因稳定。
    apply_entry = by_name["apply_patch_to_workspace"]
    assert apply_entry["exposure"] == "hidden:feature_disabled"
    assert apply_entry["approval_mode"] == "prompt"
    # 脱敏红线：无 schema/描述正文。
    for entry in body["tools"]:
        assert "input_schema" not in entry
        assert "description" not in entry
    assert body["catalog_hash"] and body["visible_hash"]


async def test_diagnostics_intent_tag_filters_and_validates(client, monkeypatch):
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(
        routes_agent_runs.cfg, "agent_v2_tool_snapshot_enabled", True
    )
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", True)

    resp = await client.get(
        "/agent-runs/tool-diagnostics?intent_tags=file.mutate,code.inspect"
    )
    assert resp.status_code == 200, resp.text
    by_name = {i["canonical_name"]: i for i in resp.json()["tools"]}
    assert by_name["apply_patch_to_workspace"]["exposure"] == "direct"

    bad = await client.get("/agent-runs/tool-diagnostics?intent_tags=nonsense")
    assert bad.status_code == 422
