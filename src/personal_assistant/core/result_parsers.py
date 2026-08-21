"""v0.7.0 E2：命令结果解析器（result_parser 枚举冻结于 E0 §6）。

按 profile 的 ``result_parser`` 把已脱敏、有界的命令输出解析为结构化结果，
供 WorkflowCompletionVerifier / Artifact 与报告引用（不信任模型文本声明）。

统一输出结构（有界、脱敏输入复用）：

```json
{
  "parser": "pytest",
  "summary": "8 passed, 1 failed in 1.23s",
  "passed": 8, "failed": 1, "skipped": 0, "errors": 0, "warnings": 0,
  "failures": [{"file", "line", "column", "code", "message"}],
  "truncated": false
}
```

- 失败条目上限 ``MAX_FAILURE_ENTRIES=50``，超限只保留前 50 并置 ``truncated=true``；
- 所有字段有界（file ≤2048、code ≤128、message ≤4000、summary ≤8000）；
- 解析器是纯函数，不执行命令、不访问磁盘，输入即已脱敏的输出文本。
"""

from __future__ import annotations

import re
from typing import Any

RESULT_PARSERS = frozenset(
    {
        "pytest",
        "ruff",
        "mypy",
        "compileall",
        "npm_test",
        "npm_build",
        "npm_lint",
        "vue_tsc",
        "cargo_test",
        "cargo_check",
        "plain",
    }
)

MAX_FAILURE_ENTRIES = 50
_MAX_SUMMARY_CHARS = 8000
_MAX_FILE_CHARS = 2048
_MAX_CODE_CHARS = 128
_MAX_MESSAGE_CHARS = 4000
# 解析输入上限：超出部分不解析（输出本身已在执行层有界）
_MAX_INPUT_CHARS = 2 * 1024 * 1024


def _bounded(text: str, limit: int) -> str:
    return text[:limit]


def _entry(
    message: str,
    *,
    file: str | None = None,
    line: int = 0,
    column: int = 0,
    code: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {"message": _bounded(message, _MAX_MESSAGE_CHARS)}
    if file:
        entry["file"] = _bounded(file, _MAX_FILE_CHARS)
    if line:
        entry["line"] = max(0, int(line))
    if column:
        entry["column"] = max(0, int(column))
    if code:
        entry["code"] = _bounded(code, _MAX_CODE_CHARS)
    return entry


def _make(
    parser: str,
    summary: str,
    failures: list[dict[str, Any]],
    *,
    passed: int | None = None,
    failed: int | None = None,
    skipped: int | None = None,
    errors: int | None = None,
    warnings: int | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "parser": parser,
        "summary": _bounded(summary, _MAX_SUMMARY_CHARS),
        "failures": failures[:MAX_FAILURE_ENTRIES],
        "truncated": truncated or len(failures) > MAX_FAILURE_ENTRIES,
    }
    for key, value in (
        ("passed", passed),
        ("failed", failed),
        ("skipped", skipped),
        ("errors", errors),
        ("warnings", warnings),
    ):
        if value is not None:
            result[key] = max(0, int(value))
    return result


# === 各解析器 ===

_PYTEST_STATS = re.compile(
    r"(?P<passed>\d+)\s+passed|(?P<failed>\d+)\s+failed|"
    r"(?P<skipped>\d+)\s+skipped|(?P<errors>\d+)\s+error",
    re.IGNORECASE,
)
_PYTEST_FAILED = re.compile(r"^FAILED\s+(\S+)\s+-\s+(.*)$", re.MULTILINE)
_PYTEST_SUMMARY = re.compile(
    r"^=+.*\b(\d+ passed.*?)(?=\s*={2,}|\s*$)", re.MULTILINE | re.DOTALL
)


def _parse_pytest(output: str) -> dict[str, Any]:
    stats = _PYTEST_STATS.findall(output)
    counts: dict[str, int] = {}
    for group in stats:
        for name, value in zip(
            ("passed", "failed", "skipped", "errors"), group, strict=False
        ):
            if value:
                counts[name] = counts.get(name, 0) + int(value)
    failures = [
        _entry(message, file=path)
        for path, message in _PYTEST_FAILED.findall(output)
    ]
    match = _PYTEST_SUMMARY.search(output)
    summary = match.group(1).strip() if match else "pytest 输出未含统计行"
    return _make("pytest", summary, failures, **counts)


_RUFF_FOUND = re.compile(r"Found\s+(?P<n>\d+)\s+(?P<kind>errors|warnings)", re.IGNORECASE)
_RUFF_ITEM = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+):\s+"
    r"(?P<code>[A-Z][A-Z0-9]+)\s+(?P<message>.+)$",
    re.MULTILINE,
)


