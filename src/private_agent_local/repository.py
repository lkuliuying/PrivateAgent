"""版本化仓库读取和有界检索；游标绑定查询、目录和内容版本。"""
from __future__ import annotations

import asyncio
import base64
import bisect
import fnmatch
import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import files, policy
from .store import encode, now

MAX_ENTRIES = 10_000
MAX_SEARCH_BYTES = 16 * 1024 * 1024
MAX_RESULTS = 10_000


def page(items: list, query: dict, version: str, cursor: str | None, limit: int) -> dict:
    if not 1 <= limit <= 200:
        raise ValueError("每页数量须在 1–200 之间")
    binding = files.digest(encode({"query": query, "version": version}).encode())
    offset = 0
    if cursor:
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if (set(value) != {"binding", "offset"} or value["binding"] != binding
                    or type(value["offset"]) is not int or not 0 < value["offset"] < len(items)):
                raise ValueError
            offset = value["offset"]
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise ValueError("游标无效或查询、目录、文件已变化；请用 cursor=null（JSON null，不是字符串）重新查询。"
                             "仅翻页时原样使用同一工具、相同查询返回的 next_cursor；不要重复提交失效游标。") from None
    end = min(offset + limit, len(items))
    next_cursor = base64.urlsafe_b64encode(encode({"binding": binding, "offset": end}).encode()).decode() if end < len(items) else None
    return {"count": end - offset, "total": len(items), "next_cursor": next_cursor,
            "query_version": version, "truncated": next_cursor is not None, "items": items[offset:end]}


def _safe_child(root: Path, child: Path) -> bool:
    return (not policy.protected(child) and not files.linked(child)
            and not (child.is_dir() and (child / ".git").exists())
            and not any(part.casefold() in files.IGNORED for part in child.relative_to(root).parts))


def _stat(path: Path) -> list:
    value = path.lstat()
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def directory(root: Path, relative=".", *, cursor=None, limit=100) -> dict:
    policy.file_scope(root, relative, "readonly")
    path = files.within(root, relative)
    before = _stat(path)
    entries, manifest = [], []
    with os.scandir(path) as iterator:
        for index, entry in enumerate(iterator):
            if index >= MAX_ENTRIES:
                raise ValueError("目录超过 10000 项，请选择更小的子目录")
            child = Path(entry.path)
            if not _safe_child(root, child):
                continue
            state = child.stat()
            if child.is_file() and state.st_nlink != 1:
                continue
            rel = child.relative_to(root).as_posix()
            entries.append({"rel_path": rel, "name": child.name, "kind": "directory" if child.is_dir() else "file",
                            "language": child.suffix.lstrip(".") or None, "size_bytes": None if child.is_dir() else state.st_size})
            manifest.append([rel, _stat(child)])
    if before != _stat(path):
        raise ValueError("目录在读取期间变化，请重新查询")
    entries.sort(key=lambda item: (item["kind"] != "directory", item["name"].casefold(), item["name"]))
    version = files.digest(encode({"root": files.file_identity(root), "directory": before, "entries": sorted(manifest)}).encode())
    result = page(entries, {"root": str(root), "path": relative, "kind": "directory"}, version, cursor, limit)
    result["entries"] = result.pop("items")
    return {"schema_version": "2", "rel_path": relative, **result}


def _ignored(relative: str, is_directory: bool, rules: list[tuple[str, str]]) -> bool:
    ignored = False
    for base, pattern in rules:
        if base and not relative.startswith(base + "/"):
            continue
        target = relative[len(base) + 1:] if base else relative
        negate = pattern.startswith("!")
        pattern = pattern[1:] if negate else pattern
        directory_only = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        anchored = pattern.startswith("/") or "/" in pattern
        pattern = pattern.lstrip("/")
        if directory_only and not is_directory:
            continue
        expression = re.escape(pattern).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        matched = re.fullmatch(expression, target if anchored else Path(target).name) is not None
        if matched:
            ignored = not negate
    return ignored


