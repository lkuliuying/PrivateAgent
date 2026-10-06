"""备份恢复使用隔离目录，校验所有材料与冲突，不重放任务。"""
import copy
import hashlib
import json
import uuid

import pytest
from test_direct_models import configure, desktop
from test_local_attachments import commit_attachment, staged

from private_agent_core.history import encode_archive
from private_agent_local.backups import (
    export_backup,
    import_configuration,
    import_data,
    load_backup,
    preview_backup,
)
from private_agent_local.drafts import DraftData, Drafts, DraftWrite


async def records(client, root):
    root.mkdir()
    project = (await client.post("/projects", json={"name": "备份测试", "root_path": str(root)})).json()
    workspace = (await client.get(f"/projects/{project['id']}/workspaces")).json()[0]
    session = (await client.post("/sessions", json={"project_id": project["id"], "workspace_id": workspace["id"], "kind": "coding", "title": "未完成输入"})).json()
    return project["id"], workspace["id"], session


def save_package(path, package):
    package["sha256"] = hashlib.sha256(encode_archive(package["payload"])).hexdigest()
    path.write_bytes(encode_archive(package))


@pytest.mark.asyncio
async def test_application_roundtrip_restores_drafts_refs_and_preserves_original_files(tmp_path):
    async with desktop(tmp_path) as (models, app, client, _, calls):
        selected_profile = await configure(client)
        runtime = app.state.desktop.runtime
        store = runtime.store
        pid, wid, session = await records(client, tmp_path / "project")
        sent, sent_draft, _ = staged(tmp_path, store, pid, wid, session["id"])
        commit_attachment(store, sent, sent_draft, session)
        item, draft, source = staged(tmp_path, store, pid, wid, session["id"], text="还没有发送")
        key = f"pa_coding_draft_v2_{pid}_{wid}_{session['id']}"
        Drafts(store).put(key, DraftWrite(revision=0, mutation_id=uuid.uuid4().hex, data=DraftData(text="正在编辑", draftId=draft, attachments=[item], clientRequestId="old-request")))
        store.update("project", pid, model_profile_id=selected_profile)
        package = export_backup(runtime, "application", "compact")
        assert "fixture-provider-secret" not in json.dumps(package)
        path = tmp_path / "backup.json"
        save_package(path, package)
        preview = preview_backup(str(path), runtime)
        assert preview["providers"][0]["conflict"]
        data, digest = load_backup(str(path), runtime)
        result = import_data(data, digest, {str(pid): str(source.parent)}, {str(wid): str(source.parent)}, runtime)
        assert result["imported_counts"]["attachments"] == 2
        assert result["imported_counts"]["sent_attachments"] == 1
        assert result["imported_counts"]["draft_attachments"] == 1
        assert import_data(data, digest, {str(pid): str(source.parent)}, {str(wid): str(source.parent)}, runtime)["id"] == result["id"]
        imported = next(p for p in store.list("project") if p["id"] != pid)
        assert imported["model_profile_id"] == selected_profile
        assert imported["model_restore_pending"] is None
        restored = [Drafts(store).get(row[0])["data"] for row in store.db.execute("SELECT scope_key FROM composer_drafts WHERE project_id=?", (imported["id"],))]
        assert restored[0]["text"] == "正在编辑" and restored[0]["clientRequestId"] == ""
        assert store.attachments.read(restored[0]["attachments"][0]["id"], draft_id=restored[0]["draftId"])["content"] == "还没有发送"
        assert source.read_text(encoding="utf-8") == "还没有发送"
        assert store.db.execute("SELECT count(*) FROM grants").fetchone()[0] == 0
        assert calls == []


