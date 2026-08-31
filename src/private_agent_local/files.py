"""Local file operations with a fixed authorized root and bounded output."""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path, PureWindowsPath

MAX_FILE_BYTES = 1024 * 1024
MAX_OUTPUT = 32_000
IGNORED = {".git", "node_modules", ".venv", "venv", "target", "dist", "__pycache__"}
SECRET_SUFFIXES = {".pem", ".key", ".pfx", ".p12"}


def secret_path(path: Path) -> bool:
    return any(part.lower() == ".env" or part.lower().startswith(".env.") or part.lower() in {
        ".git", ".ssh", ".aws", ".gnupg", ".npmrc", ".pypirc", ".netrc", "id_rsa", "id_ed25519"
    } for part in path.parts) or path.suffix.lower() in SECRET_SUFFIXES


def authorize_root(value: str) -> Path:
    root = Path(value).expanduser()
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("请选择本机上确实存在的绝对目录")
    if root.is_symlink() or getattr(root, "is_junction", lambda: False)():
        raise ValueError("请直接选择实际目录，不使用链接目录")
    return root.resolve(strict=True)


def within(root: Path, relative: str, *, allow_missing: bool = False) -> Path:
    path = Path(relative)
    windows = PureWindowsPath(relative)
    if path.is_absolute() or windows.drive or windows.root or ".." in path.parts or "\\" in relative or ":" in relative:
        raise ValueError("文件路径必须是项目内的相对路径，不允许越界")
    if secret_path(path):
        raise ValueError("此文件可能包含凭据，不允许通过项目工具读取或写入")
    target = root / path
    current = target
    while current != root:
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise ValueError("项目工具不访问符号链接或目录联接")
        current = current.parent
    resolved = target.resolve(strict=not allow_missing)
    if not resolved.is_relative_to(root):
        raise ValueError("文件路径超出授权项目")
    return resolved


def read_text(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("只支持不超过 1 MB 的普通文本文件")
    if path.stat().st_nlink > 1:
        raise ValueError("项目工具不读取硬链接文件")
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES or b"\x00" in raw:
        raise ValueError("文件过大或不是文本文件")
    return raw.decode("utf-8-sig")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def list_directory(root: Path, relative: str = ".") -> dict:
    path = within(root, relative)
    entries = []
    for child in path.iterdir():
        if len(entries) >= 500:
            break
        if child.name in IGNORED or secret_path(child) or child.is_symlink() or getattr(child, "is_junction", lambda: False)():
            continue
        entries.append({"rel_path": child.relative_to(root).as_posix(), "name": child.name,
                        "kind": "directory" if child.is_dir() else "file", "language": child.suffix.lstrip(".") or None,
                        "size_bytes": None if child.is_dir() else child.stat().st_size})
    entries.sort(key=lambda item: (item["kind"] != "directory", item["name"].casefold()))
    return {"rel_path": relative, "entries": entries, "count": len(entries), "truncated": len(entries) >= 500}


def search_files(root: Path, query: str, *, content: bool = False) -> dict:
    results, scanned = [], 0
    for current, directories, names in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories if name not in IGNORED and not secret_path(Path(name)) and not (Path(current) / name).is_symlink() and not getattr(Path(current) / name, "is_junction", lambda: False)()]
        for name in names:
            scanned += 1
            if scanned > 10_000 or len(results) >= 50:
                return {"results": results, "count": len(results), "truncated": True}
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            if secret_path(path) or path.is_symlink():
                continue
            if not content and query.casefold() in relative.casefold():
                results.append({"rel_path": relative, "name": name, "language": path.suffix.lstrip(".") or None})
            elif content:
                try:
                    for number, line in enumerate(read_text(path).splitlines(), 1):
                        if query.casefold() in line.casefold():
                            results.append({"rel_path": relative, "line": number, "text": line[:500]})
                            if len(results) >= 50:
                                break
                except (OSError, ValueError, UnicodeError):
                    continue
    return {"results": results, "count": len(results), "truncated": False}


def patch_preview(root: Path, relative: str, content: str) -> dict:
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError("单次修改超过 1 MB 上限")
    path = within(root, relative, allow_missing=True)
    old = read_text(path) if path.exists() else ""
    before = path.read_bytes() if path.exists() else b""
    after = content.encode("utf-8")
    diff = "".join(difflib.unified_diff(old.splitlines(True), content.splitlines(True), fromfile=f"a/{relative}", tofile=f"b/{relative}"))
    return {"rel_path": relative, "creates_file": not path.exists(), "old_sha256": digest(before),
            "new_sha256": digest(after), "diff": diff[:MAX_OUTPUT], "truncated": len(diff) > MAX_OUTPUT}


