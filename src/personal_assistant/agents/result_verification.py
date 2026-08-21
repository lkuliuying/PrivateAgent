"""R4 领域级工具结果验证器（result verification）。

与 ``verification.py`` 的 ``OutputVerifier``（验证模型最终输出）不同，本模块验证
**工具执行结果**：工具完成后、结果返回模型前，由可信代码对磁盘/命令/API/数据库
事实做复核。约束（`docs/archive/planning/remaining-work-plan-20260806.md` §7.2）：

- 验证器由可信代码固定：``ValidatedToolDispatcher`` 注入，模型不能选择或宣称通过；
- 验证器本身不增加 capability、不消费审批、不执行未审批副作用（只读复核）；
- 失败只产生有界反馈（``ResultVerification.message`` ≤ 2000 字符），执行失败事件
  写入 durable run 事实（``agent_tool_executions``），重试受 run 的 max_tool_calls 约束；
- 验证结果不保存秘密、完整文件或无界 stderr。

实现顺序（§7.1）：1 文件 Diff → 2 代码 → 3 Shell → 4 API → 5 数据库 → 6 多步骤完成条件。
"""
from __future__ import annotations

import hashlib
import re
import sys
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator
from sqlalchemy.ext.asyncio import AsyncSession

MAX_MESSAGE = 2_000
MAX_CORRECTION = 4_000
_CODE_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
MAX_READ_BYTES = 5 * 1024 * 1024


class ResultVerification:
    """One verifier decision on a tool execution result; text is bounded."""

    __slots__ = ("passed", "code", "message", "correction")

    def __init__(
        self,
        passed: bool,
        code: str,
        message: str,
        correction: str | None = None,
    ) -> None:
        if not isinstance(code, str) or not _CODE_PATTERN.fullmatch(code):
            raise ValueError("verification code must match [a-z0-9_]{1,64}")
        if not isinstance(message, str) or not 1 <= len(message) <= MAX_MESSAGE:
            raise ValueError("verification message must contain 1..2000 characters")
        if correction is not None and not 1 <= len(correction) <= MAX_CORRECTION:
            raise ValueError("correction must contain 1..4000 characters")
        self.passed = bool(passed)
        self.code = code
        self.message = message
        self.correction = correction

    @classmethod
    def ok(cls, message: str = "验证通过") -> "ResultVerification":
        return cls(passed=True, code="ok", message=message)

    @classmethod
    def fail(cls, code: str, message: str, correction: str | None = None) -> "ResultVerification":
        return cls(passed=False, code=code, message=message[:MAX_MESSAGE], correction=correction)


class ToolResultVerifier(Protocol):
    name: str

    def supports(self, tool_name: str) -> bool: ...

    async def verify(
        self, tool_name: str, arguments: Mapping[str, Any], result: Any
    ) -> ResultVerification: ...


# ---------------- 1. 文件 Diff 验证器 ----------------


