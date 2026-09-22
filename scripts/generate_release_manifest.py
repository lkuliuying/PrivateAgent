#!/usr/bin/env python3
"""从明确指定的本机桌面构建目录生成产物清单，不推断测试、签名或安装验收通过。"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_manifest(bundle: Path, installer: Path | None = None) -> tuple[str, str]:
    bundle = bundle.resolve(strict=True)
    info = json.loads((bundle / "build-info.json").read_text(encoding="utf-8"))
    if info.get("accessMode") != "api-key" or info.get("sidecar") != "desktop-local" or info.get("transport") != "stdio-v2":
        raise ValueError("仅接受 API Key 本机执行器的构建目录")
    version = info.get("version")
    if not isinstance(version, str) or not version or any(char not in "0123456789." for char in version):
        raise ValueError("构建版本无效")
    source = json.loads((bundle / "source-manifest.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(json.dumps(source["sources"], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    if digest != source.get("sourceSha256") or digest != info.get("sourceSha256"):
        raise ValueError("源码清单与构建记录不一致")
    client = "PrivateAgent-windows-x64.exe" if info.get("unified") else "PrivateAgent-remote-windows-x64.exe"
    artifacts = [bundle / name for name in (client, "private-agent-local.exe", "exec-host.exe", "exec-host.sha256", "source-manifest.json", "build-info.json")]
    if any(not path.is_file() or path.is_symlink() for path in artifacts):
        raise ValueError("本机桌面构建产物缺失或为符号链接")
    if sha256(bundle / client) != info.get("sha256"):
        raise ValueError("桌面程序与构建记录不一致")
    host_hash = sha256(bundle / "exec-host.exe")
    if host_hash != info.get("executionHostSha256") or host_hash != (bundle / "exec-host.sha256").read_text(encoding="utf-8").strip():
        raise ValueError("执行宿主完整性记录不一致")
    if installer is not None:
        installer = installer.resolve(strict=True)
        if not installer.name.endswith("-setup.exe") or f"_{version}_" not in installer.name:
            raise ValueError("安装包名称与构建版本不一致")
        artifacts.append(installer)
        signature = installer.with_name(installer.name + ".sig")
        if signature.is_file():
            artifacts.append(signature)
    lines = [f"# 本机桌面构建清单 {version}", "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}", f"- 构建提交：{info.get('commit', '未知')}",
        f"- 未提交改动：{info.get('dirty', '未知')}", f"- 构建模式：{info.get('mode', '未知')}",
        "- 运行方式：API Key 直连供应商，stdio-v2 本机执行器", f"- 源码摘要：`{digest}`", "",
        "## 产物", "", "| 文件 | 字节 | SHA-256 |", "| --- | ---: | --- |"]
    lines.extend(f"| {path.name} | {path.stat().st_size} | `{sha256(path)}` |" for path in artifacts)
    lines += ["", "## 验证边界", "",
        "本清单核对文件存在性、客户端和执行宿主摘要、源码清单一致性。",
        "文件存在和签名文件存在不等于签名验证通过；本清单不声明单元测试、干净安装、升级或真实模型验收通过。",
        "签名、安装和测试结果应另附对应本次产物的实际验证记录。", ""]
    return version, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True, help="包含 build-info.json 的本次构建目录")
    parser.add_argument("--installer", type=Path, help="需要附入清单的同版本安装包")
    parser.add_argument("--write", action="store_true", help="写入 dist/release-manifest-<version>.md")
    parser.add_argument("--out", type=Path, help="明确的输出文件")
    args = parser.parse_args()
    try:
        version, text = build_manifest(args.bundle, args.installer)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(f"构建清单验证失败：{error}")
    output = args.out or (ROOT / "dist" / f"release-manifest-{version}.md" if args.write else None)
    if output is None:
        print(text)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        print(f"[manifest] written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
