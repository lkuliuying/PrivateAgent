from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from personal_assistant.agents.contracts import ModelMessage, ModelRequest
from personal_assistant.agents.runtime import CancellationToken
from personal_assistant.api import routes_providers, routes_workspaces
from personal_assistant.api.routes_model_profiles import (
    ModelProfileUpsertRequest,
    upsert_model_profile,
)
from personal_assistant.api.routes_providers import ProviderModelsRequest
from personal_assistant.core.model_profiles import ModelProfileService
from personal_assistant.core.settings import SettingsService
from personal_assistant.llm.contracts import (
    ModelCapabilities,
    ModelGatewayError,
    RetryPolicy,
)
from personal_assistant.llm.gateway import ModelGateway


@pytest.mark.asyncio
async def test_model_list_uses_draft_secret_without_persisting_it(db, monkeypatch):
    captured: dict[str, str] = {}

    class FakeClient:
        def __init__(self, **kwargs):
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            del args

        async def get(self, url: str, *, headers: dict[str, str]):
            captured["url"] = url
            captured["authorization"] = headers.get("Authorization", "")
            request = httpx.Request("GET", url, headers=headers)
            return httpx.Response(
                200,
                request=request,
                json={"data": [{"id": "glm-5"}, {"id": "glm-4.7"}]},
            )

    monkeypatch.setattr(routes_providers.httpx, "AsyncClient", FakeClient)
    before = await SettingsService(db).get("openai_api_key")
    result = await routes_providers.list_provider_models(
        ProviderModelsRequest(
            provider_type="openai",
            remote_provider_enabled=True,
            base_url="https://example.com/v1",
            api_key=SecretStr("draft-secret"),
        ),
        db,
    )

    assert result["models"] == ["glm-4.7", "glm-5"]
    assert captured == {
        "url": "https://example.com/v1/models",
        "authorization": "Bearer draft-secret",
    }
    assert await SettingsService(db).get("openai_api_key") == before


@pytest.mark.asyncio
async def test_default_profile_updates_project_wide_provider_settings(db, monkeypatch):
    monkeypatch.setattr(
        "personal_assistant.api.routes_model_profiles.cfg.coding_permission_models_enabled",
        True,
    )
    service = SettingsService(db)
    before = await service.get_all()
    profile_id = f"unified-{uuid4().hex}"
    try:
        result = await upsert_model_profile(
            profile_id,
            ModelProfileUpsertRequest(
                provider="openai",
                display_name="ignored-name",
                model_name="glm-5",
                is_local=False,
                reasoning_efforts=["high", "max"],
                is_default=True,
            ),
            db,
        )
        values = await service.get_all()
        assert result.is_default is True
        assert values["provider_type"] == "openai"
        assert values["openai_model"] == "glm-5"
    finally:
        if await ModelProfileService(db).get(profile_id):
            await ModelProfileService(db).delete(profile_id)
        await service.update(
            {
                "provider_type": before["provider_type"],
                "llm_model": before["llm_model"],
                "openai_model": before["openai_model"],
                "claude_model": before["claude_model"],
            }
        )


@pytest.mark.asyncio
async def test_rate_limit_error_keeps_safe_upstream_code_and_message():
    class LimitedAdapter:
        provider_name = "openai"
        model_name = "glm-5"
        capabilities = ModelCapabilities(False, True, False, False, True)

        async def complete(self, request, *, cancellation):
            del request, cancellation
            req = httpx.Request("POST", "https://example.com/chat/completions")
            response = httpx.Response(
                429,
                request=req,
                json={"error": {"code": "1302", "message": "并发请求达到上限"}},
            )
            raise httpx.HTTPStatusError(
                "rate limited",
                request=req,
                response=response,
            )

    with pytest.raises(ModelGatewayError) as exc_info:
        await ModelGateway(
            LimitedAdapter(),
            retry_policy=RetryPolicy(max_attempts=1),
        ).complete(
            ModelRequest(messages=(ModelMessage(role="user", content="hello"),)),
            cancellation=CancellationToken(),
        )

    assert exc_info.value.code == "rate_limited"
    assert "HTTP 429 · 1302 · 并发请求达到上限" in str(exc_info.value)


@pytest.mark.asyncio
async def test_workspace_attachment_is_copied_and_returns_relative_path(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(routes_workspaces.cfg, "project_bound_runs_enabled", True)
    root = tmp_path / "workspace"
    root.mkdir()
    source = tmp_path / "outside.txt"
    source.write_text("attachment", encoding="utf-8")

    project = await client.post(
        "/projects",
        json={"name": f"attach-{uuid4().hex[:8]}", "root_path": str(root)},
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    workspace = await client.post(f"/projects/{project_id}/workspaces/root/ensure")
    assert workspace.status_code == 201, workspace.text
    workspace_id = workspace.json()["id"]

    response = await client.post(
        f"/projects/{project_id}/workspaces/{workspace_id}/attachments",
        json={"source_path": str(source)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rel_path"].startswith(".privateagent/attachments/")
    assert not Path(body["rel_path"]).is_absolute()
    assert (root / body["rel_path"]).read_text(encoding="utf-8") == "attachment"
    await client.delete(f"/projects/{project_id}")
