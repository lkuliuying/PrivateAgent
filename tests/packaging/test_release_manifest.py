"""桌面 updater 清单生成逻辑回归测试。

覆盖（对齐 docs/archive/phases/phase8-plan.md §M5 / docs/archive/phases/phase8-requirements.md §5.5）：
- build_platform_entry：signature + 百分号编码 URL（含非 ASCII 文件名）。
- 空 .sig 报错。
- assemble_manifest：多平台 platforms 结构（windows/darwin/linux）。
- PLATFORM_BUNDLES 覆盖三类 OS。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
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


@pytest.fixture
def generator(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts/generate-latest-json.py"
    spec = importlib.util.spec_from_file_location("generate_latest_json", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "read_version", lambda: "1.0.0")
    return module


@pytest.mark.parametrize("repo", ["owner/repo", "o/r", "a-b/Repo_name.1"])
def test_github_repo_valid_identifiers(repo):
    assert ru.validate_github_repo(repo) == repo


@pytest.mark.parametrize("repo", ["", "owner", "owner/repo/path", "a--b/repo", "-owner/repo", "owner/..",
                                  "owner/repo\n", "https://secret-value@github.com/owner/repo", "owner/repo?secret-value"])
def test_invalid_repo_rejected_without_echo(repo):
    with pytest.raises(ValueError) as error:
        ru.validate_github_repo(repo)
    assert "secret-value" not in str(error.value)


@pytest.mark.parametrize("version", ["01.0.0", "1.0.0\n", "1.0.0-beta", "v1.0.0", "1.0", None])
def test_invalid_stable_version_rejected(version):
    with pytest.raises(ValueError):
        ru.validate_stable_version(version)


def test_python_and_node_github_manifests_agree(generator, tmp_path):
    installer = tmp_path / "PrivateAgent_1.0.0_x64-setup.exe"
    installer.write_bytes(b"synthetic-installer")
    installer.with_name(installer.name + ".sig").write_text("synthetic-signature\n", encoding="utf-8")
    output = tmp_path / "latest.json"
    assert generator.main(["--repo", "lkuliuying/PrivateAgent", "--tag", "v1.0.0", "--installer", str(installer), "--out", str(output)]) == 0
    manifest = json.loads(output.read_text(encoding="utf-8"))
    builder = Path(__file__).resolve().parents[2] / "scripts/build-remote-client.cjs"
    code = ('const b=require(process.argv[1]);'
            'const o=b.parseOptions(["--unified","--release","--version","1.0.0","--github-repo","lkuliuying/PrivateAgent"]);'
            'console.log(JSON.stringify(b.updateManifest(o,"PrivateAgent_1.0.0_x64-setup.exe","synthetic-signature")));')
    result = subprocess.run(["node", "-e", code, str(builder)], capture_output=True, text=True, check=True, timeout=30)
    node_manifest = json.loads(result.stdout)
    assert manifest["version"] == node_manifest["version"] == "1.0.0"
    assert manifest["platforms"] == node_manifest["platforms"]
    assert manifest["notes"] == node_manifest["notes"]


@pytest.mark.parametrize("name", ["PrivateAgentRemote_1.0.0_x64-setup.exe", "PrivateAgentCandidate_1.0.0_x64-setup.exe", "PrivateAgent_1.0.1_x64-setup.exe"])
def test_generator_rejects_other_installers(generator, tmp_path, name):
    installer = tmp_path / name
    installer.write_bytes(b"synthetic")
    installer.with_name(name + ".sig").write_text("synthetic-signature", encoding="utf-8")
    output = tmp_path / "latest.json"
    with pytest.raises(SystemExit):
        generator.main(["--repo", "owner/repo", "--installer", str(installer), "--out", str(output)])
    assert not output.exists()


@pytest.mark.parametrize("tag", ["1.0.0", "v1.0.1", "v1.0.0-test", "remote-v1.0.0"])
def test_generator_rejects_tag_version_mismatch(generator, tmp_path, tag):
    output = tmp_path / "latest.json"
    with pytest.raises(SystemExit):
        generator.main(["--repo", "owner/repo", "--tag", tag, "--out", str(output)])
    assert not output.exists()


def test_extra_platform_cannot_replace_unified_target(generator, tmp_path):
    installer = tmp_path / "PrivateAgent_1.0.0_x64-setup.exe"
    installer.write_bytes(b"synthetic")
    installer.with_name(installer.name + ".sig").write_text("synthetic-signature", encoding="utf-8")
    output = tmp_path / "latest.json"
    with pytest.raises(SystemExit, match="覆盖 unified"):
        generator.main(["--repo", "owner/repo", "--installer", str(installer), "--out", str(output),
                        "--extra-platform", f"unified-windows-x86_64:{installer}"])
    assert not output.exists()