class FileDiffResultVerifier:
    """复核文件 diff 工具结果与磁盘事实一致（§7.1.1）。

    复用现有 old SHA / diff / 回读事实：
    - ``propose_patch``（预览）：磁盘当前内容必须仍等于快照的 ``old_sha256``
      （内容在预览后变化即拒绝，防止基于过期预览继续操作）；
    - ``apply_patch_to_workspace``（写入）：磁盘回读内容 SHA 必须等于结果声明的
      ``new_sha256``；created 文件必须已存在。
    另外从工具入参重新计算 ``new_content`` 的 SHA 与结果 ``new_sha256`` 交叉校验，
    检测被篡改的结果。
    """

    name = "file_diff"

    def __init__(
        self,
        resolve_root: Callable[[int], Awaitable[str]],
        *,
        supported: Iterable[str] = (
            "propose_patch",
            "apply_patch_to_workspace",
            "apply_patch",
        ),
    ) -> None:
        if not callable(resolve_root):
            raise TypeError("resolve_root must be callable")
        self._resolve_root = resolve_root
        self._supported = frozenset(supported)

    def supports(self, tool_name: str) -> bool:
        return tool_name in self._supported

    async def verify(
        self, tool_name: str, arguments: Mapping[str, Any], result: Any
    ) -> ResultVerification:
        if not isinstance(result, Mapping):
            return ResultVerification.fail(
                "result_not_object", "工具结果必须是对象", "返回包含 rel_path 与 SHA 的对象。"
            )
        rel_path = result.get("rel_path")
        if not isinstance(rel_path, str) or not rel_path:
            return ResultVerification.fail(
                "missing_rel_path", "结果缺少 rel_path", "补全 rel_path 后重试。"
            )
        project_id = result.get("project_id") or arguments.get("project_id")
        if not isinstance(project_id, int) or project_id <= 0:
            return ResultVerification.fail(
                "missing_project_id", "结果缺少 project_id", "补全 project_id 后重试。"
            )
        try:
            root = Path(await self._resolve_root(project_id))
            full = _resolve_within(root, rel_path)
        except Exception as exc:  # noqa: BLE001
            return ResultVerification.fail(
                "root_resolution_failed",
                f"无法解析项目路径: {type(exc).__name__}",
            )

        current_sha, exists = _sha256_disk(full)
        result_old = result.get("old_sha256")
        result_new = result.get("new_sha256")

        if tool_name in {"apply_patch_to_workspace", "apply_patch"}:
            if not isinstance(result_new, str) or not result_new:
                return ResultVerification.fail(
                    "missing_new_sha256", "写入类工具结果必须包含 new_sha256"
                )
            if not exists:
                return ResultVerification.fail(
                    "write_missing_file",
                    f"写入校验失败：{rel_path} 不存在（回读事实）",
                    "重新应用补丁，确认文件已写入。",
                )
            if current_sha != result_new:
                return ResultVerification.fail(
                    "write_verification_failed",
                    f"写入校验失败：磁盘 SHA 与结果声明的 new_sha256 不一致（{rel_path}）",
                    "回读文件后重新应用补丁。",
                )
        else:  # 预览类
            expected_old = result_old
            if not isinstance(expected_old, str) or not expected_old:
                return ResultVerification.fail(
                    "missing_old_sha256", "预览类工具结果必须包含 old_sha256"
                )
            if current_sha != expected_old:
                return ResultVerification.fail(
                    "content_changed_since_preview",
                    f"预览后内容已变化（{rel_path}），旧 SHA 不再匹配",
                    "基于最新内容重新生成预览。",
                )

        # 入参交叉校验：new_content → new_sha256 必须一致
        new_content = arguments.get("new_content")
        if isinstance(new_content, str) and isinstance(result_new, str):
            if _sha256_text(new_content) != result_new:
                return ResultVerification.fail(
                    "new_sha256_mismatch",
                    "结果声明的 new_sha256 与入参 new_content 不匹配",
                )
        return ResultVerification.ok(f"文件事实校验通过（{rel_path}）")


# ---------------- 3. Shell 验证器 ----------------


