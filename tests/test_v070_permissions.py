"""v0.7.0 E4 权限与模型 profile 测试（E0 契约 §4/§5 落地）。

冻结依据：``docs/releases/v0.7.0/v0.7.0-e0-contracts-20260821.md``。

覆盖：
- 权限三模式能力映射与 run 快照组装（7 字段契约，只存非秘密摘要，
  默认最小权限 readonly，远程数据策略 no_send）；
- 模型 profile service + capability API（flag 门控 409，schema 无 secret
  字段，能力显式声明不通过名称猜测）；
- run 创建校验：permission_mode_invalid / model_profile_not_found /
  model_profile_unsupported（不支持原生工具调用的模型不能进入 Coding
  执行循环）；
- dispatcher 按 run 权限模式构建：readonly 不注册写工具（模型不可见 =
  零写入入口），workspace 命令 risk 动态化（项目全 safe → 自动允许，
  restricted 永不因模式切换自动获批，执行时拦截）；
- 历史 run 不因 profile 变化修改（快照一次性写入）。
"""
from __future__ import annotations

import hashlib
import sys
from uuid import uuid4

import pytest
from sqlalchemy import delete

from personal_assistant.agents import (
    AgentRunLimits,
    AgentRunRepository,
    CancellationToken,
    ToolCall,
    ToolRiskLevel,
)
from personal_assistant.api import routes_agent_runs
from personal_assistant.api.routes_agent_runs import get_agent_tool_bundle
from personal_assistant.config import settings as cfg
from personal_assistant.core.models import (
    AgentRun as AgentRunRecord,
)
from personal_assistant.core.models import (
    Project,
    ProjectCommandProfile,
    ProjectWorkspace,
)
from personal_assistant.core.permission_modes import (
    PERMISSION_MODE_DEFAULT,
    REMOTE_PROVIDER_DATA_POLICY_DEFAULT,
    build_permission_snapshot,
    permission_mode_capabilities,
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ===========================================================================
# A. 单元：权限模式映射与快照组装（E0 §4.1/§4.2）
# ===========================================================================


def test_permission_mode_capabilities_three_modes():
    """三模式能力映射：readonly 只读；confirm/workspace 读写 + 进程。"""
    assert permission_mode_capabilities("readonly") == frozenset(
        {"filesystem.read"}
    )
    assert permission_mode_capabilities("confirm") == frozenset(
        {"filesystem.read", "filesystem.write", "process.execute"}
    )
    assert permission_mode_capabilities("workspace") == frozenset(
        {"filesystem.read", "filesystem.write", "process.execute"}
    )


def test_permission_mode_capabilities_rejects_legacy_and_unknown():
    """read_only/full_access 与未知模式不再是合法值（替换 C0-D07 集合）。"""
    for legacy in ("read_only", "full_access", "admin", None):
        with pytest.raises(ValueError):
            permission_mode_capabilities(legacy)


def test_permission_mode_default_is_minimal():
    """默认权限模式是最小权限 readonly（E4 退出条件「默认最小」）。"""
    assert PERMISSION_MODE_DEFAULT == "readonly"


def test_build_permission_snapshot_contract_fields():
    """快照 7 字段契约：模式/能力/workspace 摘要/命令 profile 版本/
    Patch 硬上限/远程数据策略（默认 no_send）。"""
    snapshot = build_permission_snapshot(
        permission_mode="confirm",
        workspace_id=7,
        workspace_root_sha256="a" * 64,
        command_profile_version=3,
        max_patchset_files=32,
        max_patchset_total_bytes=5 * 1024 * 1024,
    )
    assert snapshot["permission_mode"] == "confirm"
    assert snapshot["capabilities"] == [
        "filesystem.read",
        "filesystem.write",
        "process.execute",
    ]
    assert snapshot["workspace"] == {
        "id": 7,
        "root_path_sha256": "a" * 64,
    }
    assert snapshot["command_profile_version"] == 3
    assert snapshot["patch_limits"] == {
        "max_files": 32,
        "max_total_bytes": 5 * 1024 * 1024,
    }
    assert snapshot["remote_provider_data_policy"] == "no_send"
    assert REMOTE_PROVIDER_DATA_POLICY_DEFAULT == "no_send"


def test_build_permission_snapshot_never_contains_root_path():
    """快照只存 root_path_sha256 摘要，绝不包含 root_path 原文（路径值）。"""
    root_path = "F:/Program/Example/secret-project"
    snapshot = build_permission_snapshot(
        permission_mode="readonly",
        workspace_id=1,
        workspace_root_sha256=_sha256_text(root_path),
        max_patchset_files=32,
        max_patchset_total_bytes=5 * 1024 * 1024,
    )
    payload = str(snapshot)
    assert root_path not in payload
    assert "root_path_sha256" in payload  # 字段名允许，路径原文禁止
    assert snapshot["workspace"]["root_path_sha256"] == _sha256_text(root_path)


def test_build_permission_snapshot_readonly_has_no_write_capability():
    """readonly 快照能力集合不含任何写/进程/网络能力（可解释且最小）。"""
    snapshot = build_permission_snapshot(
        permission_mode="readonly",
        max_patchset_files=32,
        max_patchset_total_bytes=5 * 1024 * 1024,
    )
    assert snapshot["capabilities"] == ["filesystem.read"]
    assert "workspace" not in snapshot
    assert "command_profile_version" not in snapshot


# ===========================================================================
# B. 模型 profile service 与 capability API（E0 §5）
# ===========================================================================


def test_model_profile_upsert_request_has_no_secret_field():
    """profile 设置 schema 无任何 secret/token/API key 字段（凭据边界）。"""
    from personal_assistant.api.routes_model_profiles import (
        ModelProfileUpsertRequest,
    )

    fields = set(ModelProfileUpsertRequest.model_fields)
    assert "secret" not in fields
    assert "api_key" not in fields
    assert "token" not in fields
    assert "credential" not in fields
    assert "provider_api_key" not in fields
    # 能力显式声明字段存在（不通过名称猜测模型能力）
    assert "native_tool_calls" in fields
    assert "is_local" in fields
    assert "context_tokens" in fields


async def test_model_profiles_api_flag_gated(client, monkeypatch):
    """flag 关闭时 capability API 全部 409 coding_mode_disabled。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "coding_permission_models_enabled", False)
    monkeypatch.setattr(cfg, "coding_permission_models_enabled", False)
    payload = {
        "provider": "ollama",
        "display_name": "local-coder",
        "native_tool_calls": True,
    }
    resp = await client.get("/agent-model-profiles")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "coding_mode_disabled"
    resp = await client.put("/agent-model-profiles/local-coder", json=payload)
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "coding_mode_disabled"
    resp = await client.delete("/agent-model-profiles/local-coder")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "coding_mode_disabled"


async def test_model_profiles_api_crud(client, monkeypatch):
    """flag 开启时 upsert/列表/详情/删除闭环；能力字段显式声明。"""
    monkeypatch.setattr(cfg, "coding_permission_models_enabled", True)

    payload = {
        "provider": "ollama",
        "display_name": "本地编码模型",
        "is_local": True,
        "native_tool_calls": True,
        "supports_streaming": True,
        "supports_structured_output": True,
        "context_tokens": 65536,
        "reasoning_efforts": ["low", "high"],
    }
    resp = await client.put("/agent-model-profiles/local-coder", json=payload)
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["id"] == "local-coder"
    assert created["native_tool_calls"] is True
    assert created["reasoning_efforts"] == ["low", "high"]

    resp = await client.get("/agent-model-profiles")
    assert resp.status_code == 200
    # 共享测试 DB 无事务回滚，可能残留其他用例的 profile；只断言本用例创建项存在
    ids = [p["id"] for p in resp.json()]
    assert "local-coder" in ids

    resp = await client.get("/agent-model-profiles/local-coder")
    assert resp.status_code == 200
    assert resp.json()["provider"] == "ollama"

    # upsert 更新（幂等）：切换 native_tool_calls 能力声明
    payload["native_tool_calls"] = False
    resp = await client.put("/agent-model-profiles/local-coder", json=payload)
    assert resp.status_code == 200
    assert resp.json()["native_tool_calls"] is False

    resp = await client.delete("/agent-model-profiles/local-coder")
    assert resp.status_code == 204
    resp = await client.get("/agent-model-profiles/local-coder")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "model_profile_not_found"


async def test_model_profiles_api_invalid_payload(client, monkeypatch):
    """非法 profile 字段 → 422 model_profile_invalid，零写入。"""
    monkeypatch.setattr(cfg, "coding_permission_models_enabled", True)
    resp = await client.put(
        "/agent-model-profiles/bad",
        json={"provider": "", "display_name": "x"},
    )
    assert resp.status_code == 422
    # context_tokens 下限 1
    resp = await client.put(
        "/agent-model-profiles/bad",
        json={
            "provider": "ollama",
            "display_name": "x",
            "context_tokens": 0,
        },
    )
    assert resp.status_code == 422


async def test_model_profile_service_validate_for_coding(db):
    """validate_for_coding：不存在 → NotFound；禁用/无原生工具调用 →
    Unsupported。"""
    from personal_assistant.core.model_profiles import (
        ModelProfileNotFound,
        ModelProfileService,
        ModelProfileUnsupported,
    )

    service = ModelProfileService(db)
    with pytest.raises(ModelProfileNotFound):
        await service.validate_for_coding("missing-profile")

    await service.upsert(
        "no-tools",
        {
            "provider": "ollama",
            "display_name": "no tools",
            "native_tool_calls": False,
            "context_tokens": 8192,
        },
    )
    with pytest.raises(ModelProfileUnsupported):
        await service.validate_for_coding("no-tools")

    await service.upsert(
        "disabled",
        {
            "provider": "ollama",
            "display_name": "disabled",
            "native_tool_calls": True,
            "context_tokens": 8192,
            "enabled": False,
        },
    )
    with pytest.raises(ModelProfileUnsupported):
        await service.validate_for_coding("disabled")

    await service.upsert(
        "ok-coder",
        {
            "provider": "ollama",
            "display_name": "ok",
            "native_tool_calls": True,
            "context_tokens": 8192,
        },
    )
    assert await service.validate_for_coding("ok-coder") is not None

    # 清理本用例创建的 profile（共享测试 DB 无事务回滚）
    from sqlalchemy import delete

    from personal_assistant.core.models import ModelProfile

    await db.execute(
        delete(ModelProfile).where(
            ModelProfile.id.in_(["no-tools", "disabled", "ok-coder"])
        )
    )
    await db.commit()


# ===========================================================================
# C. API：coding run 创建校验（E0 §4.1/§5 + E4 退出条件）
# ===========================================================================


async def _create_coding_env(client, tmp_path) -> dict:
    """API 创建 project + workspace + coding session，返回绑定信息。"""
    root = str((tmp_path / "ws").resolve())
    (tmp_path / "ws").mkdir()
    resp = await client.post(
        "/projects", json={"name": f"e4-{uuid4().hex[:8]}", "root_path": root}
    )
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["id"]
    resp = await client.post(f"/projects/{project_id}/workspaces/root/ensure")
    assert resp.status_code == 201, resp.text
    ws_id = resp.json()["id"]
    resp = await client.post(
        "/sessions",
        json={
            "title": "coding",
            "project_id": project_id,
            "workspace_id": ws_id,
            "kind": "coding",
        },
    )
    assert resp.status_code == 201, resp.text
    return {
        "project_id": project_id,
        "workspace_id": ws_id,
        "session_id": resp.json()["id"],
        "root": root,
    }


async def _post_coding_run(client, env: dict, **overrides) -> object:
    payload: dict = {
        "session_id": env["session_id"],
        "message": "e4-permission-test",
        "project_id": env["project_id"],
        "workspace_id": env["workspace_id"],
        "permission_mode": "confirm",
        "client_request_id": str(uuid4()),
    }
    payload.update(overrides)
    return await client.post("/agent-runs", json=payload)


async def test_legacy_permission_modes_rejected(client, monkeypatch, tmp_path):
    """read_only / full_access 创建 coding run → 422 permission_mode_invalid。

    （E0 契约 §4.1：read_only/full_access 不再是合法值；E4 实现解除 xfail）
    """
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    env = await _create_coding_env(client, tmp_path)
    for legacy in ("read_only", "full_access"):
        resp = await _post_coding_run(
            client, env, permission_mode=legacy
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["error_code"] == "permission_mode_invalid"


async def test_no_native_tool_calls_model_rejected_for_coding(
    client, monkeypatch, tmp_path
):
    """不支持原生工具调用的模型 profile 不能进入 Coding 执行循环。

    （E0 契约 §5：native_tool_calls=False → 422 model_profile_unsupported；
    E4 实现解除 xfail）
    """
    monkeypatch.setattr(cfg, "coding_permission_models_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    _enable_coding_flags(monkeypatch)
    env = await _create_coding_env(client, tmp_path)

    # 不存在的 profile → 404 model_profile_not_found
    resp = await _post_coding_run(client, env, model_profile_id="missing")
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "model_profile_not_found"

    # 不支持原生工具调用 → 422 model_profile_unsupported（仅限只读问答）
    await client.put(
        "/agent-model-profiles/qa-only",
        json={
            "provider": "ollama",
            "display_name": "QA only",
            "native_tool_calls": False,
        },
    )
    resp = await _post_coding_run(client, env, model_profile_id="qa-only")
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "model_profile_unsupported"

    # 支持原生工具调用 → 通过（进入 coding 校验链）
    await client.put(
        "/agent-model-profiles/local-coder",
        json={
            "provider": "ollama",
            "display_name": "coder",
            "native_tool_calls": True,
        },
    )
    captured: dict = {}

    def fake_start(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(routes_agent_runs.agent_run_coordinator, "start", fake_start)
    resp = await _post_coding_run(client, env, model_profile_id="local-coder")
    assert resp.status_code == 202, resp.text
    assert captured["run_id"] == resp.json()["id"]
    # 模型可见定义集包含写工具（confirm 模式重建）
    tool_names = {d.name for d in captured["tool_definitions"]}
    assert "apply_patch_set" in tool_names
    assert "run_whitelisted_command" in tool_names


async def test_coding_run_default_permission_mode_readonly(
    client, monkeypatch, tmp_path, db
):
    """未显式指定 permission_mode → 默认最小权限 readonly 并落库/快照。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    env = await _create_coding_env(client, tmp_path)
    captured: dict = {}

    def fake_start(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(routes_agent_runs.agent_run_coordinator, "start", fake_start)
    payload: dict = {
        "session_id": env["session_id"],
        "message": "default-mode",
        "project_id": env["project_id"],
        "workspace_id": env["workspace_id"],
        "client_request_id": str(uuid4()),
    }
    resp = await client.post("/agent-runs", json=payload)
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]
    try:
        assert resp.json()["permission_mode"] == "readonly"
        run = await db.get(AgentRunRecord, run_id)
        assert run.permission_mode == "readonly"
        assert run.permission_snapshot_json["permission_mode"] == "readonly"
        assert run.permission_snapshot_json["capabilities"] == ["filesystem.read"]
        # 模型可见定义集不暴露写工具（readonly = 零写入入口）
        assert not any(
            d.name in ("apply_patch_set", "run_whitelisted_command")
            for d in captured.get("tool_definitions", ())
        )
    finally:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
        await db.commit()


async def test_coding_run_permission_snapshot_complete(client, monkeypatch, tmp_path, db):
    """confirm coding run 快照 7 字段完整；workspace 只存 sha256 摘要。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    env = await _create_coding_env(client, tmp_path)

    def fake_start(**kwargs) -> None:
        del kwargs

    monkeypatch.setattr(routes_agent_runs.agent_run_coordinator, "start", fake_start)
    resp = await _post_coding_run(client, env, permission_mode="confirm")
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]
    try:
        run = await db.get(AgentRunRecord, run_id)
        snapshot = run.permission_snapshot_json
        assert snapshot["permission_mode"] == "confirm"
        assert snapshot["capabilities"] == [
            "filesystem.read",
            "filesystem.write",
            "process.execute",
        ]
        assert snapshot["workspace"]["id"] == env["workspace_id"]
        # 快照 sha 与 workspace 表事实源一致（Windows 大小写不敏感哈希）
        ws = await db.get(ProjectWorkspace, env["workspace_id"])
        assert snapshot["workspace"]["root_path_sha256"] == ws.root_path_sha256
        # 路径原文禁止出现在快照（只存 sha256 摘要）
        assert env["root"] not in str(snapshot)
        assert snapshot["patch_limits"] == {"max_files": 32, "max_total_bytes": 5 * 1024 * 1024}
        assert snapshot["remote_provider_data_policy"] == "no_send"
    finally:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
        await db.commit()


async def test_historical_run_snapshot_unchanged_after_profile_change(
    client, monkeypatch, tmp_path, db
):
    """profile 变化不修改历史 run（快照一次性；E4 退出条件）。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    env = await _create_coding_env(client, tmp_path)

    def fake_start(**kwargs) -> None:
        del kwargs

    monkeypatch.setattr(routes_agent_runs.agent_run_coordinator, "start", fake_start)
    resp = await _post_coding_run(client, env, permission_mode="confirm")
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]
    try:
        run = await db.get(AgentRunRecord, run_id)
        assert run.permission_snapshot_json.get("command_profile_version") is None

        # 创建 profile 后再跑一个 run：快照含版本 1
        from personal_assistant.core.repo_patch_sets import (
            ProjectCommandProfileRepository,
        )

        profile_repo = ProjectCommandProfileRepository(db)
        profile = await profile_repo.create(
            project_id=env["project_id"],
            name=f"e4-{uuid4().hex[:6]}",
            command_json={"args": [sys.executable, "-m", "pytest"]},
            kind="test",
            risk_level="safe",
        )
        profile_id = profile.id
        # 结束 create 内部 refresh 开启的悬空读事务，避免 MySQL REPEATABLE
        # READ 快照看不到后续 HTTP 请求提交的 run（连接池时序不定）。
        await db.commit()
        resp2 = await _post_coding_run(client, env, permission_mode="confirm")
        assert resp2.status_code == 202, resp2.text
        run2 = await db.get(AgentRunRecord, resp2.json()["id"])
        assert run2.permission_snapshot_json["command_profile_version"] == 1

        # 版本递增后：新 run 快照 2，历史 run（run/run2）不变
        await profile_repo.update(
            profile_id, profile_version=2, risk_level="safe"
        )
        resp3 = await _post_coding_run(client, env, permission_mode="confirm")
        assert resp3.status_code == 202, resp3.text
        run3 = await db.get(AgentRunRecord, resp3.json()["id"])
        assert run3.permission_snapshot_json["command_profile_version"] == 2
        # 历史 run 快照不因 profile 版本变化而修改（键可省略，用 .get）
        assert run.permission_snapshot_json.get("command_profile_version") is None
        assert run2.permission_snapshot_json["command_profile_version"] == 1
    finally:
        await db.execute(
            delete(ProjectCommandProfile).where(
                ProjectCommandProfile.project_id == env["project_id"]
            )
        )
        await db.execute(
            delete(AgentRunRecord).where(AgentRunRecord.project_id == env["project_id"])
        )
        await db.execute(delete(ProjectWorkspace).where(ProjectWorkspace.project_id == env["project_id"]))
        await db.execute(delete(Project).where(Project.id == env["project_id"]))
        await db.commit()


