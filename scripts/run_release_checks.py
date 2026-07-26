#!/usr/bin/env python3
"""Run the full release evidence pipeline against an isolated test database."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from _release_utils import read_version  # noqa: E402
from _test_database import (  # noqa: E402
    IsolatedDatabasePlan,
    activate_test_environment,
    build_database_plan,
    drop_database,
    make_test_data_dir,
    provision_database,
    remove_test_data_dir,
    upgrade_database,
)

DIST = PROJECT_ROOT / "dist"


def run_shell_step(
    name: str,
    cmd: list[str],
    cwd: str | None = None,
    timeout: int = 600,
    *,
    required: bool = True,
) -> dict:
    """Run one evidence step and retain a bounded diagnostic tail."""

    started = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "name": name,
            "kind": "shell",
            "status": "passed" if result.returncode == 0 else "failed",
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "returncode": result.returncode,
            "detail": (result.stdout + result.stderr)[-2000:],
            "required": required,
        }
    except subprocess.TimeoutExpired:
        return {
            "name": name,
            "kind": "shell",
            "status": "failed",
            "duration_ms": timeout * 1000,
            "returncode": -1,
            "detail": "timeout",
            "required": required,
        }
    except FileNotFoundError as exc:
        return {
            "name": name,
            "kind": "shell",
            "status": "skipped",
            "duration_ms": 0,
            "returncode": None,
            "detail": f"not found: {exc}",
            "required": required,
        }


def skipped_step(name: str, detail: str, *, required: bool = False) -> dict:
    return {
        "name": name,
        "kind": "shell",
        "status": "skipped",
        "duration_ms": 0,
        "returncode": None,
        "detail": detail,
        "required": required,
    }


def npm_script_exists(script: str) -> bool:
    package_json = PROJECT_ROOT / "apps" / "desktop" / "package.json"
    if not package_json.exists():
        return False
    try:
        scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts", {})
        return script in scripts
    except Exception:  # noqa: BLE001
        return False


def resolve_executable(name: str) -> str:
    """Resolve Windows command shims explicitly for CreateProcess."""

    candidates = [f"{name}.cmd", f"{name}.exe", name] if os.name == "nt" else [name]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return name


def python_module_command(module: str, *args: str) -> list[str]:
    """Use the active Python instead of starting a nested uv environment."""

    return [sys.executable, "-m", module, *args]


def zip_members_containing(path: Path, secret: bytes) -> list[str]:
    """Return members whose decompressed payload contains the secret."""

    leaked: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if not info.is_dir() and secret in archive.read(info):
                leaked.append(info.filename)
    return leaked


def diagnostic_redaction_smoke() -> dict:
    """Export diagnostics and scan every decompressed member for a fake key."""

    started = time.perf_counter()
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from personal_assistant.config import settings as cfg
    from personal_assistant.core.db import engine as app_engine
    from personal_assistant.core.diagnostics import DiagnosticsService
    from personal_assistant.core.models import Setting
    from personal_assistant.core.settings import SettingsService

    fake_key = "sk-release-check-redaction-smoke-9999"

    async def _run() -> list[str]:
        engine = create_async_engine(cfg.db_url)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as db:
                original = await db.get(Setting, "openai_api_key")
                original_exists = original is not None
                original_value = original.value if original is not None else None
                try:
                    await SettingsService(db).update({"openai_api_key": fake_key})
                    export_dir = cfg.data_dir / "diagnostic-redaction-smoke"
                    export_dir.mkdir(parents=True, exist_ok=True)
                    exported = await DiagnosticsService(db).export(
                        output_dir=str(export_dir)
                    )
                    return zip_members_containing(
                        Path(exported["path"]), fake_key.encode("utf-8")
                    )
                finally:
                    row = await db.get(Setting, "openai_api_key")
                    if original_exists:
                        if row is None:
                            db.add(Setting(key="openai_api_key", value=original_value))
                        else:
                            row.value = original_value
                    elif row is not None:
                        await db.delete(row)
                    await db.commit()
        finally:
            await engine.dispose()
            # HealthService uses the application engine during diagnostics.
            await app_engine.dispose()

    try:
        leaked_members = asyncio.run(_run())
        ok = not leaked_members
        return {
            "name": "diagnostic_redaction_smoke",
            "kind": "python",
            "status": "passed" if ok else "failed",
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "detail": (
                "诊断包逐成员脱敏校验通过"
                if ok
                else f"API key 泄漏于: {', '.join(leaked_members)}"
            ),
            "required": True,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": "diagnostic_redaction_smoke",
            "kind": "python",
            "status": "failed",
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "detail": str(exc)[:500],
            "required": True,
        }


def validate_latest_json(dist: Path | None = None) -> dict:
    """Validate updater version, signatures and URLs when latest.json exists."""

    started = time.perf_counter()
    path = (dist or DIST) / "latest.json"
    if not path.exists():
        return skipped_step(
            "latest_json_validation",
            "dist/latest.json 不存在；生成更新清单后再校验",
            required=False,
        ) | {"kind": "python"}
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
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "detail": "; ".join(issues) or "latest.json 结构与签名字段有效",
            "required": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": "latest_json_validation",
            "kind": "python",
            "status": "failed",
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "detail": str(exc)[:500],
            "required": False,
        }


def assemble_report(steps: list[dict], version: str) -> dict:
    failed = [step for step in steps if step["status"] == "failed"]
    skipped = [step for step in steps if step["status"] == "skipped"]
    passed = [step for step in steps if step["status"] == "passed"]
    blocking_skipped = [step for step in skipped if step.get("required", False)]
    return {
        "version": version,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "passed": len(passed),
            "failed": len(failed),
            "skipped": len(skipped),
        },
        "ok": not failed and not blocking_skipped,
        "blocking_skipped": [step["name"] for step in blocking_skipped],
        "steps": steps,
    }


def write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"release-check-{report['version']}.json"
    markdown_path = out_dir / f"release-check-{report['version']}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"# Release Check - v{report['version']}",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- passed: {report['summary']['passed']}",
        f"- failed: {report['summary']['failed']}",
        f"- skipped: {report['summary']['skipped']}",
        f"- blocking_skipped: {report['blocking_skipped']}",
        f"- ok: {report['ok']}",
        "",
        "| 步骤 | 状态 | 必需 | 耗时(ms) | 说明 |",
        "|---|---|---|---|---|",
    ]
    for step in report["steps"]:
        detail = str(step.get("detail", ""))[:120].replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {step['name']} | {step['status']} | "
            f"{step.get('required', False)} | {step['duration_ms']} | {detail} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def run_all() -> dict:
    version = read_version()
    desktop = str(PROJECT_ROOT / "apps" / "desktop")
    npm = resolve_executable("npm")
    steps: list[dict] = []

    steps.append(
        run_shell_step(
            "pytest",
            python_module_command("pytest", "-q"),
            cwd=str(PROJECT_ROOT),
        )
    )
    steps.append(run_shell_step("npm_build", [npm, "run", "build"], cwd=desktop))
    if npm_script_exists("test"):
        steps.append(run_shell_step("npm_test", [npm, "run", "test"], cwd=desktop))
    else:
        steps.append(
            skipped_step("npm_test", "package.json 缺少必需的 test 脚本", required=True)
        )
    if npm_script_exists("e2e"):
        steps.append(run_shell_step("npm_e2e", [npm, "run", "e2e"], cwd=desktop))
    else:
        steps.append(
            skipped_step("npm_e2e", "package.json 缺少必需的 e2e 脚本", required=True)
        )
    steps.append(
        run_shell_step(
            "cargo_check",
            ["cmd", "/c", "scripts\\cargo-check-tauri.bat"],
            cwd=str(PROJECT_ROOT),
        )
    )
    steps.append(
        run_shell_step(
            "alembic_current",
            python_module_command("alembic", "current", "--check-heads"),
            cwd=str(PROJECT_ROOT),
        )
    )
    steps.append(
        run_shell_step(
            "alembic_check",
            python_module_command("alembic", "check"),
            cwd=str(PROJECT_ROOT),
        )
    )
    steps.append(
        run_shell_step("git_diff_check", ["git", "diff", "--check"], cwd=str(PROJECT_ROOT))
    )
    steps.append(
        run_shell_step(
            "git_cached_diff_check",
            ["git", "diff", "--cached", "--check"],
            cwd=str(PROJECT_ROOT),
        )
    )
    steps.append(diagnostic_redaction_smoke())
    steps.append(validate_latest_json())
    return assemble_report(steps, version)


def _prepare_isolated_release_database() -> tuple[IsolatedDatabasePlan, Path]:
    """Provision isolation before any application DB engine is imported."""

    import personal_assistant.config as config_module

    plan = build_database_plan(
        config_module.settings.db_url,
        explicit_test_url=os.environ.get("PA_TEST_DB_URL"),
        run_token=f"release_{uuid.uuid4().hex}",
        worker_id="release",
    )
    data_dir = make_test_data_dir(
        plan.database_name,
        temp_root=PROJECT_ROOT / ".run" / "release-check",
    )
    activate_test_environment(plan, data_dir)
    config_module.settings.db_url = plan.database_url
    config_module.settings.data_dir = data_dir
    try:
        provision_database(plan)
        upgrade_database(PROJECT_ROOT)
    except BaseException:
        try:
            if plan.created_by_run:
                drop_database(plan)
        finally:
            remove_test_data_dir(
                data_dir,
                temp_root=PROJECT_ROOT / ".run" / "release-check",
            )
        raise

    # The child pytest process reuses this DB as an explicit target and cannot drop it.
    os.environ["PA_TEST_DB_URL"] = plan.database_url
    return plan, data_dir


def _cleanup_isolated_release_database(
    plan: IsolatedDatabasePlan,
    data_dir: Path,
) -> None:
    try:
        try:
            from personal_assistant.core.db import engine as app_engine
        except ImportError:
            app_engine = None
        if app_engine is not None:
            asyncio.run(app_engine.dispose())
    finally:
        try:
            if plan.created_by_run:
                drop_database(plan)
        finally:
            remove_test_data_dir(
                data_dir,
                temp_root=PROJECT_ROOT / ".run" / "release-check",
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--out", default=str(DIST), help="报告输出目录（默认 dist/）")
    args = parser.parse_args()

    plan, data_dir = _prepare_isolated_release_database()
    try:
        report = run_all()
        _, markdown_path = write_report(report, Path(args.out))
        print(f"[release-check] report: {markdown_path}")
        print(
            f"  passed={report['summary']['passed']} "
            f"failed={report['summary']['failed']} "
            f"skipped={report['summary']['skipped']} ok={report['ok']}"
        )
        return 0 if report["ok"] else 1
    finally:
        _cleanup_isolated_release_database(plan, data_dir)


if __name__ == "__main__":
    sys.exit(main())