def _parse_ruff(output: str) -> dict[str, Any]:
    found = _RUFF_FOUND.findall(output)
    errors = warnings = None
    for n, kind in found:
        if kind.lower() == "errors":
            errors = int(n)
        else:
            warnings = int(n)
    failures = []
    for m in _RUFF_ITEM.finditer(output):
        failures.append(
            _entry(
                m.group("message"),
                file=m.group("file"),
                line=int(m.group("line")),
                column=int(m.group("col")),
                code=m.group("code"),
            )
        )
    summary = "、".join(f"{n} {k}" for n, k in found) or "ruff 输出未含统计行"
    return _make(
        "ruff", summary, failures, errors=errors, warnings=warnings,
        truncated=False,
    )


_MYPY_FOUND = re.compile(
    r"Found\s+(?P<errors>\d+)\s+errors?\s+in\s+(?P<files>\d+)\s+files", re.IGNORECASE
)
_MYPY_ITEM = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):\s+error:\s+(?P<message>.+?)"
    r"(?:\s*\[(?P<code>[^\]]+)\])?$",
    re.MULTILINE,
)


def _parse_mypy(output: str) -> dict[str, Any]:
    errors = None
    for m in _MYPY_FOUND.finditer(output):
        errors = int(m.group("errors"))
    failures = []
    for m in _MYPY_ITEM.finditer(output):
        failures.append(
            _entry(
                m.group("message"),
                file=m.group("file"),
                line=int(m.group("line")),
                code=m.group("code"),
            )
        )
    summary = "mypy 输出未含统计行"
    if errors is not None:
        summary = f"Found {errors} errors in {len(failures)} files"
    return _make("mypy", summary, failures, errors=errors)


_COMPILEALL_ERROR = re.compile(
    r"^(?P<file>[^:\n]+):\s*Error:\s*(?P<message>.+)$", re.IGNORECASE | re.MULTILINE
)
_COMPILEALL_MISSING = re.compile(
    r"^(?P<file>[^:\n]+):\s*(?P<message>.+)$", re.MULTILINE
)

def _parse_compileall(output: str) -> dict[str, Any]:
    failures = []
    for m in _COMPILEALL_ERROR.finditer(output):
        failures.append(
            _entry(m.group("message"), file=m.group("file"))
        )
    if not failures:
        for m in _COMPILEALL_MISSING.finditer(output):
            if "Error" in m.group("message") or "error" in m.group("message"):
                failures.append(
                    _entry(m.group("message"), file=m.group("file"))
                )
    errors = len(failures)
    summary = f"compileall 完成，{errors} 个错误" if errors else "compileall 全部编译成功"
    return _make("compileall", summary, failures, errors=errors)


_NPM_ERR = re.compile(r"^npm\s+ERR!\s+(?P<message>.+)$", re.MULTILINE)
_JEST_TESTS = re.compile(
    r"Tests:\s+(?P<failed>\d+)\s+failed,\s+(?P<passed>\d+)\s+passed", re.IGNORECASE
)
_NPM_FAIL = re.compile(r"^FAIL\s+(?P<file>\S+)(?P<rest>.*)$", re.MULTILINE)


def _parse_npm_test(output: str) -> dict[str, Any]:
    failures = []
    for m in _NPM_FAIL.finditer(output):
        failures.append(_entry("FAIL", file=m.group("file")))
    for m in _NPM_ERR.finditer(output):
        failures.append(_entry(m.group("message")))
    passed = failed = None
    for m in _JEST_TESTS.finditer(output):
        failed = int(m.group("failed"))
        passed = int(m.group("passed"))
    summary = "npm test 输出未含统计行"
    if passed is not None:
        summary = f"Tests: {failed} failed, {passed} passed"
    elif failures:
        summary = f"npm test 失败（{len(failures)} 条错误）"
    return _make("npm_test", summary, failures, passed=passed, failed=failed)


_NPM_BUILD_ERROR = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+):\s+error\s+"
    r"(?:(?P<code>TS\d+):\s+)?(?P<message>.+)$",
    re.IGNORECASE | re.MULTILINE,
)


def _parse_npm_build(output: str) -> dict[str, Any]:
    failures = [
        _entry(
            m.group("message"),
            file=m.group("file"),
            line=int(m.group("line")),
            column=int(m.group("col")),
            code=m.group("code"),
        )
        for m in _NPM_BUILD_ERROR.finditer(output)
    ]
    for m in _NPM_ERR.finditer(output):
        failures.append(_entry(m.group("message")))
    errors = len(failures)
    summary = f"npm build 失败（{errors} 条错误）" if errors else "npm build 成功"
    return _make("npm_build", summary, failures, errors=errors)


_ESLINT_ITEM = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+)\s+(?P<code>\S+)\s+"
    r"(?P<message>.+)$",
    re.MULTILINE,
)
_ESLINT_PROBLEMS = re.compile(
    r"(?P<n>\d+)\s+problem(?:s)?\s+\((?P<errors>\d+)\s+errors?,\s+"
    r"(?P<warnings>\d+)\s+warnings?\)",
    re.IGNORECASE,
)


