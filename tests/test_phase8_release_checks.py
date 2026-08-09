"""第八阶段 M2 测试：发布检查 2.0 证据管线逻辑。

覆盖（对齐 docs/archive/phases/phase8-plan.md §M2 / docs/archive/phases/phase8-requirements.md §5.2）：
- assemble_report：passed/failed/skipped 汇总 + ok 判定。
- write_report：输出 JSON + Markdown。
- validate_latest_json：合法 / 缺失（skipped）/ 签名空（failed）。
- npm_script_exists / npm_executable：脚本探测与 Windows launcher。
- 缺少强制命令时发布门禁失败，不得静默 skipped。
"""
from __future__ import annotations

import json
import os
import re
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


def test_validate_latest_json_prerelease_keeps_stable_channel(tmp_path):
    """0.3.0-alpha.2：预发布检查点不更新正式渠道，latest.json 保持旧稳定版合法。"""
    if not re.search(r"(?i)(alpha|beta|rc)", CURRENT_VERSION):
        return  # 仅预发布构建有此语义
    (tmp_path / "latest.json").write_text(
        json.dumps(
            {
                "version": "0.2.1",
                "platforms": {"windows-x86_64": {"signature": "sig", "url": "http://x/y.exe"}},
            }
        ),
        encoding="utf-8",
    )
    res = rc.validate_latest_json(tmp_path)
    assert res["status"] == "passed"
    assert "预发布检查点" in res["detail"]


def test_npm_script_exists():
    assert rc.npm_script_exists("build") is True
    assert rc.npm_script_exists("nonexistent_script_xyz") is False


def test_npm_executable_is_platform_specific():
    assert rc.npm_executable(platform="win32") == "npm.cmd"
    assert rc.npm_executable(platform="linux") == "npm"


def test_container_config_uses_independent_ephemeral_secret_files(monkeypatch):
    observed: dict[str, object] = {}

    def fake_shell_step(name, cmd, cwd=None, timeout=600, env=None):
        observed["name"] = name
        observed["cmd"] = cmd
        observed["env"] = env
        paths = [
            Path(env["PA_API_TOKEN_SECRET_FILE"]),
            Path(env["PA_MYSQL_PASSWORD_SECRET_FILE"]),
            Path(env["PA_MYSQL_ROOT_PASSWORD_SECRET_FILE"]),
        ]
        observed["paths"] = paths
        observed["values"] = [path.read_text(encoding="utf-8") for path in paths]
        return {
            "name": name,
            "kind": "shell",
            "status": "passed",
            "duration_ms": 1,
            "returncode": 0,
            "detail": "",
        }

    monkeypatch.setattr(rc, "run_shell_step", fake_shell_step)

    result = rc.run_docker_compose_config_step(source_env={"PATH": "safe-path"})

    assert result["status"] == "passed"
    assert observed["name"] == "docker_compose_config"
    assert observed["env"]["PATH"] == "safe-path"
    assert observed["cmd"][-3:] == ["ollama-gpu", "config", "--quiet"]
    assert all(len(value) == 64 for value in observed["values"])
    assert len(set(observed["values"])) == 3
    assert all(not path.exists() for path in observed["paths"])


def test_missing_mandatory_command_fails(tmp_path):
    result = rc.run_shell_step(
        "missing",
        ["private-agent-command-that-does-not-exist"],
        cwd=str(tmp_path),
    )
    assert result["status"] == "failed"
    assert result["returncode"] is None


def test_shell_step_captures_output_without_pipe(tmp_path):
    result = rc.run_shell_step(
        "capture",
        [sys.executable, "-c", "print('release-check-output')"],
        cwd=str(tmp_path),
    )
    assert result["status"] == "passed"
    assert "release-check-output" in result["detail"]


def test_managed_e2e_uses_external_server_and_stops_it(tmp_path, monkeypatch):
    vite_entry = tmp_path / "node_modules" / "vite" / "bin" / "vite.js"
    vite_entry.parent.mkdir(parents=True)
    vite_entry.touch()
    observed: dict[str, object] = {}

    class FakeServer:
        stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout):
            observed["wait_timeout"] = timeout
            return 0

        def kill(self):
            raise AssertionError("graceful termination should have succeeded")

    fake_server = FakeServer()

    def fake_popen(cmd, **kwargs):
        observed["server_cmd"] = cmd
        observed["server_env"] = kwargs["env"]
        return fake_server

    def fake_shell_step(name, cmd, cwd=None, timeout=600, env=None):
        observed["e2e_env"] = env
        return {
            "name": name,
            "kind": "shell",
            "status": "passed",
            "duration_ms": 1,
            "returncode": 0,
            "detail": "13 passed",
        }

    monkeypatch.setattr(rc, "_available_loopback_port", lambda: 54321)
    monkeypatch.setattr(rc, "_wait_for_server", lambda *_args: True)
    monkeypatch.setattr(rc.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rc, "run_shell_step", fake_shell_step)

    result = rc.run_managed_e2e_step("npm.cmd", str(tmp_path))

    assert result["status"] == "passed"
    assert fake_server.stopped is True
    assert observed["server_cmd"][-3:] == ["--port", "54321", "--strictPort"]
    assert observed["e2e_env"]["PA_E2E_BASE_URL"] == "http://127.0.0.1:54321"
    assert observed["e2e_env"]["PA_E2E_EXTERNAL_SERVER"] == "1"
    assert observed["server_env"]["PATH"] == os.environ["PATH"]
