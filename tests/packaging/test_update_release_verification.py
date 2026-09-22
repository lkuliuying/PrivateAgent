"""发布契约与离线验签集成；只使用公开测试向量，不生成或读取私钥。"""
from __future__ import annotations

import base64
import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import verify_update_release as verifier
from _release_utils import (
    UNIFIED_IDENTIFIER,
    UNIFIED_TARGET,
    github_download_url,
    github_update_url,
)
from generate_release_manifest import sha256

ROOT = Path(__file__).resolve().parents[2]
REPO = "lkuliuying/PrivateAgent"
VERSION = "1.0.0"
NAME = "PrivateAgent_1.0.0_x64-setup.exe"
# 来自 minisign-verify 0.2.5 的公开文档样本，原始消息为 test，非正式安装包。
PUBLIC = base64.b64encode(
    b"untrusted comment: minisign public key\nRWQf6LRCGA9i53mlYecO4IzT51TGPpvWucNSCh1CBM0QTaLn73Y7GFO3\n"
).decode()
SIGNATURE = base64.b64encode((
    "untrusted comment: signature from minisign secret key\n"
    "RUQf6LRCGA9i559r3g7V1qNyJDApGip8MfqcadIgT9CuhV3EMhHoN1mGTkUidF/z7SrlQgXdy8ofjb7bNJJylDOocrCo8KLzZwo=\n"
    "trusted comment: timestamp:1633700835\tfile:test\tprehashed\n"
    "wLMDjy9FLAuxZ3q4NlEvkgtyhrr0gtTu6KC4KBJdITbbOeAi1zBIYo0v4iTgt8jJpIidRJnp94ABQkJAgAooBQ==\n"
).encode()).decode()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def change_json(path, callback):
    data = json.loads(path.read_text(encoding="utf-8"))
    callback(data)
    write_json(path, data)


def refresh_sums(bundle):
    names = ["PrivateAgent-windows-x64.exe", "private-agent-local.exe", "exec-host.exe",
             f"publish/{VERSION}/{NAME}", f"publish/{VERSION}/{NAME}.sig", "publish/latest.json"]
    (bundle / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(bundle / name)}  {name}\n" for name in names), encoding="utf-8")


