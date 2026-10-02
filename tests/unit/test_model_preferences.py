"""作用域模型引用、继承与禁用边界，不调用真实模型。"""
import pytest
from test_direct_models import configuration, configure, desktop

from private_agent_local.model_catalog import ProviderInput


@pytest.mark.asyncio
async def test_scopes_inherit_persist_and_reject_provider_overrides(tmp_path):
    async with desktop(tmp_path) as (models, app, client, _, calls):
        first = await configure(client)
        models.catalog.upsert("second", ProviderInput.model_validate(configuration()))
        second = next(item["id"] for item in models.catalog.profiles() if item["provider_id"] == "second")
        root = tmp_path / "project"
        root.mkdir()
        project = (await client.post("/projects", json={"name": "项目", "root_path": str(root)})).json()
        workspace = (await client.get(f"/projects/{project['id']}/workspaces")).json()[0]
        session = (await client.post("/sessions", json={"project_id": project["id"], "workspace_id": workspace["id"], "title": "会话", "kind": "coding"})).json()
        binding = {"project_id": project["id"], "session_id": session["id"]}
        assert (await client.get("/model-preferences", params=binding)).json()["source"] == "global"
        value = {**binding, "scope": "project", "profile_id": second}
        assert (await client.put("/model-preferences", json=value)).json()["source"] == "project"
        value.update(scope="session", profile_id=first)
        assert (await client.put("/model-preferences", json=value)).json()["profile_id"] == first
        value["profile_id"] = None
        inherited = (await client.put("/model-preferences", json=value)).json()
        assert (inherited["source"], inherited["profile_id"]) == ("project", second)
        invalid = await client.put("/model-preferences", json={**value, "base_url": "https://other.example.test"})
        assert invalid.status_code == 422
        invalid = await client.get("/model-preferences", params={**binding, "project_id": 9999})
        assert invalid.status_code >= 400
        models.catalog.delete("second")
        unavailable = (await client.get("/model-preferences", params=binding)).json()
        assert unavailable["profile_id"] == second and unavailable["available"] is False
        result = await client.post("/agent-runs", json={**binding, "workspace_id": workspace["id"], "message": "不能静默回退"})
        assert result.status_code == 409
        assert calls == []
