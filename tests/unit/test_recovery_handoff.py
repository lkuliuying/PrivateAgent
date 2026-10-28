"""失败续跑与显式模型切换：只验证恢复资格、预览绑定与交接记录，不调用真实模型。"""
import io
import json
import sqlite3

import pytest
from test_local_executor import close, response, setup, until

from private_agent.agent.recovery import RESUMABLE_ERRORS
from private_agent.agent.runtime import TERMINAL
from private_agent.context.context_manager import LocalContext
from private_agent.contracts.runtime import ModelMessage, ProviderState
from private_agent.storage.store import encode


@pytest.fixture
async def api(tmp_path):
    values = await setup(tmp_path)
    values[4]["recovery_contract_version"] = "1.0"
    try:
        yield values
    finally:
        await close(values[0], values[1])


async def create(api, **kwargs):
    result = await api[1].post("/agent-runs", json={**api[4], **kwargs})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def edit_run(api, run_id, mutate):
    """直接改写运行 JSON，构造旧现场；验证恢复资格只读已提交事实。"""
    db = sqlite3.connect(api[0].state.desktop.runtime.store.path)
    try:
        (data,) = db.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
        value = json.loads(data)
        mutate(value)
        db.execute("UPDATE runs SET data=? WHERE id=?", (encode(value), run_id))
        db.commit()
    finally:
        db.close()


def run_row(api, run_id):
    db = sqlite3.connect(api[0].state.desktop.runtime.store.path)
    try:
        (data,) = db.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
        return json.loads(data)
    finally:
        db.close()


async def finished(api, *, text="已核对"):
    api[2].responses = [response(text=text)]
    run_id = await create(api)
    await until(api[1], run_id, TERMINAL)
    return run_id


async def control(api, run_id, **kwargs):
    report = (await api[1].get(f"/agent-runs/{run_id}/recovery")).json()
    data = {"request_id": "resume-request", "expected_state_version": report["state_version"],
            "checkpoint_id": report["checkpoint_id"], **kwargs}
    return data, await api[1].post(f"/agent-runs/{run_id}/resume", json=data)


def add_alt_profile(api):
    """增加一个不同供应商与模型的配置，用于检查跨路由交接。"""
    api[2].profiles.append({"id": "alt-profile", "model_name": "alt", "provider": "other",
                                   "context_tokens": 64000, "enabled": True, "is_default": False,
                                   "supports_structured_output": True, "supports_vision": True,
                                   "native_tool_calls": True})


@pytest.mark.asyncio
@pytest.mark.parametrize("code", sorted(RESUMABLE_ERRORS))
async def test_model_transport_failures_allow_manual_resume(api, tmp_path, code):
    run_id = await finished(api)
    edit_run(api, run_id, lambda run: run.update(status="failed", error_code=code,
                                                      error_message="模型调用失败"))

    report = (await api[1].get(f"/agent-runs/{run_id}/recovery")).json()
    assert report["can_resume"] is True
    assert report["recovery_class"] == "model_error"
    assert report["resumable_error"] == code
    assert report["blockers"] == []

    parent = (await api[1].get(f"/agent-runs/{run_id}")).json()
    data, result = await control(api, run_id)
    assert result.status_code == 202, result.text
    child = (await api[1].get(f"/agent-runs/{result.json()['result_run_id']}")).json()
    assert child["resumed_from_run_id"] == run_id
    assert child["model_profile_id"] == parent["model_profile_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["model_not_configured", "permission_blocked", "context_limit",
                                  "execution_unknown", "model_unauthorized"])
async def test_other_failures_stay_blocked(api, tmp_path, code):
    run_id = await finished(api)
    edit_run(api, run_id, lambda run: run.update(status="failed", error_code=code))

    report = (await api[1].get(f"/agent-runs/{run_id}/recovery")).json()
    assert report["can_resume"] is False
    assert report["recovery_class"] == "not_resumable"
    _, result = await control(api, run_id)
    assert result.status_code == 422


@pytest.mark.asyncio
async def test_resume_inherits_task_identity_and_keeps_parent_facts(api, tmp_path):
    run_id = await finished(api)
    edit_run(api, run_id, lambda run: run.update(status="failed", error_code="model_timeout"))
    before = run_row(api, run_id)

    _, result = await control(api, run_id)
    assert result.status_code == 202, result.text
    child_id = result.json()["result_run_id"]
    assert child_id != run_id
    child = (await api[1].get(f"/agent-runs/{child_id}")).json()
    assert child["logical_task_id"] == before["logical_task_id"]
    assert child["resumed_from_run_id"] == run_id
    assert child["ancestor_run_ids"] == [*before.get("ancestor_run_ids", []), run_id]
    assert child["model_profile_id"] == before["model_profile_id"]
    # 原运行的失败与未知结果保留，不被续跑改写。
    parent = (await api[1].get(f"/agent-runs/{run_id}")).json()
    assert parent["status"] == "failed" and parent["error_code"] == "model_timeout"
    # 审阅视图按轮次呈现续跑关系，旧运行不被覆盖。
    review = (await api[1].get(f"/sessions/{api[4]['session_id']}/review?scope=task")).json()
    entries = {item["id"]: item for item in review["runs"]}
    assert entries[run_id]["status"] == "failed"
    assert entries[child_id]["resumed_from_run_id"] == run_id
    assert entries[child_id]["logical_task_id"] == entries[run_id]["logical_task_id"]
    assert entries[child_id]["recovery_class"] == "active"


