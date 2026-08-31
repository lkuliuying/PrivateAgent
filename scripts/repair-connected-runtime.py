"""修复已确认的 1.0.3 安装包错位；仅处理五个固定文件，不修改配置或数据库。"""

import argparse
import ast
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

FILES = {
    "config.py": (
        "2a05f0b66bb0b8cb7380078856ebf4a367315bc367c571a9a2f65d5ceaf66045",
        {"086ca522165def85cfcb5fdb15ecf7b778aa790136527ddda5a920f236a48a94"},
    ),
    "main_api.py": (
        "a62d9da0b5841f0455d6b03354ee9c1b75aa059e90e491f0baf0217850a98476",
        {
            "fa755bfe54faa25868f56dd2433418af3aff1bb716b4de4df857d2b60ef46e9e",
            "bd45b6240287e97eb3911a6f2d44c762062f81730acea62e25127073fa9abeba",
        },
    ),
    "api/routes_admin_logs.py": (
        None, {"6164a651c186c01771456b7a8a99637f6869d6906fb654abb510092944aae530"},
    ),
    "api/routes_desktop_model.py": (
        None, {
            "6cc944005325654c85a5c0c3ded180bcd1ea37f88b9ac1db3c674f17d47383b5",
            "e978968f313921c32de9c2a15b29505a222e4985830dd29866848f60109aaf55",
        },
    ),
    "core/admin_logs.py": (
        None, {"e327fb073085e8d2c445f3af1c83e4497d22e05e7feacf54b657063bee76c522"},
    ),
}
SOURCE = Path("/opt/private-agent/current/src/personal_assistant")
PACKAGE = Path("/opt/private-agent/venv/lib/python3.12/site-packages/personal_assistant")
BACKUP = Path("/opt/private-agent/rollback-connected-runtime-1.0.3")


