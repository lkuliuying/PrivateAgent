#!/usr/bin/env python3
"""在服务器核对上传包，保留旧版本并最后原子切换更新清单。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

TARGET = "unified-windows-x86_64"


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read_json(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("JSON 包含重复字段")
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError("发布 JSON 必须为有效的 UTF-8 文档") from error
    if not isinstance(value, dict):
        raise ValueError("JSON 必须为对象")
    return value


def regular(path: Path) -> None:
    if not path.is_file() or path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("上传文件必须为普通文件，路径不能含符号链接")


def validate_package(package: Path) -> tuple[dict, dict[str, str]]:
    regular(package / "SHA256SUMS")
    regular(package / "mirror-verification.json")
    record = read_json(package / "mirror-verification.json")
    version = record.get("version")
    domain = record.get("domain")
    if (not isinstance(version, str) or re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version) is None
            or not isinstance(domain, str) or len(domain) > 253
            or "." not in domain or re.fullmatch(r"[a-z0-9.-]+", domain) is None
            or any(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
                   for label in domain.split("."))
            or record.get("target") != TARGET or record.get("updaterSignatureVerified") is not True):
        raise ValueError("镜像记录缺少有效版本、域名、安装目标或本机验签结果")
    name = f"PrivateAgent_{version}_x64-setup.exe"
    expected = {f"site/{version}/{name}", f"site/{version}/{name}.sig", "site/latest.json", "DOMAIN",
                "privateagent-download.conf", "setup-download-source.sh", "publish_download_source.py",
                "updater-public-key.txt", "mirror-verification.json"}
    sums = {}
    for line in (package / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None or match[2] not in expected or match[2] in sums:
            raise ValueError("摘要清单包含未知路径、重复路径或无效摘要")
        sums[match[2]] = match[1]
    if set(sums) != expected:
        raise ValueError("摘要清单缺少必要上传文件")
    if ({path.name for path in (package / "site" / version).iterdir()} != {name, name + ".sig"}
            or {path.name for path in (package / "site").iterdir()} != {version, "latest.json"}):
        raise ValueError("站点目录包含未核验的额外文件，拒绝发布")
    for filename, expected_hash in sums.items():
        path = package / filename
        regular(path)
        if digest(path) != expected_hash:
            raise ValueError("上传文件的 SHA-256 不匹配")
    manifest = read_json(package / "site/latest.json")
    platforms = manifest.get("platforms")
    if not isinstance(platforms, dict) or set(platforms) != {TARGET}:
        raise ValueError("镜像清单必须为 unified Windows 静态目标")
    target = platforms[TARGET]
    url = f"https://{domain}/{version}/{name}"
    if (manifest.get("version") != version or "url" in manifest or "signature" in manifest
            or not isinstance(target, dict) or target.get("url") != url
            or target.get("signature") != (package / f"site/{version}/{name}.sig").read_text(encoding="utf-8").strip()
            or (package / "DOMAIN").read_text(encoding="ascii").strip() != domain):
        raise ValueError("镜像清单与上传资产、域名或签名不一致")
    return manifest, sums


def publish(package: Path, destination: Path) -> None:
    package = package.absolute()
    manifest, sums = validate_package(package)
    version = manifest["version"]
    name = f"PrivateAgent_{version}_x64-setup.exe"
    destination = destination.absolute()
    if destination.is_symlink() or any(parent.is_symlink() for parent in destination.parents):
        raise ValueError("站点目录不能含符号链接")
    lock = destination.with_name(destination.name + ".publish-lock")
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise ValueError("发布锁已存在；请确认没有其他发布进程后再人工处理") from error
    try:
        destination.mkdir(exist_ok=True)
        current = destination / "latest.json"
        if current.exists() or current.is_symlink():
            regular(current)
            previous = read_json(current)
            previous_version = previous.get("version")
            if not isinstance(previous_version, str) or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", previous_version) is None:
                raise ValueError("已有清单版本无效，拒绝自动替换")
            if tuple(map(int, version.split("."))) < tuple(map(int, previous_version.split("."))):
                raise ValueError("拒绝将更新清单降级到旧版本")
            if version == previous_version and manifest != previous:
                raise ValueError("同版本清单内容不同，拒绝覆盖")
        published = destination / version
        with tempfile.TemporaryDirectory(prefix=".privateagent-stage-", dir=destination.parent) as temp:
            staging = Path(temp)
            staged_assets = staging / version
            staged_assets.mkdir()
            for filename in (name, name + ".sig"):
                shutil.copyfile(package / "site" / version / filename, staged_assets / filename)
            staged_manifest = staging / "latest.json"
            shutil.copyfile(package / "site/latest.json", staged_manifest)
            # 复核实际就位的副本，避免源文件在复制期间变化。
            for path, filename in ((staged_assets / name, f"site/{version}/{name}"),
                                   (staged_assets / (name + ".sig"), f"site/{version}/{name}.sig"),
                                   (staged_manifest, "site/latest.json")):
                if digest(path) != sums[filename]:
                    raise ValueError("复制期间上传文件发生变化，已停止发布")
                path.chmod(0o644)
            staged_assets.chmod(0o755)
            destination.chmod(0o755)
            if published.exists() or published.is_symlink():
                if published.is_symlink() or not published.is_dir():
                    raise ValueError("已有版本路径不是普通目录")
                for filename in (name, name + ".sig"):
                    regular(published / filename)
                    if digest(published / filename) != sums[f"site/{version}/{filename}"]:
                        raise ValueError("同版本安装包或签名内容不同，拒绝覆盖")
            else:
                staged_assets.rename(published)
            # 清单替换失败时，旧清单仍可用；完整版本目录可供下次重试复用。
            os.replace(staged_manifest, current)
    finally:
        lock.rmdir()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="通过 SSH/SFTP 上传的完整下载站包")
    args = parser.parse_args(argv)
    if os.name != "posix" or os.geteuid() != 0:
        parser.error("请在 Ubuntu 服务器上使用 sudo python3 运行")
    try:
        publish(args.package, Path("/srv/privateagent-download"))
    except (OSError, KeyError, TypeError, UnicodeError):
        parser.error("发布失败；请核对上传摘要、清单、旧版本及发布锁，原始异常未输出")
    except ValueError as error:
        parser.error(str(error))
    print("发布完成；请继续验收公网 HTTPS、缓存头和完整安装包下载。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
