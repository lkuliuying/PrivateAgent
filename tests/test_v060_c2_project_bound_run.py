"""v0.6.0 C2: Project-bound Run 创建 + client_request_id 幂等 测试。"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from personal_assistant.agents.contracts import AgentRunLimits, ModelResponse, TokenUsage
from personal_assistant.agents.repository import AgentRunRepository
from personal_assistant.config import settings
from personal_assistant.core.models import Project


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


class TestClientRequestIdIdempotency:
    """client_request_id 幂等创建。"""

    async def test_same_client_request_id_returns_existing_run(self, db: AsyncSession):
        """相同 client_request_id 返回原 run，不新建。"""
        repo = AgentRunRepository(db)
        client_id = str(uuid4())

        run1 = await repo.create_run(
            run_id=str(uuid4()),
            limits=AgentRunLimits(),
            client_request_id=client_id,
        )
        run2 = await repo.create_run(
            run_id=str(uuid4()),
            limits=AgentRunLimits(),
            client_request_id=client_id,
        )
        assert run1.id == run2.id

    async def test_different_client_request_id_creates_new_run(self, db: AsyncSession):
        """不同 client_request_id 创建不同 run。"""
        repo = AgentRunRepository(db)

        run1 = await repo.create_run(
            run_id=str(uuid4()),
            limits=AgentRunLimits(),
            client_request_id=str(uuid4()),
        )
        run2 = await repo.create_run(
            run_id=str(uuid4()),
            limits=AgentRunLimits(),
            client_request_id=str(uuid4()),
        )
        assert run1.id != run2.id

    async def test_null_client_request_id_always_creates_new(self, db: AsyncSession):
        """client_request_id 为 None 时每次创建新 run。"""
        repo = AgentRunRepository(db)

        run1 = await repo.create_run(
            run_id=str(uuid4()),
            limits=AgentRunLimits(),
            client_request_id=None,
        )
        run2 = await repo.create_run(
            run_id=str(uuid4()),
            limits=AgentRunLimits(),
            client_request_id=None,
        )
        assert run1.id != run2.id


class TestProjectBoundRunAPI:
    """project-bound run 创建 API 测试。"""

    async def test_create_run_with_project_binding(self, client, monkeypatch, tmp_path):
        """创建带 project 绑定的 run。"""
        monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
        monkeypatch.setattr(settings, "project_bound_runs_enabled", True)

        root = str(tmp_path.resolve())
        resp = await client.post(
            "/projects",
            json={"name": "c2-test", "root_path": root},
        )
        assert resp.status_code == 201
        project_id = resp.json()["id"]

        resp = await client.post(
            f"/projects/{project_id}/workspaces/root/ensure"
        )
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
        session_id = resp.json()["id"]

        resp = await client.post(
            "/agent-runs",
            json={
                "session_id": session_id,
                "message": "test project-bound",
                "project_id": project_id,
                "workspace_id": ws_id,
                "permission_mode": "confirm",
                "client_request_id": str(uuid4()),
            },
        )
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert data["project_id"] == project_id
        assert data["workspace_id"] == ws_id
        assert data["permission_mode"] == "confirm"
        assert data["idempotent_replay"] is False

    async def test_create_run_with_wrong_workspace_rejected(
        self, client, monkeypatch, tmp_path
    ):
        """workspace 不属于 project 时拒绝（403 workspace_outside_trust）。"""
        monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
        monkeypatch.setattr(settings, "project_bound_runs_enabled", True)

        root1 = str((tmp_path / "p1").resolve())
        (tmp_path / "p1").mkdir()
        root2 = str((tmp_path / "p2").resolve())
        (tmp_path / "p2").mkdir()

        resp = await client.post(
            "/projects",
            json={"name": "c2-p1", "root_path": root1},
        )
        p1_id = resp.json()["id"]

        resp = await client.post(
            "/projects",
            json={"name": "c2-p2", "root_path": root2},
        )
        p2_id = resp.json()["id"]

        resp = await client.post(
            f"/projects/{p2_id}/workspaces/root/ensure"
        )
        ws2_id = resp.json()["id"]

        # coding session 绑定 p1 + ws2（session 层面一致）
        resp = await client.post(
            "/sessions",
            json={
                "title": "coding",
                "project_id": p1_id,
                "workspace_id": ws2_id,
                "kind": "coding",
            },
        )
        session_id = resp.json()["id"]

        # 请求用 p1 的 project_id 但 ws2 的 workspace_id（ws2 实际属于 p2）
        resp = await client.post(
            "/agent-runs",
            json={
                "session_id": session_id,
                "message": "test",
                "project_id": p1_id,
                "workspace_id": ws2_id,
                "permission_mode": "confirm",
                "client_request_id": str(uuid4()),
            },
        )
        assert resp.status_code == 403, resp.text
        assert resp.json().get("error_code") == "workspace_outside_trust"

    async def test_client_request_id_idempotent_via_api(
        self, client, monkeypatch, tmp_path
    ):
        """通过 API 验证 client_request_id 幂等。"""
        monkeypatch.setattr(settings, "agent_runs_api_enabled", True)

        client_id = str(uuid4())

        resp1 = await client.post(
            "/agent-runs",
            json={
                "message": "test",
                "client_request_id": client_id,
            },
        )
        assert resp1.status_code == 202

        resp2 = await client.post(
            "/agent-runs",
            json={
                "message": "test",
                "client_request_id": client_id,
            },
        )
        assert resp2.status_code == 202
        assert resp1.json()["id"] == resp2.json()["id"]
