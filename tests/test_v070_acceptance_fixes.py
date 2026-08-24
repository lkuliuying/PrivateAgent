"""v0.7.0 外部验收修复回归测试（4 项：P0-1/P0-2/P1-1/P1-2）。

依据：外部验收结论（2026-08-21）——0.7 暂不通过，2 个 P0 + 2 个 P1：

- P0-1 模型 profile 没有驱动实际 Provider（本地 profile 可能被全局远程路由
  带走；reasoning_effort 未生效；快照 remote_provider_data_policy 固定声明）。
- P0-2 项目命令可通过后缀参数越出 workspace（前缀白名单不校验剩余参数）。
- P1-1 PatchSet 在持久化终态前删除回滚备份（DB 失败留下幽灵状态）。
- P1-2 Windows 设备路径校验不完整（nul.txt/CON.md/com1.json 被接受；
  唯一性未按大小写归一化）。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete
from test_v070_patchset import (
    _apply_call,
    _cleanup,
    _create_coding_run,
    _make_project,
    _no_pa_leftovers,
    _op_create,
    _op_update,
    _request_approval_and_approve,
)
from test_v070_permissions import _create_coding_env, _post_coding_run

from personal_assistant.agents import (
    AgentRunLimits,
    AgentRunRepository,
    CancellationToken,
)
from personal_assistant.api import routes_agent_runs
from personal_assistant.config import settings as cfg
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import (
    ProjectCommandProfile,
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _enable_coding_flags(monkeypatch) -> None:
    monkeypatch.setattr(cfg, "coding_patchset_enabled", True)
    monkeypatch.setattr(cfg, "coding_command_profiles_enabled", True)
    monkeypatch.setattr(cfg, "coding_artifacts_enabled", True)
    monkeypatch.setattr(cfg, "coding_permission_models_enabled", True)
    monkeypatch.setattr(cfg, "agent_run_plan_enabled", True)


async def _delete_run(run_id: str) -> None:
    from personal_assistant.core.db import async_session_factory

    async with async_session_factory() as s:
        await s.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
        await s.commit()


_PROVIDER_SETTING_KEYS = [
    "provider_type",
    "remote_provider_enabled",
    "openai_api_key",
    "openai_model",
    "llm_temperature",
    "llm_context_length",
]


async def _reset_provider_settings(db) -> None:
    """清理测试写入的全局 Provider 设置（共享测试库防残留污染）。"""
    from personal_assistant.core.models import Setting

    await db.execute(
        delete(Setting).where(Setting.key.in_(_PROVIDER_SETTING_KEYS))
    )
    await db.commit()


# ===========================================================================
# P0-1：模型 profile 驱动实际 Provider
# ===========================================================================


async def _run_with_profile(db, project_id: int, workspace_id: int, profile_id: str):
    """创建带 model_profile_id 的 coding run，返回 run 记录。"""
    run_id = str(uuid4())
    await AgentRunRepository(db).create_run(
        run_id=run_id,
        limits=AgentRunLimits(),
        project_id=project_id,
        workspace_id=workspace_id,
        model_profile_id=profile_id,
        permission_mode="confirm",
        permission_snapshot_json={"permission_mode": "confirm"},
        client_request_id=str(uuid4()),
    )
    return await AgentRunRepository(db).get_run(run_id)


async def test_local_profile_forces_local_route_even_with_remote_enabled(
    db, tmp_path, monkeypatch
):
    """本地 profile 强制 Ollama 路由：即使全局启用远程 Provider 也不发送远程。"""
    from personal_assistant.core.model_profiles import ModelProfileService

    project_id, workspace_id = await _make_project(db, tmp_path)
    await ModelProfileService(db).upsert(
        "local-coder",
        {
            "provider": "ollama",
            "display_name": "Local",
            # v0.9.0 H1-D：具体模型路由字段（实际传给 Provider 的 model）
            "model_name": "local-route-model",
            "is_local": True,
            "native_tool_calls": True,
            "context_tokens": 32768,
        },
    )
    run = await _run_with_profile(db, project_id, workspace_id, "local-coder")

    async def _remote_settings(_self):
        # P0 场景：全局启用远程 OpenAI，但 run 绑定本地 profile
        return {
            "provider_type": "openai",
            "remote_provider_enabled": "true",
            "openai_api_key": "",
            "openai_model": "gpt-4o-mini",
            "llm_temperature": "0.7",
            "llm_context_length": "8192",
        }

    monkeypatch.setattr(routes_agent_runs.SettingsService, "get_all", _remote_settings)
    gateway = await routes_agent_runs._model_gateway_for_run(db, run)
    assert gateway.adapter.provider_name == "ollama"
    # v0.9.0 H1-D：实际 model = profile 路由字段（不回落全局 openai_model）
    assert gateway.adapter.model_name == "local-route-model"
    try:
        await ModelProfileService(db).delete("local-coder")
    finally:
        await _cleanup(
            db, run_id=run.id, project_id=project_id, workspace_id=workspace_id
        )


async def test_remote_profile_run_creation_rejected_without_remote(
    client, monkeypatch, tmp_path, db
):
    """远程 profile 在全局远程未启用时创建 coding run → 422（fail-fast）。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    _enable_coding_flags(monkeypatch)
    await _reset_provider_settings(db)
    env = await _create_coding_env(client, tmp_path)
    await client.put(
        "/agent-model-profiles/remote-coder",
        json={
            "provider": "openai",
            "display_name": "Remote",
            "is_local": False,
            "native_tool_calls": True,
        },
    )
    resp = await _post_coding_run(client, env, model_profile_id="remote-coder")
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "model_profile_unsupported"
    assert "远程 Provider 未启用" in resp.json()["detail"]
    await _reset_provider_settings(db)


async def test_remote_profile_drives_remote_route_and_snapshot_send(
    client, monkeypatch, tmp_path, db
):
    """远程 profile + 全局启用远程：coordinator 收到解析后的远程 gateway，
    快照 remote_provider_data_policy 如实声明 send。"""
    from personal_assistant.core.settings import SettingsService

    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    _enable_coding_flags(monkeypatch)
    await _reset_provider_settings(db)
    env = await _create_coding_env(client, tmp_path)
    # secret 保持原生凭据边界：只声明引用（不写入明文）
    await SettingsService(db).update(
        {
            "provider_type": "openai",
            "remote_provider_enabled": "true",
            "openai_api_key": "secret://os-keyring/provider/openai",
            "openai_model": "gpt-4o-mini",
        }
    )
    await client.put(
        "/agent-model-profiles/remote-coder",
        json={
            "provider": "openai",
            "display_name": "Remote",
            # v0.9.0 H1-D：具体模型路由字段（不回落全局 openai_model）
            "model_name": "gpt-4o-route",
            "is_local": False,
            "native_tool_calls": True,
        },
    )
    captured: dict = {}

    def fake_start(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(routes_agent_runs.agent_run_coordinator, "start", fake_start)
    resp = await _post_coding_run(client, env, model_profile_id="remote-coder")
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]
    try:
        # coordinator 收到按 profile 解析的远程 gateway（provider=openai_compatible）
        model = captured["model"]
        assert model.adapter.provider_name == "openai_compatible"
        # v0.9.0 H1-D：实际 model = profile 路由字段（快照 send 声明不变）
        assert model.adapter.model_name == "gpt-4o-route"
        # 独立 session 查询（HTTP 请求独立 session 提交，测试 session 的
        # REPEATABLE READ 快照看不到；沿用 E1 _run_events 约定）
        from personal_assistant.core.db import async_session_factory

        async with async_session_factory() as s:
            stored = await AgentRunRepository(s).get_run(run_id)
            assert stored is not None
            snapshot = stored.permission_snapshot_json or {}
            assert snapshot["remote_provider_data_policy"] == "send"
    finally:
        await _delete_run(run_id)
        await _reset_provider_settings(db)


