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
from urllib.parse import quote

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
    (matches the ``_<version>_`` segment, e.g. ``PrivateAgent_0.1.10_x64-setup.exe``).

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


# ============ 跨平台 updater 清单（第八阶段 M5）============

# 平台 -> (bundle 子目录, 安装包 glob)。跨平台 latest.json 按此发现资产。
PLATFORM_BUNDLES = {
    "windows-x86_64": ("nsis", "*-setup.exe"),
    "darwin-aarch64": ("dmg", "*.dmg"),
    "darwin-x86_64": ("dmg", "*.dmg"),
    "linux-x86_64": ("appimage", "*.AppImage"),
}

BUNDLE_ROOT = (
    PROJECT_ROOT / "apps" / "desktop" / "src-tauri" / "target" / "release" / "bundle"
)


def percent_encode_filename(name: str) -> str:
    """百分号编码文件名：Tauri updater 的 HTTP 客户端要求 ASCII URL。"""
    return quote(name, safe="")


def github_download_url(repo: str, tag: str, filename: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{percent_encode_filename(filename)}"


def read_signature(sig_path) -> str:
    """读取 .sig 内容，空则报错（updater 会拒绝空签名）。"""
    sig = Path(sig_path).read_text(encoding="utf-8").strip()
    if not sig:
        raise SystemExit(f"[release] signature file is empty: {sig_path}")
    return sig


def build_platform_entry(installer_path, sig_path, repo: str, tag: str) -> dict:
    """构造单个平台的 updater 条目：{signature, url}（文件名百分号编码）。"""
    installer = Path(installer_path)
    return {
        "signature": read_signature(sig_path),
        "url": github_download_url(repo, tag, installer.name),
    }


def assemble_manifest(version: str, notes: str, pub_date: str, platforms: dict) -> dict:
    """构造 latest.json manifest（platforms: {key: {signature, url}}）。"""
    return {
        "version": version,
        "notes": notes,
        "pub_date": pub_date,
        "platforms": platforms,
    }


def find_cross_platform_installers(version: str) -> dict:
    """扫描 bundle 目录，返回 {platform_key: (installer_path, sig_path)}。

    仅返回实际存在安装包 + .sig 的平台；windows 必须存在，macOS/Linux 可选。
    darwin-aarch64 / darwin-x86_64 共用 dmg 目录，按文件名架构关键字区分。
    """
    found: dict = {}
    for key, (subdir, glob) in PLATFORM_BUNDLES.items():
        d = BUNDLE_ROOT / subdir
        if not d.exists():
            continue
        matches = [p for p in d.glob(glob) if version in p.name]
        if not matches:
            continue
        if key.startswith("darwin") and len(matches) > 1:
            arch = "aarch64" if key.endswith("aarch64") else "x86_64"
            arch_matches = [p for p in matches if arch in p.name.lower()]
            matches = arch_matches or matches
        installer = matches[0]
        sig = installer_sig(installer)
        if sig.exists():
            found[key] = (installer, sig)
    return found
