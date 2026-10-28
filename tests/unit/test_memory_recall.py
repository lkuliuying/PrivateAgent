"""M4：按当前目标、步骤、路径与追加要求召回长期记忆。"""
import asyncio
import json

import pytest
from test_local_executor import close, response, setup
from test_local_memories import enable, worker  # noqa: F401  pytest 夹具

from private_agent.memory.memories import compose_query, recall_query
from private_agent.memory.memory_store import MemoryInput


def project_session(store):
    project = store.create("project", {"name": "召回项目"})
    session = store.create("session", {"project_id": project["id"]})
    return project, session


def test_recall_query_includes_long_goal_tail_step_paths_and_steer():
    goal = "前置背景说明。" * 300 + "最后要求：更新 docs/接口说明.md"
    run = {"goal": goal,
           "plan": {"items": [{"title": "修改 src/auth.py 的登录流程", "detail": "保留旧返回字段", "status": "in_progress"}]},
           "completion_policy": {"access_scopes": [["src/"]], "forbidden_write_paths": ["src/private.py"]},
           "task_interpretation": {"sources": [{"kind": "steer", "text": "追加要求：保留旧接口"}]}}
    query, signals = recall_query(run)
    # 长目标同时保留首段与末段，后半部分需求仍有召回机会。
    assert "前置背景说明" in query and "最后要求：更新 docs/接口说明.md" in query
    assert set(signals) == {"goal", "step", "paths", "steer"}
    assert "src/auth.py" in signals["paths"] and "src/" in signals["paths"]
    assert "src/private.py" in signals["paths"]
    assert "保留旧接口" in signals["steer"]
    # 组合查询保持既有 500 字符上限，并且就是各信号的拼接结果。
    assert len(query) <= 500 and query == " ".join(signals[name] for name in ("goal", "step", "paths", "steer"))
    # 没有计划或追加要求时不伪造信号。
    only_goal, only_signals = recall_query({"goal": "检查项目"})
    assert set(only_signals) == {"goal"} and only_goal == "检查项目"


def test_recall_query_keeps_latest_steer_within_total_budget():
    goal = "很长的目标说明。" * 400
    steers = [{"kind": "steer", "text": f"追加要求 {index}：" + "补充说明" * 80} for index in range(3)]
    steers.append({"kind": "steer", "text": "最终追加要求：交付前必须核对 ZEBRA_REQUIRED_MARKER"})
    run = {"goal": goal,
           "plan": {"items": [{"title": "步骤 " + "很长的步骤说明" * 40, "detail": "路径 " + "src/深/路径.py " * 30,
                               "status": "in_progress"}]},
           "completion_policy": {"access_scopes": [[f"src/long/path/number-{index}.py" for index in range(20)]]},
           "task_interpretation": {"sources": steers}}
    query, signals = recall_query(run)
    assert len(query) <= 500
    # 各信号先分到自己的额度，不会因为拼接后被整体截断而丢掉最新追加要求。
    assert "ZEBRA_REQUIRED_MARKER" in signals["steer"] and "ZEBRA_REQUIRED_MARKER" in query
    assert all(len(signals[name]) <= quota for name, quota in
               (("goal", 210), ("step", 110), ("paths", 90), ("steer", 80)))
    assert len(query) == len(compose_query(signals))


def test_steer_only_memory_is_recalled_within_query_budget(worker):  # noqa: F811
    enable(worker, generate_memories=False)
    project, session = project_session(worker.owner.store)
    memory = worker.store.put(project["id"], stable_key="project:zebra", source_updated_at="2026-01-01",
                              data=MemoryInput(title="交付标记", content="交付前补齐 ZEBRA_REQUIRED_MARKER 说明"))
    run = {"goal": "很长的目标说明。" * 400,
           "task_interpretation": {"sources": [{"kind": "steer", "text": "追加要求：" + "补充" * 200
                                                + " 最终必须核对 ZEBRA_REQUIRED_MARKER"}]}}
    query, signals = recall_query(run)
    assert "ZEBRA_REQUIRED_MARKER" in query
    _, ids, details = worker.recall_with_details(session["id"], project["id"], query, signals=signals)
    assert memory["id"] in ids
    assert "steer" in next(item for item in details if item["memory_id"] == memory["id"])["matched_signals"]
    # 组合查询仍受 500 字符上限约束，超出写入会被拒绝。
    with pytest.raises(ValueError, match="500"):
        worker.search(project["id"], "x" * 501)


