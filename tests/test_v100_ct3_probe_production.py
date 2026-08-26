"""v1.0 CT-3 生产接线（专项计划 §8.2/§8.3）：探测结果映射、快照持久化、
自动探测与工具面门禁。

覆盖验收关闭项：
- 探测结果 → ModelRequirements 能力映射（same_turn_multi_call →
  parallel_tool_calls，不再永远取默认值）；
- 快照持久化与有效性（digest 与当前 model_name 绑定；换模型即失效）；
- run_probe_for_profile 部分未过 → failed 快照留痕；
- 路由门禁：绑定 profile 的 coding run 无有效快照时，文件写入意图
  409 tool_model_unsupported；补快照后放行。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from personal_assistant.agent_v2.application.model_probe import (
    ModelToolProfileSnapshot,
    ProbeCapability,
    requirements_from_results,
)
from personal_assistant.core.model_probe_service import (
    PROBE_STATUS_FAILED,
    ModelProbeSnapshotRepository,
    probe_gate_for_run,
    profile_tool_protocol_valid,
    run_probe_for_profile,
)
from personal_assistant.core.model_profiles import ModelProfileService
from personal_assistant.core.models import ModelProfile


def _all_results(value: bool = True) -> dict[str, bool]:
    return {capability.value: value for capability in ProbeCapability}


def _digest(provider: str, model_name: str) -> str:
    return hashlib.sha256(f"{provider}:{model_name}".encode("utf-8")).hexdigest()[:16]


def test_requirements_mapping_from_probe_results() -> None:
    req = requirements_from_results(_all_results(True))
    assert req.function_calling is True
    assert req.parallel_tool_calls is True
    assert req.freeform_patch is False
    assert req.vision is False

    no_single = _all_results(True)
    no_single[ProbeCapability.SINGLE_JSON_TOOL_CALL.value] = False
    assert requirements_from_results(no_single).function_calling is False

    no_multi = _all_results(True)
    no_multi[ProbeCapability.SAME_TURN_MULTI_CALL.value] = False
    mapped = requirements_from_results(no_multi)
    assert mapped.parallel_tool_calls is False
    assert mapped.function_calling is True


def _snapshot(provider: str, model_name: str, *, results: dict[str, bool]) -> ModelToolProfileSnapshot:
    return ModelToolProfileSnapshot(
        provider=provider,
        model_name=model_name,
        model_digest=_digest(provider, model_name),
        probed_at=datetime.now(timezone.utc),
        sample_count=6,
        pass_count=sum(results.values()),
        results=results,
        requirements=requirements_from_results(results),
    )


async def seed_valid_probe_snapshot(
    db, profile_id: str, *, provider: str = "ollama", model_name: str
) -> None:
    """为 profile 种一条全能力通过的有效快照（供绑定 profile 的用例放行写工具面）。"""
    await ModelProbeSnapshotRepository(db).save(
        profile_id, _snapshot(provider, model_name, results=_all_results(True))
    )


@pytest.mark.asyncio
async def test_probe_snapshot_persistence_and_validity(db) -> None:
    profile = ModelProfile(
        id=f"ct3-snap-{uuid4().hex[:8]}",
        provider="ollama",
        display_name="CT3 probe",
        model_name="qwen-local",
        is_local=True,
        native_tool_calls=True,
        enabled=True,
    )
    db.add(profile)
    await db.commit()
    try:
        repository = ModelProbeSnapshotRepository(db)
        await repository.save(
            profile.id, _snapshot("ollama", "qwen-local", results=_all_results(True))
        )
        assert await profile_tool_protocol_valid(db, profile) is True

        # 换模型后 digest 失配 → 未知能力失败关闭。
        profile.model_name = "other-model"
        await db.commit()
        assert await profile_tool_protocol_valid(db, profile) is False

        # 为新模型补一条 failed 快照 → 仍无效。
        failed = _snapshot("ollama", "other-model", results=_all_results(True))
        await repository.save(
            profile.id, failed, status=PROBE_STATUS_FAILED, error_code="capability_unproven"
        )
        assert await profile_tool_protocol_valid(db, profile) is False

        # function_calling 未证 → 无效（最小工具面）。
        weak = _all_results(True)
        weak[ProbeCapability.REQUIRED_FIELD_COMPLIANCE.value] = False
        await repository.save(profile.id, _snapshot("ollama", "other-model", results=weak))
        assert await profile_tool_protocol_valid(db, profile) is False
    finally:
        await db.delete(profile)
        await db.commit()


class _SilentClient:
    """永远只回文字、不发工具调用的受控客户端（探测应全部未证）。"""

    async def complete(self, request):
        class _Response:
            tool_calls = ()
            content = "好的。"

        return _Response()


@pytest.mark.asyncio
async def test_run_probe_for_profile_partial_failure_persists_failed(db) -> None:
    profile = ModelProfile(
        id=f"ct3-run-{uuid4().hex[:8]}",
        provider="ollama",
        display_name="CT3 run",
        model_name="qwen-local",
        is_local=True,
        native_tool_calls=True,
        enabled=True,
    )
    db.add(profile)
    await db.commit()
    try:
        record = await run_probe_for_profile(db, profile, client=_SilentClient())
        assert record.status == PROBE_STATUS_FAILED
        assert record.error_code == "capability_unproven"
        assert record.results_json is not None
        assert await profile_tool_protocol_valid(db, profile) is False
    finally:
        await db.delete(profile)
        await db.commit()


@pytest.mark.asyncio
async def test_route_gate_blocks_file_write_without_valid_probe(
    client, monkeypatch, tmp_path, db
) -> None:
    """绑定 profile 的 coding run：无有效快照 → 409 tool_model_unsupported；
    补有效快照后放行（§8.2 末条 + AD-T04 失败关闭）。"""
    from test_v070_permissions import _create_coding_env, _post_coding_run

    from personal_assistant.api import routes_agent_runs

    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", True)

    profile_id = f"ct3-gate-{uuid4().hex[:8]}"
    await ModelProfileService(db).upsert(
        profile_id,
        {
            "provider": "ollama",
            "display_name": "CT3 gate",
            "model_name": "qwen-local",
            "is_local": True,
            "native_tool_calls": True,
            "enabled": True,
        },
    )
    env = await _create_coding_env(client, tmp_path)
    message = "在根目录创建 hello.py 文件，写入打印 hello world 的代码"
    try:
        blocked = await _post_coding_run(
            client, env, message=message, model_profile_id=profile_id
        )
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["error_code"] == "tool_model_unsupported"

        await ModelProbeSnapshotRepository(db).save(
            profile_id, _snapshot("ollama", "qwen-local", results=_all_results(True))
        )
        allowed = await _post_coding_run(
            client, env, message=message, model_profile_id=profile_id
        )
        assert allowed.status_code in (200, 202), allowed.text
    finally:
        await ModelProfileService(db).delete(profile_id)


@pytest.mark.asyncio
async def test_probe_gate_for_run_fail_closed(db) -> None:
    """三次验收 P1：绑定 profile 缺失/无快照 → 失败关闭；仅无绑定保持旧行为。"""
    assert await probe_gate_for_run(db, None) is True
    assert await probe_gate_for_run(db, "missing-profile-id") is False

    profile = ModelProfile(
        id=f"ct3-gatefc-{uuid4().hex[:8]}",
        provider="ollama",
        display_name="CT3 gate fc",
        model_name="qwen-local",
        is_local=True,
        native_tool_calls=True,
        enabled=True,
    )
    db.add(profile)
    await db.commit()
    try:
        assert await probe_gate_for_run(db, profile.id) is False
        await seed_valid_probe_snapshot(
            db, profile.id, provider="ollama", model_name="qwen-local"
        )
        assert await probe_gate_for_run(db, profile.id) is True
        # profile 删除后（门禁再查）仍失败关闭。
        await ModelProfileService(db).delete(profile.id)
        assert await probe_gate_for_run(db, profile.id) is False
    finally:
        if await ModelProfileService(db).get(profile.id) is not None:
            await ModelProfileService(db).delete(profile.id)


class _FakeGateway:
    """模拟生产 ModelGateway：complete 强制要求 cancellation 关键字。

    若探测链路未补齐 cancellation（P0 缺陷），这里会招致 TypeError →
    全部用例失败；并记录是否真的收到了取消令牌。
    """

    def __init__(self) -> None:
        self.calls = 0
        self.saw_cancellation = False

    async def complete(self, request, *, cancellation):
        self.calls += 1
        self.saw_cancellation = cancellation is not None

        class _Response:
            tool_calls = ()
            content = "好的。"

        return _Response()


@pytest.mark.asyncio
async def test_background_probe_supplies_cancellation_and_persists(
    db, monkeypatch
) -> None:
    """P0：后台探测经适配层补齐 cancellation；结果落库（未证 → failed）。"""
    import asyncio

    from personal_assistant.config import settings as cfg
    from personal_assistant.core import model_probe_service as svc

    gateway = _FakeGateway()
    monkeypatch.setattr(cfg, "agent_v2_model_probe_enabled", True)
    monkeypatch.setattr(
        svc, "build_gateway_for_profile", lambda *a, **kw: gateway
    )

    profile = ModelProfile(
        id=f"ct3-bg-{uuid4().hex[:8]}",
        provider="ollama",
        display_name="CT3 bg",
        model_name="qwen-local",
        is_local=True,
        native_tool_calls=True,
        enabled=True,
    )
    db.add(profile)
    await db.commit()
    try:
        assert svc.start_probe_for_profile(db, profile, cfg=cfg) is True
        repository = ModelProbeSnapshotRepository(db)
        record = None
        for _ in range(100):
            await asyncio.sleep(0.1)
            record = await repository.latest(profile.id)
            if record is not None and record.status != "running":
                break
        assert record is not None, "后台探测未落库"
        assert record.status == PROBE_STATUS_FAILED
        assert record.error_code == "capability_unproven"
        assert gateway.calls > 0, "探测未实际调用模型"
        assert gateway.saw_cancellation is True, "cancellation 未补齐（P0 回归）"
    finally:
        await ModelProfileService(db).delete(profile.id)


@pytest.mark.asyncio
async def test_probe_endpoints_status_and_ineligible(client, monkeypatch) -> None:
    """探测状态/重试端点：无快照 → none；不合格 → 409 probe_ineligible。"""
    from personal_assistant.config import settings as cfg

    monkeypatch.setattr(cfg, "coding_permission_models_enabled", True)
    monkeypatch.setattr(cfg, "agent_v2_model_probe_enabled", True)

    profile_id = f"ct3-ep-{uuid4().hex[:8]}"
    put = await client.put(
        f"/agent-model-profiles/{profile_id}",
        json={
            "provider": "ollama",
            "display_name": "CT3 endpoint",
            "model_name": "qwen-local",
            "native_tool_calls": False,
        },
    )
    assert put.status_code == 200, put.text
    try:
        status = await client.get(f"/agent-model-profiles/{profile_id}/tool-probe")
        assert status.status_code == 200, status.text
        assert status.json()["status"] == "none"

        retry = await client.post(
            f"/agent-model-profiles/{profile_id}/tool-probe"
        )
        assert retry.status_code == 409, retry.text
        assert retry.json()["error_code"] == "probe_ineligible"
    finally:
        await client.delete(f"/agent-model-profiles/{profile_id}")
