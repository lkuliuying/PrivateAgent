"""S1-T8 门禁：protocol schema/codegen 骨架与 agent_v2 依赖方向。

覆盖上位计划 §8.5（单一事实源、零 diff、P0 清单完整）与
§6.1/§3.3 目标指标 2（Agent Core 不依赖传输/ORM/Provider 实现）。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def codegen():
    return _load_module("protocol_codegen", PROJECT_ROOT / "scripts" / "protocol_codegen.py")


@pytest.fixture(scope="module")
def import_checker():
    return _load_module(
        "check_agent_v2_imports", PROJECT_ROOT / "scripts" / "check_agent_v2_imports.py"
    )


@pytest.fixture(scope="module")
def schema():
    path = (
        PROJECT_ROOT
        / "src"
        / "personal_assistant"
        / "agent_v2"
        / "protocol"
        / "schema"
        / "agent_protocol.schema.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_schema_covers_p0_methods(schema: dict) -> None:
    """上位计划 §8.2 的 17 个 P0 方法必须全部在 schema 中。"""
    expected = {
        "initialize", "server/capabilities",
        "thread/start", "thread/resume", "thread/read", "thread/list",
        "thread/archive", "thread/name/set",
        "turn/start", "turn/steer", "turn/interrupt", "turn/read", "turn/items/list",
        "approval/resolve", "execution/output/read", "execution/unknown/resolve",
        "context/compact",
    }
    actual = {method["name"] for method in schema["methods"]}
    assert actual == expected


def test_schema_covers_p0_notifications(schema: dict) -> None:
    """上位计划 §8.3 的 11 个 P0 通知必须全部在 schema 中。"""
    expected = {
        "thread/started", "thread/status/changed",
        "turn/started", "turn/status/changed",
        "item/started", "item/delta", "item/completed", "item/failed",
        "approval/required", "turn/completed", "server/overloaded",
    }
    assert set(schema["notifications"]) == expected


def test_schema_covers_p0_item_kinds(schema: dict) -> None:
    """上位计划 §7.4 的 15 种 P0 Item kind。"""
    assert len(schema["domain"]["item_kinds"]) == 15
    assert "patch_set" in schema["domain"]["item_kinds"]
    assert "context_compaction" in schema["domain"]["item_kinds"]


def test_error_envelope_fixed_five_fields(schema: dict) -> None:
    """上位计划 §8.4-6：错误信封固定五字段。"""
    assert schema["envelopes"]["error"] == [
        "code", "message", "retryable", "details", "trace_id"
    ]


def test_notification_envelope_required_fields(schema: dict) -> None:
    """上位计划 §8.4-2：每个通知必带四字段。"""
    assert schema["envelopes"]["notification_envelope_required"] == [
        "thread_id", "turn_id", "sequence", "schema_version"
    ]


def test_codegen_zero_diff(codegen) -> None:
    """§8.5：生成物必须与仓库内产物一致（零 diff），否则视为手改漂移。"""
    artifacts = codegen.generate()
    drifted = []
    for path_text, content in artifacts.items():
        path = Path(path_text)
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing != content:
            drifted.append(path_text)
    assert not drifted, f"codegen drift: {drifted}（运行 scripts/protocol_codegen.py）"


def test_generated_python_importable_and_consistent(codegen) -> None:
    """生成的 Python 契约可导入，且注册表与 schema 一致。"""
    models = _load_module("agent_v2_generated_models", codegen.PY_OUT)
    assert models.METHOD_NAMES == {m["name"] for m in codegen.load_schema()["methods"]}
    assert models.NOTIFICATION_TYPES == set(codegen.load_schema()["notifications"])
    assert len(models.ITEM_KINDS) == 15
    assert "turn/start" in models.IDEMPOTENT_KEY_METHODS
    # 错误信封五字段可实例化
    err = models.JsonRpcError(
        code=-32003, message="server_overloaded", retryable=True,
        details="queue saturated", trace_id="t-1",
    )
    assert err.retryable is True


def test_dependency_rules_pass(import_checker) -> None:
    """§6.1：依赖方向与实现依赖禁令当前必须零违规。"""
    assert import_checker.check() == []


def test_dependency_rules_detect_forbidden_import(
    import_checker, tmp_path: Path, monkeypatch
) -> None:
    """反向用例：domain 导入 fastapi 必须被检出（防止检查器空转）。"""
    agent_v2 = tmp_path / "agent_v2"
    (agent_v2 / "domain").mkdir(parents=True)
    (agent_v2 / "domain" / "bad.py").write_text("import fastapi\n", encoding="utf-8")
    monkeypatch.setattr(import_checker, "AGENT_V2", agent_v2)
    violations = import_checker.check()
    assert any("fastapi" in v for v in violations)
