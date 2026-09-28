#!/usr/bin/env python3
"""只读核验 GitHub 更新资产，标准输出仅返回可归档的 JSON 证据。"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from _release_utils import (
    TAURI_CONF,
    UNIFIED_IDENTIFIER,
    UNIFIED_TARGET,
    github_download_url,
    github_release_tag,
    github_update_url,
    installer_sig,
    unified_installer_name,
    validate_github_repo,
    validate_stable_version,
)
from coding_validation_process import managed_process
from generate_release_manifest import build_manifest, sha256

ROOT = Path(__file__).resolve().parents[1]
VERIFIER_MANIFEST = ROOT / "scripts/windows/updater-signature-verifier/Cargo.toml"


def checked_file(path: Path, label: str, within: Path | None = None) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label}缺失、不是普通文件或为符号链接")
    resolved = path.resolve(strict=True)
    if within is not None and not resolved.is_relative_to(within):
        raise ValueError(f"{label}超出构建目录")
    return resolved


def read_object(path: Path) -> dict:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("JSON 包含重复字段")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError("发布记录不是有效的 UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ValueError("发布记录必须为 JSON 对象")
    return value


def require_fields(actual: dict, expected: dict, label: str) -> None:
    if any(type(actual.get(key)) is not type(value) or actual[key] != value for key, value in expected.items()):
        raise ValueError(f"{label}与正式 GitHub 发布契约不一致")


def object_field(value: dict, key: str) -> dict:
    result = value.get(key)
    if not isinstance(result, dict):
        raise ValueError("发布配置缺少必要对象")
    return result


def check_timestamp(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])", value
    ) is None:
        raise ValueError("pub_date 必须为带时区的 RFC 3339 时间")
    try:
        datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("pub_date 包含无效日期或时间") from error


def verify_signature(installer: Path, signature: Path, public_key: Path, verifier: Path | None) -> None:
    if verifier is None:
        command = ["cargo", "run", "--offline", "--locked", "--release", "--manifest-path", str(VERIFIER_MANIFEST), "--"]
    else:
        command = [str(checked_file(verifier, "验签程序"))]
    command.extend(map(str, (installer, signature, public_key)))
    # 只转交工具链所需环境；验签进程不继承签名私钥、令牌或业务配置。
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE", "TEMP", "TMP",
               "USERPROFILE", "HOME", "CARGO_HOME", "RUSTUP_HOME", "INCLUDE", "LIB", "LIBPATH"}
    env = {key: os.environ[key] for key in os.environ if key.upper() in allowed}
    try:
        with managed_process(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", errors="replace") as process:
            process.communicate(timeout=180)
            returncode = process.returncode
    except subprocess.TimeoutExpired as error:
        raise ValueError("离线验签超时；请先编译验证器，再用 --verifier 指定程序") from error
    except OSError as error:
        raise ValueError("无法启动离线验签器；请检查 Rust/MSVC 或 --verifier 程序") from error
    if returncode:
        # 不转发依赖工具的原始输出，避免错误输入或环境信息进入发布证据。
        raise ValueError("离线验签失败；请核对最终安装器、签名、公钥及离线工具链")


def verify_release(bundle: Path, installer: Path, manifest: Path, repo: str,
                   verifier: Path | None = None) -> dict:
    repo = validate_github_repo(repo)
    bundle = bundle.resolve(strict=True)
    if not bundle.is_dir():
        raise ValueError("构建目录不存在")
    paths = {name: checked_file(bundle / name, name, bundle) for name in (
        "build-info.json", "tauri-build.json", "source-manifest.json", "SHA256SUMS.txt", "updater-public-key.txt",
        "PrivateAgent-windows-x64.exe", "private-agent-local.exe", "exec-host.exe", "exec-host.sha256",
    )}
    info = read_object(paths["build-info.json"])
    version = validate_stable_version(info.get("version"))
    tag = github_release_tag(version)
    endpoint = github_update_url(repo)
    asset_base = f"https://github.com/{repo}/releases/download/{tag}"
    require_fields(info, {
        "mode": "release", "unified": True, "qa": False, "dirty": False,
        "applicationIdentifier": UNIFIED_IDENTIFIER, "target": "x86_64-pc-windows-msvc",
        "updateTarget": UNIFIED_TARGET, "signing": "updater-verified", "accessMode": "api-key",
        "sidecar": "desktop-local", "transport": "stdio-v2", "githubRepo": repo,
        "releaseTag": tag, "updateUrl": endpoint, "downloadBaseUrl": asset_base,
    }, "构建记录")
    commit = info.get("commit")
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", commit) is None:
        raise ValueError("构建记录缺少有效提交标识")
    installer = checked_file(installer, "最终安装包")
    if installer.name != unified_installer_name(version):
        raise ValueError("安装包必须匹配当前正式 unified 版本及目标")
    signature = checked_file(installer_sig(installer), "更新签名")
    manifest = checked_file(manifest, "更新清单")
    if manifest.name != "latest.json":
        raise ValueError("更新清单文件名必须为 latest.json")

    config = read_object(paths["tauri-build.json"])
    require_fields(config, {"identifier": UNIFIED_IDENTIFIER, "version": version,
                           "productName": "PrivateAgent", "mainBinaryName": "privateagent"}, "应用配置")
    require_fields(object_field(config, "bundle"), {"createUpdaterArtifacts": True, "targets": ["nsis"]}, "打包配置")
    updater = object_field(object_field(config, "plugins"), "updater")
    require_fields(updater, {"endpoints": [endpoint]}, "更新源配置")
    trusted = read_object(checked_file(TAURI_CONF, "源码 Tauri 配置"))
    require_fields(trusted, {"identifier": UNIFIED_IDENTIFIER, "version": version}, "源码配置")
    trusted_key = object_field(object_field(trusted, "plugins"), "updater").get("pubkey")
    if (not isinstance(trusted_key, str) or not trusted_key.strip()
            or paths["updater-public-key.txt"].read_text(encoding="utf-8").strip() != trusted_key
            or ("pubkey" in updater and updater["pubkey"] != trusted_key)):
        raise ValueError("构建公钥必须与源码内置公钥一致")

    release = read_object(manifest)
    require_fields(release, {"version": version}, "清单版本")
    check_timestamp(release.get("pub_date"))
    if "notes" in release and not isinstance(release["notes"], str):
        raise ValueError("更新说明必须为字符串")
    platforms = object_field(release, "platforms")
    if set(platforms) != {UNIFIED_TARGET} or "url" in release or "signature" in release:
        raise ValueError("正式清单只能包含 unified Windows 静态目标")
    sig_text = signature.read_text(encoding="utf-8").strip()
    if not sig_text:
        raise ValueError("更新签名不能为空")
    require_fields(object_field(platforms, UNIFIED_TARGET), {
        "url": github_download_url(repo, tag, installer.name), "signature": sig_text,
    }, "清单资产")

    # 复用原有客户端、宿主和源码清单核对，再补充发布资产与执行器摘要。
    build_manifest(bundle, installer)
    expected_files = {name: paths[name] for name in ("PrivateAgent-windows-x64.exe", "private-agent-local.exe", "exec-host.exe")}
    expected_files.update({f"publish/{version}/{installer.name}": installer,
                           f"publish/{version}/{signature.name}": signature, "publish/latest.json": manifest})
    sums = {}
    for line in paths["SHA256SUMS.txt"].read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None or match[2] in sums:
            raise ValueError("SHA256SUMS 格式无效或包含重复文件")
        sums[match[2]] = match[1]
    if set(sums) != set(expected_files) or any(sha256(path) != sums[name] for name, path in expected_files.items()):
        raise ValueError("发布资产或执行器摘要与 SHA256SUMS 不一致")
    snapshots = {path: sha256(path) for path in {*paths.values(), installer, signature, manifest, TAURI_CONF}}
    verify_signature(installer, signature, paths["updater-public-key.txt"], verifier)
    if any(sha256(path) != digest for path, digest in snapshots.items()):
        raise ValueError("验签期间发布输入发生变化，必须重新核验")
    return {
        "version": version, "repo": repo, "tag": tag, "target": UNIFIED_TARGET, "commit": commit,
        "sourceSha256": info["sourceSha256"], "updaterSignatureVerified": True,
        "authenticode": "not_verified", "checkedAt": datetime.now(timezone.utc).isoformat(),
        "artifacts": [{"name": path.name, "bytes": path.stat().st_size, "sha256": snapshots[path]}
                      for path in (installer, signature, manifest)],
        "limitations": ["未验证 Windows Authenticode、GitHub 在线下载、安装升级及真实模型调用"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True, help="本次正式构建目录")
    parser.add_argument("--installer", type=Path, required=True, help="最终安装器，旁边必须存在同名 .sig")
    parser.add_argument("--manifest", type=Path, required=True, help="对应的 latest.json")
    parser.add_argument("--repo", required=True, help="GitHub owner/repo")
    parser.add_argument("--verifier", type=Path, help="已编译的项目 Rust 验签器；省略则使用离线 Cargo")
    args = parser.parse_args(argv)
    try:
        evidence = verify_release(args.bundle, args.installer, args.manifest, args.repo, args.verifier)
    except (OSError, UnicodeError, KeyError, TypeError) as error:
        parser.error(f"发布验收输入无法读取或结构无效（{type(error).__name__}）")
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