async def test_reasoning_effort_validated_and_passed_to_coordinator(
    client, monkeypatch, tmp_path, db
):
    """reasoning_effort 必须落在 profile 声明集合；合法值透传到 coordinator。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    _enable_coding_flags(monkeypatch)
    env = await _create_coding_env(client, tmp_path)
    await client.put(
        "/agent-model-profiles/qa-only",
        json={
            "provider": "ollama",
            "display_name": "QA",
            "model_name": "qa-route-model",
            "native_tool_calls": True,
            "reasoning_efforts": ["low", "high"],
        },
    )
    resp = await _post_coding_run(
        client, env, model_profile_id="qa-only", reasoning_effort="medium"
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "model_profile_unsupported"
    assert "允许集合" in resp.json()["detail"]

    captured: dict = {}

    def fake_start(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(routes_agent_runs.agent_run_coordinator, "start", fake_start)
    resp = await _post_coding_run(
        client, env, model_profile_id="qa-only", reasoning_effort="high"
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]
    try:
        assert captured["reasoning_effort"] == "high"
        # 本地 profile 路由到 Ollama（不发送远程）
        assert captured["model"].adapter.provider_name == "ollama"
        stored = await AgentRunRepository(db).get_run(run_id)
        assert stored is not None and stored.reasoning_effort == "high"
    finally:
        await _delete_run(run_id)


async def test_openai_adapter_payload_carries_reasoning_effort(monkeypatch):
    """OpenAI 系请求体透传 reasoning_effort（OpenAI o 系列参数）。"""
    from personal_assistant.agents import ModelMessage, ModelRequest
    from personal_assistant.llm.adapters import OpenAIChatAdapter

    captured: dict = {}

    class _FakeResponse:
        def json(self):
            return {"choices": [{"message": {"content": "ok", "tool_calls": None}}]}

        @property
        def status_code(self):
            return 200

        def raise_for_status(self):
            return None

    async def _fake_post(self, url, **kwargs):
        captured["payload"] = kwargs.get("payload")
        return _FakeResponse()

    monkeypatch.setattr(OpenAIChatAdapter, "_post", _fake_post)
    adapter = OpenAIChatAdapter(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="o4-mini",
    )
    await adapter.complete(
        ModelRequest(
            messages=(ModelMessage(role="user", content="hi"),),
            reasoning_effort="high",
        ),
        cancellation=CancellationToken(),
    )
    assert captured["payload"]["reasoning_effort"] == "high"


async def test_profile_deleted_after_create_fails_closed(db, tmp_path):
    """run 创建后 profile 被删除：resume 解析失败关闭，不静默回退全局。"""
    from personal_assistant.core.model_profiles import (
        ModelProfileService,
        ModelProfileUnsupported,
    )

    project_id, workspace_id = await _make_project(db, tmp_path)
    await ModelProfileService(db).upsert(
        "doomed",
        {"provider": "ollama", "display_name": "Doomed", "native_tool_calls": True},
    )
    run = await _run_with_profile(db, project_id, workspace_id, "doomed")
    await ModelProfileService(db).delete("doomed")
    try:
        with pytest.raises(ModelProfileUnsupported):
            await routes_agent_runs._model_gateway_for_run(db, run)
    finally:
        await _cleanup(
            db, run_id=run.id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# P0-2：项目命令后缀参数不得越出 workspace
# ===========================================================================


async def _make_project_with_profiles(db, tmp_path: Path, profiles: list[dict]):
    project_id, workspace_id = await _make_project(db, tmp_path)
    for profile in profiles:
        db.add(
            ProjectCommandProfile(
                project_id=project_id,
                name=profile["name"],
                command_json={"args": profile["args"]},
                kind="custom",
                timeout_seconds=30,
                enabled=True,
                profile_version=1,
                result_parser="plain",
            )
        )
    await db.commit()
    return project_id, workspace_id


async def test_command_profile_rejects_out_of_workspace_args(db, tmp_path):
    """验收复现三案例（cargo --manifest-path / npm --prefix / pytest 绝对路径）
    全部拒绝；工作区内相对路径允许；等号形式与 .. 越界同样拒绝。"""
    from personal_assistant.core.command_workflow import _resolve_command
    from personal_assistant.core.permissions import PermissionError_

    project_id, workspace_id = await _make_project_with_profiles(
        db,
        tmp_path,
        [
            {"name": "cargo-test", "args": ["cargo", "test"]},
            {"name": "npm-build", "args": ["npm", "run", "build"]},
            {"name": "py-tests", "args": [sys.executable, "-m", "pytest"]},
        ],
    )
    try:
        outside = str((tmp_path.parent / "outside").resolve())
        cases = [
            # 验收复现三案例
            ["cargo", "test", "--manifest-path", f"{outside}/Cargo.toml"],
            ["npm", "run", "build", "--prefix", outside],
            [sys.executable, "-m", "pytest", f"{outside}/test_payload.py"],
            # 等号形式与 .. 越界
            ["cargo", "test", "--manifest-path", f"{outside}/Cargo.toml"],
            ["npm", "run", "build", f"--prefix={outside}"],
            ["cargo", "test", "--manifest-path", "../outside/Cargo.toml"],
            [sys.executable, "-m", "pytest", "../outside/test_payload.py"],
        ]
        for args in cases:
            with pytest.raises(PermissionError_):
                await _resolve_command(db, project_id, args, timeout=None)

        # 工作区内相对路径允许（resolve 校验包含性）
        (tmp_path / "Cargo.toml").write_text("", encoding="utf-8")
        ok = await _resolve_command(
            db,
            project_id,
            ["cargo", "test", "--manifest-path", "./Cargo.toml"],
            timeout=None,
        )
        assert ok.matched_profile_name == "cargo-test"
    finally:
        await _cleanup(db, project_id=project_id, workspace_id=workspace_id)


async def test_global_whitelist_remaining_args_guarded(db, tmp_path):
    """无 profile 时全局白名单前缀之后的绝对路径参数同样拒绝。"""
    from personal_assistant.core.command_workflow import _resolve_command
    from personal_assistant.core.permissions import PermissionError_

    project_id, workspace_id = await _make_project(db, tmp_path)
    try:
        outside = str((tmp_path.parent / "outside").resolve())
        with pytest.raises(PermissionError_):
            await _resolve_command(
                db,
                project_id,
                ["python", "-m", "pytest", f"{outside}/t.py"],
                timeout=None,
            )
        # 无路径特征的剩余参数不受影响
        ok = await _resolve_command(
            db, project_id, ["python", "-m", "pytest", "-q", "-x"], timeout=None
        )
        assert ok.args == ["python", "-m", "pytest", "-q", "-x"]
    finally:
        await _cleanup(db, project_id=project_id, workspace_id=workspace_id)


# ===========================================================================
# P1-1：PatchSet 先持久化终态，后清理备份
# ===========================================================================


async def test_apply_persists_terminal_state_before_backup_cleanup(db, tmp_path):
    """apply 成功路径：DB 终态（applied）先于 .pa-bak 清理（P1-1 顺序）。"""
    from personal_assistant.core.patch_set_service import PatchSetService

    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        preview = await PatchSetService(db).propose(
            run_id,
            [_op_update("a.py", "v2\n", _sha256_text("v1\n"))],
        )
        await _request_approval_and_approve(db, run_id, _apply_call(preview))
        # 顺序断言：transition_status（DB 提交）执行时备份必须仍在
        svc = PatchSetService(db)
        orig_transition = svc.repo.transition_status
        backups_at_transition: list[bool] = []

        async def _transition_checked(patch_set_id, expected, new_status, **kw):
            backups_at_transition.append(bool(_no_pa_leftovers(tmp_path)))
            return await orig_transition(
                patch_set_id, expected, new_status, **kw
            )

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(svc.repo, "transition_status", _transition_checked)
        try:
            result = await svc.apply(
                run_id,
                preview["patch_set_id"],
                preview["preview_version"],
                preview["parameters_hash"],
            )
            assert result["status"] == "applied"
            assert result["verified"] is True
        finally:
            monkeypatch.undo()
        # transition 执行时备份尚在（清理发生在 DB 提交之后）
        assert backups_at_transition and backups_at_transition[0] is True
        # 全部完成后零 .pa 残留
        assert _no_pa_leftovers(tmp_path) == []
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


async def test_apply_cleanup_failure_does_not_block_terminal_state(db, tmp_path):
    """备份清理失败不阻断：状态已 applied（残留备份无害，非幽灵状态）。"""
    from personal_assistant.core import patch_set_service as pss
    from personal_assistant.core.patch_set_service import PatchSetService

    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        preview = await PatchSetService(db).propose(
            run_id,
            [_op_update("a.py", "v2\n", _sha256_text("v1\n"))],
        )
        await _request_approval_and_approve(db, run_id, _apply_call(preview))
        monkeypatch = pytest.MonkeyPatch()

        def _boom(_staged):
            raise OSError("cleanup failed")

        monkeypatch.setattr(pss, "_cleanup_staged", _boom)
        try:
            result = await PatchSetService(db).apply(
                run_id,
                preview["patch_set_id"],
                preview["preview_version"],
                preview["parameters_hash"],
            )
            assert result["status"] == "applied"
            assert result["verified"] is True
        finally:
            monkeypatch.undo()
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# P1-2：Windows 设备路径校验 + 大小写归一化
# ===========================================================================


async def test_windows_device_names_with_extension_rejected(db, tmp_path):
    """nul.txt / CON.md / com1.json / con. / con 尾随空格均按设备名拒绝。"""
    from personal_assistant.core.patch_set_service import (
        PatchSetError,
        PatchSetService,
    )

    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        for bad in ("nul.txt", "CON.md", "com1.json", "con.", "con ", "aux.py"):
            with pytest.raises(PatchSetError) as exc:
                await PatchSetService(db).propose(run_id, [_op_create(bad, "x\n")])
            assert exc.value.error_code == "patchset_invalid", bad
        assert list(tmp_path.iterdir()) == []
        # 非设备名相似名允许
        preview = await PatchSetService(db).propose(
            run_id, [_op_create("console.txt", "x\n")]
        )
        assert preview["file_count"] == 1
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


async def test_path_uniqueness_case_insensitive(db, tmp_path):
    """路径唯一性按 Windows 大小写不敏感归一化：Readme.md 与 readme.md 冲突。"""
    from personal_assistant.core.patch_set_service import (
        PatchSetError,
        PatchSetService,
    )

    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        with pytest.raises(PatchSetError) as exc:
            await PatchSetService(db).propose(
                run_id,
                [
                    _op_create("Readme.md", "a\n"),
                    _op_create("readme.md", "b\n"),
                ],
            )
        assert exc.value.error_code == "patchset_invalid"
        # 大小写不同的 rename 目标同样冲突
        with pytest.raises(PatchSetError) as exc:
            await PatchSetService(db).propose(
                run_id,
                [
                    _op_create("a.py", "a\n"),
                    {
                        "operation": "rename",
                        "rename": {
                            "old_path": "a.py",
                            "new_path": "A.PY",
                            "expected_old_sha256": _sha256_text("a\n"),
                        },
                    },
                ],
            )
        assert exc.value.error_code == "patchset_invalid"
        assert list(tmp_path.iterdir()) == []
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 第六轮验收修复（2026-08-22 复核）：P0-1 网络隔离本质 / P0-2 未知工具代码
# 执行 / P0-3 前缀策略遮蔽 / P1-1 手动运行路由绕过
# ===========================================================================


async def test_workspace_safe_requires_allow_network_all(db, tmp_path):
    """第六轮 P0-1：workspace SAFE 仅当全部 profile safe 且全部
    allow_network=True；存在 allow_network=False → CONFIRM（禁止自动执行）。"""
    from personal_assistant.agents import ToolRiskLevel
    from personal_assistant.api.routes_agent_runs import _workspace_command_risk

    project_id, workspace_id = await _make_project(db, tmp_path)
    db.add(
        ProjectCommandProfile(
            project_id=project_id,
            name="safe-no-net",
            command_json={"args": ["curl"]},
            kind="custom",
            timeout_seconds=30,
            enabled=True,
            profile_version=1,
            allow_network=False,
            risk_level="safe",
            result_parser="plain",
        )
    )
    await db.commit()
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        risk = await _workspace_command_risk(db, run_id)
        assert risk == ToolRiskLevel.CONFIRM
        # 全部 allow_network=True → SAFE（删除 allow_network=False 的 profile
        # 后添加 allow_network=True 的 safe profile）
        from personal_assistant.core.models import ProjectCommandProfile as PCP2

        await db.execute(delete(PCP2).where(PCP2.name == "safe-no-net"))
        db.add(
            PCP2(
                project_id=project_id,
                name="safe-net",
                command_json={"args": ["wget"]},
                kind="custom",
                timeout_seconds=30,
                enabled=True,
                profile_version=1,
                allow_network=True,
                risk_level="safe",
                result_parser="plain",
            )
        )
        await db.commit()
        risk = await _workspace_command_risk(db, run_id)
        assert risk == ToolRiskLevel.SAFE
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


async def test_safe_unknown_tool_requires_exact_argv(db, tmp_path):
    """第六轮 P0-2：safe profile 的未知工具必须精确 argv（node -e 等拒绝）。"""
    from personal_assistant.core.command_workflow import _resolve_command
    from personal_assistant.core.permissions import PermissionError_

    project_id, workspace_id = await _make_project(db, tmp_path)
    db.add(
        ProjectCommandProfile(
            project_id=project_id,
            name="node-safe",
            command_json={"args": ["node"]},
            kind="custom",
            timeout_seconds=30,
            enabled=True,
            profile_version=1,
            allow_network=True,
            risk_level="safe",
            result_parser="plain",
        )
    )
    db.add(
        ProjectCommandProfile(
            project_id=project_id,
            name="node-exact",
            command_json={"args": ["node", "tool.js"]},
            kind="custom",
            timeout_seconds=30,
            enabled=True,
            profile_version=1,
            allow_network=True,
            risk_level="safe",
            result_parser="plain",
        )
    )
    db.add(
        ProjectCommandProfile(
            project_id=project_id,
            name="node-confirm",
            command_json={"args": ["node", "run-confirm"]},
            kind="custom",
            timeout_seconds=30,
            enabled=True,
            profile_version=1,
            allow_network=True,
            risk_level="confirm",
            result_parser="plain",
        )
    )
    await db.commit()
    try:
        # safe + 未知工具（node 无 schema）+ 追加参数 → 拒绝
        # （[node] 同长度仅 node-safe，最严格 = safe → 精确 argv 约束）
        with pytest.raises(PermissionError_):
            await _resolve_command(
                db, project_id, ["node", "-e", "process.exit(0)"], timeout=None
            )
        # safe + 精确 argv（node tool.js 全等）→ 允许
        (tmp_path / "tool.js").write_text("console.log(1)", encoding="utf-8")
        ok = await _resolve_command(
            db, project_id, ["node", "tool.js"], timeout=None
        )
        assert ok.matched_profile_name == "node-exact"
        # confirm + 未知工具 + 追加参数 → 允许（人工审批把关；
        # 最长匹配 [node, run-confirm] 优先）
        ok2 = await _resolve_command(
            db, project_id, ["node", "run-confirm", "-e", "x"], timeout=None
        )
        assert ok2.matched_profile_name == "node-confirm"
    finally:
        await _cleanup(db, project_id=project_id, workspace_id=workspace_id)


async def test_profile_prefix_longest_match_strictest(db, tmp_path):
    """第六轮 P0-3：最长前缀优先 + 同长度最严格 risk——宽泛 safe 不遮蔽 restricted。"""
    from personal_assistant.core.command_workflow import _resolve_command
    from personal_assistant.core.permissions import PermissionError_

    project_id, workspace_id = await _make_project(db, tmp_path)
    db.add(
        ProjectCommandProfile(
            project_id=project_id,
            name="py-restricted",
            command_json={"args": [sys.executable, "-m", "pytest"]},
            kind="custom",
            timeout_seconds=30,
            enabled=True,
            profile_version=1,
            allow_network=True,
            risk_level="restricted",
            result_parser="plain",
        )
    )
    await db.commit()
    db.add(
        ProjectCommandProfile(
            project_id=project_id,
            name="py-safe",
            command_json={"args": [sys.executable]},
            kind="custom",
            timeout_seconds=30,
            enabled=True,
            profile_version=1,
            allow_network=True,
            risk_level="safe",
            result_parser="plain",
        )
    )
    await db.commit()
    try:
        # 最长匹配 = [sys.executable, -m, pytest]（restricted）→ 拒绝
        with pytest.raises(PermissionError_):
            await _resolve_command(
                db, project_id, [sys.executable, "-m", "pytest", "-q"], timeout=None
            )
        # 未命中 restricted 前缀的调用落到宽泛 safe（精确 argv 约束）
        (tmp_path / "tool.py").write_text("print(1)", encoding="utf-8")
        ok = await _resolve_command(
            db, project_id, [sys.executable, "tool.py"], timeout=None
        )
        assert ok.matched_profile_name == "py-safe"
    finally:
        await _cleanup(db, project_id=project_id, workspace_id=workspace_id)


async def test_command_run_route_rejects_cross_project(client, db, tmp_path):
    """第六轮 P1-1：run 端点校验 project_id 归属——跨项目引用 404；
    同项目走受审计执行器（含 argv 校验与进程树清理语义）。"""
    from personal_assistant.core.models import Project

    root_a = tmp_path / "proj-a"
    root_b = tmp_path / "proj-b"
    root_a.mkdir()
    root_b.mkdir()
    resp = await client.post(
        "/projects",
        json={"name": f"r6-a-{uuid4().hex[:6]}", "root_path": str(root_a)},
    )
    assert resp.status_code == 201, resp.text
    project_a = resp.json()["id"]
    resp = await client.post(
        "/projects",
        json={"name": f"r6-b-{uuid4().hex[:6]}", "root_path": str(root_b)},
    )
    assert resp.status_code == 201, resp.text
    project_b = resp.json()["id"]
    resp = await client.post(
        f"/projects/{project_a}/commands",
        json={
            "name": "echo-run",
            "command_json": {"args": [sys.executable, "-c", "print(1)"]},
            "kind": "custom",
            "timeout_seconds": 30,
        },
    )
    assert resp.status_code == 201, resp.text
    command_id = resp.json()["id"]
    try:
        resp = await client.post(f"/projects/{project_b}/commands/{command_id}/run")
        assert resp.status_code == 404, resp.text
        resp = await client.post(f"/projects/{project_a}/commands/{command_id}/run")
        assert resp.status_code == 200, resp.text
        assert resp.json()["succeeded"] is True
    finally:
        from personal_assistant.core.models import ProjectCommandProfile as PCP

        await db.execute(delete(PCP).where(PCP.id == command_id))
        await db.execute(
            delete(Project).where(Project.id.in_([project_a, project_b]))
        )
        await db.commit()

# ===========================================================================
# 第二轮验收修复（2026-08-21 复核）：P0-1 命令 schema / P0-2 本地 Ollama
# loopback / P1-1 DB 终态失败回滚 / P1-2 尾随字符规范化
# ===========================================================================


async def test_command_drive_relative_and_module_load_args_rejected(db, tmp_path):
    """第二轮 P0-1：drive-relative（C:outside）与模块加载参数（-p/--pyargs）拒绝。"""
    from personal_assistant.core.command_workflow import _resolve_command
    from personal_assistant.core.permissions import PermissionError_

    project_id, workspace_id = await _make_project_with_profiles(
        db,
        tmp_path,
        [
            {"name": "cargo-test", "args": ["cargo", "test"]},
            {"name": "py-tests", "args": [sys.executable, "-m", "pytest"]},
        ],
    )
    try:
        cases = [
            # drive-relative（冒号后无斜杠）
            ["cargo", "test", "--manifest-path", "C:outside/Cargo.toml"],
            [sys.executable, "-m", "pytest", "--basetemp=C:outside"],
            [sys.executable, "-m", "pytest", "C:outside/test_payload.py"],
            # 工作区外模块/插件加载能力（无路径特征，必须 flag 级拒绝）
            [sys.executable, "-m", "pytest", "-p", "outside_plugin"],
            [sys.executable, "-m", "pytest", "--pyargs", "outside_package"],
            [sys.executable, "-m", "pytest", "--pyargs=outside_pkg"],
            [sys.executable, "-m", "pytest", "--rootdir", "C:/outside"],
        ]
        for args in cases:
            with pytest.raises(PermissionError_):
                await _resolve_command(db, project_id, args, timeout=None)

        # 合法参数不受影响
        ok = await _resolve_command(
            db, project_id, [sys.executable, "-m", "pytest", "-q", "-x"], timeout=None
        )
        assert ok.matched_profile_name == "py-tests"
        ok2 = await _resolve_command(
            db,
            project_id,
            ["cargo", "test", "--manifest-path", "./Cargo.toml"],
            timeout=None,
        )
        assert ok2.matched_profile_name == "cargo-test"
    finally:
        await _cleanup(db, project_id=project_id, workspace_id=workspace_id)


async def test_local_profile_rejects_remote_ollama_base_url(db, tmp_path, monkeypatch):
    """第二轮 P0-2：本地 profile 的 ollama_base_url 必须 loopback，远程主机拒绝。"""
    from personal_assistant.core.model_profiles import (
        ModelProfileService,
        ModelProfileUnsupported,
    )

    project_id, workspace_id = await _make_project(db, tmp_path)
    await ModelProfileService(db).upsert(
        "local-coder",
        {
            "provider": "ollama",
            "display_name": "Local",
            "model_name": "loopback-route-model",
            "native_tool_calls": True,
        },
    )
    run = await _run_with_profile(db, project_id, workspace_id, "local-coder")

    async def _settings(_self):
        return {
            "provider_type": "ollama",
            "remote_provider_enabled": "false",
            "llm_temperature": "0.7",
            "llm_context_length": "8192",
            "llm_model": "qwen2.5",
        }

    monkeypatch.setattr(routes_agent_runs.SettingsService, "get_all", _settings)
    try:
        # 远程 Ollama 主机 → 失败关闭（不静默连接，快照 no_send 保持真实）
        monkeypatch.setattr(cfg, "ollama_base_url", "https://ollama.example.com")
        with pytest.raises(ModelProfileUnsupported):
            await routes_agent_runs._model_gateway_for_run(db, run)
        # loopback 主机 → 正常路由（实际 model = profile 路由字段）
        monkeypatch.setattr(cfg, "ollama_base_url", "http://127.0.0.1:11434")
        gateway = await routes_agent_runs._model_gateway_for_run(db, run)
        assert gateway.adapter.provider_name == "ollama"
        assert "127.0.0.1" in gateway.adapter.base_url
        assert gateway.adapter.model_name == "loopback-route-model"
    finally:
        try:
            await ModelProfileService(db).delete("local-coder")
        finally:
            await _cleanup(
                db, run_id=run.id, project_id=project_id, workspace_id=workspace_id
            )


async def test_apply_db_terminal_failure_rolls_back_disk(db, tmp_path):
    """第二轮 P1-1：DB 终态写入普通异常 → 自动回滚磁盘 + 状态 rolled_back。"""
    from personal_assistant.core.patch_set_service import (
        PatchSetError,
        PatchSetService,
    )

    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        preview = await PatchSetService(db).propose(
            run_id,
            [_op_update("a.py", "v2\n", _sha256_text("v1\n"))],
        )
        await _request_approval_and_approve(db, run_id, _apply_call(preview))
        svc = PatchSetService(db)
        orig_transition = svc.repo.transition_status
        calls: list[tuple] = []

        async def _flaky_transition(patch_set_id, expected, new_status, **kw):
            calls.append((expected, new_status))
            if new_status == "applied":
                raise RuntimeError("simulated SQL/commit failure")
            return await orig_transition(patch_set_id, expected, new_status, **kw)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(svc.repo, "transition_status", _flaky_transition)
        try:
            with pytest.raises(PatchSetError) as exc:
                await svc.apply(
                    run_id,
                    preview["patch_set_id"],
                    preview["preview_version"],
                    preview["parameters_hash"],
                )
            assert exc.value.error_code == "patchset_conflict"
        finally:
            monkeypatch.undo()
        # 磁盘已恢复原状（回滚成功），状态落为 rolled_back，零 .pa 残留
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v1\n"
        assert _no_pa_leftovers(tmp_path) == []
        stored = await svc.repo.get_by_id(preview["patch_set_id"])
        assert stored is not None and stored.status == "rolled_back"
        assert ("previewed", "applied") in calls
        assert ("previewed", "rolled_back") in calls
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


async def test_path_uniqueness_trailing_dot_space_normalized(db, tmp_path):
    """第二轮 P1-2：尾随点/空格逐组件规范化——README.MD. 与 Readme.md 判重复。"""
    from personal_assistant.core.patch_set_service import (
        PatchSetError,
        PatchSetService,
    )

    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        pairs = [
            ("Readme.md", "README.MD."),
            ("a.py", "a.py "),
            ("dir/x.py", "dir./x.py"),
            ("A.PY.", "a.py"),
        ]
        for first, second in pairs:
            with pytest.raises(PatchSetError) as exc:
                await PatchSetService(db).propose(
                    run_id,
                    [_op_create(first, "a\n"), _op_create(second, "b\n")],
                )
            assert exc.value.error_code == "patchset_invalid", (first, second)
        assert list(tmp_path.iterdir()) == []
        # 无冲突路径正常
        preview = await PatchSetService(db).propose(
            run_id, [_op_create("a.py", "x\n"), _op_create("b.py", "y\n")]
        )
        assert preview["file_count"] == 2
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 第三轮验收修复（2026-08-21 复核：等价绕过）：P0-1 allowlist / P0-2 代理 /
# P1-1 post-commit 反向分叉 / P1-2 空组件别名
# ===========================================================================


async def test_command_nested_bypass_rejected(db, tmp_path):
    """第三轮 P0-1：--override-ini/addopts 嵌套注入与 wrapper 变体全部拒绝。"""
    from personal_assistant.core.command_workflow import _resolve_command
    from personal_assistant.core.permissions import PermissionError_

    project_id, workspace_id = await _make_project_with_profiles(
        db,
        tmp_path,
        [
            {"name": "py-tests", "args": [sys.executable, "-m", "pytest"]},
            {"name": "uv-tests", "args": ["uv", "run", "pytest"]},
        ],
    )
    try:
        cases = [
            # --override-ini / -o 嵌套 pythonpath 注入
            [sys.executable, "-m", "pytest", "--override-ini=pythonpath=C:outside"],
            [sys.executable, "-m", "pytest", "-o", "pythonpath=C:outside"],
            # addopts 注入（-o addopts=-p x）与 -c 外部配置
            [sys.executable, "-m", "pytest", "-o", "addopts=-p outside_plugin"],
            [sys.executable, "-m", "pytest", "-c", "C:/outside/pytest.ini"],
            # wrapper 变体（uv run 选项 / python -I）
            ["uv", "run", "--offline", "pytest", "-p", "outside_plugin"],
            ["uv", "run", "--offline", "pytest", "--pyargs", "outside_pkg"],
            [sys.executable, "-I", "-m", "pytest", "--pyargs", "outside_pkg"],
            # 未列入 allowlist 的 flag 一律拒绝
            [sys.executable, "-m", "pytest", "--import-mode=importlib"],
            [sys.executable, "-m", "pytest", "--addopts=-p x"],
        ]
        for args in cases:
            with pytest.raises(PermissionError_):
                await _resolve_command(db, project_id, args, timeout=None)

        # wrapper 选项（--offline/-I）不在 profile 前缀也不在 pytest allowlist：
        # 拒绝是安全语义（模型不能注入 wrapper 选项）；allowlist 内参数合法。
        ok = await _resolve_command(
            db, project_id, ["uv", "run", "pytest", "-q", "-x"], timeout=None
        )
        assert ok.matched_profile_name == "uv-tests"
        ok2 = await _resolve_command(
            db,
            project_id,
            [sys.executable, "-m", "pytest", "-q"],
            timeout=None,
        )
        assert ok2.matched_profile_name == "py-tests"
    finally:
        await _cleanup(db, project_id=project_id, workspace_id=workspace_id)


def test_ollama_adapter_bypasses_proxy_and_requires_loopback(monkeypatch):
    """第三轮 P0-2：Ollama 本地适配器 trust_env=False（不走 HTTP_PROXY）；
    require_loopback 拒绝远程主机。"""
    from personal_assistant.llm.adapters import OllamaChatAdapter

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.com:8080")
    monkeypatch.setenv("http_proxy", "http://proxy.example.com:8080")
    adapter = OllamaChatAdapter(
        base_url="http://127.0.0.1:11434",
        model="qwen2.5",
        require_loopback=True,
    )
    assert adapter._trust_env is False
    # 远程主机在 require_loopback 下构造即拒绝
    with pytest.raises(ValueError):
        OllamaChatAdapter(
            base_url="https://ollama.example.com",
            model="qwen2.5",
            require_loopback=True,
        )
    # 默认（legacy 全局路径）不强制 loopback，但同样不走代理
    legacy = OllamaChatAdapter(base_url="http://127.0.0.1:11434", model="qwen2.5")
    assert legacy._trust_env is False


def test_ollama_adapter_client_trust_env_false(monkeypatch):
    """第三轮 P0-2：_post 创建的 httpx 客户端显式 trust_env=False。"""
    import httpx

    from personal_assistant.llm.adapters import OllamaChatAdapter

    captured: dict = {}

    class _FakeResponse:
        def json(self):
            return {"message": {"content": "ok", "tool_calls": None}}

        @property
        def status_code(self):
            return 200

        def raise_for_status(self):
            return None

    class _FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    adapter = OllamaChatAdapter(base_url="http://127.0.0.1:11434", model="qwen2.5")
    import asyncio

    async def _run():
        from personal_assistant.agents import ModelMessage, ModelRequest
        from personal_assistant.agents.runtime import CancellationToken

        await adapter.complete(
            ModelRequest(messages=(ModelMessage(role="user", content="hi"),)),
            cancellation=CancellationToken(),
        )

    asyncio.run(_run())
    assert captured.get("trust_env") is False


async def test_apply_post_commit_query_failure_keeps_disk(db, tmp_path):
    """第三轮 P1-1：commit 成功但提交后查询失败 → 新事务确认 applied，
    不回滚磁盘（防反向分叉：DB=applied + 磁盘=旧内容）。"""
    from personal_assistant.core.patch_set_service import PatchSetService

    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        preview = await PatchSetService(db).propose(
            run_id,
            [_op_update("a.py", "v2\n", _sha256_text("v1\n"))],
        )
        await _request_approval_and_approve(db, run_id, _apply_call(preview))
        svc = PatchSetService(db)
        orig_transition = svc.repo.transition_status

        async def _commit_then_raise(patch_set_id, expected, new_status, **kw):
            await orig_transition(patch_set_id, expected, new_status, **kw)
            raise RuntimeError("post-commit query failed")

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(svc.repo, "transition_status", _commit_then_raise)
        try:
            result = await svc.apply(
                run_id,
                preview["patch_set_id"],
                preview["preview_version"],
                preview["parameters_hash"],
            )
            assert result["status"] == "applied"
        finally:
            monkeypatch.undo()
        # 磁盘保持新内容（未反向回滚），DB applied，零 .pa 残留
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v2\n"
        assert _no_pa_leftovers(tmp_path) == []
        stored = await svc.repo.get_by_id(preview["patch_set_id"])
        assert stored is not None and stored.status == "applied"
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


async def test_path_component_collapses_to_empty_rejected(db, tmp_path):
    """第三轮 P1-2：规范化后为空/折叠的组件（...、.. 、. ）拒绝。"""
    from personal_assistant.core.patch_set_service import (
        PatchSetError,
        PatchSetService,
    )

    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        for bad in ("src/.../config.py", "src/.. /x.py", "src/. /x.py", "..."):
            with pytest.raises(PatchSetError) as exc:
                await PatchSetService(db).propose(run_id, [_op_create(bad, "x\n")])
            assert exc.value.error_code == "patchset_invalid", bad
        assert list(tmp_path.iterdir()) == []
        # 合法路径不受影响
        preview = await PatchSetService(db).propose(
            run_id, [_op_create("src/config.py", "x\n")]
        )
        assert preview["file_count"] == 1
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 第四轮验收修复（2026-08-21 复核）：P0-1 @argsfile / P0-2 cargo/npm 内联值 /
# P1-1 durable 不可判定 / P1-2 重复斜杠别名
# ===========================================================================


async def test_command_argsfile_and_double_dash_rejected(db, tmp_path):
    """第四轮 P0-1/P0-2：@argsfile 与 -- 分隔符、cargo/npm 未知 flag 内联值拒绝。"""
    from personal_assistant.core.command_workflow import _resolve_command
    from personal_assistant.core.permissions import PermissionError_

    project_id, workspace_id = await _make_project_with_profiles(
        db,
        tmp_path,
        [
            {"name": "py-tests", "args": [sys.executable, "-m", "pytest"]},
            {"name": "npm-build", "args": ["npm", "run", "build"]},
            {"name": "npm-test", "args": ["npm", "test"]},
            {"name": "cargo-test", "args": ["cargo", "test"]},
        ],
    )
    try:
        outside = str((tmp_path.parent / "outside").resolve())
        (tmp_path / "args.txt").write_text("-p outside_plugin", encoding="utf-8")
        cases = [
            # pytest @argsfile（展开后可重新注入禁用能力）
            [sys.executable, "-m", "pytest", "@args.txt"],
            [sys.executable, "-m", "pytest", f"@{outside}/args.txt"],
            # -- 分隔符透传底层工具参数（npm run -- --config=... → vite）
            ["npm", "run", "build", "--", "--config=../outside/vite.config.ts"],
            ["npm", "test", "--", "--config=C:outside"],
            ["npm", "test", "--config=../outside/vitest.config.ts"],
            # cargo/npm 未知 flag 的内联值（--target / --config 外部路径）
            ["cargo", "test", "--target=C:outside"],
            ["cargo", "test", "--target-dir=../outside"],
            ["npm", "run", "build", "--cache=C:outside"],
        ]
        for args in cases:
            with pytest.raises(PermissionError_):
                await _resolve_command(db, project_id, args, timeout=None)

        # allowlist 内参数合法（含 cargo -p 包选择与 --offline）
        ok = await _resolve_command(
            db, project_id, ["cargo", "test", "-p", "my-crate", "--offline"], timeout=None
        )
        assert ok.matched_profile_name == "cargo-test"
        ok2 = await _resolve_command(
            db,
            project_id,
            ["npm", "run", "build", "--if-present"],
            timeout=None,
        )
        assert ok2.matched_profile_name == "npm-build"
    finally:
        await _cleanup(db, project_id=project_id, workspace_id=workspace_id)


async def test_apply_durable_unknown_keeps_disk_and_backup(db, tmp_path, monkeypatch):
    """第四轮 P1-1：durable 查询也失败（DB 不可达）→ 保留磁盘与备份 + partial_unknown。"""
    from personal_assistant.core.patch_set_service import (
        PatchSetError,
        PatchSetService,
    )

    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        preview = await PatchSetService(db).propose(
            run_id,
            [_op_update("a.py", "v2\n", _sha256_text("v1\n"))],
        )
        await _request_approval_and_approve(db, run_id, _apply_call(preview))
        svc = PatchSetService(db)
        orig_transition = svc.repo.transition_status

        async def _flaky_transition(patch_set_id, expected, new_status, **kw):
            if new_status == "applied":
                raise RuntimeError("simulated commit failure")
            return await orig_transition(patch_set_id, expected, new_status, **kw)

        def _db_down(*args, **kwargs):
            # 同步抛异常（async_session_factory 被调用时直接失败，
            # 避免未 await 的 coroutine 警告）
            raise RuntimeError("database unreachable")

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(svc.repo, "transition_status", _flaky_transition)
        monkeypatch.setattr(
            "personal_assistant.core.db.async_session_factory",
            _db_down,
        )
        try:
            with pytest.raises(PatchSetError) as exc:
                await svc.apply(
                    run_id,
                    preview["patch_set_id"],
                    preview["preview_version"],
                    preview["parameters_hash"],
                )
            assert exc.value.error_code == "patchset_partial_unknown"
        finally:
            monkeypatch.undo()
        # 磁盘保持新内容（未回滚）+ 备份保留（可人工处置），状态尽力落为
        # partial_unknown（durable 不可判定 → 人工处置态；DB 可用时写入成功）
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v2\n"
        assert _no_pa_leftovers(tmp_path) != []
        stored = await svc.repo.get_by_id(preview["patch_set_id"])
        assert stored is not None and stored.status == "partial_unknown"
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


async def test_path_uniqueness_double_slash_normalized(db, tmp_path):
    """第四轮 P1-2：重复斜杠归一化——a//b 与 a/b 判重复（Windows 同一目标）。"""
    from personal_assistant.core.patch_set_service import (
        PatchSetError,
        PatchSetService,
    )

    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        with pytest.raises(PatchSetError) as exc:
            await PatchSetService(db).propose(
                run_id,
                [
                    _op_create("src/config.py", "a\n"),
                    _op_create("src//config.py", "b\n"),
                ],
            )
        assert exc.value.error_code == "patchset_invalid"
        with pytest.raises(PatchSetError) as exc:
            await PatchSetService(db).propose(
                run_id,
                [
                    _op_create("a/b.py", "a\n"),
                    {
                        "operation": "rename",
                        "rename": {
                            "old_path": "x.py",
                            "new_path": "a//b.py",
                            "expected_old_sha256": _sha256_text(""),
                        },
                    },
                ],
            )
        assert exc.value.error_code == "patchset_invalid"
        assert list(tmp_path.iterdir()) == []
        # 无冲突路径正常
        preview = await PatchSetService(db).propose(
            run_id, [_op_create("src/config.py", "x\n")]
        )
        assert preview["file_count"] == 1
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 第五轮验收修复（2026-08-22 复核）：P0-1 SAFE 工具级泄漏 / P0-2 -W 与 python
# 代码参数 / P0-3 allow_network 执行层约束 / P1-1 . 组件唯一性键
# ===========================================================================


