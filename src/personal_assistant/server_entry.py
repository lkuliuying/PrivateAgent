"""PyInstaller 打包入口（M4 打包预研）。

与 ``main_api.py`` 的区别：
- ``reload=False``：uvicorn ``--reload`` 依赖文件监听，与 PyInstaller 冻结环境不兼容。
- 启动前自动执行 Alembic 迁移到 ``head``：打包后无 ``alembic`` CLI，需进程内调用。
- 端口由 Tauri 通过 ``PA_API_PORT`` 环境变量传入（pydantic-settings 自动读取）。

开发模式下也可用 ``python -m personal_assistant.server_entry`` 启动（会自动迁移），
但日常开发推荐 ``main_api.py`` + 手动 ``alembic upgrade head``。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _project_base() -> Path:
    """项目根（开发模式）或 PyInstaller 解压目录（打包模式 ``sys._MEIPASS``）。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]

    # A normal source checkout resolves directly from ``__file__``.  A
    # non-editable wheel installation (including the Docker image) places this
    # module under ``.venv/site-packages`` while the Alembic resources remain
    # at the application root.  Prefer the first candidate that actually owns
    # both resources instead of assuming one fixed installation layout.
    source_base = Path(__file__).resolve().parent.parent.parent
    candidates = [source_base, Path.cwd().resolve()]
    candidates.extend(Path(sys.executable).resolve().parents)
    for candidate in dict.fromkeys(candidates):
        if (candidate / "alembic.ini").is_file() and (candidate / "alembic").is_dir():
            return candidate
    return source_base


def _ensure_data_dirs() -> None:
    """确保用户数据目录及 chroma/logs 子目录存在。"""
    from personal_assistant.config import settings

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)


def _read_db_revision() -> str | None:
    """读取数据库当前 alembic revision（连接或查询失败返回 None）。"""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine

    from personal_assistant.config import settings

    async def _run() -> str | None:
        eng = create_async_engine(make_url(settings.db_url))
        try:
            async with eng.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT version_num FROM alembic_version")
                    )
                ).fetchone()
                return str(row[0]) if row else None
        finally:
            await eng.dispose()

    try:
        return asyncio.run(_run())
    except Exception:  # noqa: BLE001
        return None


def _run_migrations() -> None:
    """进程内执行 Alembic ``upgrade head``（打包后无 alembic CLI）。

    只向前迁移：数据库 revision 若不在本应用已知迁移链内（例如新版已升级
    schema 后回退安装本版本），跳过迁移并继续启动，绝不执行破坏性 downgrade
    （v0.6.0 第 7 节）。revision 读不到时保持原行为：交给 upgrade 处理（空库
    建链）或失败拒绝启动（连接/表异常，避免在未知 schema 上启动可写 API）。
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from alembic import command

    base = _project_base()
    ini = base / "alembic.ini"
    alembic_dir = base / "alembic"
    if not ini.exists() or not alembic_dir.exists():
        raise FileNotFoundError(
            "required Alembic resources are missing from the application root: "
            f"{base}"
        )
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(alembic_dir))
    db_revision = _read_db_revision()
    if db_revision is not None:
        known = {r.revision for r in ScriptDirectory.from_config(cfg).walk_revisions()}
        if db_revision not in known:
            print(
                f"[server_entry] database revision {db_revision} is not in this "
                "application's migration chain; skipping migrations "
                "(rollback-safe: no destructive downgrade).",
                file=sys.stderr,
            )
            return
    # env.py 会注入 settings.db_url，此处不设置 sqlalchemy.url
    command.upgrade(cfg, "head")


def _start_parent_watchdog() -> None:
    """父进程（Tauri 主程序）消失时立即退出 sidecar。

    NSIS 卸载会 TerminateProcess 强杀 Tauri 主程序，RunEvent::Exit 不触发，
    lib.rs 的 child.kill() 不执行 -> sidecar 孤儿进程占用 exe，NSIS 删不掉
    （残留 personal-assistant-server*.exe）。此守护线程检测父进程消失后
    os._exit 立即退出，释放 exe 文件句柄，让卸载能清理干净。
    """
    import threading
    import time

    # PyInstaller onefile：Python 子进程的父是 bootloader（始终活着），不是 Tauri 主程序。
    # 故优先用 Tauri 注入的 PA_PARENT_PID（主程序 PID），回退 getppid()。
    parent_pid = int(os.environ.get("PA_PARENT_PID") or os.getppid() or 0)
    if parent_pid <= 1:
        return  # 直接运行（无 Tauri 父进程），不监控

    if sys.platform == "win32":
        import ctypes

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

        def _alive(pid: int) -> bool:
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            k32.CloseHandle(h)
            return True
    else:
        def _alive(pid: int) -> bool:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    def _watch() -> None:
        while True:
            if not _alive(parent_pid):
                # 父进程已退出（含被 NSIS 强杀/崩溃），立即退出释放 exe 句柄。
                os._exit(0)
            time.sleep(0.3)

    threading.Thread(target=_watch, daemon=True, name="parent-watchdog").start()


def main() -> None:
    _ensure_data_dirs()
    # 父进程守护：Tauri 主程序被强杀（NSIS 卸载/崩溃）时立即退出 sidecar，
    # 避免孤儿进程占用 exe 导致卸载残留。
    _start_parent_watchdog()
    # PA_SKIP_MIGRATIONS lets tooling (e.g. scripts/measure_sidecar_baseline.py) spawn
    # the sidecar without running alembic against a real database -- keeps the startup
    # measurement side-effect-free. Normal packaged startup leaves it unset.
    if os.environ.get("PA_SKIP_MIGRATIONS", "").lower() in ("1", "true", "yes"):
        print("[server_entry] PA_SKIP_MIGRATIONS set; skipping alembic migration.", file=sys.stderr)
    else:
        try:
            _run_migrations()
        except Exception as exc:  # noqa: BLE001
            # A writable API on an unknown schema can corrupt user data. Do not
            # print the exception body because driver errors may include DSNs or
            # SQL parameters; diagnostics can still identify the exception type.
            print(
                "[server_entry] database migration failed; refusing to start "
                f"({type(exc).__name__})",
                file=sys.stderr,
            )
            raise SystemExit(1) from None

    import uvicorn

    from personal_assistant.config import settings
    from personal_assistant.main_api import app, register_managed_server

    # 显式 Server 实例：把句柄注册给 /internal/shutdown，桌面退出前先请求
    # 优雅停机（lifespan finally 会 flush 遥测 ended_at 并收拢 coordinator），
    # 强杀只作为兜底（M0 门槛：正常退出写 ended_at）。
    config = uvicorn.Config(
        app,
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )
    server = uvicorn.Server(config)
    register_managed_server(server)
    server.run()


if __name__ == "__main__":
    main()
