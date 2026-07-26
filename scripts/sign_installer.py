#!/usr/bin/env python3
"""Sign and verify the Windows installer with Authenticode.

Production releases are fail-closed.  Run ``--require-signing`` (or set
``PA_REQUIRE_CODESIGN=1``) so a missing/expired certificate, missing timestamp,
failed trust-chain verification, or missing updater key aborts the release.

Supported certificate sources:

* ``PA_CODESIGN_THUMBPRINT``: an existing certificate in ``CurrentUser\\My``.
* ``PA_CODESIGN_PFX`` + ``PA_CODESIGN_PASSWORD``: the PFX is imported into the
  current-user store for this run, used by thumbprint, then removed if this
  process imported it.  The password is passed only through the child-process
  environment; it is never placed on a command line, written to disk, or logged.

The byte-sensitive order is: Tauri build -> Authenticode sign -> Authenticode
verify -> regenerate the Tauri updater ``.sig`` over the signed installer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from _release_utils import find_installer, installer_sig, read_version  # noqa: E402

DIST = PROJECT_ROOT / "dist"
WINDOWS_SCRIPTS = PROJECT_ROOT / "scripts" / "windows"
DEFAULT_TIMESTAMP = "http://timestamp.digicert.com"
THUMBPRINT_RE = re.compile(r"^[0-9A-F]{40}$")
POWERSHELL_TIMEOUT_SECONDS = 120
SIGNTOOL_TIMEOUT_SECONDS = 180
UPDATER_SIGN_TIMEOUT_SECONDS = 180
UPDATER_VERIFY_TIMEOUT_SECONDS = 900
TAURI_CLI = PROJECT_ROOT / "apps" / "desktop" / "node_modules" / ".bin" / "tauri.cmd"

SIGNING_ORDER = [
    "tauri build -> NSIS exe + .sig (sig over UNSIGNED bytes)",
    "signtool sign (Authenticode, mutates bytes)",
    "signtool verify /pa /all /v",
    "PowerShell Get-AuthenticodeSignature trust + timestamp verification",
    "re-run tauri signer sign -> regenerate .sig over SIGNED bytes",
    "verify updater .sig against the tauri.conf embedded public key",
    "generate-latest-json.py (reads final .sig)",
]


class SigningError(RuntimeError):
    """A release-blocking signing or verification failure."""


@dataclass(frozen=True, slots=True)
class SigningConfig:
    require_signing: bool
    thumbprint: str | None
    pfx_path: Path | None
    password: str | None = field(repr=False)
    timestamp_url: str = DEFAULT_TIMESTAMP
    expected_subject: str | None = None

    @property
    def has_certificate(self) -> bool:
        return self.thumbprint is not None or self.pfx_path is not None


@dataclass(frozen=True, slots=True)
class PreparedCertificate:
    thumbprint: str
    imported_thumbprints: tuple[str, ...]
    details: dict[str, object]


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_thumbprint(value: str) -> str:
    normalized = re.sub(r"\s+", "", value).upper()
    if not THUMBPRINT_RE.fullmatch(normalized):
        raise SigningError("PA_CODESIGN_THUMBPRINT must be exactly 40 hexadecimal characters")
    return normalized


def _validate_timestamp_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SigningError("PA_CODESIGN_TIMESTAMP must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise SigningError("PA_CODESIGN_TIMESTAMP must not contain credentials")
    return value


def resolve_signing_config(env: Mapping[str, str] | None = None) -> SigningConfig:
    """Resolve and validate non-secret signing configuration.

    Password files are intentionally rejected for Authenticode production
    signing.  Use a secret environment variable or an already-imported
    certificate selected by thumbprint.
    """

    values = os.environ if env is None else env
    require_signing = _is_true(values.get("PA_REQUIRE_CODESIGN"))
    raw_thumbprint = values.get("PA_CODESIGN_THUMBPRINT", "").strip()
    raw_pfx = values.get("PA_CODESIGN_PFX", "").strip()
    password = values.get("PA_CODESIGN_PASSWORD", "")
    password_file = values.get("PA_CODESIGN_PASSWORD_FILE", "").strip()
    expected_subject = values.get("PA_CODESIGN_EXPECTED_SUBJECT", "").strip() or None

    if password_file:
        raise SigningError(
            "PA_CODESIGN_PASSWORD_FILE is not supported: certificate passwords must not be written to disk"
        )
    if raw_thumbprint and raw_pfx:
        raise SigningError("set exactly one of PA_CODESIGN_THUMBPRINT or PA_CODESIGN_PFX")

    thumbprint = normalize_thumbprint(raw_thumbprint) if raw_thumbprint else None
    pfx_path = Path(raw_pfx).resolve() if raw_pfx else None
    if pfx_path is not None and not pfx_path.is_file():
        raise SigningError("PA_CODESIGN_PFX does not point to a readable file")
    if pfx_path is not None and not password:
        raise SigningError("PA_CODESIGN_PASSWORD is required when PA_CODESIGN_PFX is used")
    if password and pfx_path is None:
        raise SigningError("PA_CODESIGN_PASSWORD was set without PA_CODESIGN_PFX")

    timestamp = _validate_timestamp_url(
        values.get("PA_CODESIGN_TIMESTAMP", "").strip() or DEFAULT_TIMESTAMP
    )
    return SigningConfig(
        require_signing=require_signing,
        thumbprint=thumbprint,
        pfx_path=pfx_path,
        password=password or None,
        timestamp_url=timestamp,
        expected_subject=expected_subject,
    )


def _environment_value(values: Mapping[str, str], name: str) -> str:
    expected = name.casefold()
    return next((value for key, value in values.items() if key.casefold() == expected), "")


def find_signtool(env: Mapping[str, str] | None = None) -> Path:
    """Find the x64 Windows SDK SignTool without trusting ``PATH``."""

    values = os.environ if env is None else env
    configured = _environment_value(values, "PA_SIGNTOOL_PATH").strip()
    if configured:
        path = Path(configured).resolve()
        if path.is_file():
            return path
        raise SigningError("PA_SIGNTOOL_PATH does not point to a file")

    roots = [
        Path(_environment_value(values, "ProgramFiles(x86)")) / "Windows Kits" / "10" / "bin",
        Path(_environment_value(values, "ProgramFiles")) / "Windows Kits" / "10" / "bin",
    ]
    candidates: list[Path] = []
    for root in roots:
        if root.is_dir():
            candidates.extend(root.glob("*/x64/signtool.exe"))
    if candidates:
        return sorted(candidates, key=lambda item: item.parent.parent.name, reverse=True)[0]
    raise SigningError("signtool.exe was not found; install the Windows SDK Signing Tools")


def find_windows_powershell(env: Mapping[str, str] | None = None) -> Path:
    """Resolve the inbox Windows PowerShell executable by absolute system path."""

    values = os.environ if env is None else env
    system_root = _environment_value(values, "SystemRoot").strip()
    if not system_root:
        raise SigningError("SystemRoot is unavailable; Windows PowerShell cannot be trusted")
    powershell = (
        Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    ).resolve()
    if not powershell.is_file():
        raise SigningError("inbox Windows PowerShell was not found at its trusted system path")
    return powershell


def _assert_microsoft_signed_tool(path: Path) -> None:
    """Require a valid Microsoft Authenticode identity for the production tool."""

    env = _sanitized_child_env()
    env["PA_RELEASE_TOOL_PATH"] = str(path)
    command = (
        "$s=Get-AuthenticodeSignature -LiteralPath $env:PA_RELEASE_TOOL_PATH;"
        "if($s.Status -ne [System.Management.Automation.SignatureStatus]::Valid){exit 21};"
        "if(-not $s.SignerCertificate -or $s.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation'){exit 22}"
    )
    result = _run_command(
        [
            find_windows_powershell(env),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        env=env,
        check=False,
        purpose="Microsoft release-tool identity verification",
        timeout_seconds=POWERSHELL_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise SigningError("SignTool is not a valid Microsoft-signed Windows SDK binary")


def build_signtool_sign_command(
    installer: str | Path,
    config: SigningConfig,
    *,
    signtool: str | Path = "signtool",
    thumbprint: str | None = None,
) -> list[str]:
    selected = thumbprint or config.thumbprint
    if selected is None:
        raise SigningError("a certificate-store thumbprint is required before signing")
    return [
        str(signtool),
        "sign",
        "/fd",
        "SHA256",
        "/sha1",
        normalize_thumbprint(selected),
        "/tr",
        config.timestamp_url,
        "/td",
        "SHA256",
        "/d",
        "PrivateAgent",
        str(installer),
    ]


def build_signtool_verify_command(
    installer: str | Path, *, signtool: str | Path = "signtool"
) -> list[str]:
    return [str(signtool), "verify", "/pa", "/all", "/v", str(installer)]


def _sanitized_child_env(*, include_updater_signing: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "PA_CODESIGN_PASSWORD",
        "PA_CODESIGN_PASSWORD_FILE",
        "PA_CODESIGN_PFX_BASE64",
    ):
        env.pop(name, None)
    if not include_updater_signing:
        env.pop("TAURI_SIGNING_PRIVATE_KEY", None)
        env.pop("TAURI_SIGNING_PRIVATE_KEY_PASSWORD", None)
    return env


def _run_command(
    command: Sequence[str | Path],
    *,
    purpose: str,
    timeout_seconds: float,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """Run one release command with a hard deadline and a safe error."""

    try:
        return subprocess.run(
            [str(part) for part in command],
            timeout=timeout_seconds,
            **kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        raise SigningError(
            f"{purpose} timed out after {timeout_seconds:g} seconds"
        ) from exc


def _run_powershell(script: Path, arguments: list[str], *, env: Mapping[str, str] | None = None) -> str:
    child_env = dict(env) if env is not None else _sanitized_child_env()
    powershell = find_windows_powershell(child_env)
    result = _run_command(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *arguments,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env,
        check=False,
        purpose="certificate PowerShell helper",
        timeout_seconds=POWERSHELL_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        message = result.stderr.strip().splitlines()
        safe_detail = message[-1] if message else "PowerShell helper failed"
        raise SigningError(safe_detail)
    return result.stdout.strip()


def _inspect_store_certificate(
    thumbprint: str,
    expected_subject: str | None,
    *,
    require_trusted_chain: bool = False,
) -> dict[str, object]:
    args = ["-Action", "Inspect", "-Thumbprint", thumbprint]
    if expected_subject:
        args.extend(["-ExpectedSubject", expected_subject])
    if require_trusted_chain:
        args.append("-RequireTrustedChain")
    output = _run_powershell(WINDOWS_SCRIPTS / "codesign-certificate.ps1", args)
    try:
        details = json.loads(output)
    except json.JSONDecodeError as exc:
        raise SigningError("certificate preflight returned invalid JSON") from exc
    return details


def _list_store_thumbprints() -> set[str]:
    output = _run_powershell(
        WINDOWS_SCRIPTS / "codesign-certificate.ps1", ["-Action", "List"]
    )
    try:
        payload = json.loads(output)
        values = payload.get("thumbprints") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            raise TypeError
        return {normalize_thumbprint(str(item)) for item in values}
    except (TypeError, json.JSONDecodeError) as exc:
        raise SigningError("certificate inventory returned invalid JSON") from exc


def _validate_production_certificate_identity(details: Mapping[str, object]) -> None:
    """Reject identities that cannot represent a CA-issued production signer."""

    subject = str(details.get("subject") or "").strip()
    issuer = str(details.get("issuer") or "").strip()
    if not subject or not issuer:
        raise SigningError("production certificate inspection must return subject and issuer")
    if subject.casefold() == issuer.casefold():
        raise SigningError("self-signed certificates are forbidden for production releases")


@contextmanager
def prepared_certificate(
    config: SigningConfig, *, require_trusted_chain: bool = False
) -> Iterator[PreparedCertificate]:
    """Yield a validated store certificate and remove only run-imported state."""

    imported_thumbprints: tuple[str, ...] = ()
    thumbprint = config.thumbprint
    if config.pfx_path is not None:
        present_before = _list_store_thumbprints()
        import_env = _sanitized_child_env()
        import_env["PA_CODESIGN_PASSWORD"] = config.password or ""
        output = _run_powershell(
            WINDOWS_SCRIPTS / "codesign-certificate.ps1",
            ["-Action", "Import", "-PfxPath", str(config.pfx_path)],
            env=import_env,
        )
        try:
            imported_result = json.loads(output)
            thumbprint = normalize_thumbprint(str(imported_result["thumbprint"]))
            imported_thumbprints = tuple(
                normalize_thumbprint(str(item))
                for item in imported_result.get("imported_thumbprints", [])
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            rollback_failures: list[str] = []
            try:
                imported_after_failure = _list_store_thumbprints() - present_before
            except SigningError as inventory_error:
                raise SigningError(
                    "certificate import returned invalid JSON and rollback inventory failed"
                ) from inventory_error
            for candidate in imported_after_failure:
                try:
                    removal = json.loads(
                        _run_powershell(
                            WINDOWS_SCRIPTS / "codesign-certificate.ps1",
                            ["-Action", "Remove", "-Thumbprint", candidate],
                        )
                    )
                    if removal.get("removed") is not True:
                        rollback_failures.append(candidate)
                except (json.JSONDecodeError, SigningError):
                    rollback_failures.append(candidate)
            if rollback_failures:
                raise SigningError(
                    "certificate import returned invalid JSON and rollback was incomplete"
                ) from exc
            raise SigningError("certificate import returned invalid JSON") from exc

    if thumbprint is None:
        raise SigningError("no Authenticode certificate configured")

    try:
        details = _inspect_store_certificate(
            thumbprint,
            config.expected_subject,
            require_trusted_chain=require_trusted_chain,
        )
        yield PreparedCertificate(thumbprint, imported_thumbprints, details)
    finally:
        cleanup_failures: list[str] = []
        for imported_thumbprint in imported_thumbprints:
            try:
                output = _run_powershell(
                    WINDOWS_SCRIPTS / "codesign-certificate.ps1",
                    ["-Action", "Remove", "-Thumbprint", imported_thumbprint],
                )
                removal = json.loads(output)
                if removal.get("removed") is not True:
                    raise SigningError("certificate helper reported incomplete cleanup")
            except (json.JSONDecodeError, SigningError) as exc:
                cleanup_failures.append(str(exc))
        if cleanup_failures:
            raise SigningError(
                "temporary certificate cleanup failed; production release is blocked: "
                + "; ".join(cleanup_failures)
            )


def _verify_authenticode(installer: Path, thumbprint: str) -> dict[str, object]:
    output = _run_powershell(
        WINDOWS_SCRIPTS / "verify-authenticode.ps1",
        ["-Path", str(installer), "-ExpectedThumbprint", thumbprint, "-RequireTimestamp"],
    )
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise SigningError("Authenticode verification returned invalid JSON") from exc


def unsigned_release_notes(version: str) -> str:
    return (
        f"## PrivateAgent v{version} 安装说明（未代码签名）\n\n"
        "本安装包未经过 Windows Authenticode 代码签名，仅允许用于本地开发验证，"
        "不得发布到生产更新通道。Windows SmartScreen 可能阻止安装。\n"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_status(
    version: str,
    *,
    code_signed: bool,
    timestamp_server: str = DEFAULT_TIMESTAMP,
    cert_subject: str | None = None,
    cert_thumbprint: str | None = None,
    timestamped: bool = False,
    verification_status: str = "not-run",
    installer_sha256: str | None = None,
) -> Path:
    DIST.mkdir(parents=True, exist_ok=True)
    path = DIST / f"codesign-status-{version}.json"
    payload = {
        "version": version,
        "code_signed": code_signed,
        "cert_subject": cert_subject,
        "cert_thumbprint": cert_thumbprint,
        "timestamp_server": timestamp_server,
        "timestamped": timestamped,
        "verification_status": verification_status,
        "installer_sha256": installer_sha256,
        "verified_at_utc": datetime.now(timezone.utc).isoformat() if code_signed else None,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_unsigned_note(version: str) -> Path:
    DIST.mkdir(parents=True, exist_ok=True)
    path = DIST / f"unsigned-note-{version}.md"
    path.write_text(unsigned_release_notes(version), encoding="utf-8")
    return path


def _regenerate_updater_signature(installer: Path, *, required: bool) -> Path:
    if required and not os.environ.get("TAURI_SIGNING_PRIVATE_KEY", "").strip():
        raise SigningError("TAURI_SIGNING_PRIVATE_KEY is required for a production release")
    if required and not os.environ.get("TAURI_SIGNING_PRIVATE_KEY_PASSWORD", ""):
        raise SigningError("TAURI_SIGNING_PRIVATE_KEY_PASSWORD is required for a production release")

    tauri = TAURI_CLI.resolve()
    if not tauri.is_file():
        raise SigningError("locked local Tauri CLI is missing; run npm ci before signing")
    sig = installer_sig(installer)
    sig.unlink(missing_ok=True)
    result = _run_command(
        [tauri, "signer", "sign", str(installer)],
        cwd=PROJECT_ROOT / "apps" / "desktop",
        env=_sanitized_child_env(include_updater_signing=True),
        check=False,
        purpose="Tauri updater signature generation",
        timeout_seconds=UPDATER_SIGN_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise SigningError("Tauri updater signature regeneration failed")
    if not sig.is_file() or not sig.read_text(encoding="utf-8").strip():
        raise SigningError("Tauri updater signature was not created or is empty")
    return sig


def _verify_updater_signature(installer: Path, signature: Path) -> None:
    cargo = shutil.which("cargo.exe") or shutil.which("cargo")
    if not cargo:
        raise SigningError("Cargo is required for pinned updater signature verification")
    config = json.loads(
        (PROJECT_ROOT / "apps" / "desktop" / "src-tauri" / "tauri.conf.json").read_text(
            encoding="utf-8"
        )
    )
    public_key = str(config.get("plugins", {}).get("updater", {}).get("pubkey", "")).strip()
    if not public_key:
        raise SigningError("tauri.conf.json has no updater public key")

    manifest = WINDOWS_SCRIPTS / "updater-signature-verifier" / "Cargo.toml"
    with tempfile.TemporaryDirectory(prefix="private-agent-updater-verify-") as directory:
        public_key_file = Path(directory) / "updater-pubkey.txt"
        public_key_file.write_text(public_key, encoding="utf-8")
        env = _sanitized_child_env()
        env["CARGO_TARGET_DIR"] = str(Path(directory) / "target")
        result = _run_command(
            [
                cargo,
                "run",
                "--quiet",
                "--locked",
                "--release",
                "--manifest-path",
                str(manifest),
                "--",
                str(installer),
                str(signature),
                str(public_key_file),
            ],
            env=env,
            check=False,
            purpose="pinned updater signature verification",
            timeout_seconds=UPDATER_VERIFY_TIMEOUT_SECONDS,
        )
    if result.returncode != 0:
        raise SigningError(
            "updater signature does not match the signed installer and embedded public key"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", help="installer path (default: auto-detect by version)")
    parser.add_argument(
        "--require-signing",
        action="store_true",
        help="fail when signing credentials or any verification gate is unavailable",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="validate SignTool and certificate readiness without touching an installer",
    )
    args = parser.parse_args(argv)

    version = read_version()
    installer: Path | None = None
    try:
        config = resolve_signing_config()
        required = args.require_signing or config.require_signing
        if not config.has_certificate:
            if required:
                raise SigningError(
                    "production signing is required but neither PA_CODESIGN_THUMBPRINT nor PA_CODESIGN_PFX is set"
                )
            note = write_unsigned_note(version)
            status = write_status(version, code_signed=False, verification_status="unsigned-development")
            print("[sign] development-only unsigned build; production publication is blocked")
            print(f"[sign] note: {note}")
            print(f"[sign] status: {status}")
            return 0
        if required and not config.expected_subject:
            raise SigningError(
                "PA_CODESIGN_EXPECTED_SUBJECT is required for a production release"
            )

        signtool = find_signtool()
        if required:
            _assert_microsoft_signed_tool(signtool)
        with prepared_certificate(config, require_trusted_chain=required) as cert:
            subject = str(cert.details.get("subject") or "")
            if required:
                _validate_production_certificate_identity(cert.details)
            if args.preflight:
                print(
                    "[sign] preflight OK: "
                    f"certificate={cert.thumbprint[-12:]} subject={subject!r} signtool={signtool}"
                )
                return 0

            installer = Path(args.installer).resolve() if args.installer else find_installer(version)
            if not installer.is_file():
                raise SigningError("installer does not exist")
            installer_sig(installer).unlink(missing_ok=True)

            print(f"[sign] signing {installer.name} with certificate ...{cert.thumbprint[-12:]}")
            result = _run_command(
                build_signtool_sign_command(
                    installer, config, signtool=signtool, thumbprint=cert.thumbprint
                ),
                env=_sanitized_child_env(),
                check=False,
                purpose="Authenticode signing and RFC3161 timestamping",
                timeout_seconds=SIGNTOOL_TIMEOUT_SECONDS,
            )
            if result.returncode != 0:
                raise SigningError("signtool sign failed")

            result = _run_command(
                build_signtool_verify_command(installer, signtool=signtool),
                env=_sanitized_child_env(),
                check=False,
                purpose="Authenticode trust-chain verification",
                timeout_seconds=SIGNTOOL_TIMEOUT_SECONDS,
            )
            if result.returncode != 0:
                raise SigningError("signtool trust-chain verification failed")

            verification = _verify_authenticode(installer, cert.thumbprint)
            sig = _regenerate_updater_signature(installer, required=required)
            _verify_updater_signature(installer, sig)
            status = write_status(
                version,
                code_signed=True,
                timestamp_server=config.timestamp_url,
                cert_subject=str(verification.get("subject") or subject),
                cert_thumbprint=cert.thumbprint,
                timestamped=bool(verification.get("timestamped")),
                verification_status=str(verification.get("status") or "Valid"),
                installer_sha256=sha256_file(installer),
            )
            print(f"[sign] OK: Authenticode trust and RFC3161 timestamp verified; updater sig={sig}")
            print(f"[sign] status: {status}")
            return 0
    except (OSError, SigningError) as exc:
        if installer is not None:
            installer_sig(installer).unlink(missing_ok=True)
        write_status(
            version,
            code_signed=False,
            verification_status="failed",
            installer_sha256=(
                sha256_file(installer)
                if installer is not None and installer.is_file()
                else None
            ),
        )
        print(f"[sign] FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