@pytest.mark.asyncio
async def test_preview_reports_file_metadata_and_import_counts_are_persisted(tmp_path):
    async with desktop(tmp_path) as (_, app, client, _, calls):
        runtime = app.state.desktop.runtime
        pid, wid, _ = await records(client, tmp_path / "project")
        staged(tmp_path, runtime.store, pid, wid)
        package = export_backup(runtime, "application", "standard")
        path = tmp_path / "backup.json"
        save_package(path, package)
        preview = preview_backup(str(path), runtime)
        assert preview["format"] == "privateagent.backup.v2"
        assert preview["created_at"] == package["payload"]["created_at"]
        assert preview["size_bytes"] == path.stat().st_size
        assert "运行历史子集" in preview["coverage"]
        data, digest = load_backup(str(path), runtime)
        result = import_data(data, digest, {str(pid): str(tmp_path)}, {str(wid): str(tmp_path)}, runtime)
        assert result["source_kind"] == "application" and result["backup_format"] == "privateagent.backup.v2"
        assert result["already_imported"] is False
        assert result["imported_counts"] == {"projects": 1, "workspaces": 1, "sessions": 2, "messages": 0, "runs": 0,
                                             "attachments": 1, "sent_attachments": 0,
                                             "drafts": 1, "draft_attachments": 1, "model_selections": 1, "models_pending_confirmation": 1}
        assert result["skipped_counts"] == {"projects": 0, "workspaces": 0, "sessions": 0, "messages": 0, "runs": 0, "attachments": 0}
        stored = runtime.store.db.execute("SELECT data FROM history_imports WHERE id=?", (result["id"],)).fetchone()[0]
        repeated = import_data(data, digest, {}, {}, runtime)
        assert repeated["already_imported"] is True and repeated["id"] == result["id"]
        assert repeated["imported_counts"] == result["imported_counts"]
        assert runtime.store.db.execute("SELECT data FROM history_imports WHERE id=?", (result["id"],)).fetchone()[0] == stored
        assert "already_imported" not in json.loads(stored)
        assert calls == []


@pytest.mark.asyncio
async def test_skipped_history_counts_do_not_claim_unrestored_records_or_attachments(tmp_path):
    async with desktop(tmp_path) as (_, app, client, _, calls):
        runtime = app.state.desktop.runtime
        pid, wid, session = await records(client, tmp_path / "project")
        item, draft, _ = staged(tmp_path, runtime.store, pid, wid, session["id"])
        commit_attachment(runtime.store, item, draft, session)
        package = export_backup(runtime, "application", "standard")
        package["payload"]["history"]["records"]["sessions"][0]["kind"] = "chat"
        path = tmp_path / "backup.json"
        save_package(path, package)
        data, digest = load_backup(str(path), runtime)
        result = import_data(data, digest, {str(pid): str(tmp_path)}, {str(wid): str(tmp_path)}, runtime)
        assert result["skipped_counts"] == {"projects": 0, "workspaces": 0, "sessions": 1, "messages": 1, "runs": 0, "attachments": 1}
        assert all(result["imported_counts"][key] == 0 for key in ("sessions", "messages", "attachments", "sent_attachments"))
        assert calls == []


@pytest.mark.asyncio
async def test_real_file_size_boundary_accepts_64_mib_and_rejects_one_more_byte(tmp_path):
    async with desktop(tmp_path) as (_, app, _, _, calls):
        from private_agent_local.backups import MAX_BYTES
        runtime = app.state.desktop.runtime
        package = export_backup(runtime, "configuration", "standard")
        content = encode_archive(package)
        path = tmp_path / "boundary.json"
        with path.open("wb") as stream:
            stream.write(content)
            remaining = MAX_BYTES - len(content)
            while remaining:
                chunk = min(remaining, 1024 * 1024)
                stream.write(b" " * chunk)
                remaining -= chunk
        loaded, _ = load_backup(str(path), runtime)
        assert loaded.size_bytes == 64 * 1024 * 1024
        with path.open("ab") as stream:
            stream.write(b" ")
        with pytest.raises(ValueError, match="64 MiB"):
            load_backup(str(path), runtime)
        assert calls == []


@pytest.mark.asyncio
async def test_corruption_scope_and_mapping_fail_without_new_records(tmp_path):
    async with desktop(tmp_path) as (_, app, client, _, _):
        runtime = app.state.desktop.runtime
        pid, wid, session = await records(client, tmp_path / "project")
        item, draft, _ = staged(tmp_path, runtime.store, pid, wid)
        path = tmp_path / "backup.json"
        package = export_backup(runtime, "application", "standard")
        save_package(path, package)
        data, digest = load_backup(str(path), runtime)
        with pytest.raises(ValueError, match="每个项目"):
            import_data(data, digest, {}, {}, runtime)
        damaged = copy.deepcopy(package)
        damaged["payload"]["draft_attachments"][0]["sha256"] = "0" * 64
        save_package(path, damaged)
        with pytest.raises(ValueError, match="摘要"):
            load_backup(str(path), runtime)
        damaged = copy.deepcopy(package)
        damaged["payload"]["drafts"][0]["workspace_id"] = 999
        save_package(path, damaged)
        with pytest.raises(ValueError, match="不匹配"):
            load_backup(str(path), runtime)
        assert len(runtime.store.list("project")) == 1