# ===========================================================================
# D. dispatcher 按权限模式构建（E0 §4.1；模型可见性 = 零写入入口）
# ===========================================================================


async def _make_project(db, tmp_path) -> tuple[int, int]:
    project = Project(name=f"e4d-{uuid4().hex[:8]}", root_path=str(tmp_path))
    db.add(project)
    await db.commit()
    await db.refresh(project)
    workspace = ProjectWorkspace(
        project_id=project.id,
        kind="root",
        root_path=str(tmp_path),
        root_path_sha256=_sha256_text(str(tmp_path)),
        status="active",
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return project.id, workspace.id


async def _create_profile(
    db,
    project_id: int,
    *,
    args: list[str],
    risk_level: str = "confirm",
    name: str | None = None,
    version: int = 1,
) -> int:
    profile = ProjectCommandProfile(
        project_id=project_id,
        name=name or f"e4p-{uuid4().hex[:6]}",
        command_json={"args": args},
        kind="test",
        timeout_seconds=60,
        enabled=True,
        profile_version=version,
        result_parser="plain",
        max_output_bytes=64 * 1024,
        risk_level=risk_level,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile.id


async def _create_run(
    db,
    *,
    project_id: int,
    workspace_id: int,
    permission_mode: str,
    model_profile_id: str | None = None,
    tool_call_id: str | None = None,
) -> str:
    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    await repository.create_run(
        run_id=run_id,
        limits=AgentRunLimits(),
        project_id=project_id,
        workspace_id=workspace_id,
        model_profile_id=model_profile_id,
        permission_mode=permission_mode,
        permission_snapshot_json={
            "permission_mode": permission_mode,
            "capabilities": sorted(permission_mode_capabilities(permission_mode)),
            "remote_provider_data_policy": "no_send",
            "patch_limits": {"max_files": 32, "max_total_bytes": 5 * 1024 * 1024},
        },
        client_request_id=str(uuid4()),
    )
    if tool_call_id is not None:
        # 记录 run.started + tool.requested 事件创建 active tool step
        # （首个事件必须是 run.started；execution claim 依赖 tool step）
        from personal_assistant.agents import AgentEvent, AgentEventType

        await repository.record_event(
            AgentEvent(
                run_id=run_id,
                sequence=1,
                type=AgentEventType.RUN_STARTED,
            )
        )
        await repository.record_event(
            AgentEvent(
                run_id=run_id,
                sequence=2,
                type=AgentEventType.TOOL_REQUESTED,
                step_id=str(uuid4()),
                payload={
                    "ordinal": 1,
                    "kind": "tool",
                    "tool_call_id": tool_call_id,
                    "name": "tool",
                },
            )
        )
    return run_id


async def _cleanup(db, *, run_id=None, project_id=None, workspace_id=None) -> None:
    if run_id:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    if workspace_id:
        await db.execute(
            delete(ProjectWorkspace).where(ProjectWorkspace.id == workspace_id)
        )
    if project_id:
        await db.execute(
            delete(ProjectCommandProfile).where(
                ProjectCommandProfile.project_id == project_id
            )
        )
        await db.execute(delete(Project).where(Project.id == project_id))
    await db.commit()


def _enable_coding_flags(monkeypatch) -> None:
    """开启 dispatcher 构建所需 flags（bundle 构建依赖）。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_run_read_only_tools_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", False)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_command_workflow_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "coding_patchset_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_http_workflow_enabled", False)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_sql_readonly_workflow_enabled", False)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_rag_tools_enabled", False)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_run_plan_enabled", False)
    monkeypatch.setattr(routes_agent_runs.cfg, "mcp_enabled", False)


async def test_readonly_dispatcher_hides_write_tools(db, tmp_path, monkeypatch):
    """readonly run：写工具不注册（apply_patch_set/run_whitelisted_command
    模型不可见），只读工具与 propose_patch_set 保留。"""
    _enable_coding_flags(monkeypatch)
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_run(
        db,
        project_id=project_id,
        workspace_id=workspace_id,
        permission_mode="readonly",
    )
    try:
        bundle = await get_agent_tool_bundle(db)
        assert bundle is not None
        dispatcher = await bundle.dispatcher_factory(db, run_id)
        names = {d.name for d in dispatcher.model_definitions()}
        assert "propose_patch_set" in names
        assert "apply_patch_set" not in names
        assert "run_whitelisted_command" not in names
        assert "propose_patch" in names  # 单文件只读预览保留（可回退性）
    finally:
        await _cleanup(db, run_id=run_id, project_id=project_id, workspace_id=workspace_id)


async def test_confirm_dispatcher_registers_write_tools(db, tmp_path, monkeypatch):
    """confirm run：写工具注册且命令工具 risk=confirm（审批把关）。"""
    _enable_coding_flags(monkeypatch)
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_run(
        db,
        project_id=project_id,
        workspace_id=workspace_id,
        permission_mode="confirm",
    )
    try:
        bundle = await get_agent_tool_bundle(db)
        assert bundle is not None
        dispatcher = await bundle.dispatcher_factory(db, run_id)
        names = {d.name for d in dispatcher.model_definitions()}
        assert "apply_patch_set" in names
        assert "run_whitelisted_command" in names
        command_spec = bundle_dispatcher_spec(dispatcher, "run_whitelisted_command")
        assert command_spec.risk_level == ToolRiskLevel.CONFIRM
        patch_spec = bundle_dispatcher_spec(dispatcher, "apply_patch_set")
        assert patch_spec.risk_level == ToolRiskLevel.CONFIRM
    finally:
        await _cleanup(db, run_id=run_id, project_id=project_id, workspace_id=workspace_id)


def bundle_dispatcher_spec(dispatcher, name):
    """取 dispatcher 内部注册表 spec（测试钩子）。"""
    registry = dispatcher._registry
    return registry.get(name)


async def test_workspace_dispatcher_command_risk_safe_when_all_profiles_safe(
    db, tmp_path, monkeypatch
):
    """workspace + 项目全 safe profile → 命令工具 risk=safe（自动允许）。"""
    _enable_coding_flags(monkeypatch)
    project_id, workspace_id = await _make_project(db, tmp_path)
    await _create_profile(
        db, project_id, args=[sys.executable, "-m", "pytest"], risk_level="safe"
    )
    run_id = await _create_run(
        db,
        project_id=project_id,
        workspace_id=workspace_id,
        permission_mode="workspace",
    )
    try:
        bundle = await get_agent_tool_bundle(db)
        assert bundle is not None
        dispatcher = await bundle.dispatcher_factory(db, run_id)
        command_spec = bundle_dispatcher_spec(dispatcher, "run_whitelisted_command")
        assert command_spec.risk_level == ToolRiskLevel.SAFE
    finally:
        await _cleanup(db, run_id=run_id, project_id=project_id, workspace_id=workspace_id)


async def test_workspace_dispatcher_command_risk_confirm_when_mixed_profiles(
    db, tmp_path, monkeypatch
):
    """workspace + 存在 confirm/restricted profile → 整体确认（审批把关）。"""
    _enable_coding_flags(monkeypatch)
    project_id, workspace_id = await _make_project(db, tmp_path)
    await _create_profile(
        db, project_id, args=[sys.executable, "-m", "pytest"], risk_level="safe"
    )
    await _create_profile(
        db,
        project_id,
        args=[sys.executable, "-m", "ruff"],
        risk_level="confirm",
        name="ruff-confirm",
    )
    run_id = await _create_run(
        db,
        project_id=project_id,
        workspace_id=workspace_id,
        permission_mode="workspace",
    )
    try:
        bundle = await get_agent_tool_bundle(db)
        assert bundle is not None
        dispatcher = await bundle.dispatcher_factory(db, run_id)
        command_spec = bundle_dispatcher_spec(dispatcher, "run_whitelisted_command")
        assert command_spec.risk_level == ToolRiskLevel.CONFIRM
    finally:
        await _cleanup(db, run_id=run_id, project_id=project_id, workspace_id=workspace_id)


async def test_workspace_safe_command_executes_without_approval(
    db, tmp_path, monkeypatch
):
    """workspace + safe profile：命令自动允许，真实执行成功且零审批记录。"""
    _enable_coding_flags(monkeypatch)
    project_id, workspace_id = await _make_project(db, tmp_path)
    await _create_profile(
        db, project_id, args=[sys.executable, "-m", "pytest"], risk_level="safe"
    )
    # 项目内放一个可通过的测试文件，保证 pytest 退出码 0
    (tmp_path / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    run_id = await _create_run(
        db,
        project_id=project_id,
        workspace_id=workspace_id,
        permission_mode="workspace",
        tool_call_id="call-safe",
    )
    try:
        bundle = await get_agent_tool_bundle(db)
        assert bundle is not None
        dispatcher = await bundle.dispatcher_factory(db, run_id)
        result = await dispatcher.execute(
            ToolCall(
                id="call-safe",
                name="run_whitelisted_command",
                arguments={
                    "project_id": project_id,
                    "command": [sys.executable, "-m", "pytest", "-q"],
                },
            ),
            cancellation=CancellationToken(),
        )
        assert result.success is True, result.error
        assert result.output["succeeded"] is True
        # 零 pending approval（safe 自动允许，不产生审批记录）
        from personal_assistant.agents import ToolApprovalRepository

        approvals = await ToolApprovalRepository(db).list_for_run(run_id)
        assert all(a.status != "pending" for a in approvals)
        # durable execution 落库（verified 事实）
        from personal_assistant.agents import ToolExecutionRepository

        executions = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
        assert len(executions) == 1
        assert executions[0].status == "succeeded"
    finally:
        await _cleanup(db, run_id=run_id, project_id=project_id, workspace_id=workspace_id)


async def _execute_with_approval_flow(db, bundle, run_id, call):
    """restricted 场景：先请求审批，再批准，最后用消费绑定重新执行。

    restricted profile 使命令工具整体 risk=CONFIRM（审批把关）；批准后
    executor 仍按匹配 profile 的 restricted 标记拒绝（永不自动获批）。
    """
    from personal_assistant.agents import ToolApprovalRepository

    pending = await (await bundle.dispatcher_factory(db, run_id)).execute(
        call, cancellation=CancellationToken()
    )
    assert pending.success is False
    assert pending.error_code == "approval_required"
    approvals = await ToolApprovalRepository(db).list_for_run(run_id)
    assert len(approvals) == 1
    approved = await ToolApprovalRepository(db).approve(approvals[0].id)
    dispatcher = await bundle.resume_dispatcher_factory(
        db, run_id, approved.approval_id, approved.token
    )
    return await dispatcher.execute(call, cancellation=CancellationToken())


async def test_restricted_command_rejected_at_execution(db, tmp_path, monkeypatch):
    """restricted profile 匹配命令执行时拦截：即使审批通过也拒绝。"""
    _enable_coding_flags(monkeypatch)
    project_id, workspace_id = await _make_project(db, tmp_path)
    await _create_profile(
        db,
        project_id,
        args=[sys.executable, "-m", "pytest"],
        risk_level="restricted",
    )
    run_id = await _create_run(
        db,
        project_id=project_id,
        workspace_id=workspace_id,
        permission_mode="workspace",
        tool_call_id="call-restricted",
    )
    try:
        bundle = await get_agent_tool_bundle(db)
        assert bundle is not None
        call = ToolCall(
            id="call-restricted",
            name="run_whitelisted_command",
            arguments={
                "project_id": project_id,
                "command": [sys.executable, "-m", "pytest", "-q"],
            },
        )
        result = await _execute_with_approval_flow(db, bundle, run_id, call)
        assert result.success is False
        assert "restricted" in (result.error or "").lower()
        from personal_assistant.agents import ToolExecutionRepository

        executions = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
        assert executions[0].status == "failed"
    finally:
        await _cleanup(db, run_id=run_id, project_id=project_id, workspace_id=workspace_id)


async def test_profile_switch_does_not_auto_approve_existing_run(
    db, tmp_path, monkeypatch
):
    """run 创建后项目 profile 从 safe 改为 restricted：已创建 run 的命令
    执行仍被拦截（restricted 不因 profile 切换自动获批；执行时防御）。"""
    _enable_coding_flags(monkeypatch)
    project_id, workspace_id = await _make_project(db, tmp_path)
    profile_id = await _create_profile(
        db, project_id, args=[sys.executable, "-m", "pytest"], risk_level="safe"
    )
    run_id = await _create_run(
        db,
        project_id=project_id,
        workspace_id=workspace_id,
        permission_mode="workspace",
        tool_call_id="call-switch",
    )
    try:
        # run 创建后 profile 切换为 restricted（模拟后续配置变化）
        from personal_assistant.core.repo_patch_sets import (
            ProjectCommandProfileRepository,
        )

        await ProjectCommandProfileRepository(db).update(
            profile_id, risk_level="restricted", profile_version=2
        )
        bundle = await get_agent_tool_bundle(db)
        assert bundle is not None
        call = ToolCall(
            id="call-switch",
            name="run_whitelisted_command",
            arguments={
                "project_id": project_id,
                "command": [sys.executable, "-m", "pytest", "-q"],
            },
        )
        # 审批也不能让 restricted 命令执行（executor 二次拦截）
        result = await _execute_with_approval_flow(db, bundle, run_id, call)
        assert result.success is False
        assert "restricted" in (result.error or "").lower()
        # 历史 run 快照 command_profile_version 仍为创建时值
        run = await db.get(AgentRunRecord, run_id)
        assert run.permission_snapshot_json.get("command_profile_version") is None
    finally:
        await _cleanup(db, run_id=run_id, project_id=project_id, workspace_id=workspace_id)


async def test_readonly_run_tool_call_denied(db, tmp_path, monkeypatch):
    """readonly run 尝试调用写工具 → 未注册/拒绝（零写入入口）。"""
    _enable_coding_flags(monkeypatch)
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_run(
        db,
        project_id=project_id,
        workspace_id=workspace_id,
        permission_mode="readonly",
    )
    try:
        bundle = await get_agent_tool_bundle(db)
        assert bundle is not None
        dispatcher = await bundle.dispatcher_factory(db, run_id)
        result = await dispatcher.execute(
            ToolCall(
                id="call-write",
                name="apply_patch_set",
                arguments={"project_id": project_id, "operations": []},
            ),
            cancellation=CancellationToken(),
        )
        assert result.success is False
        assert result.error_code == "unknown_tool"
    finally:
        await _cleanup(db, run_id=run_id, project_id=project_id, workspace_id=workspace_id)
