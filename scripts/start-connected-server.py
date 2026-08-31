"""从仓库源码启动联网服务器；检查模式不加载配置、不连接数据库。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from importlib.machinery import PathFinder
from pathlib import Path


def source_layout(root: Path) -> tuple[Path, Path]:
    root = root.resolve(strict=True)
    package = root / "src/personal_assistant"
    for relative in ("__init__.py", "server_entry.py"):
        path = package / relative
        if not path.is_file() or path.resolve().parent != package:
            raise ValueError("源码入口缺失或指向仓库外，拒绝回退到安装副本")
    if package.resolve() != package or not (root / "alembic.ini").is_file() or not (root / "alembic").is_dir():
        raise ValueError("源码目录或 Alembic 资源不完整")
    return root, package


def select_source(package: Path) -> None:
    if any(name == "personal_assistant" or name.startswith("personal_assistant.") for name in sys.modules):
        raise ValueError("应用模块已加载，无法安全切换源码来源")
    sys.path.insert(0, str(package.parent))
    importlib.invalidate_caches()
    spec = importlib.util.find_spec("personal_assistant")
    entry = PathFinder.find_spec("personal_assistant.server_entry", [str(package)])
    if spec is None or spec.origin != str(package / "__init__.py") or entry is None or entry.origin != str(package / "server_entry.py"):
        raise ValueError("应用入口未解析到指定源码目录")


def code_hashes(package: Path) -> dict[str, str]:
    if not package.is_dir() or package.is_symlink():
        raise ValueError("待核对目录不存在或是符号链接")
    result = {}

    def fail_walk(exc: OSError) -> None:
        raise exc

    for directory, subdirs, files in os.walk(package, followlinks=False, onerror=fail_walk):
        for name in subdirs:
            if (Path(directory) / name).is_symlink():
                raise ValueError("待核对包中存在符号链接目录，需人工核对")
        subdirs[:] = [name for name in subdirs if name != "__pycache__"]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("源码文件类型或大小异常")
            content = path.read_bytes().replace(b"\r\n", b"\n")
            result[path.relative_to(package).as_posix()] = hashlib.sha256(content).hexdigest()
    if "__init__.py" not in result or "server_entry.py" not in result:
        raise ValueError("待核对目录不是完整的 personal_assistant 包")
    return result


def audit_installed(package: Path, installed: Path) -> dict:
    source, previous = code_hashes(package), code_hashes(installed)
    differences = [
        {"path": name, "source_sha256": source.get(name), "installed_sha256": previous.get(name)}
        for name in sorted(source.keys() | previous.keys()) if source.get(name) != previous.get(name)
    ]
    return {"status": "REVIEW_REQUIRED" if differences else "PYTHON_FILES_MATCH", "differences": differences}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="只验证入口来源，不启动服务")
    modes.add_argument("--audit-installed", type=Path, help="只比较安装包与源码中的 Python 文件摘要")
    args = parser.parse_args(argv)
    try:
        root, package = source_layout(Path(__file__).resolve().parents[1])
        if args.audit_installed is not None:
            report = audit_installed(package, args.audit_installed)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2 if report["differences"] else 0
        select_source(package)
        if args.check:
            print(json.dumps({"status": "SOURCE_ENTRY_OK", "package": str(package), "entry": str(package / "server_entry.py")}, ensure_ascii=False))
            return 0
        # 保留配置文件的相对路径语义，禁止悄悄换目录后加载另一套配置。
        if Path.cwd().resolve() != root:
            raise ValueError("工作目录必须为仓库根目录，请核对 Supervisor 的 directory")
    except (OSError, ValueError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"SOURCE_ENTRY_REFUSED: {message}", file=sys.stderr)
        return 1

    # 沿用既有迁移、父进程监控和服务生命周期，不绕过迁移启动 API。
    from personal_assistant.server_entry import main as run_server

    run_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