class ShellResultVerifier:
    """复核命令执行工具的退出码、stderr、超时、截断与取消状态（§7.1.3）。"""

    name = "shell"

    def __init__(
        self,
        *,
        supported: Iterable[str] = ("run_whitelisted_command", "run_shell"),
        expected_returncode: int = 0,
        reject_timeout: bool = True,
        reject_cancelled: bool = True,
        reject_truncated: bool = False,
        reject_stderr: bool = False,
    ) -> None:
        self._supported = frozenset(supported)
        self._expected_returncode = int(expected_returncode)
        self._reject_timeout = bool(reject_timeout)
        self._reject_cancelled = bool(reject_cancelled)
        self._reject_truncated = bool(reject_truncated)
        self._reject_stderr = bool(reject_stderr)

    def supports(self, tool_name: str) -> bool:
        return tool_name in self._supported

    async def verify(
        self, tool_name: str, arguments: Mapping[str, Any], result: Any
    ) -> ResultVerification:
        del tool_name, arguments
        if not isinstance(result, Mapping):
            return ResultVerification.fail(
                "result_not_object", "命令执行结果必须是对象"
            )
        if self._reject_cancelled and result.get("cancelled") is True:
            return ResultVerification.fail(
                "shell_cancelled", "命令执行已取消，结果无效", "重新执行命令。"
            )
        if self._reject_timeout and result.get("timed_out") is True:
            return ResultVerification.fail(
                "shell_timeout",
                f"命令超时（限制 {result.get('timeout_seconds')}s 内未完成）",
                "缩短命令或加大超时后重试。",
            )
        if self._reject_truncated and result.get("truncated") is True:
            return ResultVerification.fail(
                "shell_output_truncated",
                "命令输出超过上限被截断，结果不完整",
                "缩小输出范围（如定向测试）后重试。",
            )
        returncode = result.get("returncode")
        if returncode is None or int(returncode) != self._expected_returncode:
            stderr = str(result.get("stderr") or "")[:400]
            return ResultVerification.fail(
                "shell_exit_code_unexpected",
                f"退出码 {returncode} 与预期 {self._expected_returncode} 不一致"
                + (f"；stderr: {stderr}" if stderr else ""),
                "修复命令失败原因后重试。",
            )
        if self._reject_stderr and result.get("stderr"):
            return ResultVerification.fail(
                "shell_stderr_nonempty", "命令在 stderr 输出了内容"
            )
        return ResultVerification.ok(
            f"命令退出码 {returncode} 符合预期，超时/取消状态正常"
        )


# ---------------- 2. 代码验证器 ----------------


class CodeCommandResultVerifier(ShellResultVerifier):
    """代码工作流验证器（§7.1.2）：白名单命令 + 结构化通过标记。

    在 Shell 结构检查之上增加：
    - 命令 args 必须命中白名单前缀（测试/编译/Lint/类型检查）；
    - 输出必须包含命令类型对应的成功标记，出现失败标记即拒绝。
    """

    name = "code_command"

    def __init__(
        self,
        *,
        supported: Iterable[str] = ("run_code_check", "run_whitelisted_command"),
        allowed_prefixes: Sequence[Sequence[str]] = (
            ("pytest",),
            ("python", "-m", "pytest"),
            ("py", "-m", "pytest"),
            ("uv", "run", "pytest"),
            ("npm", "test"),
            ("npm", "run", "build"),
            ("cargo", "check"),
            ("cargo", "test"),
            # E4：当前解释器执行 pytest 是标准用法（Windows sidecar / venv
            # 下 argv[0] 为具体 python.exe 路径，不属于静态前缀）。
            (sys.executable, "-m", "pytest"),
        ),
        success_markers: Sequence[str] = (
            "passed",
            "ok",
            "Finished",
            "built",
            "successful",
            "All checks passed",
        ),
        failure_markers: Sequence[str] = (
            "FAILED",
            "FAILURES",
            "error:",
            "Error:",
            "Traceback",
        ),
    ) -> None:
        super().__init__(supported=supported)
        self._prefixes = tuple(tuple(str(p).casefold() for p in prefix) for prefix in allowed_prefixes)
        self._success_markers = tuple(success_markers)
        self._failure_markers = tuple(failure_markers)

    async def verify(
        self, tool_name: str, arguments: Mapping[str, Any], result: Any
    ) -> ResultVerification:
        shell_check = await super().verify(tool_name, arguments, result)
        if not shell_check.passed:
            return shell_check
        if not isinstance(result, Mapping):
            return ResultVerification.fail(
                "result_not_object", "命令执行结果必须是对象"
            )
        args = result.get("args")
        lowered = tuple(str(a).casefold() for a in args) if isinstance(args, (list, tuple)) else ()
        if not lowered or not any(lowered[: len(prefix)] == prefix for prefix in self._prefixes):
            return ResultVerification.fail(
                "code_command_not_whitelisted",
                "执行命令不在代码检查白名单内",
                "只允许白名单命令（测试/编译/Lint/类型检查）。",
            )
        output = str(result.get("output") or "")
        if any(marker in output for marker in self._failure_markers):
            snippet = _bounded_snippet(output)
            return ResultVerification.fail(
                "code_check_failed",
                f"代码检查输出包含失败标记：{snippet}",
                "修复失败项后重试。",
            )
        if not any(marker in output for marker in self._success_markers):
            return ResultVerification.fail(
                "code_check_no_success_marker",
                "命令退出码为 0，但输出未包含任何成功标记",
            )
        return ResultVerification.ok("代码检查通过（退出码 0 + 成功标记）")


