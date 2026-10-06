"""恢复模型身份、默认继承和二次备份均使用隔离配置，不请求模型。"""
import copy
import json

import pytest
from test_direct_models import configuration, configure, desktop
from test_local_backups import records, save_package

from private_agent_core.history import encode_archive
from private_agent_local.backups import (
    export_backup,
    import_configuration,
    import_data,
    load_backup,
    preview_backup,
)
from private_agent_local.model_preferences import resolve


def load_package(tmp_path, runtime, package, *, legacy=False):
    if legacy:
        package = copy.deepcopy(package)
        package["format"] = "privateagent.backup.v1"
        if package["payload"]["kind"] == "application":
            package["payload"]["model_selections"] = [
                {key: item[key] for key in ("scope", "id", "profile_id")}
                for item in package["payload"]["model_selections"] if item["source_scope"] != "global"
            ]
    path = tmp_path / "backup.json"
    save_package(path, package)
    return load_backup(str(path), runtime)


def restore(tmp_path, runtime, data, digest):
    records = data["history"]["records"]
    return import_data(data, digest, {str(item["id"]): str(tmp_path) for item in records["projects"]},
                       {str(item["id"]): str(tmp_path) for item in records["workspaces"]}, runtime)


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["project", "session", "global"])
@pytest.mark.parametrize("legacy", [False, True])
async def test_matching_model_identity_restores_without_changing_scope(tmp_path, scope, legacy):
    async with desktop(tmp_path) as (models, app, client, _, calls):
        profile = await configure(client)
        runtime = app.state.desktop.runtime
        pid, _, session = await records(client, tmp_path / "project")
        if scope != "global":
            runtime.store.update(scope, pid if scope == "project" else session["id"], model_profile_id=profile)
        package = export_backup(runtime, "application", "standard")
        data, digest = load_package(tmp_path, runtime, package, legacy=legacy)
        result = restore(tmp_path, runtime, data, digest)
        project = next(item for item in runtime.store.list("project") if item["id"] != pid)
        restored_session = next(item for item in runtime.store.list("session") if item["id"] != session["id"])
        preference = resolve(runtime.store, models.catalog.profiles(enabled_only=True), project["id"], restored_session["id"])
        assert preference["profile_id"] == profile and preference["available"] is True
        assert preference["source"] == scope
        assert not project.get("model_restore_pending") and not restored_session.get("model_restore_pending")
        assert result["imported_counts"]["models_pending_confirmation"] == 0
        assert calls == []


@pytest.mark.asyncio
async def test_endpoint_conflict_stays_pending_through_second_export_and_restore(tmp_path):
    async with desktop(tmp_path) as (models, app, client, _, calls):
        profile = await configure(client)
        runtime = app.state.desktop.runtime
        pid, _, session = await records(client, tmp_path / "project")
        runtime.store.update("project", pid, model_profile_id=profile)
        runtime.store.update("session", session["id"], model_profile_id=profile)
        package = export_backup(runtime, "application", "standard")
        result = await client.put("/model-providers/provider", json=configuration(base_url="https://destination.example.test/v1"))
        assert result.status_code == 200
        data, digest = load_package(tmp_path, runtime, package)
        assert import_configuration(data, models.catalog)["skipped"] == ["provider"]
        preview = preview_backup(str(tmp_path / "backup.json"), runtime)
        assert all(item["requires_confirmation"] for item in preview["model_selections"])
        assert all(item["target_identity"]["base_url"] == "https://destination.example.test/v1" for item in preview["model_selections"])
        imported = restore(tmp_path, runtime, data, digest)
        assert imported["imported_counts"]["models_pending_confirmation"] == 2
        project = next(item for item in runtime.store.list("project") if item["id"] != pid)
        assert project["model_profile_id"] is None
        assert project["model_restore_pending"]["source_identity"]["base_url"] == "https://provider.example.test/v1"
        second_package = export_backup(runtime, "application", "standard")
        pending = [item for item in second_package["payload"]["model_selections"] if item["requires_confirmation"]]
        assert len(pending) == 2
        assert all(item["source_identity"]["base_url"] == "https://provider.example.test/v1" for item in pending)
        # 即使本机后来恢复原地址，也不能替用户消掉上次的待确认状态。
        assert (await client.put("/model-providers/provider", json=configuration())).status_code == 200
        second_data, second_digest = load_package(tmp_path, runtime, second_package)
        second_result = restore(tmp_path, runtime, second_data, second_digest)
        assert second_result["imported_counts"]["models_pending_confirmation"] >= 2
        new_projects = [item for item in runtime.store.list("project") if item.get("import_id") == second_result["id"]]
        assert any(item.get("model_restore_pending", {}).get("source_identity", {}).get("base_url") == "https://provider.example.test/v1" for item in new_projects)
        assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_changed_global_default_cannot_silently_replace_inherited_model(tmp_path, legacy):
    async with desktop(tmp_path) as (models, app, client, _, calls):
        source_profile = await configure(client)
        runtime = app.state.desktop.runtime
        pid, _, _ = await records(client, tmp_path / "project")
        package = export_backup(runtime, "application", "standard")
        other = await client.put("/model-providers/other", json=configuration(base_url="https://other.example.test/v1"))
        assert other.status_code == 200
        models.catalog.set_default(other.json()["models"][0]["profile_id"])
        data, digest = load_package(tmp_path, runtime, package, legacy=legacy)
        result = restore(tmp_path, runtime, data, digest)
        project = next(item for item in runtime.store.list("project") if item["id"] != pid)
        pending = project["model_restore_pending"]
        assert project["model_profile_id"] is None
        assert pending["source_scope"] == "global" and pending["profile_id"] == source_profile
        assert resolve(runtime.store, models.catalog.profiles(enabled_only=True), project["id"])["available"] is False
        assert result["imported_counts"]["models_pending_confirmation"] == 1
        assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["missing", "disabled_provider", "disabled_profile", "unknown_source"])