def apply_patch(root: Path, preview: dict, content: str) -> dict:
    path = within(root, preview["rel_path"], allow_missing=True)
    current = path.read_bytes() if path.exists() else b""
    if digest(current) != preview["old_sha256"] or (not path.exists()) != preview["creates_file"]:
        raise ValueError("文件自预览后已变化，请重新生成修改预览")
    if not path.parent.is_dir():
        raise ValueError("父目录不存在，请先在本机创建目录")
    data = content.encode("utf-8")
    if digest(data) != preview["new_sha256"]:
        raise ValueError("修改内容与已批准预览不一致")
    # Stage in the same directory: interruptions cannot truncate the original.
    descriptor, temporary_name = tempfile.mkstemp(prefix=".privateagent-write-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        path = within(root, preview["rel_path"], allow_missing=True)
        if preview["creates_file"]:
            os.link(temporary, path)  # Atomic creation; fails if another writer created the target.
        else:
            if digest(path.read_bytes()) != preview["old_sha256"]:
                raise ValueError("文件在写入前发生变化，已取消")
            os.chmod(temporary, path.stat().st_mode)
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    if digest(path.read_bytes()) != preview["new_sha256"]:
        raise ValueError("写入后的文件校验失败")
    return {**preview, "applied": True, "verified": True}


def prepare_process(args: list[str]) -> tuple[list[str], dict[str, str]]:
    if not args or len(args) > 40 or any(len(arg) > 2000 or "\x00" in arg for arg in args):
        raise ValueError("命令参数超出限制")
    environment_names = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "HOME",
                         "USERPROFILE", "APPDATA", "LOCALAPPDATA", "LANG", "LC_ALL", "NUMBER_OF_PROCESSORS"}
    env = {key: value for key, value in os.environ.items() if key.upper() in environment_names}
    if getattr(sys, "frozen", False):
        bundle = str(getattr(sys, "_MEIPASS", ""))
        env["PATH"] = os.pathsep.join(part for part in env.get("PATH", "").split(os.pathsep)
                                      if part and (not bundle or not part.casefold().startswith(bundle.casefold())))
    env["GIT_TERMINAL_PROMPT"] = "0"
    executable = shutil.which(args[0], path=env.get("PATH", ""))
    if not executable:
        raise ValueError("本机尚未安装该命令所需的开发工具")
    command = [executable, *args[1:]]
    if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        # 批处理只接收已经验证的参数，拒绝 shell 元字符。
        if any(any(c in arg for c in '&|<>^%!\r\n"') for arg in args[1:]):
            raise ValueError("命令参数包含不支持的 shell 字符")
        command = [env.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", subprocess.list2cmdline([executable, *args[1:]])]
    return command, env


async def run_process(root: Path, args: list[str], *, timeout: float = 120) -> dict:
    command, env = prepare_process(args)
    job = None
    dll_search = nullcontext()
    if os.name == "nt":
        from .windows_process import ProcessJob, system_dll_search
        job = ProcessJob()
        if getattr(sys, "frozen", False):
            dll_search = system_dll_search()
    process = None
    try:
        with dll_search:
            process = await asyncio.create_subprocess_exec(*command, cwd=root, env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                **({"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}))
        if job:
            job.assign(process.pid)
    except BaseException:
        if job:
            job.close()
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        raise
    buffers = [bytearray(), bytearray()]

    async def drain(stream, output):
        while chunk := await stream.read(4096):
            if len(output) < MAX_OUTPUT:
                output.extend(chunk[:MAX_OUTPUT - len(output)])

    readers = [asyncio.create_task(drain(process.stdout, buffers[0])), asyncio.create_task(drain(process.stderr, buffers[1]))]
    try:
        async with asyncio.timeout(timeout):
            await process.wait()
            await asyncio.gather(*readers)
    except (TimeoutError, asyncio.CancelledError):
        if job:
            job.close()
        if process.returncode is None:
            if os.name == "nt":
                killer = await asyncio.create_subprocess_exec("taskkill", "/PID", str(process.pid), "/T", "/F", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                await killer.wait()
            else:
                import signal
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
        raise
    finally:
        if job:
            job.close()
        for reader in readers:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
    return {"returncode": process.returncode, "stdout": buffers[0].decode("utf-8", errors="replace"),
            "stderr": buffers[1].decode("utf-8", errors="replace"), "truncated": any(len(b) >= MAX_OUTPUT for b in buffers)}


def parse_command(command: str) -> list[str]:
    args = shlex.split(command, posix=True)
    allowed = (("pytest",), ("python", "-m", "pytest"), ("npm", "test"), ("npm", "run", "test"), ("npm", "run", "build"), ("cargo", "test"), ("cargo", "check"))
    if tuple(args) not in allowed:
        raise ValueError("仅允许测试与构建命令；文件修改请使用预览和审批工具")
    if any(arg.startswith(("/", "\\")) or PureWindowsPath(arg).drive or ".." in Path(arg).parts for arg in args[1:]):
        raise ValueError("命令参数不允许引用项目外路径")
    return args