# ---------------- 4. API 验证器 ----------------


class ApiResultVerifier:
    """复核 API 调用工具的状态码、固定响应 Schema、重试与幂等边界（§7.1.4）。"""

    name = "api"

    def __init__(
        self,
        *,
        supported: Iterable[str] = ("call_api", "http_request"),
        allowed_status_ranges: Sequence[tuple[int, int]] = ((200, 299),),
        response_schema: dict[str, Any] | None = None,
        max_attempts: int | None = None,
        require_idempotency_key: bool = False,
        reject_schema_invalid: bool = False,
    ) -> None:
        self._supported = frozenset(supported)
        self._ranges = tuple(
            (int(lo), int(hi)) for lo, hi in allowed_status_ranges
        )
        self._schema = response_schema
        self._validator = (
            Draft202012Validator(response_schema) if response_schema is not None else None
        )
        self._max_attempts = int(max_attempts) if max_attempts is not None else None
        self._require_idempotency_key = bool(require_idempotency_key)
        # v0.5.0 B3：executor 已按 profile 固定响应 Schema 校验并输出
        # schema_valid 字段；开启后该字段为 False 即失败关闭。
        self._reject_schema_invalid = bool(reject_schema_invalid)

    def supports(self, tool_name: str) -> bool:
        return tool_name in self._supported

    async def verify(
        self, tool_name: str, arguments: Mapping[str, Any], result: Any
    ) -> ResultVerification:
        del tool_name, arguments
        if not isinstance(result, Mapping):
            return ResultVerification.fail(
                "result_not_object", "API 调用结果必须是对象"
            )
        if self._reject_schema_invalid and result.get("schema_valid") is False:
            return ResultVerification.fail(
                "api_schema_invalid",
                "响应不符合 endpoint profile 固定 Schema",
                "确认端点返回结构与 profile 的 response_schema 一致。",
            )
        status = result.get("status_code")
        if status is None:
            status = result.get("status")
        if not isinstance(status, int) or not any(
            lo <= status <= hi for lo, hi in self._ranges
        ):
            return ResultVerification.fail(
                "api_status_unexpected",
                f"HTTP 状态码 {status} 不在允许范围 {list(self._ranges)} 内",
                "确认端点可用性与参数后重试。",
            )
        if self._max_attempts is not None:
            attempts = result.get("attempts")
            if isinstance(attempts, int) and attempts > self._max_attempts:
                return ResultVerification.fail(
                    "api_retry_bound_exceeded",
                    f"重试次数 {attempts} 超过上限 {self._max_attempts}",
                )
        if self._require_idempotency_key and not result.get("idempotency_key"):
            return ResultVerification.fail(
                "api_missing_idempotency_key",
                "可重试请求缺少幂等键",
                "为请求提供幂等键后再重试。",
            )
        if self._validator is not None:
            body = result.get("body")
            if body is None:
                body = result.get("response")
            error = next(self._validator.iter_errors(body), None)
            if error is not None:
                path = "$" + "".join(
                    f"[{item}]" if isinstance(item, int) else f".{item}"
                    for item in error.absolute_path
                )
                return ResultVerification.fail(
                    "api_schema_mismatch",
                    f"响应不符合固定 Schema（{path}, rule: {error.validator}）",
                )
        return ResultVerification.ok(f"API 状态码 {status} 与响应结构校验通过")


# ---------------- 5. 数据库验证器 ----------------