def digest(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest() if data is not None else None


def read_regular(path):
    """只读普通文件，拒绝中间目录链接、特殊文件和超过上限的文件。"""
    if path.resolve() != path or path.is_symlink():
        raise ValueError("拒绝链接路径")
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(before.st_mode) or before.st_size > 1024 * 1024:
        raise ValueError("文件类型或大小不符合预期")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        actual = os.fstat(stream.fileno())
        if not stat.S_ISREG(actual.st_mode) or (actual.st_dev, actual.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("文件在检查期间变化")
        data = stream.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("文件超过上限")
    return data


def check(source, package):
    """先检查所有来源与目标；任何未知差异都拒绝覆盖。"""
    records = []
    for relative, (old_hash, new_hashes) in FILES.items():
        src, target = source / relative, package / relative
        desired, current = read_regular(src), read_regular(target)
        if desired is None or digest(desired) not in new_hashes:
            raise ValueError(f"源码摘要不匹配，停止：{relative}")
        if relative == "api/routes_desktop_model.py":
            # 已交接源码仍有旧字段名时，只在待安装副本中应用已验证的一行修复。
            desired = desired.replace(b"profile.reasoning_efforts or []", b"profile.reasoning_efforts_json or []")
            if digest(desired) != "e978968f313921c32de9c2a15b29505a222e4985830dd29866848f60109aaf55":
                raise ValueError("模型代理字段修复摘要不匹配")
        ast.parse(desired.decode("utf-8-sig"), filename=relative)
        current_hash = digest(current)
        if current_hash not in {old_hash, *new_hashes}:
            raise ValueError(f"安装目录存在未核对的改动，停止：{relative}")
        if not target.parent.is_dir():
            raise ValueError(f"安装包目录不完整，停止：{relative}")
        metadata = target.stat() if current is not None else target.parent.stat()
        if current is not None and stat.S_IMODE(metadata.st_mode) > 0o777:
            raise ValueError(f"目标具有特殊权限位，停止：{relative}")
        records.append({
            "path": relative, "before": current, "after": desired,
            "mode": stat.S_IMODE(metadata.st_mode) if current is not None else 0o644,
            "uid": metadata.st_uid, "gid": metadata.st_gid,
        })
    return records


def require_stopped():
    """不替用户停止服务；只有明确 STOPPED 才允许写运行包。"""
    environment = os.environ.copy()
    environment.pop("PYTHONINSPECT", None)
    result = subprocess.run(
        ["supervisorctl", "-c", "/etc/supervisord.conf", "status", "private-agent"],
        env=environment, stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=False,
    )
    lines = result.stdout.decode("utf-8", errors="replace").splitlines()
    if len(lines) != 1 or lines[0].split()[:2] != ["private-agent", "STOPPED"]:
        raise ValueError("private-agent 未确认 STOPPED；未修改运行包")


def write_atomic(path, data, metadata):
    """同目录原子替换，保留原所有者和权限；不覆盖目录或链接。"""
    if path.resolve() != path or path.is_symlink():
        raise ValueError("拒绝链接目标")
    descriptor, name = tempfile.mkstemp(prefix=".pa-repair-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if hasattr(os, "chown"):
            os.chown(temporary, metadata["uid"], metadata["gid"])
        os.chmod(temporary, metadata["mode"])
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def apply(source, package, backup):
    require_stopped()
    records = check(source, package)
    if all(digest(record["before"]) == digest(record["after"]) for record in records):
        return "ALREADY_APPLIED"
    if backup.resolve() != backup or backup.is_symlink():
        raise ValueError("拒绝链接备份路径")
    backup.mkdir(mode=0o700)
    manifest = {"schema": 1, "package": str(package), "files": []}
    for index, record in enumerate(records):
        if record["before"] is not None:
            path = backup / f"{index}.before"
            with path.open("xb") as stream:
                stream.write(record["before"])
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(path, 0o600)
        manifest["files"].append({
            "path": record["path"], "before": digest(record["before"]), "after": digest(record["after"]),
            "mode": record["mode"], "uid": record["uid"], "gid": record["gid"],
        })
    # 全部备份完成并落盘后才开始更新；部分写入失败时也能凭此清单回滚。
    manifest_path = backup / "manifest.json"
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(manifest_path, 0o600)
    require_stopped()
    for record in records:
        if read_regular(package / record["path"]) != record["before"]:
            raise ValueError("备份后目标发生变化；保持停止并检查备份")
    for record in records:
        if digest(record["before"]) != digest(record["after"]):
            write_atomic(package / record["path"], record["after"], record)
    verified = check(source, package)
    if not all(digest(record["before"]) == digest(record["after"]) for record in verified):
        raise ValueError("修复后校验失败；保持停止并回滚")
    return "APPLIED_AND_VERIFIED"


def rollback(package, backup):
    require_stopped()
    raw = read_regular(backup / "manifest.json")
    if raw is None:
        raise ValueError("找不到备份清单")
    manifest = json.loads(raw)
    if not isinstance(manifest, dict):
        raise ValueError("备份清单结构无效")
    entries = manifest.get("files", [])
    if (not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries)
            or manifest.get("schema") != 1 or manifest.get("package") != str(package)
            or [entry.get("path") for entry in entries] != list(FILES)):
        raise ValueError("备份清单不符合五个固定文件范围")
    restored = []
    for index, entry in enumerate(entries):
        old_hash, new_hashes = FILES[entry["path"]]
        if entry["before"] not in {old_hash, *new_hashes} or entry["after"] not in new_hashes:
            raise ValueError("备份摘要不是已核对版本")
        if any(not isinstance(entry.get(key), int) or entry[key] < 0 for key in ("uid", "gid", "mode")):
            raise ValueError("备份元数据无效")
        if entry["mode"] > 0o777:
            raise ValueError("拒绝恢复特殊权限位")
        before = read_regular(backup / f"{index}.before") if entry["before"] is not None else None
        if digest(before) != entry["before"]:
            raise ValueError("备份文件损坏，停止回滚")
        current = read_regular(package / entry["path"])
        if digest(current) not in {entry["before"], entry["after"]}:
            raise ValueError("修复后出现新改动，拒绝覆盖回滚")
        restored.append((entry, before, current))
    require_stopped()
    for entry, before, current in restored:
        target = package / entry["path"]
        if read_regular(target) != current:
            raise ValueError("回滚期间目标发生变化")
        if before is None:
            if current is not None:
                target.unlink()
        else:
            write_atomic(target, before, entry)
    if any(digest(read_regular(package / entry["path"])) != entry["before"] for entry in entries):
        raise ValueError("回滚后校验失败；不要启动服务")
    return "ROLLED_BACK_AND_VERIFIED"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "apply", "rollback"))
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.exit(1, "STOP: 此工具只能在已核对的 Linux 服务器执行。\n")
    if args.action != "check" and os.geteuid() != 0:
        parser.exit(1, "STOP: 写入及备份需要 root；应用本身仍使用 privateagent 运行。\n")
    try:
        if args.action == "check":
            records = check(SOURCE, PACKAGE)
            result = {
                "status": "CHECK_PASSED", "package": str(PACKAGE),
                "files": [{"path": record["path"], "change": digest(record["before"]) != digest(record["after"])} for record in records],
            }
        elif args.action == "apply":
            result = {"status": apply(SOURCE, PACKAGE, BACKUP), "backup": str(BACKUP)}
        else:
            result = {"status": rollback(PACKAGE, BACKUP), "backup": str(BACKUP)}
    except (OSError, ValueError, SyntaxError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        # 不输出操作系统异常正文；源码校验错误只含固定文件名和受控提示。
        message = str(error) if type(error) is ValueError else type(error).__name__
        parser.exit(1, f"STOP: {message}。不要继续启动或更新服务。\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
