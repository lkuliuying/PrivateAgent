#!/usr/bin/env python3
"""Shared helpers for Phase 5 release scripts: version + installer discovery.

Used by generate_release_manifest.py, generate-latest-json.py, and
measure_sidecar_baseline.py so they all select the NSIS installer the same way:
by the version embedded in its filename (``_<version>_``), NOT by lexicographic
sort -- a lexicographic sort misorders across digit-count boundaries
(e.g. 0.1.9 vs 0.1.10, where "0.1.10" < "0.1.9") and would point the updater at a
signed downgrade. Stale installers in the nsis dir are caught loudly.
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TAURI_CONF = PROJECT_ROOT / "apps" / "desktop" / "src-tauri" / "tauri.conf.json"
NSIS_DIR = (
    PROJECT_ROOT / "apps" / "desktop" / "src-tauri" / "target" / "release" / "bundle" / "nsis"
)


def read_version() -> str:
    """Read the app version from tauri.conf.json."""
    data = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    v = data.get("version")
    if not v:
        raise SystemExit("[release] tauri.conf.json has no 'version' field")
    return v


def find_installer(version: str) -> Path:
    """Return the NSIS setup exe whose filename embeds ``version``
    (matches the ``_<version>_`` segment, e.g. ``私人助手_0.1.10_x64-setup.exe``).

    Aborts (SystemExit) if the bundle dir is missing, no installer matches the
    version, or multiple match (stale installers) -- never silently picks the
    wrong build. Callers that want graceful "not found" handling should catch
    SystemExit.
    """
    if not NSIS_DIR.exists():
        raise SystemExit(
            f"[release] NSIS bundle dir not found: {NSIS_DIR}\n"
            "Run scripts/build-release.bat first."
        )
    matches = [p for p in NSIS_DIR.glob("*-setup.exe") if f"_{version}_" in p.name]
    if not matches:
        existing = [p.name for p in NSIS_DIR.glob("*-setup.exe")]
        raise SystemExit(
            f"[release] no *-setup.exe matching version {version} in {NSIS_DIR}.\n"
            f"Existing: {existing}\n"
            "Delete stale *-setup.exe and rerun scripts/build-release.bat."
        )
    if len(matches) > 1:
        raise SystemExit(
            f"[release] multiple installers match version {version}: "
            f"{[p.name for p in matches]}\n"
            f"Delete stale *-setup.exe in {NSIS_DIR} and rebuild."
        )
    return matches[0]


def installer_sig(installer: Path) -> Path:
    """Return the .sig path adjacent to an installer (may not exist)."""
    return installer.with_name(installer.name + ".sig")
