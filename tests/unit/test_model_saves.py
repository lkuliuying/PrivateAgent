"""配置与凭据准备分离，失败和重启不提前切换活动路由。"""
import json
import sqlite3
import uuid

import pytest
from test_direct_models import configuration, configure, desktop

from private_agent_local.model_catalog import ProviderInput
from private_agent_local.model_errors import CloudError
from private_agent_local.model_saves import ModelSaves, PreparedSecret, PrepareSave


def operation(**values):
    return PrepareSave(operation_id=uuid.uuid4().hex, provider_id="provider", configuration=ProviderInput.model_validate(configuration()), **values)


@pytest.mark.asyncio
async def test_prepare_and_credential_do_not_change_live_model_or_key(tmp_path):
    async with desktop(tmp_path) as (models, _, client, _, calls):
        profile = await configure(client)
        service = ModelSaves(models, models.token)
        before = models.selection(models.token, profile)
        prepared = service.prepare(operation(credential_action="replace"))
        assert models.selection(models.token, profile) == before
        assert prepared["credential_alias"] != models.catalog.reference("provider")["alias"]
        with pytest.raises(CloudError, match="尚未就绪"):
            service.commit(prepared["id"])
        service.credential(prepared["id"], PreparedSecret(alias=prepared["credential_alias"], secret="synthetic-new-value"))
        assert models.selection(models.token, profile) == before
        committed = service.commit(prepared["id"])
        assert committed["status"] == "completed"
        assert service.commit(prepared["id"]) == committed
        assert models.selection(models.token, profile)[2] == "synthetic-new-value"
        assert calls == []
        rows = models.catalog.db.execute("SELECT data FROM model_save_operations").fetchall()
        assert "synthetic-new-value" not in json.dumps(rows)


@pytest.mark.asyncio
async def test_restart_preserves_pending_operation_and_requires_explicit_commit(tmp_path):
    async with desktop(tmp_path) as (models, _, client, _, calls):
        await configure(client)
        service = ModelSaves(models, models.token)
        value = operation(credential_action="replace")
        value.configuration.base_url = "https://other.example.test/v1"
        prepared = service.prepare(value)
        directory, scope, token = models.catalog.db.execute("PRAGMA database_list").fetchone()[2], models.catalog.scope, models.token
        from pathlib import Path
        await models.bind_models(Path(directory).parent, scope, token)
        restarted = ModelSaves(models, token)
        assert restarted.list()[0]["id"] == prepared["id"]
        assert models.catalog.provider("provider")["base_url"] != value.configuration.base_url
        models.secrets["secret://os-keyring/model-provider/" + prepared["credential_alias"]] = "synthetic-reloaded-value"
        assert restarted.list()[0]["credential_ready"]
        assert models.catalog.provider("provider")["base_url"] != value.configuration.base_url
        restarted.commit(prepared["id"])
        assert models.catalog.provider("provider")["base_url"] == value.configuration.base_url
        assert calls == []


@pytest.mark.asyncio
async def test_changed_configuration_blocks_stale_commit(tmp_path):
    async with desktop(tmp_path) as (models, _, client, _, _):
        await configure(client)
        service = ModelSaves(models, models.token)
        prepared = service.prepare(operation())
        models.catalog.upsert("provider", ProviderInput.model_validate(configuration(name="另一个窗口")))
        with pytest.raises(CloudError, match="发生变化"):
            service.commit(prepared["id"])
        assert models.catalog.provider("provider")["name"] == "另一个窗口"


@pytest.mark.asyncio
async def test_failed_commit_rolls_back_catalog_and_journal(tmp_path):
    async with desktop(tmp_path) as (models, _, client, _, _):
        await configure(client)
        service = ModelSaves(models, models.token)
        value = operation()
        value.configuration.name = "新名称"
        prepared = service.prepare(value)
        before = json.dumps(models.catalog.data, sort_keys=True)
        models.catalog.db.execute("CREATE TEMP TRIGGER reject_commit BEFORE UPDATE ON model_save_operations WHEN NEW.status='completed' BEGIN SELECT RAISE(ABORT,'controlled failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match="controlled"):
            service.commit(prepared["id"])
        assert json.dumps(models.catalog.data, sort_keys=True) == before
        assert service.raw(prepared["id"])["status"] == "prepared"
        saved = json.loads(models.catalog.db.execute("SELECT data FROM model_catalog").fetchone()[0])
        assert saved == models.catalog.data


@pytest.mark.asyncio
async def test_cleanup_reservation_prevents_alias_reuse_and_preserves_active_keys(tmp_path):
    async with desktop(tmp_path) as (models, _, client, _, _):
        await configure(client)
        service = ModelSaves(models, models.token)
        old = models.catalog.reference("provider")["alias"]
        value = operation(credential_action="replace")
        value.configuration.base_url = "https://second.example.test/v1"
        prepared = service.prepare(value)
        service.credential(prepared["id"], PreparedSecret(alias=prepared["credential_alias"], secret="synthetic-second-value"))
        service.commit(prepared["id"])
        assert service.unused_aliases() == [old]
        with pytest.raises(CloudError):
            service.reserve_cleanup([prepared["credential_alias"]])
        service.reserve_cleanup([old])
        models.catalog.upsert("provider", ProviderInput.model_validate(configuration()))
        assert models.catalog.reference("provider")["alias"] != old
        service.confirm_cleanup(old)
        assert old not in service.unused_aliases()
        assert "secret://os-keyring/model-provider/" + old not in models.secrets


@pytest.mark.asyncio
async def test_operation_validation_and_duplicate_identity(tmp_path):
    async with desktop(tmp_path) as (models, _, client, _, _):
        service = ModelSaves(models, models.token)
        value = operation()
        first = service.prepare(value)
        assert service.prepare(value) == first
        with pytest.raises(ValueError, match="不匹配"):
            service.credential(first["id"], PreparedSecret(alias="0" * 64, secret="synthetic-value"))
        value.configuration.name = "更改内容"
        with pytest.raises(CloudError):
            service.prepare(value)
        service.discard(first["id"])
        with pytest.raises(CloudError, match="放弃"):
            service.commit(first["id"])
        response = await client.post("/model-save-operations", json={"unexpected": "synthetic-private-input"})
        assert response.status_code == 422 and "synthetic-private-input" not in response.text


@pytest.mark.asyncio
async def test_completed_operation_cannot_confirm_a_later_configuration(tmp_path):
    async with desktop(tmp_path) as (models, _, client, _, _):
        await configure(client)
        service = ModelSaves(models, models.token)
        value = operation()
        service.prepare(value)
        service.commit(value.operation_id)
        models.catalog.upsert("provider", ProviderInput.model_validate(configuration(name="后续配置")))
        with pytest.raises(CloudError, match="随后已改变"):
            service.prepare(value)


@pytest.mark.asyncio
async def test_changed_endpoint_without_credential_cannot_replace_active_configuration(tmp_path):
    async with desktop(tmp_path) as (models, _, client, _, _):
        await configure(client)
        service = ModelSaves(models, models.token)
        value = operation()
        value.configuration.base_url = "https://new.example.test/v1"
        prepared = service.prepare(value)
        assert prepared["credential_ready"] is False
        with pytest.raises(CloudError, match="密钥尚未就绪"):
            service.commit(prepared["id"])
        assert models.catalog.provider("provider")["base_url"] != value.configuration.base_url
        service.credential(prepared["id"], PreparedSecret(alias=prepared["credential_alias"], secret="synthetic-restored-credential"))
        service.commit(prepared["id"])
        assert models.catalog.provider("provider")["base_url"] == value.configuration.base_url
