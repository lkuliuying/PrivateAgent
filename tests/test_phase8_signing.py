"""第八阶段 M4 测试：代码签名编排与 unsigned 透明策略。

覆盖（对齐 docs/phase8-plan.md §M4 / docs/phase8-requirements.md §5.4/§9）：
- resolve_signing_config：无证书 / 有证书 / 密码文件 / 证书缺失。
- signtool sign / verify 命令构造（/fd SHA256 /tr /td /pa /v）。
- 无证书 SmartScreen 说明。
- 签名顺序：Authenticode 在 updater .sig 重新生成之前。
- 私钥/证书不入库：.gitignore 覆盖证书与密钥扩展名。
- write_status 输出 code_signed 状态。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import sign_installer as si  # noqa: E402


def test_resolve_signing_config_no_cert():
    cfg = si.resolve_signing_config({})
    assert cfg["has_cert"] is False
    assert cfg["pfx_path"] is None
    assert cfg["timestamp_url"] == si.DEFAULT_TIMESTAMP


def test_resolve_signing_config_with_cert(tmp_path):
    pfx = tmp_path / "cert.pfx"
    pfx.write_bytes(b"fake")
    cfg = si.resolve_signing_config(
        {"PA_CODESIGN_PFX": str(pfx), "PA_CODESIGN_PASSWORD": "secret"}
    )
    assert cfg["has_cert"] is True
    assert cfg["pfx_path"] == str(pfx)
    assert cfg["password"] == "secret"


def test_resolve_signing_config_password_from_file(tmp_path):
    pfx = tmp_path / "cert.pfx"
    pfx.write_bytes(b"fake")
    pwd = tmp_path / "pwd.txt"
    pwd.write_text("filepassword", encoding="utf-8")
    cfg = si.resolve_signing_config(
        {"PA_CODESIGN_PFX": str(pfx), "PA_CODESIGN_PASSWORD_FILE": str(pwd)}
    )
    assert cfg["password"] == "filepassword"


def test_resolve_signing_config_pfx_missing(tmp_path):
    """PA_CODESIGN_PFX 指向不存在的文件 -> 视为无证书（不阻塞，走 unsigned）。"""
    cfg = si.resolve_signing_config({"PA_CODESIGN_PFX": str(tmp_path / "nope.pfx")})
    assert cfg["has_cert"] is False


def test_build_signtool_sign_command():
    cfg = {"pfx_path": "C:/cert.pfx", "password": "pw", "timestamp_url": "http://ts"}
    cmd = si.build_signtool_sign_command("installer.exe", cfg)
    assert cmd[0] == "signtool" and cmd[1] == "sign"
    assert "/fd" in cmd and "SHA256" in cmd
    assert "/f" in cmd and "C:/cert.pfx" in cmd
    assert "/p" in cmd and "pw" in cmd
    assert "/tr" in cmd and "http://ts" in cmd
    assert "/td" in cmd
    assert cmd[-1] == "installer.exe"


def test_build_signtool_sign_command_thumbprint():
    """证书存储指纹模式：/sha1 签名，无 /f /p（密码不进命令行）。"""
    cfg = {"thumbprint": "ABC123", "pfx_path": None, "password": None, "timestamp_url": "http://ts"}
    cmd = si.build_signtool_sign_command("installer.exe", cfg)
    assert "/sha1" in cmd and "ABC123" in cmd
    assert "/f" not in cmd and "/p" not in cmd  # 不暴露证书文件/密码
    assert cmd[-1] == "installer.exe"


def test_resolve_signing_config_thumbprint():
    """PA_CODESIGN_THUMBPRINT -> has_cert True，无需 PFX。"""
    cfg = si.resolve_signing_config({"PA_CODESIGN_THUMBPRINT": "deadbeef"})
    assert cfg["has_cert"] is True
    assert cfg["thumbprint"] == "deadbeef"
    assert cfg["pfx_path"] is None


def test_build_signtool_verify_command():
    cmd = si.build_signtool_verify_command("installer.exe")
    assert cmd == ["signtool", "verify", "/pa", "/v", "installer.exe"]


def test_unsigned_release_notes_mentions_smartscreen():
    note = si.unsigned_release_notes("0.1.1")
    assert "SmartScreen" in note
    assert "0.1.1" in note
    assert "仍要运行" in note


def test_signing_order_sign_before_updater_sig():
    """代码签名必须在 updater .sig 重新生成之前（顺序不可颠倒，否则 updater 拒绝）。"""
    sign_idx = si.SIGNING_ORDER.index("signtool sign (Authenticode, mutates bytes)")
    resign_idx = si.SIGNING_ORDER.index(
        "re-run tauri signer sign -> regenerate .sig over SIGNED bytes"
    )
    assert sign_idx < resign_idx


def test_write_status(tmp_path, monkeypatch):
    monkeypatch.setattr(si, "DIST", tmp_path)
    p = si.write_status("0.1.1", code_signed=False)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["code_signed"] is False
    assert data["version"] == "0.1.1"


def test_gitignore_covers_cert_and_key_files():
    """私钥/证书不入库：.gitignore 覆盖证书与密钥扩展名与 .tauri/。"""
    gi = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    for pat in ("*.pfx", "*.p12", "*.key", "*.pem", ".tauri/"):
        assert pat in gi, f".gitignore 缺少 {pat}"
