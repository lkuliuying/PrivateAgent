#!/usr/bin/env python3
"""Generate the Tauri v2 updater manifest (``latest.json``) for a release.

Auto-detects the NSIS installer and its ``.sig`` from the build output, reads
the version from ``tauri.conf.json``, and derives the GitHub repo from
``git remote``. The installer filename is **percent-encoded** in the download
URL: the Tauri updater's HTTP client requires an ASCII URL, so a raw non-ASCII
name like ``私人助手_0.1.0_x64-setup.exe`` would be rejected.

Usage (project root, after ``scripts/build-release.bat``)::

    uv run python scripts/generate-latest-json.py                       # dist/latest.json
    uv run python scripts/generate-latest-json.py --notes "..." --tag v0.1.1
    uv run python scripts/generate-latest-json.py --repo owner/repo --out latest.json

Then upload ``latest.json`` + the installer + the ``.sig`` to the GitHub Release.
Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from _release_utils import find_installer, installer_sig, read_version

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST = PROJECT_ROOT / "dist"


def git_origin_repo() -> str | None:
    """Return 'owner/repo' from the origin remote URL, or None."""
    try:
        out = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        url = out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return None
    # https://github.com/owner/repo(.git)  OR  git@github.com:owner/repo(.git)
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def find_installer_and_sig(version: str) -> tuple[Path, Path]:
    """Find the installer whose filename embeds `version` (version-match, not sort),
    plus its .sig. Aborts loudly on no/multiple match or missing signature."""
    installer = find_installer(version)
    sig = installer_sig(installer)
    if not sig.exists():
        raise SystemExit(
            f"[latest.json] signature not found: {sig}\n"
            "         Build with the updater signing key (see docs/signing-and-keys.md)."
        )
    return installer, sig


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--repo", help="GitHub repo as owner/repo (default: derived from git remote)")
    ap.add_argument("--tag", help="release tag (default: v<version>)")
    ap.add_argument("--notes", default=None, help="release notes (default: 私人助手 v<version>)")
    ap.add_argument("--out", default=None, help="output path (default: dist/latest.json)")
    args = ap.parse_args()

    version = read_version()
    installer, sig = find_installer_and_sig(version)
    signature = sig.read_text(encoding="utf-8").strip()
    if not signature:
        raise SystemExit(f"[latest.json] signature file is empty: {sig}")

    repo = args.repo or git_origin_repo()
    if not repo:
        raise SystemExit(
            "[latest.json] could not derive GitHub repo from git remote; pass --repo owner/repo"
        )
    tag = args.tag or f"v{version}"
    notes = args.notes if args.notes is not None else f"私人助手 v{version}"

    # Percent-encode the installer filename: non-ASCII must be encoded for HTTP.
    encoded_name = quote(installer.name, safe="")
    url = f"https://github.com/{repo}/releases/download/{tag}/{encoded_name}"
    pub_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    manifest = {
        "version": version,
        "notes": notes,
        "pub_date": pub_date,
        "platforms": {
            "windows-x86_64": {
                "signature": signature,
                "url": url,
            }
        },
    }

    out = Path(args.out) if args.out else DIST / "latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[latest.json] written: {out}")
    print(f"  version:    {version}")
    print(f"  tag:        {tag}")
    print(f"  installer:  {installer.name}")
    print(f"  url:        {url}")
    print(f"  signature:  {len(signature)} chars")
    print(f"\nNext: upload these three assets to the GitHub Release ({tag}):")
    print(f"  1. {installer.name}")
    print(f"  2. {sig.name}")
    print(f"  3. {out.name}")
    print("The updater endpoint in tauri.conf.json points to .../releases/latest/download/latest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
