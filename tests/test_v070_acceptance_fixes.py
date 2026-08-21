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
