"""第七阶段 M5 测试：诊断中心 + 脱敏诊断包。

覆盖（对齐 docs/phase7-plan.md §M5 / docs/phase7-requirements.md §5.5/§9）：
- snapshot 聚合健康/版本/迁移/失败活动/Provider 失败/提醒/导入/备份/体检/错误。
- 脱敏：API key / Provider key / DB 密码不泄露原文。
- export 生成 zip，含 diagnostics.json/health.json/settings.redacted.json/
  recent-errors.log/version.txt/migration.txt。
- 诊断包内 settings.redacted.json 不含原始 key。
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from personal_assistant import __version__
from personal_assistant.core.diagnostics import (
    DiagnosticsService,
    _mask,
    redact_db_url,
    redact_settings,
)
from personal_assistant.core.settings import SettingsService


async def _set_legacy_provider_secret(db, value: str):
    """Seed a pre-migration row without using the now reference-only service API."""
    from personal_assistant.core.models import Setting

    row = await db.get(Setting, "openai_api_key")
    if row is None:
        row = Setting(key="openai_api_key", value=value)
        db.add(row)
    else:
        row.value = value
    await db.commit()
    return row


@pytest.fixture
async def cleanup(db):
    created: list = []
    yield created
    for obj in reversed(created):
        try:
            await db.delete(obj)
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()


def test_mask_secret():
    assert _mask("") == "<empty>"
    assert _mask("sk-abcd") == "sk-a***"
    assert _mask("ab") == "***"


def test_redact_db_url():
    url = "mysql+aiomysql://user:secret_pass@localhost:3306/db"
    red = redact_db_url(url)
    assert "secret_pass" not in red
    assert "***" in red
    assert "user" in red and "localhost" in red


def test_redact_settings_keys():
    s = {"openai_api_key": "sk-secret123", "claude_api_key": "sk-ant-xyz", "llm_model": "qwen"}
    r = redact_settings(s)
    assert r["openai_api_key"] != "sk-secret123"
    assert "sk-secret123" not in r["openai_api_key"]
    assert r["llm_model"] == "qwen"  # 非密钥不改


@pytest.mark.asyncio
async def test_diagnostics_snapshot(db, cleanup):
    snap = await DiagnosticsService(db).snapshot()
    for key in (
        "generated_at",
        "version",
        "migration_head",
        "health",
        "backup",
        "failed_activities",
        "provider_failures",
        "reminder_tick",
        "import_queue",
        "integrity_summary",
        "recent_errors",
        "settings_redacted",
        "db_url_redacted",
        "compatibility_telemetry",
    ):
        assert key in snap, f"缺少诊断字段 {key}"
    assert snap["version"] == __version__


@pytest.mark.asyncio
async def test_diagnostics_snapshot_redacts_keys(db, cleanup):
    """snapshot 的 settings_redacted 不含原始 API key。"""
    cleanup.append(await _set_legacy_provider_secret(db, "sk-supersecret-value-123"))

    snap = await DiagnosticsService(db).snapshot()
    red = snap["settings_redacted"]
    assert red["openai_api_key"] != "sk-supersecret-value-123"
    assert "supersecret" not in red["openai_api_key"]
    assert "***" in red["openai_api_key"]


@pytest.mark.asyncio
async def test_diagnostics_export_zip(client, db, tmp_path):
    """export 生成 zip，含 6 个文件，settings.redacted.json 不含原始 key。"""
    svc = SettingsService(db)
    await _set_legacy_provider_secret(db, "sk-export-secret-999")

    r = await client.post("/diagnostics/export", json={"output_dir": str(tmp_path)})
    assert r.status_code == 200
    data = r.json()
    zip_path = Path(data["path"])
    assert zip_path.exists()
    assert zip_path.suffix == ".zip"

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert {
            "diagnostics.json",
            "health.json",
            "settings.redacted.json",
            "recent-errors.log",
            "version.txt",
            "migration.txt",
        } <= names
        # version.txt 含版本号
        assert __version__ in zf.read("version.txt").decode()
        # settings.redacted.json 不含原始 key
        red = json.loads(zf.read("settings.redacted.json"))
        assert red["openai_api_key"] != "sk-export-secret-999"
        assert "export-secret" not in red["openai_api_key"]
        # diagnostics.json 不含原始 key
        diag = json.loads(zf.read("diagnostics.json"))
        assert "sk-export-secret-999" not in json.dumps(diag, ensure_ascii=False)

    # 清理 zip
    zip_path.unlink(missing_ok=True)
    await svc.update({"openai_api_key": ""})
