"""Fail-closed Windows Authenticode release orchestration tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import sign_installer as si  # noqa: E402


def test_resolve_signing_config_no_cert_is_development_only():
    config = si.resolve_signing_config({})
    assert config.has_certificate is False
    assert config.require_signing is False
    assert config.timestamp_url == si.DEFAULT_TIMESTAMP


def test_resolve_signing_config_can_require_production_signing():
    config = si.resolve_signing_config({"PA_REQUIRE_CODESIGN": "true"})
    assert config.require_signing is True
    assert config.has_certificate is False


def test_resolve_signing_config_with_ephemeral_pfx(tmp_path):
    pfx = tmp_path / "cert.pfx"
    pfx.write_bytes(b"fake")
    config = si.resolve_signing_config(
        {"PA_CODESIGN_PFX": str(pfx), "PA_CODESIGN_PASSWORD": "secret"}
    )
    assert config.pfx_path == pfx.resolve()
    assert config.password == "secret"
    assert "secret" not in repr(config)


def test_password_file_is_rejected_even_when_it_exists(tmp_path):
    password_file = tmp_path / "password.txt"
    password_file.write_text("must-not-be-read", encoding="utf-8")
    with pytest.raises(si.SigningError, match="must not be written to disk"):
        si.resolve_signing_config({"PA_CODESIGN_PASSWORD_FILE": str(password_file)})


def test_missing_pfx_is_configuration_error(tmp_path):
    with pytest.raises(si.SigningError, match="does not point to a readable file"):
        si.resolve_signing_config(
            {
                "PA_CODESIGN_PFX": str(tmp_path / "missing.pfx"),
                "PA_CODESIGN_PASSWORD": "secret",
            }
        )


def test_thumbprint_is_normalized_and_strict():
    raw = "ab cd " + "ef" * 18
    config = si.resolve_signing_config({"PA_CODESIGN_THUMBPRINT": raw})
    assert config.thumbprint == ("ABCDEF" + "EF" * 17)
    with pytest.raises(si.SigningError, match="40 hexadecimal"):
        si.resolve_signing_config({"PA_CODESIGN_THUMBPRINT": "deadbeef"})


def test_sign_command_uses_store_thumbprint_and_never_password_or_pfx(tmp_path):
    pfx = tmp_path / "cert.pfx"
    pfx.write_bytes(b"fake")
    config = si.resolve_signing_config(
        {"PA_CODESIGN_PFX": str(pfx), "PA_CODESIGN_PASSWORD": "top-secret"}
    )
    thumbprint = "A" * 40
    command = si.build_signtool_sign_command(
        "installer.exe", config, signtool="signtool.exe", thumbprint=thumbprint
    )
    assert command[:2] == ["signtool.exe", "sign"]
    assert "/sha1" in command and thumbprint in command
    assert "/fd" in command and "/td" in command
    assert "/tr" in command
    assert "/p" not in command and "/f" not in command
    assert "top-secret" not in command and str(pfx) not in command


def test_verify_command_checks_all_signatures_against_windows_policy():
    command = si.build_signtool_verify_command("installer.exe")
    assert command == ["signtool", "verify", "/pa", "/all", "/v", "installer.exe"]


def test_timestamp_url_rejects_credentials():
    with pytest.raises(si.SigningError, match="must not contain credentials"):
        si.resolve_signing_config(
            {
                "PA_CODESIGN_THUMBPRINT": "A" * 40,
                "PA_CODESIGN_TIMESTAMP": "https://user:pass@example.test",
            }
        )


def test_sanitized_child_environment_removes_authenticode_secrets(monkeypatch):
    monkeypatch.setenv("PA_CODESIGN_PASSWORD", "secret")
    monkeypatch.setenv("PA_CODESIGN_PASSWORD_FILE", "secret.txt")
    monkeypatch.setenv("PA_CODESIGN_PFX_BASE64", "base64-secret")
    monkeypatch.setenv("TAURI_SIGNING_PRIVATE_KEY", "updater-secret")
    monkeypatch.setenv("TAURI_SIGNING_PRIVATE_KEY_PASSWORD", "updater-password")
    child = si._sanitized_child_env()
    assert "PA_CODESIGN_PASSWORD" not in child
    assert "PA_CODESIGN_PASSWORD_FILE" not in child
    assert "PA_CODESIGN_PFX_BASE64" not in child
    assert "TAURI_SIGNING_PRIVATE_KEY" not in child
    assert "TAURI_SIGNING_PRIVATE_KEY_PASSWORD" not in child
    updater_child = si._sanitized_child_env(include_updater_signing=True)
    assert updater_child["TAURI_SIGNING_PRIVATE_KEY"] == "updater-secret"


def test_release_subprocess_timeout_is_fail_closed(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["safe-tool"], 12)

    monkeypatch.setattr(si.subprocess, "run", fake_run)
    with pytest.raises(si.SigningError, match="timed out after 12 seconds"):
        si._run_command(
            ["safe-tool"],
            purpose="release operation",
            timeout_seconds=12,
            check=False,
        )


def test_updater_signature_command_uses_installer_as_positional_argument(
    tmp_path, monkeypatch
):
    installer = tmp_path / "PrivateAgent_1.2.3_x64-setup.exe"
    installer.write_bytes(b"signed-installer")
    tauri = tmp_path / "tauri.cmd"
    tauri.write_text("@echo off\n", encoding="utf-8")
    captured: list[str] = []

    monkeypatch.setattr(si, "TAURI_CLI", tauri)

    def fake_run(command, **_kwargs):
        captured.extend(command)
        si.installer_sig(installer).write_text("updater-signature", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(si.subprocess, "run", fake_run)
    signature = si._regenerate_updater_signature(installer, required=False)
    assert signature.is_file()
    assert captured[:3] == [str(tauri.resolve()), "signer", "sign"]
    assert captured[-1] == str(installer)
    assert "-f" not in captured


def test_pfx_chain_cleanup_tracks_every_new_certificate_and_fails_closed(
    tmp_path, monkeypatch
):
    pfx = tmp_path / "certificate.pfx"
    pfx.write_bytes(b"fake")
    config = si.resolve_signing_config(
        {"PA_CODESIGN_PFX": str(pfx), "PA_CODESIGN_PASSWORD": "secret"}
    )
    leaf = "A" * 40
    chain = "B" * 40
    removed: list[str] = []

    def fake_powershell(_script, arguments, *, env=None):
        action = arguments[arguments.index("-Action") + 1]
        if action == "List":
            return json.dumps({"thumbprints": []})
        if action == "Import":
            assert env is not None and env["PA_CODESIGN_PASSWORD"] == "secret"
            return json.dumps(
                {
                    "thumbprint": leaf,
                    "imported": True,
                    "imported_thumbprints": [leaf, chain],
                }
            )
        if action == "Inspect":
            return json.dumps({"subject": "CN=Publisher"})
        thumbprint = arguments[arguments.index("-Thumbprint") + 1]
        removed.append(thumbprint)
        if thumbprint == chain:
            raise si.SigningError("simulated cleanup failure")
        return json.dumps({"removed": True})

    monkeypatch.setattr(si, "_run_powershell", fake_powershell)
    with pytest.raises(si.SigningError, match="production release is blocked"):
        with si.prepared_certificate(config) as prepared:
            assert prepared.thumbprint == leaf
            assert prepared.imported_thumbprints == (leaf, chain)
    assert removed == [leaf, chain]


def test_invalid_pfx_import_output_rolls_back_new_store_entries(tmp_path, monkeypatch):
    pfx = tmp_path / "certificate.pfx"
    pfx.write_bytes(b"fake")
    config = si.resolve_signing_config(
        {"PA_CODESIGN_PFX": str(pfx), "PA_CODESIGN_PASSWORD": "secret"}
    )
    leaf = "C" * 40
    inventory_calls = 0
    removed: list[str] = []

    def fake_powershell(_script, arguments, *, env=None):
        nonlocal inventory_calls
        action = arguments[arguments.index("-Action") + 1]
        if action == "List":
            inventory_calls += 1
            values = [] if inventory_calls == 1 else [leaf]
            return json.dumps({"thumbprints": values})
        if action == "Import":
            return "not-json"
        removed.append(arguments[arguments.index("-Thumbprint") + 1])
        return json.dumps({"removed": True})

    monkeypatch.setattr(si, "_run_powershell", fake_powershell)
    with pytest.raises(si.SigningError, match="import returned invalid JSON"):
        with si.prepared_certificate(config):
            raise AssertionError("unreachable")
    assert removed == [leaf]


def test_production_main_fails_closed_without_certificate(tmp_path, monkeypatch):
    monkeypatch.setattr(si, "DIST", tmp_path)
    monkeypatch.setattr(si, "read_version", lambda: "1.2.3")
    monkeypatch.setattr(
        si,
        "resolve_signing_config",
        lambda: si.SigningConfig(False, None, None, None),
    )
    assert si.main(["--require-signing", "--preflight"]) == 1
    status = json.loads((tmp_path / "codesign-status-1.2.3.json").read_text("utf-8"))
    assert status["code_signed"] is False
    assert status["verification_status"] == "failed"


def test_production_main_requires_expected_certificate_subject(tmp_path, monkeypatch):
    monkeypatch.setattr(si, "DIST", tmp_path)
    monkeypatch.setattr(si, "read_version", lambda: "1.2.3")
    monkeypatch.setattr(
        si,
        "resolve_signing_config",
        lambda: si.SigningConfig(True, "A" * 40, None, None),
    )
    assert si.main(["--preflight"]) == 1
    status = json.loads((tmp_path / "codesign-status-1.2.3.json").read_text("utf-8"))
    assert status["verification_status"] == "failed"


def test_production_certificate_identity_rejects_self_signed_and_missing_issuer():
    with pytest.raises(si.SigningError, match="subject and issuer"):
        si._validate_production_certificate_identity({"subject": "CN=Publisher"})
    with pytest.raises(si.SigningError, match="self-signed"):
        si._validate_production_certificate_identity(
            {"subject": "CN=Publisher", "issuer": "cn=publisher"}
        )
    si._validate_production_certificate_identity(
        {"subject": "CN=Publisher", "issuer": "CN=Trusted Code Signing CA"}
    )


def test_certificate_inspection_can_require_a_trusted_chain(monkeypatch):
    captured: list[str] = []

    def fake_powershell(_script, arguments, *, env=None):
        captured.extend(arguments)
        return json.dumps(
            {"subject": "CN=Publisher", "issuer": "CN=Trusted Code Signing CA"}
        )

    monkeypatch.setattr(si, "_run_powershell", fake_powershell)
    si._inspect_store_certificate(
        "A" * 40,
        "CN=Publisher",
        require_trusted_chain=True,
    )
    assert "-RequireTrustedChain" in captured


def test_development_unsigned_mode_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(si, "DIST", tmp_path)
    monkeypatch.setattr(si, "read_version", lambda: "1.2.3")
    monkeypatch.setattr(
        si,
        "resolve_signing_config",
        lambda: si.SigningConfig(False, None, None, None),
    )
    assert si.main([]) == 0
    note = (tmp_path / "unsigned-note-1.2.3.md").read_text(encoding="utf-8")
    assert "不得发布到生产更新通道" in note


def test_signing_order_authenticode_precedes_final_updater_signature():
    sign_index = si.SIGNING_ORDER.index("signtool sign (Authenticode, mutates bytes)")
    updater_index = si.SIGNING_ORDER.index(
        "re-run tauri signer sign -> regenerate .sig over SIGNED bytes"
    )
    assert sign_index < updater_index


def test_write_status_records_verification_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(si, "DIST", tmp_path)
    path = si.write_status(
        "1.2.3",
        code_signed=True,
        cert_subject="CN=Publisher",
        cert_thumbprint="A" * 40,
        timestamped=True,
        verification_status="Valid",
        installer_sha256="b" * 64,
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["code_signed"] is True
    assert data["timestamped"] is True
    assert data["verification_status"] == "Valid"
    assert data["installer_sha256"] == "b" * 64
    assert data["verified_at_utc"]


def test_gitignore_covers_certificate_and_private_key_files():
    gitignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(
        encoding="utf-8"
    )
    for pattern in ("*.pfx", "*.p12", "*.key", "*.pem", ".tauri/"):
        assert pattern in gitignore