def test_long_goal_tail_requirement_recalls_related_memory(worker):  # noqa: F811
    enable(worker, generate_memories=False)
    project, session = project_session(worker.owner.store)
    worker.store.put(project["id"], stable_key="project:background", source_updated_at="2026-01-01",
                     data=MemoryInput(title="背景约定", content="前置背景说明的补充"))
    tail = worker.store.put(project["id"], stable_key="project:delivery", source_updated_at="2026-01-01",
                            data=MemoryInput(title="交付位置", content="交付清单写在 docs/交付清单.md"))
    goal = "前置背景。" * 150 + "最后要求：交付清单写在 docs/交付清单.md"
    query, signals = recall_query({"goal": goal})
    _, ids, _ = worker.recall_with_details(session["id"], project["id"], query, signals=signals)
    assert tail["id"] in ids
    # 旧行为只截取目标前 500 字，后半部分需求没有召回机会。
    _, legacy_ids, _ = worker.recall_with_details(session["id"], project["id"], goal[:500])
    assert tail["id"] not in legacy_ids


def test_step_switch_rebuilds_query_and_explanation(worker):  # noqa: F811
    enable(worker, generate_memories=False)
    project, session = project_session(worker.owner.store)
    code = worker.store.put(project["id"], stable_key="project:login", source_updated_at="2026-01-01",
                            data=MemoryInput(title="登录接口", content="修改 src/auth.py 时保留旧返回字段"))
    tests = worker.store.put(project["id"], stable_key="project:tests", source_updated_at="2026-01-01",
                             data=MemoryInput(title="测试命令", content="运行 pytest tests/unit 后再提交"))
    first_run = {"goal": "完成任务", "plan": {"items": [{"title": "修改 src/auth.py", "status": "in_progress"}]}}
    query, signals = recall_query(first_run)
    _, ids, details = worker.recall_with_details(session["id"], project["id"], query, signals=signals)
    assert code["id"] in ids and tests["id"] not in ids
    detail = next(item for item in details if item["memory_id"] == code["id"])
    assert {"step", "paths"} & set(detail["matched_signals"])
    assert detail["version"] == code["version"]
    # 步骤变化后重新计算查询，不沿用旧步骤的召回结果。
    second_run = {"goal": "完成任务", "plan": {"items": [{"title": "运行 pytest 验证", "status": "in_progress"}]}}
    query, signals = recall_query(second_run)
    _, ids, details = worker.recall_with_details(session["id"], project["id"], query, signals=signals)
    assert tests["id"] in ids and code["id"] not in ids
    assert "step" in next(item for item in details if item["memory_id"] == tests["id"])["matched_signals"]


def test_inactive_candidates_do_not_crowd_out_active_memory(worker):  # noqa: F811
    enable(worker, generate_memories=False)
    project, session = project_session(worker.owner.store)
    for index in range(25):
        stale = worker.store.put(project["id"], MemoryInput(title=f"旧约定 {index}", content=f"认证相关旧说明 {index}"))
        worker.store.set_state(project["id"], stale["id"], stale["version"], "stale")
    active = worker.store.put(project["id"], stable_key="project:auth", source_updated_at="2026-01-01",
                              data=MemoryInput(title="当前约定", content="认证使用本机配置"))
    _, ids, details = worker.recall_with_details(session["id"], project["id"], "认证")
    # 非活跃条目在候选截取前就被排除，活跃条目一定进入实际请求。
    assert ids == [active["id"]]
    excluded = [item for item in details if item["decision"] != "included"]
    assert excluded and len(excluded) <= 4
    assert all(item["reason"] == "stale" for item in excluded)
    assert all(item["memory_id"] != active["id"] for item in excluded)