async def test_workspace_mode_unmatched_profile_rejected(db, tmp_path):
    """第五轮 P0-1：workspace 模式 SAFE 只对匹配项目 profile 的命令生效——
    未匹配 profile 的全局白名单命令执行时拒绝（不因工具级 SAFE 自动放行）。"""
    from personal_assistant.core.command_workflow import _resolve_command
    from personal_assistant.core.permissions import PermissionError_

    project_id, workspace_id = await _make_project_with_profiles(
        db,
        tmp_path,
        [
            {"name": "cargo-test", "args": ["cargo", "test"], "risk_level": "safe"},
            {"name": "py-tests", "args": [sys.executable, "-m", "pytest"], "risk_level": "safe"},
        ],
    )
    try:
        # 匹配项目 profile（全部 safe）→ workspace 模式自动允许
        ok = await _resolve_command(
            db,
            project_id,
            ["cargo", "test", "-q"],
            timeout=None,
            permission_mode="workspace",
        )
        assert ok.matched_profile_name == "cargo-test"
        # 未匹配 profile 的全局白名单命令（python -m pytest 是全局前缀，
        # 但项目 profile 是 [sys.executable, -m, pytest] 不匹配此形态）
        # → workspace 模式拒绝，即使命令工具整体是 SAFE
        with pytest.raises(PermissionError_):
            await _resolve_command(
                db,
                project_id,
                ["python", "-m", "pytest", "-q"],
                timeout=None,
                permission_mode="workspace",
            )
        # 非 workspace 模式（confirm/无权限）保持全局白名单兜底
        ok2 = await _resolve_command(
            db, project_id, ["python", "-m", "pytest", "-q"], timeout=None
        )
        assert ok2.args == ["python", "-m", "pytest", "-q"]
    finally:
        await _cleanup(db, project_id=project_id, workspace_id=workspace_id)


