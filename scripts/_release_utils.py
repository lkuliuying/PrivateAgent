#!/usr/bin/env python3
"""桌面发布辅助：按版本选择安装包，避免将旧版本误认为最新产物。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TAURI_CONF = PROJECT_ROOT / "apps" / "desktop" / "src-tauri" / "tauri.conf.json"
NSIS_DIR = (
    PROJECT_ROOT / "apps" / "desktop" / "src-tauri" / "target" / "x86_64-pc-windows-msvc" / "release" / "bundle" / "nsis"
)

UNIFIED_IDENTIFIER = "com.personal-assistant.desktop"
UNIFIED_TARGET = "unified-windows-x86_64"


def validate_github_repo(repo: str) -> str:
    """仅接受仓库标识，错误不回显可能误填的凭据。"""
    parts = repo.split("/") if isinstance(repo, str) else []
    if (len(parts) != 2
            or re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", parts[0]) is None
            or "--" in parts[0]
            or re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", parts[1]) is None
            or parts[1] in {".", ".."}):
        raise ValueError("GitHub 仓库必须为不含凭据的 owner/repo")
    return repo


def validate_stable_version(version: str) -> str:
    """正式更新只接受与构建器一致的稳定版本。"""
    if not isinstance(version, str) or re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version) is None:
        raise ValueError("发布版本必须为稳定的 X.Y.Z")
    return version


def unified_installer_name(version: str) -> str:
    return f"PrivateAgent_{validate_stable_version(version)}_x64-setup.exe"


def github_release_tag(version: str, tag: str | None = None) -> str:
    expected = f"v{validate_stable_version(version)}"
    if tag is not None and tag != expected:
        raise ValueError("GitHub 标签必须为 v<当前版本>")
    return expected


def github_update_url(repo: str) -> str:
    return f"https://github.com/{validate_github_repo(repo)}/releases/latest/download/latest.json"


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
    return f"https://github.com/{validate_github_repo(repo)}/releases/download/{quote(tag, safe='')}/{percent_encode_filename(filename)}"


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