def test_manual_preference_kept_and_generated_zero_match_excluded(worker):  # noqa: F811
    enable(worker, generate_memories=False)
    project, session = project_session(worker.owner.store)
    manual = worker.store.put(project["id"], MemoryInput(scope="user", kind="preference", title="语言", content="始终使用简体中文"))
    # 人工 project 事实与查询无关时不再强制注入。
    project_fact = worker.store.put(project["id"], MemoryInput(title="发布流程", content="发布前核对变更清单"))
    generated = worker.store.put(project["id"], stable_key="project:ci", source_updated_at="2026-01-01",
                                 data=MemoryInput(title="持续集成", content="合并前等待流水线通过"))
    _, ids, details = worker.recall_with_details(session["id"], project["id"], "认证")
    assert manual["id"] in ids and generated["id"] not in ids and project_fact["id"] not in ids
    entry = next(item for item in details if item["memory_id"] == manual["id"])
    # 偏好保底不伪装成关键词命中：原因单独标注，匹配词与信号为空。
    assert entry["reason"] == "preference_floor" and entry["decision"] == "included"
    assert entry["matched_terms"] == [] and entry["matched_signals"] == []
    # 人工维护只提供参考候选，不改变作用域与权限语义。
    assert entry["scope"] == "user"


def test_manual_preference_floor_is_bounded_and_after_relevant_hits(worker):  # noqa: F811
    enable(worker, generate_memories=False)
    project, session = project_session(worker.owner.store)
    relevant = worker.store.put(project["id"], MemoryInput(kind="preference", title="认证偏好", content="认证失败先看日志"))
    floors = [worker.store.put(project["id"], MemoryInput(kind="preference", title=f"偏好 {index}", content=f"无关偏好 {index}"))
              for index in range(4)]
    _, ids, details = worker.recall_with_details(session["id"], project["id"], "认证")
    assert ids[0] == relevant["id"]
    floor_ids = [item["memory_id"] for item in details if item.get("reason") == "preference_floor"]
    assert len(floor_ids) <= 2
    assert set(floor_ids) <= {item["id"] for item in floors}


def test_empty_query_filters_inactive_before_slicing(worker):  # noqa: F811
    enable(worker, generate_memories=False)
    project, session = project_session(worker.owner.store)
    for index in range(21):
        stale = worker.store.put(project["id"], MemoryInput(title=f"旧记录 {index}", content=f"旧内容 {index}"))
        worker.store.set_state(project["id"], stale["id"], stale["version"], "stale")
    active = worker.store.put(project["id"], MemoryInput(title="当前记录", content="当前有效内容"))
    messages, ids, details = worker.recall_with_details(session["id"], project["id"], "")
    assert ids == [active["id"]] and messages
    assert all(item["decision"] == "included" for item in details)


def test_use_switch_off_and_forgotten_memory_are_not_recalled(worker):  # noqa: F811
    enable(worker, generate_memories=False)
    project, session = project_session(worker.owner.store)
    item = worker.store.put(project["id"], MemoryInput(title="认证", content="认证使用本机配置"))
    assert item["id"] in worker.recall_with_details(session["id"], project["id"], "认证")[1]
    settings = worker.store.session(session["id"])
    worker.store.save_session(session["id"], False, True, settings["version"])
    assert worker.recall_with_details(session["id"], project["id"], "认证")[1] == []
    settings = worker.store.session(session["id"])
    worker.store.save_session(session["id"], True, True, settings["version"])
    assert item["id"] in worker.recall_with_details(session["id"], project["id"], "认证")[1]
    worker.store.forget(project["id"], item["id"], item["version"])
    assert worker.recall_with_details(session["id"], project["id"], "认证")[1] == []


@pytest.mark.asyncio
async def test_long_goal_tail_memory_reaches_model_request(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    runtime = app.state.desktop.runtime
    try:
        enable(runtime.memories, generate_memories=False)
        record = runtime.memories.store.put(body["project_id"],
                                            MemoryInput(title="交付位置", content="交付清单写在 docs/交付清单.md"))
        goal = "背景说明。" * 150 + "只需说明 docs/交付清单.md 的用途，不要修改文件。"
        server.responses = [response(text="已理解要求")]
        run = (await client.post("/agent-runs", json={**body, "message": goal})).json()
        await asyncio.wait_for(runtime.tasks[run["id"]], 60)
        final = runtime.store.run(run["id"])
        assert final["status"] == "completed", final.get("error_message")
        request = [json.loads(raw)["request"] for path, raw in server.calls if path == "/desktop/model/complete"][-1]
        assert "交付清单写在 docs/交付清单.md" in json.dumps(request, ensure_ascii=False)
        stored = runtime.store.run(run["id"])
        assert record["id"] in stored["memory_context"]["recalled_ids"]
        assert stored["memory_context"]["query_signals"] == ["goal", "paths"]
    finally:
        await close(app, client)