def scan(root: Path, relative: str, glob: str, native_paths: set[str] | None = None,
         *, cancelled: threading.Event | None = None) -> tuple[list, dict, list]:
    policy.file_scope(root, relative, "readonly")
    scope = files.within(root, relative)
    started, total, entries = time.monotonic(), 0, 0
    data, manifest, skipped = [], {}, []
    rules_by_directory = {}
    def check_budget():
        if cancelled is not None and cancelled.is_set():
            raise ValueError("仓库扫描已取消")
        if time.monotonic() - started > 10:
            raise ValueError("仓库扫描超过 10 秒，请缩小范围")
    # 从根遍历以保留祖先忽略规则，目标子树以外只读取规则及目录元数据。
    for current, directories, names in os.walk(root, followlinks=False, onerror=lambda error: (_ for _ in ()).throw(error)):
        path = Path(current)
        check_budget()
        rules = list(rules_by_directory.get(path.parent, []))
        rel_dir = path.relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        if ".gitignore" in names:
            raw, _ = files.safe_bytes(root, f"{rel_dir}/.gitignore" if rel_dir else ".gitignore")
            manifest[f"ignore:{rel_dir}"] = files.digest(raw)
            for line in ([] if native_paths is not None else raw.decode("utf-8-sig").splitlines()):
                line = line.rstrip()
                if line and not line.startswith("#"):
                    if "\\" in line or "[" in line or "**" in line:
                        # 复杂规则必须用 rg 的原生忽略语义，不能近似后泄露被忽略内容。
                        raise ValueError("本机扫描暂不支持该 .gitignore 转义、字符组或 ** 规则，请使用更小的无此规则项目")
                    rules.append((rel_dir, line))
        rules_by_directory[path] = rules
        manifest[f"dir:{rel_dir}"] = _stat(path)
        entries += len(directories) + len(names)
        if entries > MAX_ENTRIES:
            raise ValueError("仓库扫描超过 10000 项，请缩小项目")
        directories[:] = sorted(name for name in directories if _safe_child(root, path / name)
                                 and not _ignored((path / name).relative_to(root).as_posix(), True, rules)
                                 and ((path / name).is_relative_to(scope) or scope.is_relative_to(path / name)))
        if not path.is_relative_to(scope):
            continue
        for name in sorted(names):
            check_budget()
            candidate = path / name
            rel = candidate.relative_to(root).as_posix()
            if not _safe_child(root, candidate) or _ignored(rel, False, rules):
                continue
            if native_paths is not None and rel not in native_paths:
                continue
            if not (fnmatch.fnmatchcase(rel, glob) or (glob.startswith("**/") and fnmatch.fnmatchcase(rel, glob[3:]))):
                continue
            manifest[rel] = _stat(candidate)
            try:
                raw, _ = files.safe_bytes(root, rel)
            except (ValueError, UnicodeError):
                skipped.append({"rel_path": rel, "reason": "二进制、不支持编码、链接或超过单文件上限"})
                continue
            total += len(raw)
            if total > MAX_SEARCH_BYTES:
                raise ValueError("搜索文本超过 16 MiB，请缩小目录或 glob")
            manifest[rel].append(files.digest(raw))
            data.append((rel, raw.decode("utf-8-sig")))
    return sorted(data), manifest, skipped


async def scan_async(root: Path, relative: str, glob: str, native_paths: set[str] | None):
    cancelled = threading.Event()
    try:
        return await asyncio.to_thread(scan, root, relative, glob, native_paths, cancelled=cancelled)
    finally:
        # 取消协程不能终止 Python 线程；通知扫描在下一个文件边界停止。
        cancelled.set()


async def search(root: Path, query: str, *, content=False, relative=".", glob="*", regex=False,
                 case_sensitive=False, cursor=None, limit=50) -> dict:
    if not query or len(query) > 200 or "\x00" in query or "\n" in query or "\r" in query:
        raise ValueError("搜索模式必须为 1–200 字符的单行文本")
    rg = shutil.which("rg")
    if regex and not rg:
        raise ValueError("正则搜索需要本机 rg；当前仅提供有界字面搜索，未自动安装依赖")
    async def native_inventory():
        if not rg:
            return None
        result = await files.run_process(root, [rg, "--files", "--hidden", "--no-config", "--null", "--", relative],
                                         timeout=10, output_limit=4 * 1024 * 1024)
        if result["returncode"] not in {0, 1} or result["truncated"]:
            raise ValueError("rg 文件清单不可用或超过上限，请缩小目录")
        return {Path(path).as_posix().removeprefix("./") for path in result["stdout"].split("\x00") if path}
    policy.file_scope(root, relative, "readonly")
    native_paths = await native_inventory()
    data, manifest, skipped = await scan_async(root, relative, glob, native_paths)
    lines, starts = [], []
    for rel, text in data:
        starts.append(len(lines) + 1)
        lines.extend(text.splitlines() if content else [rel])
    matches = []
    if rg and lines:
        args = [rg, "--json", "--no-config", "--max-columns", "32000", "--max-columns-preview"]
        if not regex:
            args.append("--fixed-strings")
        if not case_sensitive:
            args.append("--ignore-case")
        result = await files.run_process(root, [*args, "--", query, "-"], timeout=10,
                                         stdin_data=("\n".join(lines) + "\n").encode(), output_limit=4 * 1024 * 1024)
        if result["returncode"] not in {0, 1} or result["truncated"]:
            raise ValueError("搜索表达式无效或结果超过上限，请缩小查询")
        for record in result["stdout"].splitlines():
            value = json.loads(record)
            if value["type"] == "match":
                matches.append(value["data"]["line_number"])
    else:
        needle = query if case_sensitive else query.casefold()
        for number, line in enumerate(lines, 1):
            if needle in (line if case_sensitive else line.casefold()):
                matches.append(number)
            if number % 1000 == 0:
                await asyncio.sleep(0)
    if len(matches) > MAX_RESULTS:
        raise ValueError("搜索结果超过 10000 条，请缩小查询")
    results = []
    for number in matches:
        index = bisect.bisect_right(starts, number) - 1
        rel = data[index][0]
        results.append({"rel_path": rel, "line": number - starts[index] + 1, "text": lines[number - 1][:500]}
                       if content else {"rel_path": rel, "name": Path(rel).name, "language": Path(rel).suffix.lstrip(".") or None})
    native_after = await native_inventory()
    _, after, _ = await scan_async(root, relative, glob, native_after)
    if after != manifest or native_after != native_paths:
        raise ValueError("搜索期间工作区变化，请重新查询")
    version = files.digest(encode({"manifest": manifest, "root": files.file_identity(root)}).encode())
    result = page(results, {"root": str(root), "query": query, "content": content, "relative": relative,
                           "glob": glob, "regex": regex, "case_sensitive": case_sensitive}, version, cursor, limit)
    result["results"] = result.pop("items")
    return {"schema_version": "2", **result, "backend": "rg" if rg else "python_literal",
            "skipped": skipped, "skipped_count": len(skipped)}


