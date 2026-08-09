"""第八阶段 M6 测试：性能基线阈值与报告逻辑。

覆盖（对齐 docs/archive/phases/phase8-plan.md §M6 / docs/archive/phases/phase8-requirements.md §5.6）：
- check_thresholds：ok / warning / blocker 分类正确。
- write_report：输出 JSON + Markdown，含关键路径与阈值状态。
- THRESHOLDS 覆盖 Today / 搜索 / 诊断 / 完整性 / 备份。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import measure_perf_baseline as mp  # noqa: E402


def test_thresholds_cover_key_paths():
    for path in ("today", "search", "diagnostics", "integrity", "backup_export"):
        assert path in mp.THRESHOLDS
        assert mp.THRESHOLDS[path]["warning_ms"] < mp.THRESHOLDS[path]["blocker_ms"]


def test_check_thresholds_all_ok():
    th = mp.check_thresholds(
        {"today": 100, "search": 200, "diagnostics": 500, "integrity": 1000, "backup_export": 2000}
    )
    assert th["blockers"] == []
    assert th["warnings"] == []


def test_check_thresholds_warning_and_blocker():
    th = mp.check_thresholds({"today": 600, "search": 4000})
    # today 600 >= 500 warning 且 < 2000 -> warning
    assert any(w["path"] == "today" for w in th["warnings"])
    assert not any(b["path"] == "today" for b in th["blockers"])
    # search 4000 >= 3000 blocker
    assert any(b["path"] == "search" for b in th["blockers"])


def test_write_report_produces_json_and_md(tmp_path):
    results = {
        "generated_at": "2026-07-09T00:00:00Z",
        "sample_counts": {"messages": 10},
        "thresholds": mp.THRESHOLDS,
        "timings": {
            "today": 100,
            "search": 200,
            "diagnostics": 500,
            "integrity": 1000,
            "backup_export": 2000,
        },
        "warnings": [],
        "blockers": [],
        "hotspots": mp.HOTSPOTS,
    }
    json_path, md_path = mp.write_report(results, tmp_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["timings"]["today"] == 100
    assert data["hotspots"] == mp.HOTSPOTS
    md = md_path.read_text(encoding="utf-8")
    assert "性能基线报告" in md
    assert "today" in md
    assert "blocker" in md
    assert "已识别热点" in md
    assert "diagnostics" in md


def test_hotspots_document_optimization_and_followup():
    """热点记录含已优化与后续方案（对齐 phase8-plan §M6）。"""
    assert len(mp.HOTSPOTS) >= 1
    hs = mp.HOTSPOTS[0]
    assert hs["path"] == "diagnostics"
    assert hs["optimization_done"]
    assert hs["follow_up"]
