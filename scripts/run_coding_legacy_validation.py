"""隔离复跑 S1 涉及的旧服务端纯单测；不启动服务或连接任何业务数据库。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

from coding_validation_process import managed_process
from run_coding_validation import ROOT, isolated_environment, new_directory

NODES = {
    "test_agent_runtime.py": None,
    "test_agent_verification.py": [
        "json_schema_verifier_reports_parse_and_schema_failures", "composite_verifier_stops_on_first_real_failure",
        "rag_citation_verifier_accepts_only_retrieved_identity_and_exact_quote", "rag_citation_verifier_rejects_untraceable_evidence",
        "reloading_rag_verifier_uses_current_sources_and_fails_closed", "runtime_retries_rag_answer_with_fabricated_quote",
        "runtime_buffers_invalid_candidate_and_publishes_only_verified_retry", "runtime_fails_after_bounded_verification_retries_without_publishing",
    ],
    "test_result_verification.py": [
        "file_diff_preview_consistent_with_disk", "file_diff_rejects_stale_preview_after_disk_change",
        "file_diff_write_tamper_fails_readback", "file_diff_rejects_tampered_new_sha256", "file_diff_rejects_path_escape",
        "shell_success_and_failure_codes", "shell_timeout_and_cancellation_are_rejected", "shell_truncation_rejection_is_configurable",
        "code_command_whitelist_and_markers", "api_status_schema_and_retry_bounds", "database_commit_rows_and_readback",
        "workflow_completion_requires_all_trusted_conditions", "composite_verifier_runs_supported_verifiers_in_order",
    ],
    "test_v100_ct1_fake_success_gate.py": [
        "classify_message_matrix", "preview_only_clears_file_write_requirement", "model_tags_can_only_add_not_reduce",
        "zero_tool_calls_claiming_success_is_required_effect_missing", "proposal_only_is_completion_not_met_with_apply_correction",
        "unverified_write_is_side_effect_unverified", "failed_command_counts_as_evidence_but_not_as_write",
        "unknown_tool_counts_as_evidence_only", "verified_write_satisfies_contract", "contract_rejects_unknown_postcondition",
        "contract_engine_direct_evaluation_matrix", "contract_id_stable_across_rebuild_and_json_roundtrip", "no_gates_yields_no_contract",
        "preflight_blocks_when_all_write_flags_disabled", "preflight_blocks_readonly_mode_even_with_flags_on",
        "preflight_passes_when_write_tool_exposed", "preflight_reports_unsupported_model_first",
    ],
}
TEST_DB = "mysql+aiomysql://s1_fixture@127.0.0.1:9/private_agent_s1_test"


def child() -> int:
    import coding_validation_plugin
    import pytest

    directory = Path(os.environ["CODING_VALIDATION_DIR"]).resolve(strict=True)
    if (directory != Path.cwd().resolve() or not directory.is_relative_to(ROOT / ".run" / "coding-agent-validation")
            or (directory / ".env").exists() or (directory / "smtp.env").exists() or os.environ.get("PA_DB_URL") != TEST_DB):
        raise ValueError("旧服务端测试隔离前提不满足")

    def audit(event, args):
        if event == "socket.connect" and isinstance(args[1], tuple):
            host, port = args[1][:2]
            # Windows asyncio 自唤醒使用本机 socketpair；固定的不可用测试数据库仍明确禁止连接。
            if host not in {"127.0.0.1", "::1"} or port == 9:
                raise RuntimeError("旧服务端纯单测禁止业务数据库与外部网络连接")
        if event == "socket.getaddrinfo" and args[0] not in {None, "localhost", "127.0.0.1", "::1"}:
            raise RuntimeError("旧服务端纯单测禁止外部域名解析")

    sys.addaudithook(audit)
    plugin = types.ModuleType("s1_legacy_validation")
    plugin.tmp_path = coding_validation_plugin.tmp_path
    plugin.pytest_sessionfinish = coding_validation_plugin.pytest_sessionfinish
    paths = [str(ROOT / "tests" / name) + ("::test_" + test if test else "")
             for name, tests in NODES.items() for test in tests or [None]]
    return pytest.main(["-c", str(ROOT / "pyproject.toml"), "--noconftest", "-p", "no:cacheprovider",
                       "-p", "pytest_asyncio.plugin", "-o", "addopts=", "-o", "filterwarnings=", "-q", "-ra", *paths], plugins=[plugin])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["--child"]:
        return child()
    if sys.argv[1:]:
        raise ValueError("此入口只运行冻结的旧服务端纯单测")
    parent = ROOT / ".run" / "coding-agent-validation"
    if not parent.resolve().is_relative_to(ROOT):
        raise ValueError("测试根目录越界")
    parent.mkdir(parents=True, exist_ok=True)
    directory = new_directory(parent, "legacy")
    (directory / "tmp").mkdir()
    environment = isolated_environment(directory)
    environment.update(PA_DB_URL=TEST_DB, PA_DATA_DIR=str(directory / "data"), USERNAME="s1-fixture",
                       USERPROFILE=str(directory), APPDATA=str(directory / "appdata"), LOCALAPPDATA=str(directory / "appdata"))
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--child"]
    result = 124
    print(f"旧服务端纯单测隔离目录：{directory}", flush=True)
    try:
        with managed_process(command, cwd=directory, env=environment, stdin=subprocess.DEVNULL) as process:
            result = process.wait(timeout=180)
    except subprocess.TimeoutExpired:
        print("旧服务端纯单测超时，已回收测试进程树", file=sys.stderr)
    finally:
        (directory / "invocation.json").write_text(json.dumps({"command": command, "cwd": str(directory), "exit_code": result,
            "scope": "仅冻结的纯单测；未运行依赖 MySQL/client 夹具的集成用例"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
