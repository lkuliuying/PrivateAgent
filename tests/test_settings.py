"""Settings service and public secret-reference boundary tests."""
from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pytest

from personal_assistant.core.models import Setting
from personal_assistant.core.backup import BackupService
from personal_assistant.core.settings import PROVIDER_SECRET_REFS, SettingsService


@pytest.mark.asyncio
async def test_settings_has_defaults(db):
    values = await SettingsService(db).get_all()
    assert "llm_model" in values
    assert "llm_temperature" in values
    assert "kb_enabled_by_default" in values


@pytest.mark.asyncio
async def test_settings_update_and_persist(db):
    service = SettingsService(db)
    original = (await service.get_all())["llm_temperature"]
    try:
        await service.update({"llm_temperature": "0.42"})
        assert (await service.get_all())["llm_temperature"] == "0.42"
        await service.update({"unknown_key": "x"})
        assert "unknown_key" not in await service.get_all()
    finally:
        await service.update({"llm_temperature": original})


@pytest.mark.asyncio
async def test_public_settings_never_include_provider_secret_fields(client, db):
    row = await db.get(Setting, "openai_api_key")
    original = row.value if row else None
    if row is None:
        row = Setting(key="openai_api_key", value="sk-legacy-secret")
        db.add(row)
    else:
        row.value = "sk-legacy-secret"
    await db.commit()
    try:
        response = await client.get("/settings")
        assert response.status_code == 200
        body = response.json()
        assert body["openai_api_key_configured"] is True
        assert "openai_api_key" not in body
        assert "sk-legacy-secret" not in response.text
    finally:
        row = await db.get(Setting, "openai_api_key")
        if row is not None:
            row.value = original or ""
            await db.commit()


@pytest.mark.asyncio
async def test_http_settings_and_provider_routes_reject_plaintext_secrets(client):
    settings_response = await client.put(
        "/settings", json={"openai_api_key": "sk-must-not-enter-http"}
    )
    assert settings_response.status_code == 422
    provider_response = await client.patch(
        "/providers", json={"claude_api_key": "sk-must-not-enter-http"}
    )
    assert provider_response.status_code == 422


@pytest.mark.asyncio
async def test_secret_reference_resolves_only_from_process_environment(
    db, monkeypatch
):
    service = SettingsService(db)
    monkeypatch.setenv("PA_OPENAI_API_KEY", "sk-process-only")
    try:
        status = await service.set_provider_secret_reference("openai", configured=True)
        assert status == {
            "configured": True,
            "available": True,
            "storage": "os_keyring",
        }
        assert (await service.get_all())["openai_api_key"] == "sk-process-only"
        stored = await db.get(Setting, "openai_api_key")
        assert stored is not None
        assert stored.value == PROVIDER_SECRET_REFS["openai_api_key"]
    finally:
        await service.set_provider_secret_reference("openai", configured=False)


@pytest.mark.asyncio
async def test_secret_reference_endpoint_never_accepts_arbitrary_reference(client):
    response = await client.put(
        "/providers/openai/secret-reference",
        json={"configured": True, "reference": "secret://attacker/value"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_backup_redacts_legacy_provider_secret_and_excludes_os_credentials(
    db,
):
    row = await db.get(Setting, "openai_api_key")
    if row is None:
        row = Setting(key="openai_api_key", value="sk-legacy-backup-secret")
        db.add(row)
    else:
        row.value = "sk-legacy-backup-secret"
    await db.commit()

    path: Path | None = None
    try:
        result = await BackupService(db).export()
        path = Path(result["path"])
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            tables_text = archive.read("tables.json").decode("utf-8")
            tables = json.loads(tables_text)
        assert manifest["includes"]["os_credentials"] is False
        assert "sk-legacy-backup-secret" not in tables_text
        secret_rows = [
            item
            for item in tables["settings"]
            if item.get("key") == "openai_api_key"
        ]
        assert secret_rows and secret_rows[0]["value"] == ""
    finally:
        row = await db.get(Setting, "openai_api_key")
        if row is not None:
            row.value = ""
            await db.commit()
        if path is not None:
            path.unlink(missing_ok=True)