async def test_pytest_w_flag_and_python_code_args_rejected(db, tmp_path):
    """第五轮 P0-2：pytest -W（警告类别触发模块导入）与 python -c/-m/-i/-W 拒绝。"""
    from personal_assistant.core.command_workflow import _resolve_command
    from personal_assistant.core.permissions import PermissionError_

    project_id, workspace_id = await _make_project_with_profiles(
        db,
        tmp_path,
        [
            {"name": "py-tests", "args": [sys.executable, "-m", "pytest"]},
            {"name": "py-run", "args": [sys.executable]},
        ],
    )
    try:
        cases = [
            # pytest -W 警告类别可触发外部模块导入
            [sys.executable, "-m", "pytest", "-W", "ignore::outside_plugin.CustomWarning"],
            [sys.executable, "-m", "pytest", "-W=ignore::outside_plugin.CustomWarning"],
            # python 代码/模块执行参数（profile 前缀为 python 时模型不可追加）
            [sys.executable, "-c", "__import__('outside_plugin')"],
            [sys.executable, "-m", "os"],
            [sys.executable, "-i"],
            [sys.executable, "-W", "ignore"],
        ]
        for args in cases:
            with pytest.raises(PermissionError_):
                await _resolve_command(db, project_id, args, timeout=None)

        # 合法：python 运行工作区内脚本 / 安全选项
        (tmp_path / "tool.py").write_text("print(1)", encoding="utf-8")
        ok = await _resolve_command(
            db, project_id, [sys.executable, "-B", "tool.py"], timeout=None
        )
        assert ok.matched_profile_name == "py-run"
    finally:
        await _cleanup(db, project_id=project_id, workspace_id=workspace_id)