async def read_thread(function, *args, **kwargs):
    """读线程只处理有界磁盘数据；取消也等待读取释放资源，不在后台写入快照。"""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


class Repository:
    def __init__(self, store):
        self.store = store

    def read(self, run: dict, root: Path, relative: str, start_line=1, line_count=1000, expected_version=None, start_column=1,
             *, execution: dict | None = None, read_data=None) -> dict:
        policy.file_scope(root, relative, run["permission_mode"])
        raw, identity = read_data if read_data is not None else files.safe_bytes(root, relative)
        version = files.digest(raw)
        if expected_version and expected_version != version:
            raise ValueError("文件版本已变化，请从新版本重新读取")
        if not 1 <= start_line or not 1 <= line_count <= 2000:
            raise ValueError("读取行范围无效")
        lines = raw.decode("utf-8-sig").splitlines(keepends=True)
        if start_line > len(lines) + 1:
            raise ValueError("起始行超过文件末尾")
        if start_column < 1 or (start_column > 1 and (start_line > len(lines) or start_column > len(lines[start_line - 1]))):
            raise ValueError("起始列超过当前行范围")
        selected, size, numbers = [], 0, []
        next_line, next_column = None, None
        for index, line in enumerate(lines[start_line - 1:start_line - 1 + line_count], start_line):
            column = start_column if index == start_line else 1
            text = line[column - 1:]
            piece = text[:files.MAX_OUTPUT - size]
            if piece:
                selected.append(piece)
                numbers.append(index)
            size += len(piece)
            if len(piece) < len(text):
                next_line, next_column = index, column + len(piece)
                break
            if index < len(lines):
                next_line, next_column = index + 1, 1
            else:
                next_line, next_column = None, None
        end = numbers[-1] if numbers else start_line - 1
        record = {"snapshot_id": str(uuid.uuid4()), "run_id": run["id"], "rel_path": relative,
                  "sha256": version, "identity": identity, "root_identity": files.file_identity(root),
                  "root_path": str(root), "text": raw.decode("utf-8"), "created_at": now()}
        if execution:
            record.update(execution_id=execution["id"], operation_id=execution["operation_id"], tool_call_id=execution["tool_call_id"])
        with self.store.transaction():
            self.store.db.execute("INSERT INTO file_snapshots VALUES (?,?,?,?,?)", (record["snapshot_id"], run["id"], relative, version, self.store._pack(record)))
        return {"schema_version": "2", "rel_path": relative, "content": "".join(selected),
                "line_numbers": numbers, "start_column": start_column,
                "start_line": start_line, "end_line": end, "total_lines": len(lines), "sha256": version,
                "snapshot_id": record["snapshot_id"], "version_id": version, "truncated": next_line is not None,
                "next_line": next_line, "next_column": next_column}

    def snapshot(self, run_id: str, snapshot_id: str) -> dict:
        row = self.store.db.execute("SELECT data FROM file_snapshots WHERE id=? AND run_id=?", (snapshot_id, run_id)).fetchone()
        if not row:
            raise ValueError("读取版本不存在或不属于当前任务，请先读取文件")
        return self.store._unpack(row[0])

    def latest(self, run_id: str, relative: str) -> str:
        row = self.store.db.execute("SELECT id FROM file_snapshots WHERE run_id=? AND rel_path=? ORDER BY rowid DESC LIMIT 1", (run_id, relative)).fetchone()
        if not row:
            raise ValueError("修改已有文件前必须先调用 read_code_file 读取当前版本")
        return row[0]
