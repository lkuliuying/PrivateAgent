#!/usr/bin/env python3
"""Generate a release manifest for a built Windows release.

Run after ``scripts/release-check-full.bat`` **and** a successful ``tauri build``
(always run the full release check first; the manifest's checklist is derived from
``dist/release-check-<version>.json`` and must not be hand-marked).
Records the version (read from ``tauri.conf.json``), git commit/branch/remote,
SHA-256 of the sidecar, NSIS installer, and updater ``.sig``, plus the release
check summary and a checklist generated from the real step results.

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

from _release_utils import find_installer as find_installer_for_version
from _release_utils import installer_sig, read_version

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


def render_release_check(version: str, data: dict | None) -> list[str]:
    """发布检查事实摘要。release-check-<version>.json 是机器事实源，manifest 只引用其摘要。"""
    if not data:
        return [
            "",
            "## Release check (phase8): 未生成",
            "",
            f"- 缺少 dist/release-check-{version}.json，先运行 scripts/release-check-full.bat。",
            "",
        ]
    summary = data.get("summary") or {}
    commit = data.get("commit") or {}
    return [
        "",
        f"## Release check (phase8): {summary.get('passed', '?')} passed / "
        f"{summary.get('failed', '?')} failed / {summary.get('skipped', '?')} skipped",
        "",
        f"- ok: {data.get('ok')}",
        f"- generated_at: {data.get('generated_at')}",
        f"- commit: {commit.get('short')} ({commit.get('describe')})",
        f"- worktree_dirty: {commit.get('dirty')}",
        f"- database_schema: {data.get('database_schema')}",
        f"- pytest_summary: {data.get('pytest_summary')}",
        f"- signing: installer_built={data.get('signing', {}).get('installer_built')}, "
        f"code_signed={data.get('signing', {}).get('code_signed')}, "
        f"evidence={data.get('signing', {}).get('evidence')}",
        "- 机器事实源：dist/release-check-<version>.json；本清单由该报告步骤结果生成，"
        "不人工勾选。",
        "",
    ]


def checklist_items(data: dict | None) -> list[str]:
    """由 release-check 报告的真实步骤结果生成 checklist，状态缺失时如实标为未完成。"""
    if not data:
        return [
            "- [ ] `scripts/release-check-full.bat` 全量发布检查（未运行）",
            "- [ ] `/health` all green",
            "- [ ] clean-install smoke (docs/release-checklist.md)",
            "- [ ] code_signed 状态与预期一致（无证书应为 no + SmartScreen 说明已生成）",
            "- [ ] upgrade smoke vN → vN+1 (docs/release-checklist.md)",
        ]
    steps = data.get("steps") or []
    marks = {"passed": "[x]", "failed": "[ ]", "skipped": "[~]"}
    items = [f"- {marks.get(str(s.get('status')), '[ ]')} {s.get('name')} ({s.get('status')})"
             for s in steps]
    if not items:
        items.append("- [ ] release-check 报告没有步骤记录")
    items.append("- [ ] `/health` all green")
    items.append("- [ ] clean-install smoke (docs/release-checklist.md)")
    items.append("- [ ] code_signed 状态与预期一致（无证书应为 no + SmartScreen 说明已生成）")
    items.append("- [ ] upgrade smoke vN → vN+1 (docs/release-checklist.md)")
    return items


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

    # 发布检查摘要（机器事实源：dist/release-check-<version>.json，由 run_release_checks.py 写入；
    # manifest 只引用其摘要和步骤结果，不自行声明完成状态）
    release_check_data: dict | None = None
    release_check_path = DIST / f"release-check-{version}.json"
    if release_check_path.exists():
        try:
            release_check_data = json.loads(release_check_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            release_check_data = None

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
    ]
    lines += render_release_check(version, release_check_data)
    lines += [
        "## Validation checklist",
        "",
    ]
    lines += checklist_items(release_check_data)
    lines += [
        "## Rollback",
        "",
        "- Revert the GitHub Release asset, or repoint `latest.json` to the previous stable version.",
        "- See the rollback section of `docs/release-checklist.md`.",
        "",
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