async def test_allow_network_false_rejects_url_args(db, tmp_path):
    """第五轮 P0-3：allow_network=false（默认）执行层拒绝 URL 参数。"""
    from personal_assistant.core.command_workflow import _resolve_command
    from personal_assistant.core.models import ProjectCommandProfile
    from personal_assistant.core.permissions import PermissionError_

    project_id, workspace_id = await _make_project(db, tmp_path)
    db.add(
        ProjectCommandProfile(
            project_id=project_id,
            name="fetch-no-net",
            command_json={"args": ["curl"]},
            kind="custom",
            timeout_seconds=30,
            enabled=True,
            profile_version=1,
            allow_network=False,
            result_parser="plain",
        )
    )
    db.add(
        ProjectCommandProfile(
            project_id=project_id,
            name="fetch-net",
            command_json={"args": ["wget"]},
            kind="custom",
            timeout_seconds=30,
            enabled=True,
            profile_version=1,
            allow_network=True,
            result_parser="plain",
        )
    )
    await db.commit()
    try:
        with pytest.raises(PermissionError_):
            await _resolve_command(
                db, project_id, ["curl", "https://example.com/data"], timeout=None
            )
        with pytest.raises(PermissionError_):
            await _resolve_command(
                db, project_id, ["curl", "--url=http://example.com"], timeout=None
            )
        # allow_network=True 放行
        ok = await _resolve_command(
            db, project_id, ["wget", "https://example.com/data"], timeout=None
        )
        assert ok.matched_profile_name == "fetch-net"
        # 无 URL 参数不受影响
        ok2 = await _resolve_command(
            db, project_id, ["curl", "-s", "--version"], timeout=None
        )
        assert ok2.matched_profile_name == "fetch-no-net"
    finally:
        await _cleanup(db, project_id=project_id, workspace_id=workspace_id)


