"""外部 S6 JSON 契约；配置只描述数据，不提供可导入模块或判定脚本。"""
from __future__ import annotations

import hashlib
import json
import math
import re
import stat
from collections import Counter
from pathlib import Path

LIMIT = 8 * 1024 * 1024
COMMANDS = {"python": ["python", "-m", "pytest"], "vue-typescript": ["npm", "test"],
            "rust": ["cargo", "test", "--offline"]}
CONTRACTS = {"python": "python-response-v1", "vue-typescript": "vue-ssr-v1", "rust": "rust-vector-v1"}
BUDGET_LIMITS = {"max_model_requests": 24, "max_tool_calls": 48, "max_active_seconds": 600,
                 "max_attempt_tokens": 120000, "max_total_tokens": 10800000}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def fields(value, required: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("JSON 字段缺失或存在未知字段")


def nonempty(value, limit=2000) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError("文本为空、类型错误或超过配额")


def sha256(value) -> None:
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("SHA256 格式无效")


def safe_relative(name: str) -> None:
    if not isinstance(name, str) or not name or len(name) > 240:
        raise ValueError("任务文件路径无效")
    parts = name.split("/")
    for part in parts:
        if (part in {"", ".", ".."} or part.endswith((" ", "."))
                or any(ord(char) < 32 or char in '\\:*?"<>|' for char in part)
                or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", part)):
            raise ValueError("任务文件路径越界或存在 Windows 别名")


def plain_path(path: Path, *, must_exist=True) -> Path:
    path = path.absolute()
    for part in [*reversed(path.parents), path]:
        try:
            status = part.lstat()
        except FileNotFoundError:
            if must_exist:
                raise
            continue
        if (stat.S_ISLNK(status.st_mode) or getattr(status, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                or stat.S_ISREG(status.st_mode) and status.st_nlink != 1):
            raise ValueError("路径包含链接、重解析点或硬链接")
    if path.resolve() != path:
        raise ValueError("路径未经规范化或越界")
    return path


def file_hash(path: Path) -> str:
    plain_path(path)
    if not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError("清单输入不是有界普通文件")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("JSON 含重复字段")
            value[key] = item
        return value

    file_hash(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("JSON 非有限数值")))
    except (RecursionError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("JSON 编码、结构或深度无效") from error


def budget(value) -> None:
    fields(value, {*BUDGET_LIMITS, "cost_usd"})
    for key, ceiling in BUDGET_LIMITS.items():
        if type(value[key]) is not int or not 1 <= value[key] <= ceiling:
            raise ValueError("预算必须为受支持范围内的整数")
    if value["max_total_tokens"] < value["max_attempt_tokens"] or value["cost_usd"] is not None:
        raise ValueError("总预算过小或声明了尚不支持的费用预算")


def file_map(value: dict, *, initial=False) -> None:
    if not isinstance(value, dict) or not 1 <= len(value) <= 1000:
        raise ValueError("文件集合为空或超过配额")
    aliases = set()
    size = 0
    for name, content in value.items():
        safe_relative(name)
        alias = name.casefold()
        if alias in aliases or any(alias.startswith(other + "/") or other.startswith(alias + "/") for other in aliases):
            raise ValueError("文件路径重复、大小写冲突或父子冲突")
        aliases.add(alias)
        if initial and any(part.casefold() in {".git", ".cargo", "target", "__pycache__", "node_modules"}
                           or part.casefold().startswith(".env") for part in name.split("/")):
            raise ValueError("初始文件包含保留目录或环境配置")
        if not isinstance(content, str) or "\x00" in content or "\r" in content:
            raise ValueError("文件内容必须为使用 LF 的 UTF-8 文本")
        size += len(content.encode("utf-8"))
    if size > LIMIT:
        raise ValueError("文件内容超过 8 MiB 配额")


def distribution(tasks: list[dict]) -> None:
    if len(tasks) != 30 or len({task["id"].casefold() for task in tasks}) != 30:
        raise ValueError("S6 必须包含 30 个唯一任务")
    if Counter(task["family"] for task in tasks) != dict.fromkeys(COMMANDS, 10):
        raise ValueError("S6 项目语言分布不符")
    if Counter(task["category"] for task in tasks) != dict.fromkeys(
            ("bug", "feature", "refactor", "long_context", "recovery", "boundary"), 5):
        raise ValueError("S6 主分类分布不符")
    for family in COMMANDS:
        if Counter(task["split"] for task in tasks if task["family"] == family) != {"development": 6, "holdout": 4}:
            raise ValueError("S6 开发/保留集划分不符")


def load_external(path: Path) -> dict:
    path = plain_path(path)
    frozen_hash = file_hash(path)
    data = read_json(path)
    fields(data, {"schema_version", "version", "purpose", "repetitions", "quality_target", "budget", "tasks", "assessment"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("不支持的题集 schema 版本")
    nonempty(data["version"], 120)
    if data["purpose"] not in ("public_calibration", "independent_evaluation"):
        raise ValueError("题集用途无效")
    if type(data["repetitions"]) is not int or data["repetitions"] != 3 or type(data["quality_target"]) is not float or data["quality_target"] != 0.8:
        raise ValueError("正式计划固定为三次重复及 0.8 质量目标")
    budget(data["budget"])
    fields(data["assessment"], {"path", "sha256"})
    safe_relative(data["assessment"]["path"])
    sha256(data["assessment"]["sha256"])
    assessment = plain_path(path.parent / data["assessment"]["path"])
    if file_hash(assessment) != data["assessment"]["sha256"]:
        raise ValueError("验收材料摘要不符")
    if not isinstance(data["tasks"], list) or not data["tasks"]:
        raise ValueError("题集为空或类型错误")
    task_fields = {"id", "family", "category", "split", "title", "coding_goal", "expected_system_behavior", "scenario",
                   "source", "license", "source_revision", "files", "file_sha256", "editable_files", "validation_command",
                   "holdout_exposure", "budget", "judge_contract"}
    for task in data["tasks"]:
        fields(task, task_fields)
        if not isinstance(task["id"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", task["id"]):
            raise ValueError("任务 ID 无效")
        for key in ("title", "source", "license"):
            nonempty(task[key])
        if not isinstance(task["family"], str) or task["family"] not in COMMANDS:
            raise ValueError("语言无效")
        if task["category"] not in ("bug", "feature", "refactor", "long_context", "recovery", "boundary") or task["split"] not in ("development", "holdout"):
            raise ValueError("分类或分组无效")
        if type(task["coding_goal"]) is not bool or task["expected_system_behavior"] not in ("verified_change", "blocked_without_write"):
            raise ValueError("编码目标或预期行为无效")
        if task["scenario"] not in ("normal", "deny", "pause_resume", "failure_then_fix"):
            raise ValueError("系统场景无效")
        if (task["scenario"] == "deny") != (task["expected_system_behavior"] == "blocked_without_write"):
            raise ValueError("拒绝场景与预期系统行为不符")
        if task["holdout_exposure"] not in ("public_calibration", "unexposed", "contaminated"):
            raise ValueError("题集暴露状态无效")
        if data["purpose"] == "public_calibration" and task["holdout_exposure"] != "public_calibration":
            raise ValueError("公开题不能声明为未知保留题")
        file_map(task["files"], initial=True)
        if not {"README.md", "user-notes.txt"} <= task["files"].keys():
            raise ValueError("缺少题面或用户保护文件")
        required_files = {"python": {"src/domain.py", "src/service.py", "tests/test_public.py", "pytest.ini"},
                          "vue-typescript": {"src/model.ts", "src/Result.vue", "tests/public.test.cjs", "package.json"},
                          "rust": {"src/logic.rs", "src/lib.rs", "tests/smoke.rs", "Cargo.toml"}}
        if not required_files[task["family"]] <= task["files"].keys():
            raise ValueError("缺少固定判定契约的初始代码或公开测试")
        if any(name.casefold() == ".s6-tools.json" for name in task["files"]):
            raise ValueError("初始文件占用运行器工具映射")
        fields(task["file_sha256"], set(task["files"]))
        for name, content in task["files"].items():
            sha256(task["file_sha256"][name])
            if hashlib.sha256(content.encode("utf-8")).hexdigest() != task["file_sha256"][name]:
                raise ValueError("初始文件摘要不符")
        sha256(task["source_revision"])
        if hashlib.sha256(json.dumps(task["files"], sort_keys=True, ensure_ascii=False).encode()).hexdigest() != task["source_revision"]:
            raise ValueError("任务初始版本摘要不符")
        editable = task["editable_files"]
        if (not isinstance(editable, list) or not editable or any(not isinstance(name, str) for name in editable)
                or len(set(editable)) != len(editable) or not set(editable) <= task["files"].keys()
                or any(not name.startswith("src/") for name in editable)):
            raise ValueError("可修改范围必须为唯一的现有 src 文件")
        if task["validation_command"] != COMMANDS[task["family"]] or task["judge_contract"] != CONTRACTS[task["family"]]:
            raise ValueError("不支持的验证命令或判定契约")
        budget(task["budget"])
        if any(task["budget"][key] > data["budget"][key] for key in BUDGET_LIMITS):
            raise ValueError("任务预算超过题集预算")
    distribution(data["tasks"])
    if file_hash(path) != frozen_hash:
        raise ValueError("加载时题集发生变化")
    data.update(catalog_sha256=frozen_hash, catalog_path=str(path), catalog_source="external_json",
                blind_quality_eligible=False, isolation={"verified": False, "reason": "independent_execution_backend_unavailable"})
    for task in data["tasks"]:
        task.update(task_sha256=fingerprint(task), assessment_path=str(assessment),
                    assessment_sha256=data["assessment"]["sha256"], catalog_source="external_json", purpose=data["purpose"])
    verify_catalog(data)
    return data


def assessment_for(task: dict, data=None) -> dict:
    if data is None:
        path = Path(task["assessment_path"])
        if file_hash(path) != task["assessment_sha256"]:
            raise ValueError("验收材料摘要变化")
        data = read_json(path)
    fields(data, {"schema_version", "tasks"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or not isinstance(data["tasks"], dict):
        raise ValueError("验收清单版本或任务集合无效")
    item = data["tasks"].get(task["id"])
    fields(item, {"cases", "exception_cases", "reference_files", "forbidden_fragments", "timeout_seconds", "output_bytes"})
    if (type(item["timeout_seconds"]) not in {float, int} or not math.isfinite(item["timeout_seconds"])
            or not 0 < item["timeout_seconds"] <= 30 or type(item["output_bytes"]) is not int or not 1 <= item["output_bytes"] <= 64000):
        raise ValueError("判定时长或输出配额无效")
    file_map(item["reference_files"])
    if set(item["reference_files"]) != set(task["editable_files"]):
        raise ValueError("参考文件与可修改范围不符")
    fragments = item["forbidden_fragments"]
    if not isinstance(fragments, dict) or not fragments.keys() <= set(task["editable_files"]):
        raise ValueError("结构约束范围无效")
    for values in fragments.values():
        if not isinstance(values, list) or not 1 <= len(values) <= 20:
            raise ValueError("结构约束集合无效")
        for value in values:
            nonempty(value, 10000)
    if not isinstance(item["cases"], list) or not 1 <= len(item["cases"]) <= 100:
        raise ValueError("验收样例为空或过多")
    for case in item["cases"]:
        if not isinstance(case, list) or len(case) != 2:
            raise ValueError("验收样例必须为输入和输出对")
        if task["family"] == "rust" and any(not isinstance(values, list) or len(values) > 1000
                or any(type(value) is not int or not -(2**63) <= value < 2**63 for value in values) for values in case):
            raise ValueError("Rust 契约只接受有界 i64 向量")
    if not isinstance(item["exception_cases"], list) or len(item["exception_cases"]) > 20:
        raise ValueError("异常样例格式无效")
    for case in item["exception_cases"]:
        fields(case, {"input", "error"})
        if task["family"] != "python" or case["error"] not in ("ValueError", "TypeError"):
            raise ValueError("不支持的异常契约")
    return item


def verify_catalog(catalog: dict) -> None:
    if file_hash(Path(catalog["catalog_path"])) != catalog["catalog_sha256"]:
        raise ValueError("题集摘要变化")
    if catalog["catalog_source"] == "external_json":
        task = catalog["tasks"][0]
        path = Path(task["assessment_path"])
        if file_hash(path) != task["assessment_sha256"]:
            raise ValueError("验收材料摘要变化")
        data = read_json(path)
        fields(data, {"schema_version", "tasks"})
        fields(data["tasks"], {task["id"] for task in catalog["tasks"]})
        for task in catalog["tasks"]:
            assessment_for(task, data)
