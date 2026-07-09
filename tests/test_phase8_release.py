"""第八阶段 M5 测试：跨平台 updater 清单生成逻辑。

覆盖（对齐 docs/phase8-plan.md §M5 / docs/phase8-requirements.md §5.5）：
- build_platform_entry：signature + 百分号编码 URL（含非 ASCII 文件名）。
- 空 .sig 报错。
- assemble_manifest：多平台 platforms 结构（windows/darwin/linux）。
- PLATFORM_BUNDLES 覆盖三类 OS。
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import _release_utils as ru  # noqa: E402


def test_build_platform_entry_percent_encodes_filename(tmp_path):
    installer = tmp_path / "PrivateAgent_0.1.1_x64-setup.exe"
    installer.write_bytes(b"fake")
    sig = tmp_path / (installer.name + ".sig")
    sig.write_text("sig-windows", encoding="utf-8")
    entry = ru.build_platform_entry(installer, sig, "owner/repo", "v0.1.1")
    assert entry["signature"] == "sig-windows"
    assert entry["url"] == (
        "https://github.com/owner/repo/releases/download/v0.1.1/"
        "PrivateAgent_0.1.1_x64-setup.exe"
    )


def test_build_platform_entry_encodes_non_ascii(tmp_path):
    installer = tmp_path / "私人助手_0.1.1_aarch64.dmg"
    installer.write_bytes(b"fake")
    sig = tmp_path / (installer.name + ".sig")
    sig.write_text("sig-mac", encoding="utf-8")
    entry = ru.build_platform_entry(installer, sig, "owner/repo", "v0.1.1")
    assert entry["url"].endswith(quote(installer.name, safe=""))
    assert "私人助手" not in entry["url"]


def test_build_platform_entry_empty_sig_raises(tmp_path):
    installer = tmp_path / "x.AppImage"
    installer.write_bytes(b"")
    sig = tmp_path / "x.AppImage.sig"
    sig.write_text("   ", encoding="utf-8")
    with pytest.raises(SystemExit):
        ru.build_platform_entry(installer, sig, "o/r", "v1")


def test_assemble_manifest_multi_platform():
    platforms = {
        "windows-x86_64": {"signature": "sig-w", "url": "http://w"},
        "darwin-aarch64": {"signature": "sig-m", "url": "http://m"},
        "linux-x86_64": {"signature": "sig-l", "url": "http://l"},
    }
    m = ru.assemble_manifest("0.1.1", "notes", "2026-07-09T00:00:00Z", platforms)
    assert m["version"] == "0.1.1"
    assert m["pub_date"] == "2026-07-09T00:00:00Z"
    assert set(m["platforms"].keys()) == {
        "windows-x86_64",
        "darwin-aarch64",
        "linux-x86_64",
    }


def test_platform_bundles_covers_three_oses():
    keys = set(ru.PLATFORM_BUNDLES.keys())
    assert "windows-x86_64" in keys
    assert any(k.startswith("darwin") for k in keys)
    assert "linux-x86_64" in keys
