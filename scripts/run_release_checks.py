#!/usr/bin/env python3
"""第八阶段 M2：发布检查 2.0（full evidence pipeline）。

串联后端测试 / Ruff / compileall / 前端构建 / 前端测试 / E2E / Rust check / Rust test /
sidecar smoke / 迁移 head / git diff / 诊断包脱敏 smoke / latest.json+.sig 校验，
输出 dist/release-check-<version>.json + .md，任一非跳过步骤失败时退出码非 0。

quick check 仍用 scripts/release-check.bat（pytest/npm build/cargo check/alembic current）。
Ruff 门禁口径为 pyproject.toml 的 [tool.ruff.lint]：E/F/I，忽略 E501（仓库既有长行）。
npm test / e2e 在 M1 接入前端测试工具前会标记 skipped（不阻断）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from _release_utils import NSIS_DIR, read_version  # noqa: E402

DIST = PROJECT_ROOT / "dist"


# ============ 通用步骤运行 ============


def run_shell_step(
    name: str,
    cmd: list[str],
    cwd: str | None = None,
    timeout: int = 600,
    env: Mapping[str, str] | None = None,
) -> dict:
    t0 = time.perf_counter()
    try:
        # A real file avoids Windows PIPE EOF deadlocks when Node workers inherit
        # stdout after npm/vitest's direct launcher has already exited.
        with tempfile.TemporaryFile(mode="w+b") as captured:
            r = subprocess.run(
                cmd,
                cwd=cwd,
                stdout=captured,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
                env=env,
            )
            captured.flush()
            captured.seek(0)
            detail = captured.read().decode("utf-8", errors="replace")[-2000:]
        ms = round((time.perf_counter() - t0) * 1000, 1)
        status = "passed" if r.returncode == 0 else "failed"
        return {
            "name": name,
            "kind": "shell",
            "status": status,
            "duration_ms": ms,
            "returncode": r.returncode,
            "detail": detail,
        }
    except subprocess.TimeoutExpired:
        return {
            "name": name,
            "kind": "shell",
            "status": "failed",
            "duration_ms": timeout * 1000,
            "returncode": -1,
            "detail": "timeout",
        }
    except FileNotFoundError as e:
        return {
            "name": name,
            "kind": "shell",
            "status": "failed",
            "duration_ms": 0,
            "returncode": None,
            "detail": f"not found: {e}",
        }


def skipped_step(name: str, detail: str) -> dict:
    return {
        "name": name,
        "kind": "shell",
        "status": "skipped",
        "duration_ms": 0,
        "returncode": None,
        "detail": detail,
    }


def npm_script_exists(script: str) -> bool:
    pkg = PROJECT_ROOT / "apps" / "desktop" / "package.json"
    if not pkg.exists():
        return False
    try:
        return script in json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
    except Exception:  # noqa: BLE001
        return False


def npm_executable(*, platform: str | None = None) -> str:
    """Return the directly executable npm launcher for the current platform."""
    return "npm.cmd" if (platform or sys.platform) == "win32" else "npm"


def run_docker_compose_config_step(
    *,
    source_env: Mapping[str, str] | None = None,
    timeout: int = 60,
) -> dict:
    """Validate Compose with short-lived secret files that are always removed."""
    secret_parent = PROJECT_ROOT / "data" / "rehearsals" / "release-check-compose"
    secret_parent.mkdir(parents=True, exist_ok=True)
    secret_dir = secret_parent / f"run-{secrets.token_hex(8)}"
    secret_dir.mkdir()
    result: dict | None = None
    cleanup_error: OSError | None = None
    try:
        env = dict(os.environ if source_env is None else source_env)
        secret_names = {
            "PA_API_TOKEN_SECRET_FILE": "api_token",
            "PA_MYSQL_PASSWORD_SECRET_FILE": "mysql_password",
            "PA_MYSQL_ROOT_PASSWORD_SECRET_FILE": "mysql_root_password",
        }
        for env_name, filename in secret_names.items():
            path = secret_dir / filename
            path.write_text(secrets.token_hex(32), encoding="utf-8")
            path.chmod(0o600)
            env[env_name] = str(path)
        result = run_shell_step(
            "docker_compose_config",
            [
                "docker",
                "compose",
                "--file",
                "compose.yaml",
                "--profile",
                "ollama-gpu",
                "config",
                "--quiet",
            ],
            cwd=str(PROJECT_ROOT),
            timeout=timeout,
            env=env,
        )
    finally:
        try:
            shutil.rmtree(secret_dir)
        except OSError as exc:
            cleanup_error = exc

    assert result is not None
    if cleanup_error is not None:
        result.update(
            status="failed",
            returncode=-1,
            detail="ephemeral Compose secret files could not be removed",
        )
    return result


def _available_loopback_port() -> int:
    """Reserve and release a loopback port for the short-lived E2E server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_server(process: subprocess.Popen[bytes], port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _stop_managed_process(process: subprocess.Popen[bytes]) -> bool:
    """Stop a directly spawned helper and report whether it actually exited."""
    if process.poll() is not None:
        return True
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return False
    return process.poll() is not None


def run_managed_e2e_step(
    npm: str,
    desktop: str,
    *,
    timeout: int = 600,
    startup_timeout: float = 60,
) -> dict:
    """Run Playwright against a directly managed Vite process.

    Playwright's nested ``npm -> cmd -> vite`` webServer process can hang during
    cleanup on Windows even after every test passed.  Starting Vite directly
    gives the release check a process handle it can always terminate and verify.
    """
    t0 = time.perf_counter()
    desktop_path = Path(desktop)
    vite_entry = desktop_path / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite_entry.is_file():
        return {
            "name": "npm_e2e",
            "kind": "shell",
            "status": "failed",
            "duration_ms": 0,
            "returncode": None,
            "detail": f"not found: {vite_entry}",
        }

    port = _available_loopback_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["PA_E2E_BASE_URL"] = base_url
    env["PA_E2E_EXTERNAL_SERVER"] = "1"
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0

    with tempfile.TemporaryFile(mode="w+b") as server_output:
        server = subprocess.Popen(
            [
                "node",
                str(vite_entry),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--strictPort",
            ],
            cwd=desktop,
            stdout=server_output,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=creationflags,
            start_new_session=sys.platform != "win32",
        )
        try:
            if not _wait_for_server(server, port, startup_timeout):
                server_output.flush()
                server_output.seek(0)
                detail = server_output.read().decode("utf-8", errors="replace")[-2000:]
                return {
                    "name": "npm_e2e",
                    "kind": "shell",
                    "status": "failed",
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "returncode": server.poll(),
                    "detail": f"Vite did not become ready at {base_url}\n{detail}".strip(),
                }
            result = run_shell_step(
                "npm_e2e",
                [npm, "run", "e2e"],
                cwd=desktop,
                timeout=timeout,
                env=env,
            )
        finally:
            stopped = _stop_managed_process(server)

    if not stopped:
        result.update(
            status="failed",
            returncode=-1,
            detail=f"{result['detail']}\nmanaged Vite process did not exit".strip(),
        )
    result["duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return result


# ============ Python 检查 ============


def diagnostic_redaction_smoke() -> dict:
    """诊断包脱敏 smoke：写入假 API key，导出诊断包，校验 zip 内不含原文。"""
    t0 = time.perf_counter()
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from personal_assistant.config import settings as cfg
    from personal_assistant.core.diagnostics import DiagnosticsService
    from personal_assistant.core.models import DiagnosticRun, Setting
    from personal_assistant.testing import resolve_test_database_url

    fake_key = "sk-release-check-redaction-smoke-9999"
    test_db_url = resolve_test_database_url(
        cfg.db_url,
        os.environ.get("PA_TEST_DB_URL"),
    )

    async def _run() -> bool:
        eng = create_async_engine(test_db_url)
        try:
            factory = async_sessionmaker(eng, expire_on_commit=False)
            async with factory() as db:
                row = await db.get(Setting, "openai_api_key")
                created = row is None
                original = row.value if row else None
                if row is None:
                    row = Setting(key="openai_api_key", value=fake_key)
                    db.add(row)
                else:
                    row.value = fake_key
                await db.commit()
                previous_diagnostic_id = int(
                    await db.scalar(
                        select(DiagnosticRun.id)
                        .order_by(DiagnosticRun.id.desc())
                        .limit(1)
                    )
                    or 0
                )
                output_path: Path | None = None
                try:
                    output_dir = (
                        PROJECT_ROOT / "data" / "rehearsals" / "release-check-redaction"
                    )
                    output_dir.mkdir(parents=True, exist_ok=True)
                    result = await DiagnosticsService(db).export(
                        output_dir=str(output_dir)
                    )
                    output_path = Path(result["path"])
                    zip_bytes = output_path.read_bytes()
                    return fake_key.encode() not in zip_bytes
                finally:
                    if output_path is not None:
                        with suppress(OSError):
                            output_path.unlink(missing_ok=True)
                    new_diagnostic_runs = list(
                        (
                            await db.scalars(
                                select(DiagnosticRun).where(
                                    DiagnosticRun.id > previous_diagnostic_id
                                )
                            )
                        )
                        .unique()
                        .all()
                    )
                    for diagnostic_run in new_diagnostic_runs:
                        await db.delete(diagnostic_run)
                    if created:
                        await db.delete(row)
                    else:
                        row.value = original
                    await db.commit()
        finally:
            await eng.dispose()

    try:
        ok = asyncio.run(_run())
        return {
            "name": "diagnostic_redaction_smoke",
            "kind": "python",
            "status": "passed" if ok else "failed",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            "detail": "诊断包不含原始 API key" if ok else "诊断包泄露 API key!",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "name": "diagnostic_redaction_smoke",
            "kind": "python",
            "status": "failed",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            "detail": str(e)[:500],
        }


def sidecar_smoke_step() -> dict:
    """启动已构建 PyInstaller sidecar 的 /health smoke（未构建时如实标记 skipped）。"""
    binary = (
        PROJECT_ROOT
        / "apps"
        / "desktop"
        / "src-tauri"
        / "binaries"
        / "personal-assistant-server-x86_64-pc-windows-msvc.exe"
    )
    if not binary.is_file():
        return skipped_step("sidecar_smoke", "sidecar 二进制未构建（运行 scripts/build-sidecar.bat）")
    return run_shell_step(
        "sidecar_smoke",
        ["uv", "run", "python", "scripts/sidecar_smoke.py"],
        cwd=str(PROJECT_ROOT),
        timeout=240,
    )


def _version_key(value: str) -> tuple[int, ...]:
    """把版本字符串映射为可比较的数字元组（忽略预发布后缀）。"""
    return tuple(int(part) for part in re.findall(r"\d+", value) or [0])


def validate_latest_json(dist: Path | None = None) -> dict:
    """校验 dist/latest.json：version 匹配 tauri.conf.json，platforms 各项 signature/url 非空。

    内部预发布检查点（版本含 alpha/beta/rc）不上传正式 updater 渠道：
    latest.json 保持较旧（数字版本不高于当前）的稳定版本视为合法，仅当
    latest.json 版本高于当前版本时才失败；platforms 完整性始终校验。
    """
    t0 = time.perf_counter()
    base = dist or DIST
    path = base / "latest.json"
    if not path.exists():
        return {
            "name": "latest_json_validation",
            "kind": "python",
            "status": "skipped",
            "duration_ms": 0,
            "detail": "dist/latest.json 不存在（运行 generate-latest-json.py 后再校验）",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        version = read_version()
        issues: list[str] = []
        is_prerelease = re.search(r"(?i)(alpha|beta|rc)", version) is not None
        latest_version = str(data.get("version") or "")
        if latest_version != version:
            if is_prerelease and _version_key(latest_version) <= _version_key(version):
                issues.append(
                    f"预发布检查点 {version} 不更新正式渠道 "
                    f"(latest.json 保持 {latest_version})"
                )
            else:
                issues.append(f"version 不匹配 {latest_version} vs {version}")
        platforms = data.get("platforms", {})
        if not platforms:
            issues.append("platforms 为空")
        for key, entry in platforms.items():
            if not entry.get("signature"):
                issues.append(f"{key} signature 为空")
            if not entry.get("url"):
                issues.append(f"{key} url 为空")
        passed = not issues or (
            is_prerelease
            and len(issues) == 1
            and issues[0].startswith("预发布检查点")
        )
        return {
            "name": "latest_json_validation",
            "kind": "python",
            "status": "passed" if passed else "failed",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            "detail": "; ".join(issues) or "latest.json 结构与签名 OK",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "name": "latest_json_validation",
            "kind": "python",
            "status": "failed",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            "detail": str(e)[:500],
        }


# ============ 报告 ============


def git_commit_info() -> dict:
    """返回当前代码 commit 绑定信息（供发布报告审计）。"""

    def _run(cmd: list[str]) -> str | None:
        try:
            r = subprocess.run(
                cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=30, check=False
            )
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:  # noqa: BLE001
            return None

    dirty = _run(["git", "status", "--porcelain"])
    return {
        "head": _run(["git", "rev-parse", "HEAD"]),
        "short": _run(["git", "rev-parse", "--short", "HEAD"]),
        "describe": _run(["git", "describe", "--tags", "--always"]),
        "dirty": dirty not in (None, ""),
    }


def signing_status(version: str) -> dict:
    """报告签名状态：0.x.x 的 Authenticode 证据（可能缺失）+ 安装包是否已构建。

    Authenticode 证据来自 dist/codesign-status-<version>.json（由
    scripts/sign_installer.py 写入）；缺失即尚无该版本的签名核验结论，
    报告如实标记 code_signed=None，不伪称已签。安装包未构建时 latest.json
    校验步骤会失败并留证。
    """
    status_file = DIST / f"codesign-status-{version}.json"
    installer_built = any(p.name for p in NSIS_DIR.glob(f"*_{version}_*-setup.exe"))
    code_signed: bool | None = None
    evidence: str | None = None
    if status_file.exists():
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            code_signed = bool(data.get("code_signed"))
            evidence = status_file.name
        except Exception:  # noqa: BLE001
            code_signed = None
    return {
        "version": version,
        "installer_built": installer_built,
        "code_signed": code_signed,
        "evidence": evidence,
    }


def assemble_report(
    steps: list[dict], version: str, *, strict_gates: bool = True
) -> dict:
    failed = [s for s in steps if s["status"] == "failed"]
    skipped = [s for s in steps if s["status"] == "skipped"]
    passed = [s for s in steps if s["status"] == "passed"]
    schema: str | None = None
    tests: str | None = None
    for s in steps:
        if s["name"] == "alembic_current":
            m = re.search(r"(\d{4})\s*\(head\)", str(s.get("detail", "")))
            if m:
                schema = m.group(1)
        if s["name"] == "pytest":
            m = re.search(
                r"(\d+ passed[^\r\n]*?(?: in [\d.]+s)?)", str(s.get("detail", ""))
            )
            if m:
                tests = m.group(1).strip(" =")
    commit = git_commit_info()
    signing = signing_status(version)
    # rc.2：发布门槛不再只看步骤成败——脏工作区/版本不一致/安装包缺失/
    # 证据未绑定当前提交都视为不通过（issue 记录原因）。
    # strict_gates=False 仅供单元测试隔离步骤汇总逻辑。
    gate_issues: list[str] = []
    if strict_gates:
        if commit.get("dirty"):
            gate_issues.append("worktree_dirty")
        if not version_consistent(version):
            gate_issues.append("version_inconsistent")
        if not signing["installer_built"]:
            gate_issues.append("installer_missing")
        if not evidence_bound(version, commit.get("head")):
            gate_issues.append("evidence_not_bound")
    ok = len(failed) == 0 and not gate_issues
    return {
        "version": version,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit,
        "database_schema": schema,
        "pytest_summary": tests,
        "signing": signing,
        "release_gate_issues": gate_issues,
        "summary": {"passed": len(passed), "failed": len(failed), "skipped": len(skipped)},
        "ok": ok,
        "steps": steps,
    }


def version_consistent(version: str) -> bool:
    """rc.2：五处版本源（Python/Vue/Tauri/Cargo）必须与报告版本一致。"""
    sources = [
        PROJECT_ROOT / "src" / "personal_assistant" / "__init__.py",
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "apps" / "desktop" / "package.json",
        PROJECT_ROOT / "apps" / "desktop" / "src-tauri" / "tauri.conf.json",
        PROJECT_ROOT / "apps" / "desktop" / "src-tauri" / "Cargo.toml",
    ]
    for path in sources:
        if not path.exists():
            return False
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return False
        if version not in text:
            return False
    return True


def evidence_bound(version: str, head: str | None) -> bool:
    """rc.2：qa-evidence-<version>.json 必须存在且绑定当前 HEAD。"""
    evidence = DIST / f"qa-evidence-{version}.json"
    if not evidence.exists():
        return False
    try:
        data = json.loads(evidence.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return False
    return bool(head) and data.get("git_commit") == head


def write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"release-check-{report['version']}.json"
    md_path = out_dir / f"release-check-{report['version']}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        f"# Release Check - v{report['version']}",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- commit: {report['commit'].get('short')} ({report['commit'].get('describe')})",
        f"- worktree_dirty: {report['commit'].get('dirty')}",
        f"- database_schema: {report['database_schema']}",
        f"- pytest_summary: {report['pytest_summary']}",
        f"- signing: installer_built={report['signing']['installer_built']}, code_signed={report['signing']['code_signed']}, evidence={report['signing']['evidence']}",
        f"- release_gate_issues: {report.get('release_gate_issues') or 'none'}",
        f"- passed: {report['summary']['passed']}",
        f"- failed: {report['summary']['failed']}",
        f"- skipped: {report['summary']['skipped']}",
        f"- ok: {report['ok']}",
        "",
        "| 步骤 | 状态 | 耗时(ms) | 说明 |",
        "|---|---|---|---|",
    ]
    for s in report["steps"]:
        detail = str(s.get("detail", ""))[:120].replace("|", "/")
        lines.append(f"| {s['name']} | {s['status']} | {s['duration_ms']} | {detail} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


# ============ 主流程 ============


def run_all() -> dict:
    version = read_version()
    desktop = str(PROJECT_ROOT / "apps" / "desktop")
    npm = npm_executable()
    steps: list[dict] = []

    steps.append(run_shell_step("pytest", ["uv", "run", "pytest", "-q"], cwd=str(PROJECT_ROOT)))
    steps.append(
        run_shell_step(
            "ruff_check",
            ["uv", "run", "--with", "ruff", "ruff", "check", "src", "tests", "scripts"],
            cwd=str(PROJECT_ROOT),
        )
    )
    steps.append(
        run_shell_step(
            "compileall",
            ["uv", "run", "python", "-m", "compileall", "-q", "src", "scripts"],
            cwd=str(PROJECT_ROOT),
        )
    )
    steps.append(run_shell_step("npm_build", [npm, "run", "build"], cwd=desktop))
    if npm_script_exists("test"):
        steps.append(run_shell_step("npm_test", [npm, "run", "test"], cwd=desktop))
    else:
        steps.append(skipped_step("npm_test", "package.json 无 test 脚本（M1 未接入）"))
    if npm_script_exists("e2e"):
        steps.append(run_managed_e2e_step(npm, desktop))
    else:
        steps.append(skipped_step("npm_e2e", "package.json 无 e2e 脚本（M1 未接入）"))
    steps.append(
        run_shell_step(
            "cargo_check", ["cmd", "/c", "scripts\\cargo-check-tauri.bat"], cwd=str(PROJECT_ROOT)
        )
    )
    steps.append(
        run_shell_step(
            "cargo_test", ["cmd", "/c", "scripts\\cargo-test-tauri.bat"], cwd=str(PROJECT_ROOT)
        )
    )
    steps.append(sidecar_smoke_step())
    steps.append(
        run_shell_step(
            "alembic_current", ["uv", "run", "alembic", "current"], cwd=str(PROJECT_ROOT)
        )
    )
    steps.append(
        run_shell_step("git_diff_check", ["git", "diff", "--check"], cwd=str(PROJECT_ROOT))
    )
    steps.append(run_docker_compose_config_step())
    steps.append(diagnostic_redaction_smoke())
    steps.append(validate_latest_json())
    return assemble_report(steps, version)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", default=str(DIST), help="报告输出目录（默认 dist/）")
    args = ap.parse_args()

    report = run_all()
    _json_path, md_path = write_report(report, Path(args.out))
    print(f"[release-check] report: {md_path}")
    print(
        f"  passed={report['summary']['passed']} "
        f"failed={report['summary']['failed']} "
        f"skipped={report['summary']['skipped']} ok={report['ok']}"
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