@pytest.fixture
def release_bundle(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    assets = bundle / "publish" / VERSION
    assets.mkdir(parents=True)
    installer = assets / NAME
    installer.write_bytes(b"test")
    installer.with_name(NAME + ".sig").write_text(SIGNATURE + "\n", encoding="utf-8")
    for name in ("PrivateAgent-windows-x64.exe", "private-agent-local.exe", "exec-host.exe"):
        (bundle / name).write_bytes(name.encode())
    host_hash = sha256(bundle / "exec-host.exe")
    (bundle / "exec-host.sha256").write_text(host_hash, encoding="utf-8")
    (bundle / "updater-public-key.txt").write_text(PUBLIC + "\n", encoding="utf-8")
    source_path = bundle / "source-manifest.json"
    write_json(source_path, [{"path": "src/local.py", "sha256": "a" * 64}])
    source_hash = sha256(source_path)
    sources = json.loads(source_path.read_text())
    write_json(source_path, {"sources": sources, "sourceSha256": source_hash})
    write_json(bundle / "build-info.json", {
        "version": VERSION, "mode": "release", "unified": True, "qa": False, "dirty": False,
        "applicationIdentifier": UNIFIED_IDENTIFIER, "target": "x86_64-pc-windows-msvc",
        "updateTarget": UNIFIED_TARGET, "signing": "updater-verified", "accessMode": "api-key",
        "sidecar": "desktop-local", "transport": "stdio-v2", "githubRepo": REPO,
        "releaseTag": "v1.0.0", "updateUrl": github_update_url(REPO),
        "downloadBaseUrl": f"https://github.com/{REPO}/releases/download/v1.0.0",
        "commit": "a" * 40, "sourceSha256": source_hash, "executionHostSha256": host_hash,
        "sha256": sha256(bundle / "PrivateAgent-windows-x64.exe"),
    })
    config = {
        "identifier": UNIFIED_IDENTIFIER, "version": VERSION, "productName": "PrivateAgent",
        "mainBinaryName": "privateagent", "bundle": {"targets": ["nsis"], "createUpdaterArtifacts": True},
        "plugins": {"updater": {"endpoints": [github_update_url(REPO)], "pubkey": PUBLIC}},
    }
    write_json(bundle / "tauri-build.json", config)
    trusted_config = tmp_path / "trusted-test-config.json"
    write_json(trusted_config, config)
    monkeypatch.setattr(verifier, "TAURI_CONF", trusted_config)
    manifest = bundle / "publish/latest.json"
    write_json(manifest, {"version": VERSION, "notes": "公开向量夹具", "pub_date": "2026-09-22T08:00:00Z",
                          "platforms": {UNIFIED_TARGET: {"url": github_download_url(REPO, "v1.0.0", NAME), "signature": SIGNATURE}}})
    refresh_sums(bundle)
    return bundle, installer, manifest


@pytest.fixture
def accepted_crypto(monkeypatch):
    calls = []
    monkeypatch.setattr(verifier, "verify_signature", lambda *args: calls.append(args))
    return calls


def test_contract_cli_is_read_only_and_reports_separate_signature_status(release_bundle, accepted_crypto, capsys):
    bundle, installer, manifest = release_bundle
    before = {p: sha256(p) for p in bundle.rglob("*") if p.is_file()}
    assert verifier.main(["--bundle", str(bundle), "--installer", str(installer), "--manifest", str(manifest), "--repo", REPO]) == 0
    evidence = json.loads(capsys.readouterr().out)
    assert evidence["updaterSignatureVerified"] is True
    assert evidence["authenticode"] == "not_verified"
    assert {item["name"] for item in evidence["artifacts"]} == {NAME, NAME + ".sig", "latest.json"}
    assert all(item["bytes"] > 0 and len(item["sha256"]) == 64 for item in evidence["artifacts"])
    assert len(accepted_crypto) == 1
    assert before == {p: sha256(p) for p in bundle.rglob("*") if p.is_file()}


@pytest.mark.parametrize(("key", "value"), [
    ("dirty", True), ("dirty", "false"), ("qa", True), ("unified", False), ("mode", "preview"),
    ("applicationIdentifier", "com.personal-assistant.desktop.remote"), ("updateTarget", "windows-x86_64"),
    ("releaseTag", "v1.0.1"), ("githubRepo", "other/repo"), ("signing", "unsigned"),
    ("version", "1.0.0-rc.1"), ("commit", "invalid"),
])
def test_invalid_build_identity_rejected_before_crypto(release_bundle, accepted_crypto, key, value):
    bundle, installer, manifest = release_bundle
    change_json(bundle / "build-info.json", lambda data: data.update({key: value}))
    with pytest.raises(ValueError):
        verifier.verify_release(bundle, installer, manifest, REPO)
    assert accepted_crypto == []


@pytest.mark.parametrize("mutation", [
    lambda data: data.update(version="1.0.1"),
    lambda data: data.update(pub_date="2026-02-30T00:00:00Z"),
    lambda data: data.update(pub_date="2026-09-22"),
    lambda data: data.update(platforms={"remote-windows-x86_64": data["platforms"][UNIFIED_TARGET]}),
    lambda data: data.update(url="https://example.test/setup.exe"),
    lambda data: data["platforms"][UNIFIED_TARGET].update(signature="mismatched"),
    lambda data: data["platforms"][UNIFIED_TARGET].update(url=f"https://github.com/{REPO}/releases/download/v1.0.0/1.0.0/{NAME}"),
])
def test_invalid_manifest_rejected_before_crypto(release_bundle, accepted_crypto, mutation):
    bundle, installer, manifest = release_bundle
    change_json(manifest, mutation)
    with pytest.raises(ValueError):
        verifier.verify_release(bundle, installer, manifest, REPO)
    assert accepted_crypto == []


@pytest.mark.parametrize("name", ["PrivateAgentRemote_1.0.0_x64-setup.exe", "PrivateAgentCandidate_1.0.0_x64-setup.exe", "PrivateAgent_1.0.1_x64-setup.exe"])
def test_wrong_installer_rejected(release_bundle, accepted_crypto, name):
    bundle, installer, manifest = release_bundle
    wrong = installer.with_name(name)
    wrong.write_bytes(installer.read_bytes())
    with pytest.raises(ValueError, match="安装包"):
        verifier.verify_release(bundle, wrong, manifest, REPO)


@pytest.mark.parametrize("name", ["updater-public-key.txt", "source-manifest.json", "SHA256SUMS.txt", "private-agent-local.exe"])
def test_missing_artifact_rejected(release_bundle, accepted_crypto, name):
    bundle, installer, manifest = release_bundle
    (bundle / name).unlink()
    with pytest.raises(ValueError, match="缺失"):
        verifier.verify_release(bundle, installer, manifest, REPO)


@pytest.mark.parametrize("name", ["private-agent-local.exe", "exec-host.exe", f"publish/{VERSION}/{NAME}"])
def test_changed_artifact_hash_rejected(release_bundle, accepted_crypto, name):
    bundle, installer, manifest = release_bundle
    (bundle / name).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="摘要|完整性"):
        verifier.verify_release(bundle, installer, manifest, REPO)