class DatabaseResultVerifier:
    """复核数据库工具的事务提交、约束、影响行数与读回（§7.1.5）。"""

    name = "database"

    def __init__(
        self,
        *,
        supported: Iterable[str] = ("execute_sql", "run_database_op"),
        require_commit: bool = True,
        affected_min: int | None = None,
        affected_max: int | None = None,
        readback: Mapping[str, Any] | None = None,
        require_read_only: bool = False,
    ) -> None:
        self._supported = frozenset(supported)
        self._require_commit = bool(require_commit)
        self._affected_min = int(affected_min) if affected_min is not None else None
        self._affected_max = int(affected_max) if affected_max is not None else None
        self._readback = dict(readback) if readback else None
        # v0.5.0 B4：只读查询工作流——结果必须声明只读事务确认且行数/截断受限。
        self._require_read_only = bool(require_read_only)

    def supports(self, tool_name: str) -> bool:
        return tool_name in self._supported

    async def verify(
        self, tool_name: str, arguments: Mapping[str, Any], result: Any
    ) -> ResultVerification:
        del tool_name, arguments
        if not isinstance(result, Mapping):
            return ResultVerification.fail(
                "result_not_object", "数据库执行结果必须是对象"
            )
        if self._require_read_only:
            if result.get("read_only_confirmed") is not True:
                return ResultVerification.fail(
                    "db_not_read_only",
                    "查询未确认为只读事务，结果不可信",
                    "只允许经过只读事务确认的查询结果。",
                )
            row_count = result.get("row_count")
            if not isinstance(row_count, int) or row_count < 0:
                return ResultVerification.fail(
                    "db_row_count_missing", "只读查询结果缺少 row_count"
                )
            columns = result.get("columns")
            rows = result.get("rows")
            if not isinstance(columns, list) or not isinstance(rows, list):
                return ResultVerification.fail(
                    "db_result_shape_invalid", "只读查询结果缺少 columns/rows"
                )
            if len(rows) != min(row_count, len(rows)) or row_count > len(rows) + 1:
                return ResultVerification.fail(
                    "db_row_count_inconsistent",
                    f"row_count {row_count} 与返回行数 {len(rows)} 不一致",
                )
        if self._require_commit and result.get("committed") is not True:
            return ResultVerification.fail(
                "db_not_committed",
                "事务未提交，结果不可信",
                "确认事务提交后再继续。",
            )
        if result.get("constraint_error"):
            return ResultVerification.fail(
                "db_constraint_error",
                f"数据库约束错误：{str(result.get('constraint_error'))[:300]}",
            )
        affected = result.get("affected_rows")
        if self._affected_min is not None or self._affected_max is not None:
            if not isinstance(affected, int):
                return ResultVerification.fail(
                    "db_affected_rows_missing",
                    "结果缺少 affected_rows 计数",
                )
            if self._affected_min is not None and affected < self._affected_min:
                return ResultVerification.fail(
                    "db_affected_rows_unexpected",
                    f"影响行数 {affected} 低于预期下限 {self._affected_min}",
                )
            if self._affected_max is not None and affected > self._affected_max:
                return ResultVerification.fail(
                    "db_affected_rows_unexpected",
                    f"影响行数 {affected} 超过预期上限 {self._affected_max}",
                )
        if self._readback is not None:
            readback = result.get("readback")
            if not isinstance(readback, Mapping):
                return ResultVerification.fail(
                    "db_readback_missing", "结果缺少读回记录 readback"
                )
            for key, expected in self._readback.items():
                if readback.get(key) != expected:
                    return ResultVerification.fail(
                        "db_readback_mismatch",
                        f"读回字段 {key} 与预期不一致",
                    )
        return ResultVerification.ok(
            f"事务已提交，影响行数 {affected} 与读回校验通过"
        )


# ---------------- 6. 多步骤完成条件 ----------------


CompletionPredicate = Callable[[], Awaitable[bool]]


