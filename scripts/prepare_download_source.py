#!/usr/bin/env python3
"""将已公开的正式资产转换为经过公钥复验的静态下载站上传包。"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from pathlib import Path

from _release_utils import (
    TAURI_CONF,
    UNIFIED_IDENTIFIER,
    UNIFIED_TARGET,
    github_download_url,
    github_release_tag,
    unified_installer_name,
    validate_stable_version,
)
from generate_release_manifest import sha256
from verify_update_release import (
    check_timestamp,
    checked_file,
    object_field,
    read_object,
    verify_signature,
)

ROOT = Path(__file__).resolve().parents[1]
REPO = "lkuliuying/PrivateAgent"
LINUX = ROOT / "scripts/linux"


def validate_domain(value: str) -> str:
    """域名直接进入 Nginx 配置，只允许规范的 ASCII DNS 名称。"""
    if (not isinstance(value, str) or len(value) > 253 or value != value.lower()
            or "." not in value or value.endswith(".")
            or re.fullmatch(r"[a-z0-9.-]+", value) is None):
        raise ValueError("下载域名必须为小写 ASCII DNS 名称，不能包含 URL、端口或其他参数")
    if any(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
           for label in value.split(".")) or value.split(".")[-1].isdigit():
        raise ValueError("下载域名格式无效")
    if any(value == example or value.endswith("." + example)
           for example in ("example.com", "example.net", "example.org", "example", "localhost", "invalid", "test", "local")):
        raise ValueError("必须使用实际下载域名，不能使用示例地址")
    return value


def source_assets(source: Path) -> tuple[dict, dict, dict[str, Path]]:
    source = source.resolve(strict=True)
    manifest = read_object(checked_file(source / "latest.json", "正式更新清单", source))
    version = validate_stable_version(manifest.get("version"))
    name = unified_installer_name(version)
    record = read_object(checked_file(source / f"release-verification-{version}.json", "发布验收记录", source))
    if (record.get("version") != version or record.get("repo") != REPO
            or record.get("tag") != github_release_tag(version) or record.get("target") != UNIFIED_TARGET
            or record.get("updaterSignatureVerified") is not True):
        raise ValueError("发布验收记录与正式版本、仓库或安装目标不一致")
    entries = record.get("artifacts")
    names = {name, name + ".sig", "latest.json"}
    if (not isinstance(entries, list) or len(entries) != 3
            or any(not isinstance(item, dict) for item in entries)
            or {item.get("name") for item in entries} != names):
        raise ValueError("发布验收记录必须包含三项唯一的正式更新资产")
    paths = {filename: checked_file(source / filename, "正式更新资产", source) for filename in names}
    for entry in entries:
        path = paths[entry["name"]]
        if (type(entry.get("bytes")) is not int or entry["bytes"] <= 0
                or not isinstance(entry.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None
                or path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]):
            raise ValueError("公开资产与发布记录的大小或 SHA-256 不一致")
    check_timestamp(manifest.get("pub_date"))
    platforms = manifest.get("platforms")
    if (not isinstance(platforms, dict) or set(platforms) != {UNIFIED_TARGET}
            or not isinstance(platforms[UNIFIED_TARGET], dict)
            or "url" in manifest or "signature" in manifest):
        raise ValueError("只接受正式 unified Windows 静态清单")
    target = platforms[UNIFIED_TARGET]
    signature = paths[name + ".sig"].read_text(encoding="utf-8").strip()
    if (not signature or target.get("signature") != signature
            or target.get("url") != github_download_url(REPO, github_release_tag(version), name)):
        raise ValueError("正式清单的下载地址或签名与公开资产不一致")
    return manifest, record, paths


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def prepare(source: Path, domain: str, output: Path, verifier: Path | None = None) -> dict:
    domain = validate_domain(domain)
    manifest, record, paths = source_assets(source)
    version = manifest["version"]
    name = unified_installer_name(version)
    config = read_object(checked_file(TAURI_CONF, "客户端配置"))
    public_key = object_field(object_field(config, "plugins"), "updater").get("pubkey")
    if config.get("identifier") != UNIFIED_IDENTIFIER or not isinstance(public_key, str) or not public_key.strip():
        raise ValueError("正式客户端缺少可信更新公钥")
    output = output.absolute()
    if output.resolve().is_relative_to(source.resolve(strict=True)):
        raise ValueError("输出目录不能放在正式资产来源目录中")
    if output.exists() or output.is_symlink():
        raise ValueError("输出目录已存在，不能覆盖；请指定全新目录")
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = output.with_name(output.name + ".prepare-lock")
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise ValueError("同一输出目录正在生成或存在未处理的生成锁") from error
    try:
        with tempfile.TemporaryDirectory(prefix=".download-source-", dir=output.parent) as temp:
            package = Path(temp) / "package"
            assets = package / "site" / version
            assets.mkdir(parents=True)
            for filename in (name, name + ".sig"):
                shutil.copyfile(paths[filename], assets / filename)
            expected = {item["name"]: item for item in record["artifacts"]}
            for filename in (name, name + ".sig"):
                if sha256(assets / filename) != expected[filename]["sha256"]:
                    raise ValueError("复制期间公开资产发生变化，已拒绝生成")
            key_file = package / "updater-public-key.txt"
            key_file.write_text(public_key.strip() + "\n", encoding="utf-8", newline="\n")
            # 对将要上传的副本进行真实验签，不能仅信任验收记录中的布尔值。
            verify_signature(assets / name, assets / (name + ".sig"), key_file, verifier)
            url = f"https://{domain}/{version}/{name}"
            manifest["platforms"][UNIFIED_TARGET]["url"] = url
            write_json(package / "site/latest.json", manifest)
            (package / "DOMAIN").write_text(domain + "\n", encoding="ascii", newline="\n")
            template = (LINUX / "privateagent-download.conf.template").read_text(encoding="utf-8")
            (package / "privateagent-download.conf").write_text(
                template.replace("__DOWNLOAD_DOMAIN__", domain), encoding="utf-8", newline="\n")
            for filename in ("setup-download-source.sh", "publish_download_source.py"):
                # 发布脚本统一使用 LF，避免 Windows 检出换行影响 Linux 执行。
                (package / filename).write_text((LINUX / filename).read_text(encoding="utf-8"),
                                              encoding="utf-8", newline="\n")
            evidence = {
                "version": version, "repo": REPO, "target": UNIFIED_TARGET, "domain": domain,
                "installerUrl": url, "updaterSignatureVerified": True,
                "sourceManifestSha256": expected["latest.json"]["sha256"],
                "artifacts": [{"name": path.relative_to(package).as_posix(), "bytes": path.stat().st_size,
                               "sha256": sha256(path)} for path in (assets / name, assets / (name + ".sig"),
                                                                    package / "site/latest.json")],
                "limitations": ["未验证服务器、DNS、HTTPS、在线下载或客户端安装升级"],
            }
            write_json(package / "mirror-verification.json", evidence)
            sums = "".join(f"{sha256(path)}  {path.relative_to(package).as_posix()}\n"
                           for path in sorted(package.rglob("*")) if path.is_file())
            (package / "SHA256SUMS").write_text(sums, encoding="utf-8", newline="\n")
            if output.exists() or output.is_symlink():
                raise ValueError("输出目录在生成期间出现，已拒绝覆盖")
            package.rename(output)
    finally:
        lock.rmdir()
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="已下载的正式 GitHub 资产目录")
    parser.add_argument("--domain", required=True, help="实际下载子域名，不含协议或路径")
    parser.add_argument("--out", type=Path, required=True, help="尚不存在的上传包目录")
    parser.add_argument("--verifier", type=Path, help="已编译的现有公钥验签程序")
    args = parser.parse_args(argv)
    try:
        result = prepare(args.source, args.domain, args.out, args.verifier)
    except (OSError, KeyError, TypeError, UnicodeError):
        # 输入路径和外部工具错误可能携带敏感信息，不直接输出原始异常。
        parser.error("下载源生成失败；请核对域名、正式资产、摘要、公钥验签程序及全新输出目录")
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