async def test_path_uniqueness_dot_component_normalized(db, tmp_path):
    """第五轮 P1-1：. 组件归一化——src/./x.py 与 src/x.py 判重复（Windows 同一目标）。"""
    from personal_assistant.core.patch_set_service import (
        PatchSetError,
        PatchSetService,
    )

    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        with pytest.raises(PatchSetError) as exc:
            await PatchSetService(db).propose(
                run_id,
                [
                    _op_create("src/x.py", "a\n"),
                    _op_create("src/./x.py", "b\n"),
                ],
            )
        assert exc.value.error_code == "patchset_invalid"
        with pytest.raises(PatchSetError) as exc:
            await PatchSetService(db).propose(
                run_id,
                [
                    _op_create("./a.py", "a\n"),
                    _op_create("a.py", "b\n"),
                ],
            )
        assert exc.value.error_code == "patchset_invalid"
        assert list(tmp_path.iterdir()) == []
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 第七轮验收修复（2026-08-22 复核）：O-1 手动运行权限拒绝 403 /
# O-2 workspace SAFE 执行时按匹配 profile 复核（单回合 TOCTOU 关闭）
# ===========================================================================


async def test_command_run_route_restricted_profile_returns_403(client, db, tmp_path):
    """第七轮 O-1：手动运行 restricted profile → 403（原为 RuntimeError 500）。

    命令零执行的 fail-closed 语义不变，仅 HTTP 状态语义修正
    （与 routes_projects / routes_integrations 的 PermissionError_ 惯例一致）。
    """
    from personal_assistant.core.models import Project

    root = tmp_path / "proj-r7"
    root.mkdir()
    resp = await client.post(
        "/projects",
        json={"name": f"r7-{uuid4().hex[:6]}", "root_path": str(root)},
    )
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["id"]
    resp = await client.post(
        f"/projects/{project_id}/commands",
        json={
            "name": "restricted-echo",
            "command_json": {"args": [sys.executable, "-c", "print(1)"]},
            "kind": "custom",
            "timeout_seconds": 30,
            "risk_level": "restricted",
        },
    )
    assert resp.status_code == 201, resp.text
    command_id = resp.json()["id"]
    try:
        resp = await client.post(f"/projects/{project_id}/commands/{command_id}/run")
        assert resp.status_code == 403, resp.text
        assert "restricted" in resp.json()["detail"]
    finally:
        from personal_assistant.core.models import ProjectCommandProfile as PCP

        await db.execute(delete(PCP).where(PCP.id == command_id))
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()