def _parse_npm_lint(output: str) -> dict[str, Any]:
    failures = []
    for m in _ESLINT_ITEM.finditer(output):
        failures.append(
            _entry(
                m.group("message"),
                file=m.group("file"),
                line=int(m.group("line")),
                column=int(m.group("col")),
                code=m.group("code"),
            )
        )
    errors = warnings = None
    summary = "npm lint 输出未含统计行"
    for m in _ESLINT_PROBLEMS.finditer(output):
        errors = int(m.group("errors"))
        warnings = int(m.group("warnings"))
        summary = f"{m.group('n')} problems ({errors} errors, {warnings} warnings)"
    return _make(
        "npm_lint", summary, failures, errors=errors, warnings=warnings,
    )


_VUE_TSC_ITEM = re.compile(
    r"^(?P<file>[^(\n]+)\((?P<line>\d+),(?P<col>\d+)\):\s+"
    r"error\s+(?P<code>TS\d+):\s+(?P<message>.+)$",
    re.MULTILINE,
)
_VUE_TSC_FOUND = re.compile(
    r"Found\s+(?P<errors>\d+)\s+errors?(?:\.|$)", re.IGNORECASE
)


def _parse_vue_tsc(output: str) -> dict[str, Any]:
    failures = [
        _entry(
            m.group("message"),
            file=m.group("file"),
            line=int(m.group("line")),
            column=int(m.group("col")),
            code=m.group("code"),
        )
        for m in _VUE_TSC_ITEM.finditer(output)
    ]
    errors = None
    for m in _VUE_TSC_FOUND.finditer(output):
        errors = int(m.group("errors"))
    summary = "vue-tsc 类型检查通过" if errors in (None, 0) else (
        f"Found {errors} errors"
    )
    return _make("vue_tsc", summary, failures, errors=errors)


_CARGO_TEST_RESULT = re.compile(
    r"test result:\s+(?P<ok>ok|FAILED)\.\s+"
    r"(?P<passed>\d+)\s+passed;\s+(?P<failed>\d+)\s+failed;\s+"
    r"(?P<ignored>\d+)\s+ignored",
    re.IGNORECASE,
)
_CARGO_ERROR = re.compile(
    r"^error(?P<code>\[E\d+\])?:\s+(?P<message>.+)$"
)
_CARGO_LOCATION = re.compile(r"^\s*--\>\s+(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+)")


def _parse_cargo(output: str, parser: str) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    for line in output.splitlines():
        m = _CARGO_ERROR.match(line)
        if m:
            if pending is not None:
                failures.append(pending)
            pending = _entry(
                m.group("message"),
                code=(m.group("code") or "").strip("[]") or None,
            )
            continue
        if pending is not None:
            loc = _CARGO_LOCATION.match(line)
            if loc:
                pending["file"] = _bounded(loc.group("file"), _MAX_FILE_CHARS)
                pending["line"] = int(loc.group("line"))
                pending["column"] = int(loc.group("col"))
                failures.append(pending)
                pending = None
    if pending is not None:
        failures.append(pending)
    passed = failed = None
    summary = "cargo 输出未含统计行"
    for m in _CARGO_TEST_RESULT.finditer(output):
        passed = int(m.group("passed"))
        failed = int(m.group("failed"))
        summary = (
            f"test result: {m.group('ok')}. {passed} passed; {failed} failed; "
            f"{m.group('ignored')} ignored"
        )
    if parser == "cargo_check" and not failures:
        summary = "cargo check 未发现编译错误"
    return _make(
        parser, summary, failures, passed=passed, failed=failed,
        errors=len(failures) if parser == "cargo_check" else None,
    )


def _parse_plain(output: str) -> dict[str, Any]:
    return _make("plain", output.strip() or "（无输出）", [])


# === 分派 ===

_PARSERS: dict[str, Any] = {
    "pytest": _parse_pytest,
    "ruff": _parse_ruff,
    "mypy": _parse_mypy,
    "compileall": _parse_compileall,
    "npm_test": _parse_npm_test,
    "npm_build": _parse_npm_build,
    "npm_lint": _parse_npm_lint,
    "vue_tsc": _parse_vue_tsc,
    "cargo_test": lambda out: _parse_cargo(out, "cargo_test"),
    "cargo_check": lambda out: _parse_cargo(out, "cargo_check"),
    "plain": _parse_plain,
}


def parse_command_result(parser: str, output: str) -> dict[str, Any]:
    """按冻结枚举解析命令输出；未知 parser 回落 plain。"""
    if parser not in RESULT_PARSERS:
        return _parse_plain(output)
    bounded = output[:_MAX_INPUT_CHARS]
    return _PARSERS[parser](bounded)
