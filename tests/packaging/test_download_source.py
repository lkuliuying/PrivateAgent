"""静态下载站物料、真实公开验签向量与原子发布回归。"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
from pathlib import Path

import prepare_download_source as preparation
import pytest
from _release_utils import UNIFIED_IDENTIFIER, UNIFIED_TARGET, github_download_url
from generate_release_manifest import sha256

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("download_publisher", ROOT / "scripts/linux/publish_download_source.py")
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)
DOMAIN = "download.privateagent.dev"
VERSION = "1.0.1"
NAME = f"PrivateAgent_{VERSION}_x64-setup.exe"
# 来自 minisign-verify 的公开测试向量，只签署 b"test"，不代表正式安装包。
PUBLIC = base64.b64encode(
    b"untrusted comment: minisign public key\nRWQf6LRCGA9i53mlYecO4IzT51TGPpvWucNSCh1CBM0QTaLn73Y7GFO3\n"
).decode()
SIGNATURE = base64.b64encode((
    "untrusted comment: signature from minisign secret key\n"
    "RUQf6LRCGA9i559r3g7V1qNyJDApGip8MfqcadIgT9CuhV3EMhHoN1mGTkUidF/z7SrlQgXdy8ofjb7bNJJylDOocrCo8KLzZwo=\n"
    "trusted comment: timestamp:1633700835\tfile:test\tprehashed\n"
    "wLMDjy9FLAuxZ3q4NlEvkgtyhrr0gtTu6KC4KBJdITbbOeAi1zBIYo0v4iTgt8jJpIidRJnp94ABQkJAgAooBQ==\n"
).encode()).decode()
SUFFIX = ".exe" if os.name == "nt" else ""
VERIFIER = ROOT / f"scripts/windows/updater-signature-verifier/target/release/private-agent-updater-signature-verifier{SUFFIX}"


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def refresh_record(source):
    write_json(source / f"release-verification-{VERSION}.json", {
        "version": VERSION, "repo": preparation.REPO, "tag": f"v{VERSION}", "target": UNIFIED_TARGET,
        "updaterSignatureVerified": True,
        "artifacts": [{"name": name, "bytes": (source / name).stat().st_size, "sha256": sha256(source / name)}
                      for name in (NAME, NAME + ".sig", "latest.json")],
    })


@pytest.fixture
def source(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / NAME).write_bytes(b"test")
    (source / (NAME + ".sig")).write_text(SIGNATURE + "\n", encoding="utf-8")
    write_json(source / "latest.json", {
        "version": VERSION, "notes": "公开测试向量", "pub_date": "2026-10-06T03:00:00Z",
        "platforms": {UNIFIED_TARGET: {
            "url": github_download_url(preparation.REPO, f"v{VERSION}", NAME), "signature": SIGNATURE,
        }},
    })
    refresh_record(source)
    config = tmp_path / "trusted-test-config.json"
    write_json(config, {"identifier": UNIFIED_IDENTIFIER, "plugins": {"updater": {"pubkey": PUBLIC}}})
    monkeypatch.setattr(preparation, "TAURI_CONF", config)
    assert VERIFIER.is_file(), "先按操作文档编译已有的公钥验签器"
    return source


@pytest.fixture
def package(source, tmp_path):
    result = tmp_path / "upload"
    preparation.prepare(source, DOMAIN, result, VERIFIER)
    return result


def test_preparation_keeps_original_bytes_and_only_changes_installer_url(source, tmp_path):
    before = {path.name: sha256(path) for path in source.iterdir()}
    output = tmp_path / "upload"
    evidence = preparation.prepare(source, DOMAIN, output, VERIFIER)
    assert {path.name: sha256(path) for path in source.iterdir()} == before
    assert (output / f"site/{VERSION}/{NAME}").read_bytes() == b"test"
    assert (output / f"site/{VERSION}/{NAME}.sig").read_bytes() == (source / (NAME + ".sig")).read_bytes()
    mirror = json.loads((output / "site/latest.json").read_text(encoding="utf-8"))
    mirror["platforms"][UNIFIED_TARGET]["url"] = github_download_url(preparation.REPO, f"v{VERSION}", NAME)
    assert mirror == json.loads((source / "latest.json").read_text(encoding="utf-8"))
    assert evidence["updaterSignatureVerified"] is True
    publisher.validate_package(output)


@pytest.mark.parametrize("domain", [
    "", "download.example.com", "download.example.test", "download.local", "https://download.privateagent.dev",
    "UPPER.privateagent.dev", "download.privateagent.dev:443", "user@download.privateagent.dev",
    "download.privateagent.dev/path", "download.privateagent.dev;return 200", "127.0.0.1",
    "bad..privateagent.dev", "-bad.privateagent.dev", "download.privateagent.dev\n", "x" * 64 + ".dev",
])
def test_invalid_domain_cannot_generate_nginx_input(source, tmp_path, domain):
    output = tmp_path / "upload"
    with pytest.raises(ValueError):
        preparation.prepare(source, domain, output, VERIFIER)
    assert not output.exists()


def test_real_signature_rejects_tampered_installer_even_when_hash_record_is_updated(source, tmp_path):
    (source / NAME).write_bytes(b"tampered")
    refresh_record(source)
    output = tmp_path / "upload"
    with pytest.raises(ValueError, match="离线验签失败"):
        preparation.prepare(source, DOMAIN, output, VERIFIER)
    assert not output.exists()
    assert not output.with_name(output.name + ".prepare-lock").exists()


def test_preparation_rejects_changed_release_hash_before_creating_output(source, tmp_path):
    (source / NAME).write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="SHA-256"):
        preparation.prepare(source, DOMAIN, tmp_path / "upload", VERIFIER)


def test_preparation_preserves_existing_output(source, tmp_path):
    output = tmp_path / "upload"
    output.mkdir()
    (output / "existing.txt").write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="不能覆盖"):
        preparation.prepare(source, DOMAIN, output, VERIFIER)
    assert (output / "existing.txt").read_text() == "preserve"


def test_preparation_cannot_write_into_source(source):
    with pytest.raises(ValueError, match="来源目录"):
        preparation.prepare(source, DOMAIN, source / "upload", VERIFIER)
    assert not (source / "upload").exists()


def test_publish_is_repeatable_and_keeps_older_version(package, tmp_path):
    destination = tmp_path / "site"
    old = destination / "1.0.0"
    old.mkdir(parents=True)
    (old / "old.exe").write_bytes(b"preserve")
    write_json(destination / "latest.json", {"version": "1.0.0"})
    publisher.publish(package, destination)
    before = {str(path.relative_to(destination)): sha256(path) for path in destination.rglob("*") if path.is_file()}
    publisher.publish(package, destination)
    assert before == {str(path.relative_to(destination)): sha256(path) for path in destination.rglob("*") if path.is_file()}
    assert (old / "old.exe").read_bytes() == b"preserve"
    assert (destination / "latest.json").read_bytes() == (package / "site/latest.json").read_bytes()


def test_publish_rejects_uploaded_corruption_before_modifying_site(package, tmp_path):
    (package / f"site/{VERSION}/{NAME}").write_bytes(b"damaged")
    destination = tmp_path / "site"
    with pytest.raises(ValueError, match="SHA-256"):
        publisher.publish(package, destination)
    assert not destination.exists()


def test_publish_cannot_include_extra_unverified_files(package, tmp_path):
    (package / f"site/{VERSION}/extra.txt").write_text("not published", encoding="utf-8")
    with pytest.raises(ValueError, match="额外文件"):
        publisher.publish(package, tmp_path / "site")
    assert not (tmp_path / "site").exists()


def test_publish_rejects_checksum_path_traversal(package, tmp_path):
    (package / "SHA256SUMS").write_text("a" * 64 + "  ../outside.txt\n", encoding="utf-8")
    with pytest.raises(ValueError, match="未知路径"):
        publisher.publish(package, tmp_path / "site")


def test_publish_never_overwrites_different_installer_of_same_version(package, tmp_path):
    destination = tmp_path / "site"
    publisher.publish(package, destination)
    installed = destination / VERSION / NAME
    installed.write_bytes(b"different existing bytes")
    current = (destination / "latest.json").read_bytes()
    with pytest.raises(ValueError, match="同版本安装包"):
        publisher.publish(package, destination)
    assert installed.read_bytes() == b"different existing bytes"
    assert (destination / "latest.json").read_bytes() == current


def test_publish_refuses_version_downgrade(package, tmp_path):
    destination = tmp_path / "site"
    destination.mkdir()
    write_json(destination / "latest.json", {"version": "1.0.2"})
    before = (destination / "latest.json").read_bytes()
    with pytest.raises(ValueError, match="降级"):
        publisher.publish(package, destination)
    assert (destination / "latest.json").read_bytes() == before
    assert not (destination / VERSION).exists()


def test_failed_manifest_switch_keeps_old_manifest_and_can_be_retried(package, tmp_path, monkeypatch):
    destination = tmp_path / "site"
    destination.mkdir()
    write_json(destination / "latest.json", {"version": "1.0.0"})
    before = (destination / "latest.json").read_bytes()

    def fail_replace(*args):
        raise OSError("模拟清单替换失败")

    with monkeypatch.context() as patch:
        patch.setattr(publisher.os, "replace", fail_replace)
        with pytest.raises(OSError, match="模拟清单替换失败"):
            publisher.publish(package, destination)
    assert (destination / "latest.json").read_bytes() == before
    assert (destination / VERSION / NAME).read_bytes() == b"test"
    assert not destination.with_name(destination.name + ".publish-lock").exists()
    publisher.publish(package, destination)
    assert (destination / "latest.json").read_bytes() == (package / "site/latest.json").read_bytes()


def test_existing_publish_lock_is_preserved(package, tmp_path):
    destination = tmp_path / "site"
    lock = destination.with_name(destination.name + ".publish-lock")
    lock.mkdir()
    with pytest.raises(ValueError, match="发布锁"):
        publisher.publish(package, destination)
    assert lock.is_dir()
    assert not destination.exists()