async def test_workspace_safe_revalidates_matched_profile_at_execution(db, tmp_path):
    """第七轮 O-2：SAFE 自动允许在执行时按**当前**匹配 profile 复核。

    工具 risk 在 dispatcher 构建时求值（run start/resume）；本回合内 profile
    被改为 confirm / allow_network=False 时，旧 SAFE 判定不得继续免确认放行
    （单回合 TOCTOU 窗口关闭）；CONFIRM 工具（整体审批把关）不受影响。
    """
    from personal_assistant.agents import ToolRiskLevel
    from personal_assistant.core.command_workflow import _resolve_command
    from personal_assistant.core.permissions import PermissionError_

    project_id, workspace_id = await _make_project(db, tmp_path)
    profile = ProjectCommandProfile(
        project_id=project_id,
        name="node-safe-net",
        command_json={"args": ["node", "tool.js"]},
        kind="custom",
        timeout_seconds=30,
        enabled=True,
        profile_version=1,
        allow_network=True,
        risk_level="safe",
        result_parser="plain",
    )
    db.add(profile)
    await db.commit()
    (tmp_path / "tool.js").write_text("console.log(1)", encoding="utf-8")
    try:
        # 注册时 SAFE + 执行时仍 safe 且 allow_network=True → 自动允许
        ok = await _resolve_command(
            db,
            project_id,
            ["node", "tool.js"],
            timeout=None,
            permission_mode="workspace",
            command_risk=ToolRiskLevel.SAFE,
        )
        assert ok.matched_profile_name == "node-safe-net"
        # 本回合内 profile 被改为 confirm → SAFE 自动允许不再放行
        profile.risk_level = "confirm"
        await db.commit()
        with pytest.raises(PermissionError_):
            await _resolve_command(
                db,
                project_id,
                ["node", "tool.js"],
                timeout=None,
                permission_mode="workspace",
                command_risk=ToolRiskLevel.SAFE,
            )
        # 改回 safe 但 allow_network=False → 同样拒绝（第六轮语义执行时复核）
        profile.risk_level = "safe"
        profile.allow_network = False
        await db.commit()
        with pytest.raises(PermissionError_):
            await _resolve_command(
                db,
                project_id,
                ["node", "tool.js"],
                timeout=None,
                permission_mode="workspace",
                command_risk=ToolRiskLevel.SAFE,
            )
        # CONFIRM 工具（审批把关）+ confirm profile → resolve 层放行
        profile.allow_network = True
        profile.risk_level = "confirm"
        await db.commit()
        ok2 = await _resolve_command(
            db,
            project_id,
            ["node", "tool.js"],
            timeout=None,
            permission_mode="workspace",
            command_risk=ToolRiskLevel.CONFIRM,
        )
        assert ok2.matched_profile_name == "node-safe-net"
    finally:
        await _cleanup(db, project_id=project_id, workspace_id=workspace_id)
