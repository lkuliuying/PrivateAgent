#!/usr/bin/env python3
"""生成 unified 桌面的 GitHub Release 静态清单，不执行签名或上传。

正式操作应通过 --installer 指定本次最终安装包；标签必须为 v<源码版本>。
清单生成只检查输入契约，密码学验签另由 verify_update_release.py 执行。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from _release_utils import (
    UNIFIED_TARGET,
    assemble_manifest,
    build_platform_entry,
    find_installer,
    github_release_tag,
    installer_sig,
    read_version,
    unified_installer_name,
    validate_github_repo,
    validate_stable_version,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST = PROJECT_ROOT / "dist"


def git_origin_repo() -> str | None:
    """只从本地远端配置提取仓库标识，不输出原始 URL。"""
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
    except OSError:
        return None
    # 兼容 HTTPS 和 SSH 配置，返回值仍须通过仓库标识校验。
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def find_installer_and_sig(version: str) -> tuple[Path, Path]:
    """保留旧的本地发现入口，缺失或多个同版本产物时中止。"""
    installer = find_installer(version)
    sig = installer_sig(installer)
    if not sig.exists():
        raise SystemExit(
            f"[latest.json] signature not found: {sig}\n"
            "         See docs/releases/v1.0.0/github-release.md."
        )
    return installer, sig


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--repo", help="GitHub repo as owner/repo (default: derived from git remote)")
    ap.add_argument("--tag", help="release tag (default: v<version>)")
    ap.add_argument("--notes", default=None, help="release notes (default: 私人助手 v<version>)")
    ap.add_argument("--out", default=None, help="output path (default: dist/latest.json)")
    ap.add_argument("--installer", type=Path, help="明确指定本次签名安装包")
    ap.add_argument(
        "--extra-platform",
        action="append",
        default=[],
        help="额外平台 KEY:INSTALLER_PATH（macOS/Linux），sig 取 installer.sig；可重复",
    )
    args = ap.parse_args(argv)

    try:
        version = validate_stable_version(read_version())
        tag = github_release_tag(version, args.tag)
        repo = validate_github_repo(args.repo or git_origin_repo() or "")
    except ValueError as error:
        ap.error(str(error))
    try:
        if args.installer:
            installer = args.installer.absolute()
            sig = installer_sig(installer)
        else:
            installer, sig = find_installer_and_sig(version)
        if installer.name != unified_installer_name(version) or not installer.is_file() or installer.is_symlink():
            raise SystemExit("[latest.json] 安装包必须为当前版本的正式 unified Windows 安装器")
        if sig.is_symlink() or not sig.is_file():
            raise SystemExit("[latest.json] 安装包旁必须存在普通 .sig 文件")
        signature = sig.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        ap.error("无法读取本次安装包或 UTF-8 签名文件")
    if not signature:
        raise SystemExit(f"[latest.json] signature file is empty: {sig}")

    notes = args.notes if args.notes is not None else f"PrivateAgent Unified v{version}"

    pub_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 与统一本机桌面的 updater target 一致，不再发布旧服务端客户端更新。
    platforms = {
        UNIFIED_TARGET: build_platform_entry(installer, sig, repo, tag),
    }
    for spec in args.extra_platform:
        key, _, path = spec.partition(":")
        if not key or not path:
            raise SystemExit("[latest.json] --extra-platform 格式应为 KEY:INSTALLER_PATH")
        if key in platforms or key not in {"darwin-aarch64", "darwin-x86_64", "linux-x86_64"}:
            raise SystemExit("[latest.json] 不允许覆盖 unified 目标或使用未知的额外平台")
        extra_installer = Path(path)
        extra_sig = installer_sig(extra_installer)
        if not extra_sig.exists():
            raise SystemExit(
                f"[latest.json] --extra-platform {key}: signature not found: {extra_sig}"
            )
        platforms[key] = build_platform_entry(extra_installer, extra_sig, repo, tag)

    manifest = assemble_manifest(version, notes, pub_date, platforms)

    out = Path(args.out) if args.out else DIST / "latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[latest.json] written: {out}")
    print(f"  version:    {version}")
    print(f"  tag:        {tag}")
    print(f"  platforms:  {', '.join(platforms.keys())}")
    print(f"  installer:  {installer.name}")
    print(f"  signature:  {len(signature)} chars")
    print(f"\nNext: upload latest.json + each platform's installer + .sig to the GitHub Release ({tag}).")
    print("更新地址必须在构建时显式配置，并与本机桌面的独立更新通道一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
