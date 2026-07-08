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
    # 开发模式：src/personal_assistant/server_entry.py -> 项目根
    return Path(__file__).resolve().parent.parent.parent


def _ensure_data_dirs() -> None:
    """确保用户数据目录及 chroma/logs 子目录存在。"""
    from personal_assistant.config import settings

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)


def _run_migrations() -> None:
    """进程内执行 Alembic ``upgrade head``（打包后无 alembic CLI）。"""
    from alembic import command
    from alembic.config import Config

    base = _project_base()
    ini = base / "alembic.ini"
    alembic_dir = base / "alembic"
    if not ini.exists() or not alembic_dir.exists():
        print(
            f"[server_entry] 未找到 alembic 资源（{ini}），跳过自动迁移。",
            file=sys.stderr,
        )
        return
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(alembic_dir))
    # env.py 会注入 settings.db_url，此处不设置 sqlalchemy.url
    command.upgrade(cfg, "head")


def main() -> None:
    _ensure_data_dirs()
    # PA_SKIP_MIGRATIONS lets tooling (e.g. scripts/measure_sidecar_baseline.py) spawn
    # the sidecar without running alembic against a real database -- keeps the startup
    # measurement side-effect-free. Normal packaged startup leaves it unset.
    if os.environ.get("PA_SKIP_MIGRATIONS", "").lower() in ("1", "true", "yes"):
        print("[server_entry] PA_SKIP_MIGRATIONS set; skipping alembic migration.", file=sys.stderr)
    else:
        try:
            _run_migrations()
        except Exception as exc:  # noqa: BLE001
            # 迁移失败不阻断启动：MySQL 可能尚未就绪，前端状态页会展示 MySQL 不可用
            print(f"[server_entry] 自动迁移失败（继续启动）: {exc}", file=sys.stderr)

    import uvicorn
    from personal_assistant.config import settings

    uvicorn.run(
        "personal_assistant.main_api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