@pytest.mark.asyncio
async def test_preview_is_read_only_and_stable(api, tmp_path):
    add_alt_profile(api)
    run_id = await finished(api)
    edit_run(api, run_id, lambda run: run.update(status="failed", error_code="model_timeout"))
    before = run_row(api, run_id)

    first = await api[1].post(f"/agent-runs/{run_id}/resume/preview", json={"model_profile_id": "alt-profile"})
    assert first.status_code == 200, first.text
    second = await api[1].post(f"/agent-runs/{run_id}/resume/preview", json={"model_profile_id": "alt-profile"})
    body = first.json()
    assert body["preview_sha256"] == second.json()["preview_sha256"]
    assert body["target"]["model_profile_id"] == "alt-profile"
    assert body["target"]["model_name"] == "alt"
    assert body["source"]["model_profile_id"] == before["model_profile_id"]
    assert body["switched"] is True and body["requires_model_change_acceptance"] is True
    assert body["capability_gaps"] == []
    assert body["eligible"] is True
    # 预览不创建运行、不改原运行与默认模型。
    assert run_row(api, run_id) == before
    assert len(api[0].state.desktop.runtime.store.runs()) == 1
    assert next(item for item in api[2].profiles if item["is_default"])["id"] == before["model_profile_id"]


@pytest.mark.asyncio
async def test_model_switch_requires_acceptance_and_bound_preview(api, tmp_path):
    add_alt_profile(api)
    run_id = await finished(api)
    edit_run(api, run_id, lambda run: run.update(status="failed", error_code="model_timeout"))
    preview = (await api[1].post(f"/agent-runs/{run_id}/resume/preview", json={"model_profile_id": "alt-profile"})).json()

    _, missing = await control(api, run_id, model_profile_id="alt-profile")
    assert missing.status_code == 422 and "显式确认" in missing.text

    _, wrong = await control(api, run_id, model_profile_id="alt-profile", accept_model_change=True,
                             preview_sha256="0" * 64)
    assert wrong.status_code == 409 and "预览已过期" in wrong.text

    _, result = await control(api, run_id, model_profile_id="alt-profile", accept_model_change=True,
                              preview_sha256=preview["preview_sha256"], accept_unconfirmed_timing=True)
    assert result.status_code == 202, result.text
    child = (await api[1].get(f"/agent-runs/{result.json()['result_run_id']}")).json()
    assert child["model_profile_id"] == "alt-profile"
    # 恢复说明进入新运行上下文，并说明跨路由不使用旧原生状态。
    messages = api[0].state.desktop.runtime.store.context.messages(api[4]["session_id"])
    contents = [item.content for item in messages if item.role == "user"]
    assert any("改用模型：alt" in text and "公开对话历史" in text for text in contents)
    assert child["model_handoff"]["from_profile_id"] == preview["source"]["model_profile_id"]
    assert child["model_handoff"]["to_profile_id"] == "alt-profile"
    assert child["model_handoff"]["preview_sha256"] == preview["preview_sha256"]
    # 原运行模型配置不改写，默认模型不变。
    parent = run_row(api, run_id)
    assert parent["model_profile_id"] == preview["source"]["model_profile_id"]
    assert next(item for item in api[2].profiles if item["is_default"])["id"] == preview["source"]["model_profile_id"]


@pytest.mark.asyncio
async def test_paused_run_cannot_switch_model_in_place(api):
    add_alt_profile(api)
    run_id = await finished(api)
    # 暂停中的协程仍持有原模型会话，不能就地换模型；只能取消后基于历史新建运行。
    edit_run(api, run_id, lambda run: run.update(status="paused"))

    preview = (await api[1].post(f"/agent-runs/{run_id}/resume/preview", json={"model_profile_id": "alt-profile"})).json()
    _, result = await control(api, run_id, model_profile_id="alt-profile", accept_model_change=True,
                              preview_sha256=preview["preview_sha256"])
    assert result.status_code == 422 and "暂停中的运行不能直接切换模型" in result.text


