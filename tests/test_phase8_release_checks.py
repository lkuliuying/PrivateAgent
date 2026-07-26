"""第八阶段 M2 测试：发布检查 2.0 证据管线逻辑。

覆盖（对齐 docs/phase8-plan.md §M2 / docs/phase8-requirements.md §5.2）：
- assemble_report：passed/failed/skipped 汇总 + ok 判定。
- write_report：输出 JSON + Markdown。
- validate_latest_json：合法 / 缺失（skipped）/ 签名空（failed）。
- npm_script_exists / resolve_executable：脚本探测与跨平台命令解析。
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import run_release_checks as rc  # noqa: E402

CURRENT_VERSION = rc.read_version()


def test_assemble_report_ok():
    steps = [
        {"name": "a", "status": "passed", "duration_ms": 1, "detail": ""},
        {"name": "b", "status": "skipped", "duration_ms": 0, "detail": ""},
    ]
    rep = rc.assemble_report(steps, "0.1.1")
    assert rep["ok"] is True
    assert rep["summary"] == {"passed": 1, "failed": 0, "skipped": 1}


def test_assemble_report_failed():
    steps = [
        {"name": "a", "status": "passed", "duration_ms": 1, "detail": ""},
        {"name": "b", "status": "failed", "duration_ms": 1, "detail": "boom"},
    ]
    rep = rc.assemble_report(steps, "0.1.1")
    assert rep["ok"] is False
    assert rep["summary"]["failed"] == 1


def test_required_skipped_step_blocks_release():
    rep = rc.assemble_report(
        [rc.skipped_step("required_tool", "missing", required=True)],
        "0.1.1",
    )

    assert rep["ok"] is False
    assert rep["blocking_skipped"] == ["required_tool"]


def test_optional_skipped_step_does_not_block_release():
    rep = rc.assemble_report(
        [rc.skipped_step("optional_artifact", "missing")],
        "0.1.1",
    )

    assert rep["ok"] is True
    assert rep["blocking_skipped"] == []


def test_write_report(tmp_path):
    rep = rc.assemble_report(
        [
            {"name": "pytest", "status": "passed", "duration_ms": 12.3, "detail": "ok"},
            {"name": "npm_e2e", "status": "skipped", "duration_ms": 0, "detail": "M1 未接入"},
        ],
        "0.1.1",
    )
    jp, mp = rc.write_report(rep, tmp_path)
    data = json.loads(jp.read_text(encoding="utf-8"))
    assert data["ok"] is True
    md = mp.read_text(encoding="utf-8")
    assert "Release Check" in md
    assert "pytest" in md and "passed" in md


def test_validate_latest_json_missing(tmp_path):
    res = rc.validate_latest_json(tmp_path)
    assert res["status"] == "skipped"


def test_validate_latest_json_valid(tmp_path):
    (tmp_path / "latest.json").write_text(
        json.dumps(
            {
                "version": CURRENT_VERSION,
                "platforms": {
                    "windows-x86_64": {"signature": "sig", "url": "http://x/y.exe"},
                },
            }
        ),
        encoding="utf-8",
    )
    res = rc.validate_latest_json(tmp_path)
    assert res["status"] == "passed"


def test_validate_latest_json_bad_signature(tmp_path):
    (tmp_path / "latest.json").write_text(
        json.dumps(
            {
                "version": CURRENT_VERSION,
                "platforms": {"windows-x86_64": {"signature": "", "url": "http://x/y.exe"}},
            }
        ),
        encoding="utf-8",
    )
    res = rc.validate_latest_json(tmp_path)
    assert res["status"] == "failed"
    assert "signature" in res["detail"]


def test_validate_latest_json_version_mismatch(tmp_path):
    (tmp_path / "latest.json").write_text(
        json.dumps(
            {
                "version": "9.9.9",
                "platforms": {"windows-x86_64": {"signature": "sig", "url": "http://x/y.exe"}},
            }
        ),
        encoding="utf-8",
    )
    res = rc.validate_latest_json(tmp_path)
    assert res["status"] == "failed"
    assert "version" in res["detail"]


def test_npm_script_exists():
    assert rc.npm_script_exists("build") is True
    assert rc.npm_script_exists("nonexistent_script_xyz") is False


def test_resolve_executable_supports_windows_cmd_shims(monkeypatch):
    expected = "npm.cmd" if rc.os.name == "nt" else "npm"
    monkeypatch.setattr(
        rc.shutil,
        "which",
        lambda candidate: f"resolved/{candidate}" if candidate == expected else None,
    )
    assert rc.resolve_executable("npm") == f"resolved/{expected}"


def test_python_module_command_uses_active_interpreter():
    assert rc.python_module_command("pytest", "-q") == [sys.executable, "-m", "pytest", "-q"]


def test_zip_members_containing_scans_decompressed_payloads(tmp_path):
    archive_path = tmp_path / "diagnostics.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("safe.json", '{"status":"ok"}')
        archive.writestr("nested/leak.txt", "prefix sk-unit-test-secret suffix")

    assert rc.zip_members_containing(archive_path, b"sk-unit-test-secret") == [
        "nested/leak.txt"
    ]


def test_tauri_csp_protects_memory_only_api_credentials():
    config_path = Path(__file__).resolve().parent.parent / "apps" / "desktop" / "src-tauri" / "tauri.conf.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    security = config["app"]["security"]
    production_csp = security["csp"]
    development_csp = security["devCsp"]

    for csp in (production_csp, development_csp):
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "object-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "http://127.0.0.1:*" in csp
        assert "*" not in csp.replace("127.0.0.1:*", "").replace("localhost:*", "")

    assert "unsafe-eval" not in development_csp