@pytest.mark.asyncio
async def test_configuration_conflicts_preserve_active_model_and_new_entries_are_disabled(tmp_path):
    async with desktop(tmp_path) as (models, app, client, _, calls):
        await configure(client)
        package = export_backup(app.state.desktop.runtime, "configuration", "standard")
        data = package["payload"]
        data["configuration"]["providers"][0]["configuration"]["base_url"] = "https://unrelated.example.test/v1"
        result = import_configuration(data, models.catalog)
        assert result["skipped"] == ["provider"]
        assert models.catalog.provider("provider")["base_url"] != "https://unrelated.example.test/v1"
        data["configuration"]["providers"][0]["id"] = "restored"
        result = import_configuration(data, models.catalog)
        assert result["imported"] == ["restored"]
        assert models.catalog.provider("restored")["enabled"] is False
        assert calls == []


@pytest.mark.asyncio
async def test_unknown_backup_version_is_rejected_before_any_import(tmp_path):
    async with desktop(tmp_path) as (models, app, client, _, calls):
        package = export_backup(app.state.desktop.runtime, "configuration", "standard")
        package["format"] = "privateagent.backup.v999"
        path = tmp_path / "unknown-version.json"
        content = encode_archive(package)
        path.write_bytes(content)
        preview = await client.post("/local-backups/preview", json={"path": str(path)})
        assert preview.status_code == 422 and "不支持的备份格式" in preview.json()["detail"]
        imported = await client.post("/local-backups/import", json={"path": str(path), "sha256": hashlib.sha256(content).hexdigest(), "part": "configuration"})
        assert imported.status_code == 422
        assert models.catalog.data["providers"] == {}
        assert app.state.desktop.runtime.store.db.execute("SELECT count(*) FROM history_imports").fetchone()[0] == 0
        assert calls == []


@pytest.mark.asyncio
async def test_preview_digest_guard_and_unknown_credentials_are_rejected(tmp_path):
    async with desktop(tmp_path) as (_, app, client, _, _):
        path = tmp_path / "backup.json"
        package = export_backup(app.state.desktop.runtime, "configuration", "standard")
        save_package(path, package)
        response = await client.post("/local-backups/preview", json={"path": str(path)})
        assert response.status_code == 200
        digest = response.json()["sha256"]
        package["payload"]["home_layout"] = "compact"
        save_package(path, package)
        result = await client.post("/local-backups/import", json={"path": str(path), "sha256": digest, "part": "configuration"})
        assert result.status_code == 422
        package["payload"]["configuration"]["api_key"] = "synthetic-input"
        save_package(path, package)
        response = await client.post("/local-backups/preview", json={"path": str(path)})
        assert response.status_code == 422 and "synthetic-input" not in response.text


@pytest.mark.asyncio
async def test_import_failure_rolls_back_records_and_attachment_files(tmp_path, monkeypatch):
    async with desktop(tmp_path) as (_, app, client, _, _):
        runtime = app.state.desktop.runtime
        pid, wid, _ = await records(client, tmp_path / "project")
        staged(tmp_path, runtime.store, pid, wid)
        path = tmp_path / "backup.json"
        package = export_backup(runtime, "application", "standard")
        save_package(path, package)
        data, digest = load_backup(str(path), runtime)
        original_files = set(runtime.store.attachments.directory.iterdir())
        def fail(*args, **kwargs):
            raise OSError("controlled disk failure")
        monkeypatch.setattr(Drafts, "put", fail)
        with pytest.raises(OSError, match="controlled"):
            import_data(data, digest, {str(pid): str(tmp_path)}, {str(wid): str(tmp_path)}, runtime)
        assert len(runtime.store.list("project")) == 1
        assert runtime.store.db.execute("SELECT count(*) FROM history_imports").fetchone()[0] == 0
        assert set(runtime.store.attachments.directory.iterdir()) == original_files


@pytest.mark.asyncio
async def test_backup_size_limit_fails_explicitly(tmp_path, monkeypatch):
    async with desktop(tmp_path) as (_, app, client, _, _):
        runtime = app.state.desktop.runtime
        pid, wid, _ = await records(client, tmp_path / "project")
        staged(tmp_path, runtime.store, pid, wid)
        monkeypatch.setattr("private_agent_local.backups.MAX_BYTES", 10)
        with pytest.raises(ValueError, match="超过 64 MiB"):
            export_backup(runtime, "application", "standard")
