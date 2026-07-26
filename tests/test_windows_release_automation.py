"""Contracts for clean-Windows release assurance automation."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WINDOWS = ROOT / "scripts" / "windows"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_production_batch_is_fail_closed():
    batch = _read(ROOT / "scripts" / "build-release.bat")
    assert "--production" in batch
    assert 'set "PA_REQUIRE_CODESIGN=1"' in batch
    assert "PA_CODESIGN_THUMBPRINT or PA_CODESIGN_PFX is required" in batch
    assert "PA_CODESIGN_EXPECTED_SUBJECT is required" in batch
    assert "TAURI_SIGNING_PRIVATE_KEY is required in production" in batch
    assert "TAURI_SIGNING_PRIVATE_KEY_PASSWORD is required in production" in batch


def test_signing_preflight_requires_expected_identity_pin():
    preflight = _read(WINDOWS / "release-preflight.ps1")
    assert "production-expected-subject" in preflight
    assert "PA_CODESIGN_EXPECTED_SUBJECT" in preflight


def test_guest_lifecycle_covers_clean_install_upgrade_and_uninstall():
    script = _read(WINDOWS / "install-lifecycle.ps1")
    for phase in ("'preflight'", "'authenticode'", "'install'", "'upgrade'", "'uninstall'"):
        assert phase in script
    assert "RequireAuthenticode" in script
    assert "TimeStamperCertificate" in script
    assert "updater_signature_verified" in script
    assert "data_preserved_on_upgrade" in script
    assert "data_preserved_on_uninstall" in script
    assert "Start-And-AssertRuntime" in script
    assert "old_runtime_started" in script
    assert "new_runtime_started" in script
    assert "upgrade_closed_running_processes" in script
    assert "uninstall_closed_running_processes" in script
    assert "Residual application processes" in script
    assert "MainBinaryName" in script
    assert ".Trim('\"')" in script


def test_guest_lifecycle_tolerates_sparse_uninstall_registry_entries():
    script = _read(WINDOWS / "install-lifecycle.ps1")
    assert "$property = $Registration.PSObject.Properties[$Name]" in script
    assert "if ($null -eq $property)" in script
    assert "$displayName = Get-RegistrationValue $_ 'DisplayName'" in script
    assert "$_.DisplayName" not in script
    for optional_name in (
        "InstallLocation",
        "UninstallString",
        "MainBinaryName",
        "DisplayIcon",
        "DisplayVersion",
    ):
        assert f"Get-RegistrationValue $Registration '{optional_name}'" in script


def test_windows_upgrade_identity_and_main_binary_are_not_guessed():
    config = json.loads(
        _read(ROOT / "apps" / "desktop" / "src-tauri" / "tauri.conf.json")
    )
    hooks = _read(ROOT / "apps" / "desktop" / "src-tauri" / "nsis" / "installer-hooks.nsh")
    lifecycle = _read(WINDOWS / "install-lifecycle.ps1")
    assert config["productName"] == "私人助手"
    assert '${MAINBINARYNAME}.exe' in hooks
    assert "'appsdesktop'" in lifecycle
    assert "MainBinaryName" in lifecycle and "DisplayIcon" in lifecycle


def test_local_clean_machine_runners_require_real_isolation():
    hyperv = _read(WINDOWS / "run-hyperv-lifecycle.ps1")
    sandbox = _read(WINDOWS / "run-windows-sandbox-lifecycle.ps1")
    assert "Restore-VMSnapshot" in hyperv and "-ConfirmRestore" in hyperv
    assert "New-PSSession -VMName" in hyperv
    assert "WindowsSandbox.exe" in sandbox
    assert "<Networking>Disable</Networking>" in sandbox
    assert "install-lifecycle.ps1" in hyperv and "install-lifecycle.ps1" in sandbox
    assert "verify-updater-signatures.ps1" in hyperv and "verify-updater-signatures.ps1" in sandbox
    assert "[string]$UpdaterVerificationScope = 'unclassified'" in hyperv
    assert "[string]$UpdaterVerificationScope = 'unclassified'" in sandbox


def test_self_signed_lane_is_explicitly_non_production():
    script = _read(WINDOWS / "self-signed-signing-smoke.ps1")
    assert "production_identity = $false" in script
    assert "SELF-SIGNED TEST ONLY" in script
    assert "RequireTimestamp" in script
    assert "Invoke-ExternalWithTimeout" in script
    assert "ExternalTimeoutSeconds = 180" in script
    assert "cleanup_verified" in script
    assert "failed_stage" in script
    assert "Import-Certificate" not in script
    assert "AllowUntrustedSelfSigned" in script
    assert "tamper_detected" in script


def test_github_hosted_vm_separates_mechanism_and_production_lanes():
    workflow = _read(ROOT / ".github" / "workflows" / "windows-release-assurance.yml")
    assert "runs-on: windows-2025" in workflow
    assert "self-signed-mechanism" in workflow
    assert "production" in workflow
    assert "CI SELF-SIGNED TEST ONLY" in workflow
    assert "WINDOWS_CODESIGN_PFX_BASE64" in workflow
    assert "WINDOWS_CODESIGN_EXPECTED_SUBJECT" in workflow
    assert "install-lifecycle.ps1" in workflow
    assert "windows-lifecycle.json" in workflow
    assert "build-without-secrets" in workflow
    assert "windows-production-signing" in workflow
    assert "identity_class=$identityClass" in workflow
    assert 'refs/tags/${{ inputs.previous_ref' in workflow
    assert 'refs/tags/v$env:EXPECTED_VERSION' in workflow
    assert "Production certificate is not currently valid" in workflow
    assert "updater-signature-verifier" in workflow
    assert "Baseline and candidate embedded Tauri updater public keys" in workflow
    assert "ToBase64String($publicKeyBytes)" not in workflow
    assert "visual-regression" in workflow
    assert "npx playwright install chromium" in workflow
    assert "updater_verification_scope=$updaterVerificationScope" in workflow
    assert "timeout-minutes: 15" in workflow
    assert "UnknownError" in workflow and "NotTrusted" in workflow
    assert "SignatureStatus]::HashMismatch" in workflow
    assert "Tampered updater payload unexpectedly verified" in workflow


def test_clean_runner_bootstraps_legacy_sidecar_destination():
    workflow = _read(ROOT / ".github" / "workflows" / "windows-release-assurance.yml")
    sidecar_build = _read(ROOT / "scripts" / "build-sidecar.bat")
    baseline_step = workflow.split("name: Build tagged baseline without secrets", 1)[
        1
    ].split("name: Build candidate without secrets", 1)[0]
    assert "apps\\desktop\\src-tauri\\binaries" in baseline_step
    assert "New-Item -ItemType Directory" in baseline_step
    assert (
        'set "BINARY_DIR=%PROJECT_ROOT%\\apps\\desktop\\src-tauri\\binaries"'
        in sidecar_build
    )
    assert 'if not exist "%BINARY_DIR%" mkdir "%BINARY_DIR%"' in sidecar_build


def test_motion_tests_pin_no_preference_on_hosted_windows():
    animation_spec = _read(ROOT / "apps" / "desktop" / "e2e" / "animation.spec.ts")
    assert 'test.beforeEach(async ({ page })' in animation_spec
    assert 'reducedMotion: "no-preference"' in animation_spec
    assert 'reducedMotion: "reduce"' in animation_spec


def test_workflow_never_uploads_private_key_or_certificate_artifacts():
    workflow = _read(ROOT / ".github" / "workflows" / "windows-release-assurance.yml")
    upload = workflow.rsplit("name: Upload lifecycle evidence only", 1)[1]
    assert "windows-lifecycle.json" in upload
    for forbidden in (".pfx", ".p12", ".key", ".pem"):
        assert forbidden not in upload


def test_release_secrets_are_not_available_to_build_or_dependency_steps():
    workflow = _read(ROOT / ".github" / "workflows" / "windows-release-assurance.yml")
    build_job = workflow.split("build-without-secrets:", 1)[1].split(
        "sign-and-test-on-clean-vm:", 1
    )[0]
    for secret_name in (
        "WINDOWS_CODESIGN_PFX_BASE64",
        "WINDOWS_CODESIGN_PASSWORD",
        "TAURI_SIGNING_PRIVATE_KEY",
        "TAURI_SIGNING_PRIVATE_KEY_PASSWORD",
    ):
        assert secret_name not in build_job
    signing_job = workflow.split("sign-and-test-on-clean-vm:", 1)[1]
    before_authenticode = signing_job.split(
        "name: Authenticode-sign installers with isolated certificate secrets", 1
    )[0]
    authenticode_step = signing_job.split(
        "name: Authenticode-sign installers with isolated certificate secrets", 1
    )[1].split("name: Generate updater signatures with isolated updater secrets", 1)[0]
    updater_step = signing_job.split(
        "name: Generate updater signatures with isolated updater secrets", 1
    )[1].split("name: Verify updater signatures", 1)[0]
    assert "WINDOWS_CODESIGN_PFX_BASE64" not in before_authenticode
    assert "WINDOWS_CODESIGN_PFX_BASE64" in authenticode_step
    assert "TAURI_SIGNING_PRIVATE_KEY" not in authenticode_step
    assert "TAURI_SIGNING_PRIVATE_KEY" in updater_step
    assert "WINDOWS_CODESIGN_PFX_BASE64" not in updater_step
    assert "verify-authenticode.ps1" not in authenticode_step
    assert "verifier\\scripts" not in authenticode_step
    assert "npm install" not in authenticode_step
    assert "npm install" not in updater_step


def test_workflow_pins_third_party_actions_and_restricts_baseline_tags():
    workflow = _read(ROOT / ".github" / "workflows" / "windows-release-assurance.yml")
    assert "uses: actions/checkout@v" not in workflow
    assert "uses: actions/setup-node@v" not in workflow
    assert "uses: actions/setup-python@v" not in workflow
    assert "uses: actions/upload-artifact@v" not in workflow
    assert "uses: actions/download-artifact@v" not in workflow
    assert "previous_ref must be an immutable SemVer tag" in workflow
    assert "rustup toolchain install 1.96.1" in workflow
    assert "Disable updater artifacts for the unsigned build stage" in workflow


def test_authenticode_password_never_appears_in_signtool_command():
    signer = _read(ROOT / "scripts" / "sign_installer.py")
    command_body = signer.split("def build_signtool_sign_command", 1)[1].split(
        "def build_signtool_verify_command", 1
    )[0]
    assert '"/p"' not in command_body
    assert "config.password" not in command_body
    assert "PA_CODESIGN_PASSWORD_FILE is not supported" in signer


def test_updater_verifier_build_outputs_are_ignored():
    gitignore = _read(ROOT / ".gitignore")
    assert "scripts/windows/updater-signature-verifier/target/" in gitignore
