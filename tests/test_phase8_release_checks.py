"""第八阶段 M2 测试：发布检查 2.0 证据管线逻辑。

覆盖（对齐 docs/phase8-plan.md §M2 / docs/phase8-requirements.md §5.2）：
- assemble_report：passed/failed/skipped 汇总 + ok 判定。
- write_report：输出 JSON + Markdown。
- validate_latest_json：合法 / 缺失（skipped）/ 签名空（failed）。
- npm_script_exists：package.json 脚本探测。
"""
from __future__ import annotations

import json
import sys
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