async def test_missing_disabled_and_unknown_models_remain_pending(tmp_path, condition):
    async with desktop(tmp_path) as (models, app, client, _, calls):
        profile = await configure(client)
        runtime = app.state.desktop.runtime
        pid, _, _ = await records(client, tmp_path / "project")
        runtime.store.update("project", pid, model_profile_id="removed-source" if condition == "unknown_source" else profile)
        package = export_backup(runtime, "application", "standard")
        if condition == "missing":
            models.catalog.delete("provider")
        elif condition == "disabled_provider":
            assert (await client.put("/model-providers/provider", json=configuration(enabled=False))).status_code == 200
        elif condition == "disabled_profile":
            changed = {**package["payload"]["configuration"]["profiles"][0]["configuration"], "enabled": False}
            assert (await client.put(f"/agent-model-profiles/{profile}", json=changed)).status_code == 200
            assert models.catalog.provider("provider")["enabled"] is True
        data, digest = load_package(tmp_path, runtime, package)
        result = restore(tmp_path, runtime, data, digest)
        project = next(item for item in runtime.store.list("project") if item["id"] != pid)
        assert project["model_profile_id"] is None and project["model_restore_pending"]
        assert result["imported_counts"]["models_pending_confirmation"] == 1
        assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change,expected_pending", [("protocol", True), ("api_format", True), ("normalized_url", False)])
async def test_identity_compares_protocol_format_and_normalized_url(tmp_path, change, expected_pending):
    async with desktop(tmp_path) as (_, app, client, _, calls):
        profile = await configure(client)
        runtime = app.state.desktop.runtime
        pid, _, _ = await records(client, tmp_path / "project")
        runtime.store.update("project", pid, model_profile_id=profile)
        package = export_backup(runtime, "application", "standard")
        if change == "protocol":
            changed = configuration("claude")
        elif change == "api_format":
            changed = configuration(api_format="responses")
        else:
            changed = configuration(base_url="https://PROVIDER.example.test:443/v1/")
        response = await client.put("/model-providers/provider", json=changed)
        assert response.status_code == 200
        assert response.json()["models"][0]["profile_id"] == profile
        data, digest = load_package(tmp_path, runtime, package)
        result = restore(tmp_path, runtime, data, digest)
        project = next(item for item in runtime.store.list("project") if item["id"] != pid)
        assert bool(project["model_restore_pending"]) is expected_pending
        assert result["imported_counts"]["models_pending_confirmation"] == int(expected_pending)
        assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("temperature", [0.0, 1.0])
@pytest.mark.parametrize("legacy", [False, True])
async def test_original_numeric_bytes_load_and_reserialized_damage_is_rejected(tmp_path, temperature, legacy):
    async with desktop(tmp_path) as (models, app, _, _, calls):
        runtime = app.state.desktop.runtime
        models.catalog.data["parameters"]["llm_temperature"] = temperature
        package = export_backup(runtime, "configuration", "standard")
        data, _ = load_package(tmp_path, runtime, package, legacy=legacy)
        assert data["configuration"]["parameters"]["llm_temperature"] == temperature
        path = tmp_path / "backup.json"
        modified = json.loads(path.read_bytes())
        modified["payload"]["configuration"]["parameters"]["llm_temperature"] = int(temperature)
        path.write_bytes(encode_archive(modified))
        with pytest.raises(ValueError, match="摘要校验失败"):
            load_backup(str(path), runtime)
        assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["duplicate_scope", "unknown_scope", "identity_mismatch"])
async def test_v2_model_selection_validation_rejects_ambiguous_sources(tmp_path, damage):
    async with desktop(tmp_path) as (_, app, client, _, _):
        await configure(client)
        runtime = app.state.desktop.runtime
        await records(client, tmp_path / "project")
        package = export_backup(runtime, "application", "standard")
        selection = package["payload"]["model_selections"][0]
        if damage == "duplicate_scope":
            package["payload"]["model_selections"].append(copy.deepcopy(selection))
        elif damage == "unknown_scope":
            selection["id"] = 999
        else:
            selection["source_identity"]["model_id"] = "different-model"
        path = tmp_path / "backup.json"
        save_package(path, package)
        with pytest.raises(ValueError, match="模型"):
            load_backup(str(path), runtime)


@pytest.mark.asyncio
async def test_pending_state_write_failure_rolls_back_whole_import(tmp_path, monkeypatch):
    async with desktop(tmp_path) as (_, app, client, _, _):
        runtime = app.state.desktop.runtime
        await records(client, tmp_path / "project")
        package = export_backup(runtime, "application", "standard")
        data, digest = load_package(tmp_path, runtime, package)
        from private_agent_local import backups
        original = backups.restore_selection

        def fail_after_marker(*args):
            original(*args)
            raise OSError("controlled pending-state write failure")

        monkeypatch.setattr(backups, "restore_selection", fail_after_marker)
        with pytest.raises(OSError, match="controlled"):
            restore(tmp_path, runtime, data, digest)
        assert len(runtime.store.list("project")) == 1
        assert runtime.store.db.execute("SELECT count(*) FROM history_imports").fetchone()[0] == 0
        assert all(not item.get("model_restore_pending") for item in runtime.store.list("project"))