def test_public_key_cannot_be_replaced_by_bundle(release_bundle, accepted_crypto):
    bundle, installer, manifest = release_bundle
    (bundle / "updater-public-key.txt").write_text("another public key", encoding="utf-8")
    with pytest.raises(ValueError, match="公钥"):
        verifier.verify_release(bundle, installer, manifest, REPO)


def test_empty_signature_rejected(release_bundle, accepted_crypto):
    bundle, installer, manifest = release_bundle
    installer.with_name(NAME + ".sig").write_text(" \n", encoding="utf-8")
    with pytest.raises(ValueError, match="签名不能为空"):
        verifier.verify_release(bundle, installer, manifest, REPO)


def test_duplicate_json_fields_rejected(release_bundle, accepted_crypto):
    bundle, installer, manifest = release_bundle
    manifest.write_text('{"version":"1.0.0","version":"1.0.1"}', encoding="utf-8")
    with pytest.raises(ValueError, match="重复字段"):
        verifier.verify_release(bundle, installer, manifest, REPO)


@pytest.mark.parametrize("value", ["2026-09-22T08:00:00+01:99", "2026-09-22T08:00:00+24:00"])
def test_invalid_timezone_offset_rejected(value):
    with pytest.raises(ValueError, match="RFC 3339"):
        verifier.check_timestamp(value)


def test_valid_timezone_offset():
    verifier.check_timestamp("2026-09-22T08:00:00+08:00")


def test_crypto_failure_is_not_reported_as_passed(release_bundle, monkeypatch, capsys):
    def failed(*args):
        raise ValueError("离线验签失败")
    monkeypatch.setattr(verifier, "verify_signature", failed)
    bundle, installer, manifest = release_bundle
    with pytest.raises(SystemExit) as error:
        verifier.main(["--bundle", str(bundle), "--installer", str(installer), "--manifest", str(manifest), "--repo", REPO])
    assert error.value.code != 0
    assert capsys.readouterr().out == ""


def test_changes_during_verification_rejected(release_bundle, monkeypatch):
    bundle, installer, manifest = release_bundle
    monkeypatch.setattr(verifier, "verify_signature", lambda *args: installer.write_bytes(b"changed during check"))
    with pytest.raises(ValueError, match="验签期间"):
        verifier.verify_release(bundle, installer, manifest, REPO)


def test_verifier_process_receives_no_signing_environment(release_bundle, monkeypatch):
    bundle, installer, _ = release_bundle
    captured = {}
    monkeypatch.setenv("TAURI_SIGNING_PRIVATE_KEY", "synthetic-never-forward")
    monkeypatch.setenv("GH_TOKEN", "synthetic-never-forward")

    @contextmanager
    def process(command, **options):
        captured.update(command=command, options=options)
        yield SimpleNamespace(returncode=0, communicate=lambda **kwargs: ("", ""))

    monkeypatch.setattr(verifier, "managed_process", process)
    verifier.verify_signature(installer, installer.with_name(NAME + ".sig"), bundle / "updater-public-key.txt", None)
    assert captured["command"][:5] == ["cargo", "run", "--offline", "--locked", "--release"]
    assert "TAURI_SIGNING_PRIVATE_KEY" not in captured["options"]["env"]
    assert "GH_TOKEN" not in captured["options"]["env"]
    assert captured["options"]["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired("verifier", 180), OSError("synthetic failure")])
def test_verifier_timeout_or_launch_failure_has_no_success_output(release_bundle, monkeypatch, capsys, failure):
    bundle, installer, manifest = release_bundle
    cleaned = []

    @contextmanager
    def process(*args, **kwargs):
        try:
            raise failure
            yield
        finally:
            cleaned.append(True)

    monkeypatch.setattr(verifier, "managed_process", process)
    with pytest.raises(SystemExit) as error:
        verifier.main(["--bundle", str(bundle), "--installer", str(installer), "--manifest", str(manifest), "--repo", REPO])
    assert error.value.code != 0
    assert cleaned == [True]
    assert capsys.readouterr().out == ""


def test_real_public_vector_passes_then_tamper_fails_even_with_updated_hashes(release_bundle):
    bundle, installer, manifest = release_bundle
    suffix = ".exe" if os.name == "nt" else ""
    binary = ROOT / f"scripts/windows/updater-signature-verifier/target/release/private-agent-updater-signature-verifier{suffix}"
    assert binary.is_file(), "先运行 cargo build --offline --locked --release --manifest-path scripts/windows/updater-signature-verifier/Cargo.toml"
    result = verifier.verify_release(bundle, installer, manifest, REPO, binary)
    assert result["updaterSignatureVerified"] is True
    installer.write_bytes(b"tampered")
    refresh_sums(bundle)
    with pytest.raises(ValueError, match="离线验签失败"):
        verifier.verify_release(bundle, installer, manifest, REPO, binary)