class WorkflowCompletionVerifier:
    """多步骤工作流的完成条件验证（§7.1.6）。

    完成条件由可信调用方（工作流代码）定义并固定，模型不能通过自由填写
    "完成"字段宣称完成。``verify`` 在真实事实（如回读文件、durable 事件、
    数据库行）上求值全部条件。
    """

    name = "workflow_completion"

    def __init__(self, conditions: Sequence[tuple[str, CompletionPredicate]]) -> None:
        if not conditions:
            raise ValueError("completion conditions must not be empty")
        self._conditions = tuple(conditions)

    async def verify(
        self,
        tool_name: str = "",
        arguments: Mapping[str, Any] | None = None,
        result: Any = None,
    ) -> ResultVerification:
        del tool_name, arguments, result
        unmet: list[str] = []
        for name, predicate in self._conditions:
            try:
                satisfied = bool(await predicate())
            except Exception:  # noqa: BLE001
                satisfied = False
            if not satisfied:
                unmet.append(name)
        if unmet:
            return ResultVerification.fail(
                "completion_not_met",
                "工作流完成条件未满足：" + ", ".join(unmet)[:MAX_MESSAGE],
                "继续执行未完成步骤。",
            )
        return ResultVerification.ok("全部完成条件已满足")


class PatchSetResultVerifier:
    """复核 PatchSet 工具结果与磁盘事实一致（E1，T2/T3）。

    - ``propose_patch_set``（预览）：每个文件磁盘内容 SHA 必须仍等于预览
      保存的 ``old_sha256``（预览后外部编辑即拒绝，防止基于过期预览操作）；
    - ``apply_patch_set``（写入）：按文件操作类型复核磁盘终态——
      create/update 目标存在且 SHA == ``new_sha256``、delete 目标不存在、
      rename 新路径存在且 SHA == ``new_sha256`` 且旧路径不存在；
      结果必须 ``verified=true`` 且状态 ``applied``。

    事实源是 DB 持久化的 PatchSet（含文件级 SHA），不信任模型文本声明；
    错误消息只含相对路径。
    """

    name = "patch_set"

    def __init__(
        self,
        db: AsyncSession,
        *,
        supported: Iterable[str] = ("propose_patch_set", "apply_patch_set"),
    ) -> None:
        self._db = db
        self._supported = frozenset(supported)

    def supports(self, tool_name: str) -> bool:
        return tool_name in self._supported

    async def verify(
        self, tool_name: str, arguments: Mapping[str, Any], result: Any
    ) -> ResultVerification:
        del arguments
        if not isinstance(result, Mapping):
            return ResultVerification.fail(
                "result_not_object", "工具结果必须是对象", "返回包含 patch_set_id 的对象。"
            )
        patch_set_id = result.get("patch_set_id")
        if not isinstance(patch_set_id, str) or not patch_set_id:
            return ResultVerification.fail(
                "missing_patch_set_id", "结果缺少 patch_set_id"
            )
        from ..core.repo_coding_patch_sets import CodingPatchSetRepository

        record = await CodingPatchSetRepository(self._db).get_by_id(patch_set_id)
        if record is None:
            return ResultVerification.fail(
                "patch_set_not_found", "PatchSet 不存在"
            )
        from ..core.workspaces import ProjectWorkspaceService

        workspace = await ProjectWorkspaceService(self._db).get(record.workspace_id)
        if workspace is None:
            return ResultVerification.fail(
                "workspace_not_found", "工作区不存在"
            )
        root = Path(workspace.root_path)
        try:
            if tool_name == "apply_patch_set":
                if record.status != "applied" or result.get("verified") is not True:
                    return ResultVerification.fail(
                        "patch_set_not_verified",
                        "apply 结果必须 verified=true 且状态 applied",
                    )
                decision = self._verify_applied(root, record)
            else:
                decision = self._verify_preview(root, record)
        except (OSError, ValueError) as exc:
            return ResultVerification.fail(
                "patch_set_disk_check_failed",
                f"磁盘复核失败: {type(exc).__name__}",
            )
        if decision is not None:
            return decision
        return ResultVerification.ok(f"PatchSet 事实校验通过（{record.id}）")

    def _verify_preview(self, root: Path, record) -> ResultVerification | None:
        """预览后内容未变：每个文件磁盘 SHA == 预览 old_sha256。"""
        empty_sha = _sha256_text("")
        for item in record.files:
            full = _resolve_within(root, item.rel_path)
            current_sha, exists = _sha256_disk(full)
            if not exists:
                if item.old_sha256 == empty_sha:
                    continue
                return ResultVerification.fail(
                    "preview_file_missing",
                    f"预览文件已消失（{item.rel_path}）",
                )
            if current_sha != item.old_sha256:
                return ResultVerification.fail(
                    "content_changed_since_preview",
                    f"预览后内容已变化（{item.rel_path}），旧 SHA 不再匹配",
                )
        return None

    def _verify_applied(self, root: Path, record) -> ResultVerification | None:
        """写入后磁盘终态与文件级声明一致（T2 事实复核）。"""
        for item in record.files:
            if item.status != "applied":
                return ResultVerification.fail(
                    "patch_file_not_applied",
                    f"文件未标记 applied（{item.rel_path}）",
                )
            full = _resolve_within(root, item.rel_path)
            if item.operation == "rename":
                assert item.new_rel_path is not None
                new_full = _resolve_within(root, item.new_rel_path)
                if full.exists():
                    return ResultVerification.fail(
                        "rename_source_still_exists",
                        f"rename 后源仍存在（{item.rel_path}）",
                    )
                current_sha, exists = _sha256_disk(new_full)
                if not exists or current_sha != item.new_sha256:
                    return ResultVerification.fail(
                        "write_verification_failed",
                        f"rename 目标 SHA 与声明不一致（{item.new_rel_path}）",
                    )
                continue
            if item.operation == "delete":
                if full.exists():
                    return ResultVerification.fail(
                        "delete_target_still_exists",
                        f"delete 后目标仍存在（{item.rel_path}）",
                    )
                continue
            current_sha, exists = _sha256_disk(full)
            if not exists:
                return ResultVerification.fail(
                    "write_missing_file",
                    f"写入校验失败：{item.rel_path} 不存在（回读事实）",
                )
            if current_sha != item.new_sha256:
                return ResultVerification.fail(
                    "write_verification_failed",
                    f"写入校验失败：磁盘 SHA 与声明 new_sha256 不一致（{item.rel_path}）",
                )
        return None


