#!/usr/bin/env python3
"""第八阶段 M4：Windows 代码签名（Authenticode）编排。

签名顺序（docs/signing-and-keys.md §2.4，必须遵守，否则 updater 拒绝更新）：
1. tauri build -> NSIS exe + .sig（.sig 覆盖未签名字节）
2. signtool sign（Authenticode，改写字节）
3. signtool verify /pa /v
4. 重新生成 .sig（覆盖已签名字节）：npx tauri signer sign -f <installer>
5. generate-latest-json.py（读最终 .sig）

证书配置（环境变量，不入库）：
- PA_CODESIGN_PFX：.pfx/.p12 证书路径
- PA_CODESIGN_PASSWORD：证书密码（或 PA_CODESIGN_PASSWORD_FILE 指向密码文件）
- PA_CODESIGN_TIMESTAMP：时间戳服务器（默认 http://timestamp.digicert.com）

无证书：不阻塞构建，写 dist/unsigned-note-<version>.md（SmartScreen 风险说明）+
dist/codesign-status-<version>.json（code_signed: false），供 release manifest 读取。

SignPath / 外部签名：CI 将 SignPath 返回的安装包复制回标准产物目录后，调用
``--verify-existing --provider SignPath``。脚本使用 Windows Authenticode API 验证
签名并记录状态，但不会接触或导出代码签名私钥。

私钥/证书不入库：.gitignore 已覆盖 *.pfx *.p12 *.key *.pem 等（见 test_phase8_signing）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from _release_utils import find_installer, installer_sig, read_version  # noqa: E402

DIST = PROJECT_ROOT / "dist"
DEFAULT_TIMESTAMP = "http://timestamp.digicert.com"

# 签名顺序（文档/测试用）：先代码签名，后 updater 签名，顺序不可颠倒。
SIGNING_ORDER = [
    "tauri build -> NSIS exe + .sig (sig over UNSIGNED bytes)",
    "signtool sign (Authenticode, mutates bytes)",
    "signtool verify /pa /v",
    "re-run tauri signer sign -> regenerate .sig over SIGNED bytes",
    "generate-latest-json.py (reads final .sig)",
]


def resolve_signing_config(env: dict | None = None) -> dict:
    """从环境变量解析签名配置。

    两种签名方式：
    - PA_CODESIGN_THUMBPRINT：证书已导入 Windows 证书存储，按指纹签名（推荐，密码不进命令行）。
    - PA_CODESIGN_PFX：.pfx/.p12 文件 + 密码（密码会出现在 signtool 命令行，仅作回退）。
    has_cert=True 当 thumbprint 非空或 pfx 文件存在。
    """
    env = env or os.environ
    thumbprint = env.get("PA_CODESIGN_THUMBPRINT", "").strip()
    pfx = env.get("PA_CODESIGN_PFX", "").strip()
    pfx_exists = bool(pfx) and Path(pfx).exists()
    has_cert = bool(thumbprint) or pfx_exists
    password = env.get("PA_CODESIGN_PASSWORD", "")
    pwd_file = env.get("PA_CODESIGN_PASSWORD_FILE", "").strip()
    if not password and pwd_file and Path(pwd_file).exists():
        password = Path(pwd_file).read_text(encoding="utf-8").strip()
    timestamp = env.get("PA_CODESIGN_TIMESTAMP", "").strip() or DEFAULT_TIMESTAMP
    return {
        "has_cert": has_cert,
        "thumbprint": thumbprint or None,
        "pfx_path": pfx if pfx_exists else None,
        "password": password if has_cert else None,
        "timestamp_url": timestamp,
    }


def build_signtool_sign_command(installer, config: dict) -> list[str]:
    """构造 signtool sign 命令。

    优先用证书存储指纹（/sha1，无 /f /p，密码不暴露）；否则用 PFX（/f /p）。
    """
    if config.get("thumbprint"):
        return [
            "signtool",
            "sign",
            "/fd",
            "SHA256",
            "/sha1",
            config["thumbprint"],
            "/tr",
            config["timestamp_url"],
            "/td",
            "SHA256",
            str(installer),
        ]
    return [
        "signtool",
        "sign",
        "/fd",
        "SHA256",
        "/f",
        config["pfx_path"],
        "/p",
        config["password"] or "",
        "/tr",
        config["timestamp_url"],
        "/td",
        "SHA256",
        str(installer),
    ]


def build_signtool_verify_command(installer) -> list[str]:
    """构造 signtool verify 命令（/pa /v）。"""
    return ["signtool", "verify", "/pa", "/v", str(installer)]


def build_powershell_signature_command(installer) -> list[str]:
    """构造只读 Authenticode 验证命令，兼容没有 signtool PATH 的 CI。"""
    script = (
        "$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new(); "
        "$signature = Get-AuthenticodeSignature -LiteralPath $args[0]; "
        "$result = [ordered]@{ "
        "Status = [string]$signature.Status; "
        "StatusMessage = [string]$signature.StatusMessage; "
        "Subject = [string]$signature.SignerCertificate.Subject; "
        "Thumbprint = [string]$signature.SignerCertificate.Thumbprint }; "
        "$result | ConvertTo-Json -Compress; "
        "if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) { exit 2 }"
    )
    return [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        script,
        str(installer),
    ]


def verify_existing_signature(installer: Path) -> dict:
    """验证 SignPath 等外部服务返回的 Authenticode 签名并返回非秘密元数据。"""
    result = subprocess.run(
        build_powershell_signature_command(installer),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = result.stdout.strip()
    try:
        details = json.loads(output.splitlines()[-1]) if output else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("could not parse Authenticode verification output") from exc
    if result.returncode != 0 or details.get("Status") != "Valid":
        status = details.get("Status") or "Unknown"
        raise RuntimeError(f"Authenticode verification failed: {status}")
    return details


def unsigned_release_notes(version: str) -> str:
    """无证书时的 SmartScreen 风险说明（写入 release notes / 安装说明）。"""
    return (
        f"## PrivateAgent v{version} 安装说明（未代码签名）\n\n"
        "本安装包未经过 Windows Authenticode 代码签名。首次运行时 Windows SmartScreen\n"
        "可能提示「Windows 已保护你的电脑」并阻止安装。绕过方式：点击「更多信息」->\n"
        "「仍要运行」。这是个人/未签名发布的预期行为；安装包本身仍由 Tauri updater\n"
        "`.sig` 校验完整性（更新通道防篡改不受影响）。\n\n"
        "如需消除 SmartScreen 提示，需使用代码签名证书（OV/EV）重新发布。\n"
    )


def write_status(
    version: str,
    code_signed: bool,
    cert_subject: str | None = None,
    provider: str | None = None,
) -> Path:
    """写 dist/codesign-status-<version>.json，供 generate_release_manifest.py 读取。"""
    DIST.mkdir(parents=True, exist_ok=True)
    path = DIST / f"codesign-status-{version}.json"
    path.write_text(
        json.dumps(
            {
                "version": version,
                "code_signed": code_signed,
                "cert_subject": cert_subject,
                "provider": provider,
                "timestamp_server": (
                    DEFAULT_TIMESTAMP if provider in (None, "local") else None
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def write_unsigned_note(version: str) -> Path:
    DIST.mkdir(parents=True, exist_ok=True)
    path = DIST / f"unsigned-note-{version}.md"
    path.write_text(unsigned_release_notes(version), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--installer", help="installer path (default: auto-detect by version)")
    ap.add_argument(
        "--verify-existing",
        action="store_true",
        help="verify an installer already signed by SignPath or another external service",
    )
    ap.add_argument(
        "--provider",
        default="external",
        help="signing provider recorded with --verify-existing (default: external)",
    )
    args = ap.parse_args()

    version = read_version()
    config = resolve_signing_config()
    installer = Path(args.installer) if args.installer else find_installer(version)

    if args.verify_existing:
        try:
            details = verify_existing_signature(installer)
        except RuntimeError as exc:
            print(f"[sign] {exc}")
            write_status(
                version,
                code_signed=False,
                cert_subject="(external signature verification failed)",
                provider=args.provider,
            )
            return 1
        status = write_status(
            version,
            code_signed=True,
            cert_subject=details.get("Subject") or "(subject unavailable)",
            provider=args.provider,
        )
        print(f"[sign] existing Authenticode signature verified ({args.provider})")
        print(f"[sign] status: {status}")
        return 0

    if not config["has_cert"]:
        note = write_unsigned_note(version)
        status = write_status(version, code_signed=False, provider=None)
        print("[sign] no certificate (PA_CODESIGN_PFX not set/missing); installer left UNSIGNED")
        print(f"[sign] SmartScreen note: {note}")
        print(f"[sign] status: {status}")
        return 0

    # 有证书：signtool sign -> verify -> 重新生成 .sig（顺序见 SIGNING_ORDER）。
    print(f"[sign] signing {installer} with {config['pfx_path']}")
    r = subprocess.run(build_signtool_sign_command(installer, config))
    if r.returncode != 0:
        print("[sign] signtool sign FAILED")
        write_status(version, code_signed=False, cert_subject="(sign failed)", provider="local")
        return 1
    r = subprocess.run(build_signtool_verify_command(installer))
    if r.returncode != 0:
        print("[sign] signtool verify FAILED")
        write_status(version, code_signed=False, cert_subject="(verify failed)", provider="local")
        return 1
    # 重新生成 .sig（覆盖已签名字节）。updater 私钥由 build-release.bat 注入 env
    # （TAURI_SIGNING_PRIVATE_KEY / _PASSWORD），tauri signer sign 自动读取。
    sig = installer_sig(installer)
    r = subprocess.run(
        ["npx", "tauri", "signer", "sign", "-f", str(installer)],
        cwd=str(PROJECT_ROOT / "apps" / "desktop"),
    )
    if r.returncode != 0:
        print("[sign] tauri signer sign (.sig regeneration) FAILED")
        return 1
    write_status(version, code_signed=True, cert_subject="(signed)", provider="local")
    print(f"[sign] OK; .sig regenerated over signed bytes: {sig}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