@pytest.mark.asyncio
async def test_unconfirmed_timing_needs_explicit_acceptance(api, tmp_path):
    run_id = await finished(api)
    edit_run(api, run_id, lambda run: (run.update(status="failed", error_code="model_timeout"),
                                            run.setdefault("timing", {}).update(unconfirmed_tail=True)))

    _, refused = await control(api, run_id, accept_unconfirmed_timing=False)
    assert refused.status_code == 422 and "未确认的活动时间" in refused.text

    _, legacy = await control(api, run_id)
    assert legacy.status_code == 202, legacy.text


def test_public_projection_drops_native_state_across_routes():
    """跨模型续跑只发送公开历史；同一路由可沿用已校验的原生状态。"""
    context = object.__new__(LocalContext)
    state = ProviderState(route="a" * 64, output_json='{"id": "resp-1"}')
    request = type("R", (), {"messages": (ModelMessage(role="assistant", content="回答", provider_state=state),),
                             "model_copy": lambda self, update: type("R", (), {**self.__dict__, **update})()})()
    route = {"provider": "other", "model_name": "alt", "api_format": "openai", "endpoint": "https://alt.test"}

    context.run = {"model_handoff": {"from_route": {"provider": "p", "model_name": "old", "api_format": "openai",
                                                    "endpoint": "https://old.test"}}}
    projected, kind = context.public_projection(request, route)
    assert kind == "public_history"
    assert projected.messages[0].provider_state is None
    # 原始历史不被改写。
    assert request.messages[0].provider_state is not None

    context.run = {"model_handoff": {"from_route": route}}
    same, kind = context.public_projection(request, route)
    assert kind == "native_same_route" and same.messages[0].provider_state is not None

    context.run = {"model_handoff": {"from_route": None}}
    unknown, kind = context.public_projection(request, route)
    assert kind == "public_history" and unknown.messages[0].provider_state is None


def tiny_png():
    """1×1 PNG：只用于附件元数据分类，不参与模型请求。"""
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), "white").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_same_profile_configuration_change_needs_explicit_acceptance(api):
    """同一 profile 换端点也算配置变化：必须先预览差异并显式接受，原运行记录不改写。"""
    run_id = await finished(api)
    edit_run(api, run_id, lambda run: run.update(status="failed", error_code="model_network_error",
                                                 error_message="模型网络中断"))
    before = run_row(api, run_id)
    assert before["model_config_version"]
    profile = api[2].profiles[0]
    # 同一 profile 的端点变化：先补齐基础能力声明，确保用例只验证配置差异门禁。
    profile.update(native_tool_calls=True, supports_structured_output=True, supports_vision=True)
    profile["endpoint"] = "https://synthetic-one.example.test/v1"

    first = (await api[1].post(f"/agent-runs/{run_id}/resume/preview", json={})).json()
    assert first["switched"] is False and first["configuration_changed"] is True
    assert first["requires_model_change_acceptance"] is True
    # 差异的“变更前”来自原运行记录，而不是当前配置。
    assert first["source"]["configuration_version"] == before["model_config_version"]
    assert any("同一模型配置已变化" in change for change in first["changes"])

    refused = await api[1].post(f"/agent-runs/{run_id}/resume", json={
        "request_id": "resume-config-1", "expected_state_version": first["state_version"],
        "checkpoint_id": first["checkpoint_id"]})
    assert refused.status_code == 422 and "显式确认" in refused.text

    profile["endpoint"] = "https://synthetic-two.example.test/v1"
    stale = await api[1].post(f"/agent-runs/{run_id}/resume", json={
        "request_id": "resume-config-2", "expected_state_version": first["state_version"],
        "checkpoint_id": first["checkpoint_id"], "accept_model_change": True,
        "preview_sha256": first["preview_sha256"]})
    assert stale.status_code == 409 and "预览已过期" in stale.text

    fresh = (await api[1].post(f"/agent-runs/{run_id}/resume/preview", json={})).json()
    accepted = await api[1].post(f"/agent-runs/{run_id}/resume", json={
        "request_id": "resume-config-3", "expected_state_version": fresh["state_version"],
        "checkpoint_id": fresh["checkpoint_id"], "accept_model_change": True,
        "preview_sha256": fresh["preview_sha256"]})
    assert accepted.status_code == 202, accepted.text
    child = run_row(api, accepted.json()["result_run_id"])
    handoff = child["model_handoff"]
    assert handoff["configuration_changed"] is True and handoff["switched_at"]
    assert handoff["target_configuration_version"] == fresh["target"]["configuration_version"]
    # 原运行与默认模型都不因接受新配置而改写。
    assert run_row(api, run_id)["model_config_version"] == before["model_config_version"]
    default = next(item for item in api[2].profiles if item.get("is_default"))
    assert default["id"] == "test-profile"


