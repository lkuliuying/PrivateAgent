#!/usr/bin/env python3
"""Measure the sidecar / installer size and (optionally) cold & warm startup time.

Size measurement is deterministic and always printed. Startup measurement
(``--startup``) spawns the frozen sidecar with a temp ``PA_DATA_DIR`` and sets
``PA_SKIP_MIGRATIONS=1`` so it does NOT run alembic against any real database
(truly side-effect-free), then records the time until ``GET /health`` responds
200 -- this captures the PyInstaller onefile ``_MEIPASS`` extraction + Python
init + uvicorn bind latency.

Usage (project root)::

    uv run python scripts/measure_sidecar_baseline.py                 # sizes only
    uv run python scripts/measure_sidecar_baseline.py --startup       # sizes + cold + warm startup
    uv run python scripts/measure_sidecar_baseline.py --startup --markdown  # emit a markdown table

Stdlib only (plus scripts/_release_utils.py for version/installer discovery).
"""
from __future__ import annotations

import argparse
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from _release_utils import find_installer as find_installer_for_version, installer_sig, read_version

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SIDECAR = (
    PROJECT_ROOT
    / "apps"
    / "desktop"
    / "src-tauri"
    / "binaries"
    / "personal-assistant-server-x86_64-pc-windows-msvc.exe"
)


def human(n: int | None) -> str:
    if n is None:
        return "n/a"
    s = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if s < 1024:
            return f"{s:.1f} {u} ({n} bytes)"
        s /= 1024
    return f"{s:.1f} TB ({n} bytes)"


def artifact_sizes() -> dict[str, tuple[int | None, Path | None]]:
    out: dict[str, tuple[int | None, Path | None]] = {}
    out["sidecar"] = (SIDECAR.stat().st_size if SIDECAR.exists() else None, SIDECAR if SIDECAR.exists() else None)
    # Select the installer by the version embedded in its filename (not lexicographic
    # sort) so a 0.1.9 -> 0.1.10 boundary can't pick a stale build.
    installer: Path | None = None
    sig: Path | None = None
    try:
        installer = find_installer_for_version(read_version())
        sig = installer_sig(installer)
        sig = sig if sig.exists() else None
    except SystemExit:
        pass
    out["installer"] = (installer.stat().st_size if installer else None, installer)
    out["signature"] = (sig.stat().st_size if sig else None, sig)
    return out


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _unquote(v: str) -> str:
    """Strip a single pair of matching surrounding quotes, mirroring python-dotenv /
    pydantic-settings, so a quoted PA_DB_URL in .env doesn't yield a malformed URL."""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def read_dev_env() -> tuple[str | None, str | None]:
    """Read PA_DB_URL / PA_OLLAMA_BASE_URL from the project .env (dev config)."""
    env_file = PROJECT_ROOT / ".env"
    db = ollama = None
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("PA_DB_URL="):
                db = _unquote(line[len("PA_DB_URL="):])
            elif line.startswith("PA_OLLAMA_BASE_URL="):
                ollama = _unquote(line[len("PA_OLLAMA_BASE_URL="):])
    return db, ollama


def kill_tree(pid: int) -> None:
    """Kill the process AND its children. PyInstaller onefile spawns a child that
    survives parent termination, so a plain .terminate() leaves orphans on Windows."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, 9)
    except Exception:
        pass


def measure_one_startup(port: int, db_url: str | None, ollama_url: str | None, timeout: float = 90.0) -> tuple[float | None, str]:
    """Spawn sidecar, return (seconds_to_health_200, status).

    Sets ``PA_SKIP_MIGRATIONS=1`` so the sidecar does NOT run alembic against any
    real database (truly side-effect-free, even when the dev DB has pending
    migrations). Uses the dev .env DB/Ollama URLs (if present) only so /health's
    probes connect to real services; a temp ``PA_DATA_DIR`` keeps chroma/logs out
    of the real user data dir.
    """
    env = os.environ.copy()
    env["PA_API_PORT"] = str(port)
    token = secrets.token_hex(32)
    env["PA_API_TOKEN"] = token
    env["PA_SKIP_MIGRATIONS"] = "1"
    if db_url:
        env["PA_DB_URL"] = db_url
    if ollama_url:
        env["PA_OLLAMA_BASE_URL"] = ollama_url
    tmp = tempfile.mkdtemp(prefix="pa_baseline_")
    env["PA_DATA_DIR"] = tmp
    env["PYTHONUNBUFFERED"] = "1"

    url = f"http://127.0.0.1:{port}/health"
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        [str(SIDECAR)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ok = False
        while time.perf_counter() - t0 < timeout:
            if proc.poll() is not None:
                return None, f"sidecar exited early (rc={proc.returncode})"
            try:
                request = urllib.request.Request(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                )
                with urllib.request.urlopen(request, timeout=2) as r:
                    if r.status == 200:
                        ok = True
                        break
            except Exception:
                time.sleep(0.3)
        elapsed = time.perf_counter() - t0
        return (elapsed if ok else None), ("ok" if ok else "timeout")
    finally:
        kill_tree(proc.pid)
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
        # The PyInstaller onefile CHILD holds chroma/sqlite handles and may release
        # them slightly after the parent exits; retry rmtree to avoid leaving orphan
        # pa_baseline_* dirs in %TEMP% (ignore_errors swallows the final failure).
        import shutil
        for _ in range(5):
            try:
                shutil.rmtree(tmp)
                break
            except OSError:
                time.sleep(0.5)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--startup", action="store_true", help="also measure cold & warm startup to /health")
    ap.add_argument("--markdown", action="store_true", help="emit a markdown table")
    args = ap.parse_args()

    sizes = artifact_sizes()

    if args.markdown:
        lines = ["## Sidecar baseline", "", "| 指标 | 值 |", "|---|---|"]
        for k, (n, p) in sizes.items():
            lines.append(f"| {k} 大小 | {human(n)} |")
        if args.startup:
            db, ollama = read_dev_env()
            if not db:
                lines.append("| 首次启动到 /health（冷） | skipped (no PA_DB_URL in .env) |")
                lines.append("| 二次启动到 /health（热） | skipped (no PA_DB_URL in .env) |")
            else:
                cold, cstat = measure_one_startup(free_port(), db, ollama)
                warm, wstat = measure_one_startup(free_port(), db, ollama)
                lines.append(f"| 首次启动到 /health（冷） | {f'{cold:.2f}s' if cold else f'n/a ({cstat})'} |")
                lines.append(f"| 二次启动到 /health（热） | {f'{warm:.2f}s' if warm else f'n/a ({wstat})'} |")
        print("\n".join(lines))
        return 0

    print("=== Sidecar baseline ===")
    for k, (n, p) in sizes.items():
        print(f"  {k:10s}: {human(n)}" + (f"  <- {p.name}" if p else "  (not found)"))

    if args.startup:
        db, ollama = read_dev_env()
        if not db:
            print("\n[startup] no PA_DB_URL in project .env; startup measurement skipped.")
            return 0
        print("\n=== Startup to /health (skip migrations, temp data dir) ===")
        cold, cstat = measure_one_startup(free_port(), db, ollama)
        print(f"  cold  : {f'{cold:.2f}s' if cold else f'n/a ({cstat})'}")
        warm, wstat = measure_one_startup(free_port(), db, ollama)
        print(f"  warm  : {f'{warm:.2f}s' if warm else f'n/a ({wstat})'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
