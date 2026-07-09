#!/usr/bin/env python3
"""Generate a release manifest for a built Windows release.

Run after ``scripts/build-release.bat`` (or after a successful ``tauri build``).
Records the version (read from ``tauri.conf.json``), git commit/branch/remote,
SHA-256 of the sidecar, NSIS installer, and updater ``.sig``, plus the
latest.json generation reminder and a validation checklist.

Usage (project root)::

    uv run python scripts/generate_release_manifest.py            # print to stdout
    uv run python scripts/generate_release_manifest.py --write    # write dist/release-manifest-<ver>.md
    uv run python scripts/generate_release_manifest.py --out PATH

Stdlib only; no third-party imports.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from _release_utils import find_installer as find_installer_for_version, installer_sig, read_version

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SIDECAR = (
    PROJECT_ROOT
    / "apps"
    / "desktop"
    / "src-tauri"
    / "binaries"
    / "personal-assistant-server-x86_64-pc-windows-msvc.exe"
)
DIST = PROJECT_ROOT / "dist"


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(args: list[str]) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def find_installer(version: str) -> tuple[Path | None, Path | None]:
    """Locate the NSIS setup exe matching `version` (version-match, not sort) and its
    .sig. Returns (None, None) if no matching build exists yet (graceful for partial
    / pre-build runs)."""
    try:
        installer = find_installer_for_version(version)
    except SystemExit:
        return None, None
    sig = installer_sig(installer)
    return installer, (sig if sig.exists() else None)


def human_size(n: int | None) -> str:
    if n is None:
        return "n/a"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)


def build_manifest() -> str:
    version = read_version()
    commit = git(["rev-parse", "HEAD"])
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"])
    remote = git(["config", "--get", "remote.origin.url"])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # 代码签名状态（由 sign_installer.py 写入 dist/codesign-status-<version>.json）
    code_signed = False
    cert_subject: str | None = None
    codesign_status_path = DIST / f"codesign-status-{version}.json"
    if codesign_status_path.exists():
        try:
            cs = json.loads(codesign_status_path.read_text(encoding="utf-8"))
            code_signed = bool(cs.get("code_signed"))
            cert_subject = cs.get("cert_subject")
        except Exception:  # noqa: BLE001
            pass

    # 发布检查摘要（由 run_release_checks.py 写入 dist/release-check-<version>.json）
    release_check_summary: dict | None = None
    release_check_path = DIST / f"release-check-{version}.json"
    if release_check_path.exists():
        try:
            rc = json.loads(release_check_path.read_text(encoding="utf-8"))
            release_check_summary = rc.get("summary")
        except Exception:  # noqa: BLE001
            pass

    sidecar_hash = sha256(SIDECAR)
    installer, sig = find_installer(version)
    installer_hash = sha256(installer) if installer else None
    sig_hash = sha256(sig) if sig else None

    sidecar_size = SIDECAR.stat().st_size if SIDECAR.exists() else None
    installer_size = installer.stat().st_size if installer and installer.exists() else None

    lines: list[str] = [
        f"# Release Manifest — v{version}",
        "",
        f"- generated_at: {now}",
        f"- version: {version}",
        f"- git_commit: {commit or '(unknown)'}",
        f"- branch: {branch or '(detached)'}",
        f"- remote: {remote or '(none)'}",
        f"- code_signed: {'yes' if code_signed else 'no'}",
        "",
        "## Artifacts",
        "",
        "### Sidecar",
        f"- path: `{rel(SIDECAR)}`" if SIDECAR.exists() else "- sidecar: (not found — run scripts/build-sidecar.bat)",
        f"- size: {human_size(sidecar_size)}",
        f"- sha256: `{sidecar_hash or '(missing)'}`",
        "",
        "### NSIS installer",
    ]
    if installer:
        lines += [
            f"- path: `{rel(installer)}`",
            f"- size: {human_size(installer_size)}",
            f"- sha256: `{installer_hash or '(missing)'}`",
        ]
    else:
        lines.append("- (not found — run scripts/build-release.bat first)")
    lines += ["", "### Updater signature (.sig)"]
    if sig:
        lines += [
            f"- path: `{rel(sig)}`",
            f"- sha256: `{sig_hash or '(missing)'}`",
        ]
    else:
        lines.append("- (no .sig — build with the updater signing key to generate; see docs/signing-and-keys.md)")
    lines += [
        "",
        "### Code signing (Authenticode)",
        f"- code_signed: {'yes' if code_signed else 'no'}",
        f"- cert_subject: {cert_subject or '(unsigned)'}",
        "- 无证书时安装包未签名，SmartScreen 会拦截首次运行；详见 dist/unsigned-note-<version>.md。",
        "",
        "## Updater manifest (latest.json)",
        "",
        "- Generate with `scripts/generate-latest-json.py` and upload alongside the installer to the GitHub Release.",
        "- Endpoint: see `plugins.updater.endpoints` in `apps/desktop/src-tauri/tauri.conf.json`.",
        "",
        "## Validation checklist",
        "",
        "- [ ] `scripts/release-check.bat` (pytest / npm build / cargo check / alembic current)",
        "- [ ] `scripts/release-check-full.bat` (phase8: + npm test / e2e / 诊断包脱敏 / 清单校验)",
        "- [ ] `/health` all green",
        "- [ ] clean-install smoke (docs/release-checklist.md)",
        "- [ ] code_signed 状态与预期一致（无证书应为 no + SmartScreen 说明已生成）",
        "- [ ] upgrade smoke vN → vN+1 (docs/release-checklist.md)",
        "",
        "## Rollback",
        "",
        "- Revert the GitHub Release asset, or repoint `latest.json` to the previous stable version.",
        "- See the rollback section of `docs/release-checklist.md`.",
        "",
    ]
    if release_check_summary:
        lines += [
            "",
            "## Release check (phase8)",
            f"- passed: {release_check_summary.get('passed')}",
            f"- failed: {release_check_summary.get('failed')}",
            f"- skipped: {release_check_summary.get('skipped')}",
            "- 详见 dist/release-check-<version>.md（scripts/release-check-full.bat）",
        ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="write to dist/release-manifest-<version>.md")
    ap.add_argument("--out", help="explicit output path (implies --write)")
    args = ap.parse_args()

    manifest = build_manifest()
    if args.out:
        out = Path(args.out)
    elif args.write:
        DIST.mkdir(parents=True, exist_ok=True)
        out = DIST / f"release-manifest-{read_version()}.md"
    else:
        print(manifest)
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(manifest, encoding="utf-8")
    print(f"[manifest] written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
