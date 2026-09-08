"""重建固定编码任务并独立判定产物；不会调用模型或自动安装依赖。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

from coding_validation_process import managed_process

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "tests/coding_acceptance/tasks.json"


def load_catalog() -> dict:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    tasks = catalog["tasks"]
    if len(tasks) != 30 or len({task["id"] for task in tasks}) != 30:
        raise ValueError("基线必须包含 30 个唯一任务")
    for task in tasks:
        if not task["cases"] or set(task["editable_files"]) - task["files"].keys():
            raise ValueError("任务缺少判定样例或可编辑文件")
        for name in task["files"]:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
                raise ValueError("任务夹具路径越界")
    return catalog


def materialize(task: dict, destination: Path) -> None:
    destination = destination.absolute()
    parent = destination.parent.resolve(strict=True)
    if destination.exists() or destination.is_symlink():
        raise ValueError("只允许创建全新任务目录，不覆盖已有工作")
    destination.mkdir()
    if destination.resolve().parent != parent:
        raise ValueError("任务目录越界")
    for relative, content in task["files"].items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def inspect_files(task: dict, directory: Path) -> tuple[list[str], dict | None]:
    modified = []
    for name, original in task["files"].items():
        path = directory / name
        if path.is_symlink() or not path.resolve().is_relative_to(directory) or not path.is_file():
            return modified, {"passed": False, "reason": "missing_or_unsafe_file", "file": name}
        if name not in task["editable_files"] and path.read_bytes() != original.encode("utf-8"):
            return modified, {"passed": False, "reason": "user_work_changed", "file": name}
        if path.read_bytes() != original.encode("utf-8"):
            modified.append(name)
    return modified, None


def judge(task: dict, directory: Path) -> dict:
    directory = directory.resolve(strict=True)
    modified, error = inspect_files(task, directory)
    if error:
        return error
    target = directory / task["editable_files"][0]
    # 判定器保留在目标项目以外，候选项目中没有答案或可修改的测试。
    if task["language"] == "python":
        program = (
            "import importlib.util,json,sys; "
            "spec=importlib.util.spec_from_file_location('candidate',sys.argv[1]); "
            "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
            "print(json.dumps([module.solve(x) for x in json.load(sys.stdin)],ensure_ascii=False))"
        )
        command = [sys.executable, "-I", "-X", "utf8", "-B", "-c", program, str(target)]
    else:
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("缺少 Node，不能将环境缺失计作产品失败")
        program = (
            "import fs from 'node:fs'; import {pathToFileURL} from 'node:url'; "
            "const m=await import(pathToFileURL(process.argv[1]).href); "
            "console.log(JSON.stringify(JSON.parse(fs.readFileSync(0,'utf8')).map(x=>m.solve(x))));"
        )
        command = [node, "--input-type=module", "-e", program, str(target)]
    environment = {k: v for k, v in os.environ.items() if k.upper() in {
        "SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP",
    }}
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            with managed_process(command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                 cwd=directory, env=environment) as process:
                process.communicate(json.dumps([case[0] for case in task["cases"]]).encode("utf-8"), timeout=10)
        except subprocess.TimeoutExpired:
            return {"passed": False, "reason": "candidate_timeout"}
        if process.returncode != 0:
            return {"passed": False, "reason": "candidate_error", "exit_code": process.returncode}
        if stdout.tell() > 1024 * 1024 or stderr.tell() > 1024 * 1024:
            return {"passed": False, "reason": "output_limit"}
        stdout.seek(0)
        output = stdout.read()
    try:
        outputs = json.loads(output.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"passed": False, "reason": "invalid_json_output"}
    modified, error = inspect_files(task, directory)
    if error:
        return error
    expected = [case[1] for case in task["cases"]]
    matched = json.dumps(outputs, sort_keys=True) == json.dumps(expected, sort_keys=True)
    return {"passed": matched, "reason": "matched" if matched else "assertion_failed",
            "case_count": len(expected), "modified_files": modified,
            "artifact_sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["list", "rebuild", "judge"])
    parser.add_argument("--task")
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    catalog = load_catalog()
    if args.action == "list":
        print(json.dumps([{k: task[k] for k in ("id", "repository", "split", "title")} for task in catalog["tasks"]], ensure_ascii=False, indent=2))
        return 0
    task = next((task for task in catalog["tasks"] if task["id"] == args.task), None)
    if task is None or args.directory is None:
        parser.error("必须指定有效的 --task 和 --directory")
    if args.action == "rebuild":
        materialize(task, args.directory)
        return 0
    result = judge(task, args.directory)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
