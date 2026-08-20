"""v0.6.0 C3: RunPlan + SSE 事件续读 测试。"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from personal_assistant.agents.contracts import (
    AgentRunLimits,
    ModelResponse,
    TokenUsage,
)
from personal_assistant.agents.repository import AgentRunRepository
from personal_assistant.config import settings
from personal_assistant.core.run_plan import (
    PlanTransitionInvalid,
    PlanVersionConflict,
    RunPlanService,
)


@pytest.fixture(autouse=True)
def _inject_immediate_model():
    """注入立即完成的模型，避免触发真实模型调用。"""
    from personal_assistant.api.routes_agent_runs import get_agent_model_client
    from personal_assistant.main_api import app

    class _ImmediateModel:
        async def complete(self, request, *, cancellation):
            del request, cancellation
            return ModelResponse(
                text="回答",
                usage=TokenUsage(input_tokens=4, output_tokens=2, cached_tokens=0),
                provider="fake",
                model="fake-model",
                request_id="fake-request",
                latency_ms=0.5,
            )

    app.dependency_overrides[get_agent_model_client] = lambda: _ImmediateModel()
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_agent_model_client, None)


def _items(*keys: str) -> list[dict]:
    """构造契约 §7.1 输入格式的 items。"""
    return [
        {"item_key": key, "title": f"任务 {key}", "detail": f"detail {key}"}
        for key in keys
    ]


class TestRunPlanService:
    """RunPlan 服务层测试。"""

    async def test_create_plan(self, db: AsyncSession):
        """创建计划项。"""
        repo = AgentRunRepository(db)
        run = await repo.create_run(
            run_id=str(uuid4()),
            limits=AgentRunLimits(),
        )

        svc = RunPlanService(db)
        items = await svc.create_plan(
            run_id=run.id,
            items=_items("analyze", "fix", "verify"),
        )
        assert len(items) == 3
        assert items[0]["plan_version"] == 1
        assert items[0]["status"] == "pending"
        assert items[0]["item_key"] == "analyze"
        assert items[0]["ordinal"] == 1

    async def test_plan_version_increments(self, db: AsyncSession):
        """计划更新时版本号递增。"""
        repo = AgentRunRepository(db)
        run = await repo.create_run(
            run_id=str(uuid4()),
            limits=AgentRunLimits(),
        )

        svc = RunPlanService(db)
        v1 = await svc.create_plan(
            run_id=run.id,
            items=_items("v1"),
        )
        assert v1[0]["plan_version"] == 1

        v2 = await svc.update_plan(
            run_id=run.id,
            expected_plan_version=1,
            items=_items("v2"),
        )
        assert v2[0]["plan_version"] == 2

    async def test_stale_version_rejected(self, db: AsyncSession):
        """过期版本更新被拒绝（不做 last-write-wins）。"""
        repo = AgentRunRepository(db)
        run = await repo.create_run(
            run_id=str(uuid4()),
            limits=AgentRunLimits(),
        )

        svc = RunPlanService(db)
        await svc.create_plan(run_id=run.id, items=_items("v1"))
        await svc.update_plan(
            run_id=run.id, expected_plan_version=1, items=_items("v2")
        )
        with pytest.raises(PlanVersionConflict):
            await svc.update_plan(
                run_id=run.id, expected_plan_version=1, items=_items("stale")
            )

    async def test_plan_item_status_transitions(self, db: AsyncSession):
        """计划项状态机转换。"""
        repo = AgentRunRepository(db)
        run = await repo.create_run(
            run_id=str(uuid4()),
            limits=AgentRunLimits(),
        )

        svc = RunPlanService(db)
        items = await svc.create_plan(
            run_id=run.id,
            items=_items("test"),
        )
        item_id = items[0]["id"]

        # pending -> in_progress
        result = await svc.update_item_status(
            item_id=item_id, new_status="in_progress"
        )
        assert result["status"] == "in_progress"

        # in_progress -> completed
        result = await svc.update_item_status(
            item_id=item_id, new_status="completed"
        )
        assert result["status"] == "completed"

    async def test_invalid_transition_rejected(self, db: AsyncSession):
        """非法状态转换被拒绝（pending 不能直接 completed）。"""
        repo = AgentRunRepository(db)
        run = await repo.create_run(
            run_id=str(uuid4()),
            limits=AgentRunLimits(),
        )

        svc = RunPlanService(db)
        items = await svc.create_plan(
            run_id=run.id,
            items=_items("test"),
        )
        item_id = items[0]["id"]

        with pytest.raises(PlanTransitionInvalid):
            await svc.update_item_status(
                item_id=item_id, new_status="completed"
            )

    async def test_terminal_item_cannot_regress(self, db: AsyncSession):
        """终态（completed）不能回到 pending/in_progress。"""
        repo = AgentRunRepository(db)
        run = await repo.create_run(
            run_id=str(uuid4()),
            limits=AgentRunLimits(),
        )

        svc = RunPlanService(db)
        items = await svc.create_plan(
            run_id=run.id,
            items=[
                {
                    "item_key": "item_a",
                    "title": "A",
                    "status": "completed",
                }
            ],
        )
        item_id = items[0]["id"]
        with pytest.raises(PlanTransitionInvalid):
            await svc.update_item_status(
                item_id=item_id, new_status="pending"
            )

    async def test_at_most_one_in_progress(self, db: AsyncSession):
        """创建时最多一个 in_progress 被拒绝。"""
        repo = AgentRunRepository(db)
        run = await repo.create_run(
            run_id=str(uuid4()),
            limits=AgentRunLimits(),
        )

        svc = RunPlanService(db)
        with pytest.raises(PlanTransitionInvalid):
            await svc.create_plan(
                run_id=run.id,
                items=[
                    {"item_key": "a", "title": "A", "status": "in_progress"},
                    {"item_key": "b", "title": "B", "status": "in_progress"},
                ],
            )

    async def test_get_plan_by_version(self, db: AsyncSession):
        """按版本号获取计划。"""
        repo = AgentRunRepository(db)
        run = await repo.create_run(
            run_id=str(uuid4()),
            limits=AgentRunLimits(),
        )

        svc = RunPlanService(db)
        await svc.create_plan(run_id=run.id, items=_items("v1"))
        await svc.update_plan(
            run_id=run.id, expected_plan_version=1, items=_items("v2")
        )

        v1_items = await svc.get_plan(run.id, plan_version=1)
        assert v1_items[0]["title"] == "任务 v1"

        v2_items = await svc.get_plan(run.id, plan_version=2)
        assert v2_items[0]["title"] == "任务 v2"


class TestPlanAPI:
    """RunPlan API 路由测试。"""

    async def test_create_plan_via_api(self, client, monkeypatch):
        """通过 API 创建计划。"""
        monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
        monkeypatch.setattr(settings, "agent_run_plan_enabled", True)

        resp = await client.post(
            "/agent-runs",
            json={"message": "test plan"},
        )
        assert resp.status_code == 202
        run_id = resp.json()["id"]

        resp = await client.post(
            f"/agent-runs/{run_id}/plan",
            json={
                "items": _items("step1", "step2"),
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["version"] == 1
        assert len(data["items"]) == 2

    async def test_stale_version_via_api(self, client, monkeypatch):
        """过期版本更新返回 409 plan_version_conflict。"""
        monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
        monkeypatch.setattr(settings, "agent_run_plan_enabled", True)

        resp = await client.post(
            "/agent-runs",
            json={"message": "test stale"},
        )
        run_id = resp.json()["id"]

        resp = await client.post(
            f"/agent-runs/{run_id}/plan",
            json={
                "expected_plan_version": 1,
                "items": _items("v1"),
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["version"] == 1

        # 基于 v1 更新 → v2
        resp = await client.post(
            f"/agent-runs/{run_id}/plan",
            json={
                "expected_plan_version": 1,
                "items": _items("v2"),
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["version"] == 2

        # 过期版本 1 再更新 → 409
        resp = await client.post(
            f"/agent-runs/{run_id}/plan",
            json={
                "expected_plan_version": 1,
                "items": _items("stale"),
            },
        )
        assert resp.status_code == 409
        assert resp.json().get("error_code") == "plan_version_conflict"

    async def test_update_plan_item_status_via_api(self, client, monkeypatch):
        """通过 API 更新计划项状态。"""
        monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
        monkeypatch.setattr(settings, "agent_run_plan_enabled", True)

        resp = await client.post(
            "/agent-runs",
            json={"message": "test status"},
        )
        run_id = resp.json()["id"]

        resp = await client.post(
            f"/agent-runs/{run_id}/plan",
            json={"items": _items("step1")},
        )
        item_id = resp.json()["items"][0]["id"]

        resp = await client.patch(
            f"/agent-runs/{run_id}/plan/{item_id}",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "in_progress"

    async def test_plan_api_hidden_when_flag_disabled(self, client):
        """flag 关闭时 plan API 返回 404。"""
        resp = await client.get("/agent-runs/test-run-id/plan")
        assert resp.status_code == 404