@pytest.mark.asyncio
async def test_capability_gaps_use_pending_context_and_attachment_metadata(api):
    """容量按当前待发上下文核对，视觉按附件元数据核对；累计用量只作预算继承。"""
    runtime = api[0].state.desktop.runtime
    run_id = await finished(api)
    run = run_row(api, run_id)
    run.update(input_tokens=200000, output_tokens=50000, context_budget={"estimated_input_tokens": 9000})
    narrow = {"id": "narrow", "provider": "p", "model_name": "narrow", "context_tokens": 128000,
              "native_tool_calls": True, "supports_structured_output": True, "supports_vision": False}
    # 累计用量远超目标窗口，但当前待发上下文可以容纳。
    assert runtime.recovery.capability_gaps(run, narrow) == []

    run["context_budget"] = {"estimated_input_tokens": 200000}
    assert any("上下文容量" in gap for gap in runtime.recovery.capability_gaps(run, narrow))

    run["context_budget"] = {"estimated_input_tokens": 9000}
    text = runtime.store.attachments.install("说明.txt", "纯文本附件", run["project_id"], run["workspace_id"])
    run["attachment_ids"] = [text["id"]]
    assert runtime.recovery.capability_gaps(run, narrow) == []

    image = runtime.store.attachments.install_bytes("示意图.png", tiny_png(), run["project_id"], run["workspace_id"])
    assert image["requires_vision"] is True
    run["attachment_ids"] = [text["id"], image["id"]]
    assert any("图片输入" in gap for gap in runtime.recovery.capability_gaps(run, narrow))

    # 结构化输出与工具能力检查保持有效。
    run["attachment_ids"] = []
    run["output_schema"] = {"type": "object", "properties": {}}
    run["tool_catalog"] = {"tools": [{"name": "read_file"}]}
    limited = {**narrow, "supports_structured_output": False, "native_tool_calls": False}
    gaps = runtime.recovery.capability_gaps(run, limited)
    assert any("结构化输出" in gap for gap in gaps)
    assert any("原生工具" in gap for gap in gaps)






@pytest.mark.asyncio
async def test_second_resume_keeps_public_history_projection(api):
    """换过模型后再次续跑：即使本次不换，也不能把旧路由的不透明状态发出去。"""
    run_id = await finished(api)
    edit_run(api, run_id, lambda run: run.update(status="interrupted"))
    add_alt_profile(api)
    preview = (await api[1].post(f"/agent-runs/{run_id}/resume/preview",
                                 json={"model_profile_id": "alt-profile"})).json()
    assert preview["switched"] is True and preview["eligible"] is True

    api[2].responses = [response(text="已切换继续")]
    accepted = await api[1].post(f"/agent-runs/{run_id}/resume", json={
        "request_id": "resume-switch-1", "expected_state_version": preview["state_version"],
        "checkpoint_id": preview["checkpoint_id"], "model_profile_id": "alt-profile",
        "accept_model_change": True, "preview_sha256": preview["preview_sha256"]})
    assert accepted.status_code == 202
    child_id = accepted.json()["result_run_id"]
    await until(api[1], child_id, TERMINAL)

    # 第二次续跑不换模型：目标仍为切换后的模型，历史里已混有两条路由。
    edit_run(api, child_id, lambda run: run.update(status="interrupted", error_code="desktop_restarted"))
    again = (await api[1].get(f"/agent-runs/{child_id}/recovery")).json()
    assert again["can_resume"] is True
    api[2].responses = [response(text="再次继续")]
    resumed = await api[1].post(f"/agent-runs/{child_id}/resume", json={
        "request_id": "resume-same-1", "expected_state_version": again["state_version"],
        "checkpoint_id": again["checkpoint_id"]})
    assert resumed.status_code == 202
    grandchild = run_row(api, resumed.json()["result_run_id"])
    assert grandchild["model_profile_id"] == "alt-profile"
    assert grandchild["public_history_required"] is True
    assert "model_handoff" not in grandchild
    assert grandchild["ancestor_run_ids"] == [run_id, child_id]

    # 出站组装按公开历史投影，旧路由的不透明状态不会进入新请求。
    context = object.__new__(LocalContext)
    state = ProviderState(route="b" * 64, output_json='{"id": "resp-old"}')
    request = type("R", (), {"messages": (ModelMessage(role="assistant", content="回答", provider_state=state),),
                             "model_copy": lambda self, update: type("R", (), {**self.__dict__, **update})()})()
    context.run = grandchild
    projected, kind = context.public_projection(request, {"provider": "other", "model_name": "alt",
                                                          "api_format": "openai", "endpoint": None})
    assert kind == "public_history"
    assert projected.messages[0].provider_state is None
    assert request.messages[0].provider_state is not None