class CompositeToolResultVerifier:
    """按注册顺序对受支持的工具做验证，首个失败即返回。"""

    name = "composite_result"

    def __init__(self, verifiers: Sequence[ToolResultVerifier]) -> None:
        if not verifiers:
            raise ValueError("composite result verifier requires at least one verifier")
        self._verifiers = tuple(verifiers)

    def supports(self, tool_name: str) -> bool:
        return any(verifier.supports(tool_name) for verifier in self._verifiers)

    async def verify(
        self, tool_name: str, arguments: Mapping[str, Any], result: Any
    ) -> ResultVerification:
        for verifier in self._verifiers:
            if verifier.supports(tool_name):
                decision = await verifier.verify(tool_name, arguments, result)
                if not decision.passed:
                    return decision
        return ResultVerification.ok("工具结果验证通过")


# ---------------- 内部工具函数 ----------------


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_disk(full: Path) -> tuple[str, bool]:
    """读取磁盘文件内容（有界）并返回 (sha256, exists)。"""
    if not full.exists() or not full.is_file():
        return _sha256_text(""), False
    if full.stat().st_size > MAX_READ_BYTES:
        raise ValueError("verification read-back file too large")
    return _sha256_text(full.read_text(encoding="utf-8", errors="ignore")), True


def _resolve_within(root: Path, rel_path: str) -> Path:
    """防越界解析：结果必须仍在项目根下。"""
    candidate = (root / rel_path).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError("rel_path escapes the project root")
    return candidate


def _bounded_snippet(output: str, limit: int = 300) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    snippet = "\n".join(lines[-6:])[:limit]
    return snippet.replace("\n", " ⏎ ")[:limit]
