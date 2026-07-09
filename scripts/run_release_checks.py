#!/usr/bin/env python3
"""第八阶段 M2：发布检查 2.0（full evidence pipeline）。

串联后端测试 / 前端构建 / 前端测试 / E2E / Rust 检查 / 迁移 head / git diff /
诊断包脱敏 smoke / latest.json+.sig 校验，输出 dist/release-check-<version>.json + .md，
任一非跳过步骤失败时退出码非 0。

quick check 仍用 scripts/release-check.bat（pytest/npm build/cargo check/alembic current）。
npm test / e2e 在 M1 接入前端测试工具前会标记 skipped（不阻断）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from _release_utils import read_version  # noqa: E402

DIST = PROJECT_ROOT / "dist"


# ============ 通用步骤运行 ============


def run_shell_step(
    name: str, cmd: list[str], cwd: str | None = None, timeout: int = 600
) -> dict:
    t0 = time.perf_counter()
    try:
        r = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        ms = round((time.perf_counter() - t0) * 1000, 1)
        status = "passed" if r.returncode == 0 else "failed"
        detail = (r.stdout + r.stderr)[-2000:]
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
            "status": "skipped",
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


# ============ Python 检查 ============


def diagnostic_redaction_smoke() -> dict:
    """诊断包脱敏 smoke：写入假 API key，导出诊断包，校验 zip 内不含原文。"""
    t0 = time.perf_counter()
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from personal_assistant.config import settings as cfg
    from personal_assistant.core.diagnostics import DiagnosticsService
    from personal_assistant.core.models import Setting
    from personal_assistant.core.settings import SettingsService

    fake_key = "sk-release-check-redaction-smoke-9999"

    async def _run() -> bool:
        eng = create_async_engine(cfg.db_url)
        try:
            factory = async_sessionmaker(eng, expire_on_commit=False)
            async with factory() as db:
                await SettingsService(db).update({"openai_api_key": fake_key})
                try:
                    with tempfile.TemporaryDirectory() as td:
                        result = await DiagnosticsService(db).export(output_dir=td)
                        zip_bytes = Path(result["path"]).read_bytes()
                        return fake_key.encode() not in zip_bytes
                finally:
                    row = await db.get(Setting, "openai_api_key")
                    if row:
                        await db.delete(row)
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


def validate_latest_json(dist: Path | None = None) -> dict:
    """校验 dist/latest.json：version 匹配 tauri.conf.json，platforms 各项 signature/url 非空。"""
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
        if data.get("version") != version:
            issues.append(f"version 不匹配: {data.get('version')} vs {version}")
        platforms = data.get("platforms", {})
        if not platforms:
            issues.append("platforms 为空")
        for key, entry in platforms.items():
            if not entry.get("signature"):
                issues.append(f"{key} signature 为空")
            if not entry.get("url"):
                issues.append(f"{key} url 为空")
        return {
            "name": "latest_json_validation",
            "kind": "python",
            "status": "failed" if issues else "passed",
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


def assemble_report(steps: list[dict], version: str) -> dict:
    failed = [s for s in steps if s["status"] == "failed"]
    skipped = [s for s in steps if s["status"] == "skipped"]
    passed = [s for s in steps if s["status"] == "passed"]
    return {
        "version": version,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {"passed": len(passed), "failed": len(failed), "skipped": len(skipped)},
        "ok": len(failed) == 0,
        "steps": steps,
    }


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
    steps: list[dict] = []

    steps.append(run_shell_step("pytest", ["uv", "run", "pytest", "-q"], cwd=str(PROJECT_ROOT)))
    steps.append(run_shell_step("npm_build", ["npm", "run", "build"], cwd=desktop))
    if npm_script_exists("test"):
        steps.append(run_shell_step("npm_test", ["npm", "run", "test"], cwd=desktop))
    else:
        steps.append(skipped_step("npm_test", "package.json 无 test 脚本（M1 未接入）"))
    if npm_script_exists("e2e"):
        steps.append(run_shell_step("npm_e2e", ["npm", "run", "e2e"], cwd=desktop))
    else:
        steps.append(skipped_step("npm_e2e", "package.json 无 e2e 脚本（M1 未接入）"))
    steps.append(
        run_shell_step(
            "cargo_check", ["cmd", "/c", "scripts\\cargo-check-tauri.bat"], cwd=str(PROJECT_ROOT)
        )
    )
    steps.append(
        run_shell_step("alembic_current", ["uv", "run", "alembic", "current"], cwd=str(PROJECT_ROOT))
    )
    steps.append(
        run_shell_step("git_diff_check", ["git", "diff", "--check"], cwd=str(PROJECT_ROOT))
    )
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
    json_path, md_path = write_report(report, Path(args.out))
    print(f"[release-check] report: {md_path}")
    print(
        f"  passed={report['summary']['passed']} "
        f"failed={report['summary']['failed']} "
        f"skipped={report['summary']['skipped']} ok={report['ok']}"
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
