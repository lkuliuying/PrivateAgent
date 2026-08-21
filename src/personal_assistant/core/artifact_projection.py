"""v0.7.0 E3：Artifact 投影（可信执行层 → 脱敏有界 Artifact 引用）。

冻结依据：``docs/releases/v0.7.0/v0.7.0-e0-contracts-20260821.md`` §3。

投影源是 durable facts（``coding_patch_sets`` 记录、``agent_tool_executions``
执行事实），不是模型文本声明；全部投影受 ``PA_CODING_ARTIFACTS_ENABLED``
控制，flag 关闭时所有方法 no-op（零副作用，回退契约 §10，关闭 Artifact
UI 不删除 execution 事实）。

- ``patch_preview`` / ``patch_applied``：PatchSet 预览/应用成功时即时投影
  （``patch_set_service`` 内调用）；metadata 只含文件清单与统计，diff 原文
  保留在 ``coding_patch_set_files``（UI 经 PatchSet API 读取），不重复存储；
- ``command_result`` / ``test_report`` / ``lint_report`` / ``build_report``：
  run 进入终态时从 executions 重建投影（幂等：按 ``source_execution_id``
  去重，重复调用不产生重复引用）；
- ``final_report``：run 终态时生成，metadata 含来源引用（run_id、关键
  step_id、tool 名列表），不内嵌完整命令输出或文件内容。

所有 metadata 字段有界、脱敏（不含本地绝对路径与 secret）。
"""
from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from ..logging_setup import get_logger
from .run_artifact import RunArtifactService

logger = get_logger(__name__)

# 报告分类（按 result_parsers 枚举；plain 只投影 command_result）
_TEST_PARSERS = frozenset({"pytest", "cargo_test", "npm_test"})
_LINT_PARSERS = frozenset({"ruff", "mypy", "vue_tsc", "npm_lint"})
_BUILD_PARSERS = frozenset({"npm_build", "cargo_check", "compileall"})

# metadata 字段有界上限（与 E0 契约 §3 一致：只保存脱敏、有界、可展示内容）
_MAX_ARGS_CHARS = 1024
_MAX_SUMMARY_CHARS = 8_000
_MAX_FAILURE_ITEMS = 10
_MAX_TOOL_NAMES = 32
_MAX_ARTIFACT_REFS = 32
_MAX_STEP_IDS = 32
_PARSED_KEYS = frozenset({"parser", "summary", "failures", "truncated"})


class ArtifactProjectionService:
    """把可信执行事实投影为 Artifact 引用（flag 关闭时全部 no-op）。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._svc = RunArtifactService(db)

    # ---- PatchSet 即时投影（patch_set_service 调用） ----

    async def project_patch_preview(self, *, run_id: str, patch_set_id: str) -> None:
        """预览成功 → patch_preview Artifact（含文件清单与统计）。"""
        if not cfg.coding_artifacts_enabled:
            return
        patch_set = await self._get_patch_set(run_id, patch_set_id)
        if patch_set is None:
            return
        files = [
            {
                "operation": item.operation,
                "path": item.rel_path,
                "truncated": bool(item.truncated),
            }
            | ({"new_path": item.new_rel_path} if item.new_rel_path else {})
            | ({"old_sha256": item.old_sha256} if item.old_sha256 else {})
            | ({"new_sha256": item.new_sha256} if item.new_sha256 else {})
            for item in patch_set.files
        ]
        metadata: dict[str, Any] = {
            "patch_set_id": patch_set.id,
            "preview_version": patch_set.preview_version,
            "file_count": patch_set.file_count,
            "additions": patch_set.additions,
            "deletions": patch_set.deletions,
            "truncated": bool(patch_set.truncated),
            "files": files,
        }
        if patch_set.base_head_sha:
            metadata["base_head_sha"] = patch_set.base_head_sha
        await self._create(
            run_id=run_id,
            kind="patch_preview",
            title=f"PatchSet 预览（{patch_set.file_count} 个文件）",
            step_id=None,
            metadata=metadata,
        )

    async def project_patch_applied(self, *, run_id: str, patch_set_id: str) -> None:
        """应用成功 → patch_applied Artifact（含文件级终态与 SHA）。"""
        if not cfg.coding_artifacts_enabled:
            return
        patch_set = await self._get_patch_set(run_id, patch_set_id)
        if patch_set is None:
            return
        files = [
            {
                "path": item.rel_path,
                "operation": item.operation,
                "status": item.status,
            }
            | ({"new_path": item.new_rel_path} if item.new_rel_path else {})
            | ({"old_sha256": item.old_sha256} if item.old_sha256 else {})
            | ({"new_sha256": item.new_sha256} if item.new_sha256 else {})
            for item in patch_set.files
        ]
        await self._create(
            run_id=run_id,
            kind="patch_applied",
            title=f"PatchSet 已应用（{patch_set.file_count} 个文件）",
            step_id=None,
            metadata={
                "patch_set_id": patch_set.id,
                "preview_version": patch_set.preview_version,
                "status": patch_set.status,
                "verified": patch_set.status == "applied",
                "file_count": patch_set.file_count,
                "files": files,
            },
        )

    # ---- run 终态重建投影（coordinator 调用；幂等） ----

    async def rebuild_terminal(self, *, run_id: str, status: str) -> None:
        """run 进入终态时从 durable facts 重建 Artifact 并生成 final_report。

        - 命令类 executions → ``command_result``（含 parsed 摘要）；
          parsed.parser 按分类额外投影 ``test_report`` / ``lint_report`` /
          ``build_report``；
        - PatchSet 记录兜底补投影（即时投影失败/flag 后开时）；
        - 最后生成 ``final_report``（来源引用 + 完成条件摘要）。
        全部按来源指纹幂等，重复调用不产生重复引用。
        """
        if not cfg.coding_artifacts_enabled:
            return
        if status not in _TERMINAL_STATUSES:
            return
        from ..agents.executions import ToolExecutionRepository
        from ..agents.repository import AgentRunRepository

        run = await AgentRunRepository(self.db).get_run(run_id)
        if run is None or run.project_id is None:
            return

        step_ids: list[str] = []
        tool_names: list[str] = []
        records = await ToolExecutionRepository(self.db, run_id=run_id).list_for_run()
        # 已投影执行指纹（command_result/报告按 source_execution_id 去重）
        projected_ids = await self._existing_source_execution_ids(run_id)
        for record in records:
            if record.step_id is not None and record.step_id not in step_ids:
                step_ids.append(record.step_id)
            if record.tool_name not in tool_names:
                tool_names.append(record.tool_name)
            if not _is_command_execution(record):
                continue
            if record.id in projected_ids:
                continue
            await self._project_command(record)
            projected_ids.add(record.id)

        patch_sets = await self._list_patch_sets(run_id)
        for patch_set in patch_sets:
            await self._backfill_patch_set(patch_set)
        await self._project_final_report(
            run_id=run_id,
            status=status,
            step_ids=step_ids[: _MAX_STEP_IDS],
            tool_names=tool_names[: _MAX_TOOL_NAMES],
        )

    # ---- 内部实现 ----

    _COMMAND_KINDS = frozenset(
        {"command_result", "test_report", "lint_report", "build_report"}
    )

    async def _existing_source_execution_ids(self, run_id: str) -> set[str]:
        """已投影命令类 Artifact 的 source_execution_id 集合（幂等去重指纹）。"""
        ids: set[str] = set()
        for kind in self._COMMAND_KINDS:
            for metadata in await self._svc.list_metadata_by_kind(run_id, kind):
                source_id = metadata.get("source_execution_id")
                if isinstance(source_id, str):
                    ids.add(source_id)
        return ids

    async def _project_command(self, record) -> None:
        """单条命令执行 → command_result + 按 parser 分类的报告。"""
        output = record.output_json if isinstance(record.output_json, dict) else None
        output = output or {}
        parsed = output.get("parsed") if isinstance(output.get("parsed"), dict) else None
        parser = str(parsed.get("parser")) if parsed else None
        metadata: dict[str, Any] = {
            "source_execution_id": record.id,
            "tool_name": record.tool_name,
            "status": record.status,
            "args": _bounded_args(output.get("args") or record.arguments_json, _MAX_ARGS_CHARS),
            "returncode": output.get("returncode"),
            "succeeded": output.get("succeeded"),
            "cancelled": output.get("cancelled"),
            "truncated": output.get("truncated"),
        }
        if record.step_id:
            metadata["step_id"] = record.step_id
        if output.get("profile"):
            metadata["profile"] = str(output["profile"])[:64]
        if output.get("profile_version"):
            metadata["profile_version"] = output["profile_version"]
        if parsed:
            metadata["parsed"] = _bounded_parsed(parsed)
        await self._create(
            run_id=record.run_id,
            kind="command_result",
            title=f"命令结果：{record.tool_name}",
            step_id=record.step_id,
            metadata=metadata,
        )
        if parser in _TEST_PARSERS:
            await self._project_report(record, parser, "test_report")
        elif parser in _LINT_PARSERS:
            await self._project_report(record, parser, "lint_report")
        elif parser in _BUILD_PARSERS:
            await self._project_report(record, parser, "build_report")

    async def _project_report(self, record, parser: str, kind: str) -> None:
        """解析器分类报告（test/lint/build）：只投影 parsed 摘要，不含原文。"""
        output = record.output_json if isinstance(record.output_json, dict) else None
        parsed = (output or {}).get("parsed")
        if not isinstance(parsed, dict):
            return
        await self._create(
            run_id=record.run_id,
            kind=kind,
            title=_REPORT_TITLES[kind],
            step_id=record.step_id,
            metadata={
                "source_execution_id": record.id,
                "parser": parser,
                "parsed": _bounded_parsed(parsed),
            },
        )

    async def _backfill_patch_set(self, patch_set) -> None:
        """兜底补投影 PatchSet（幂等：按 patch_set_id 去重）。"""
        preview_meta = await self._svc.list_metadata_by_kind(
            patch_set.run_id, "patch_preview"
        )
        if not any(
            str(item.get("patch_set_id")) == patch_set.id for item in preview_meta
        ):
            await self.project_patch_preview(
                run_id=patch_set.run_id, patch_set_id=patch_set.id
            )
        if patch_set.status == "applied":
            applied_meta = await self._svc.list_metadata_by_kind(
                patch_set.run_id, "patch_applied"
            )
            if not any(
                str(item.get("patch_set_id")) == patch_set.id for item in applied_meta
            ):
                await self.project_patch_applied(
                    run_id=patch_set.run_id, patch_set_id=patch_set.id
                )

    async def _get_patch_set(self, run_id: str, patch_set_id: str):
        from .repo_coding_patch_sets import CodingPatchSetRepository

        try:
            patch_set = await CodingPatchSetRepository(self.db).get_by_id(patch_set_id)
        except Exception:  # noqa: BLE001
            logger.warning(
                "artifact projection patch set load failed",
                run_id=run_id,
                patch_set_id=patch_set_id,
                exc_info=True,
            )
            return None
        if patch_set is None or patch_set.run_id != run_id:
            return None
        return patch_set

    async def _project_final_report(
        self,
        *,
        run_id: str,
        status: str,
        step_ids: Sequence[str],
        tool_names: Sequence[str],
    ) -> None:
        """final_report：来源引用 + 完成条件摘要（幂等：只生成一次）。"""
        if await self._svc.list_metadata_by_kind(run_id, "final_report"):
            return
        from ..agents.repository import AgentRunRepository

        run = await AgentRunRepository(self.db).get_run(run_id)
        conditions = (
            dict(run.completion_conditions_json)
            if run is not None and isinstance(run.completion_conditions_json, dict)
            else None
        )
        existing = await self._svc.list_artifacts(run_id, limit=_MAX_ARTIFACT_REFS)
        await self._create(
            run_id=run_id,
            kind="final_report",
            title="编码任务最终报告",
            step_id=None,
            metadata={
                "run_id": run_id,
                "status": status,
                "completion_satisfied": status == "completed",
                "completion_conditions": conditions,
                "step_ids": list(step_ids),
                "tool_names": list(tool_names),
                "artifacts": [
                    {"kind": item["kind"], "title": item["title"]}
                    for item in existing
                    if item.get("kind") != "final_report"
                ][: _MAX_ARTIFACT_REFS],
            },
        )

    async def _create(
        self,
        *,
        run_id: str,
        kind: str,
        title: str,
        step_id: str | None,
        metadata: dict,
    ) -> None:
        try:
            await self._svc.create_artifact(
                run_id=run_id,
                kind=kind,
                title=title,
                step_id=step_id,
                metadata=metadata,
            )
        except Exception:  # noqa: BLE001 - 投影失败不影响执行事实
            logger.warning(
                "artifact projection failed",
                run_id=run_id,
                kind=kind,
                exc_info=True,
            )

    async def _list_patch_sets(self, run_id: str) -> list:
        from .repo_coding_patch_sets import CodingPatchSetRepository

        try:
            return await CodingPatchSetRepository(self.db).list_for_run(run_id)
        except Exception:  # noqa: BLE001
            logger.warning(
                "artifact projection patch set listing failed",
                run_id=run_id,
                exc_info=True,
            )
            return []


_TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "timed_out", "limit_exceeded"}
)

_REPORT_TITLES = {
    "test_report": "测试报告",
    "lint_report": "Lint 报告",
    "build_report": "构建报告",
}


def _is_command_execution(record) -> bool:
    """命令类执行判定：工具名或输出结构（profile/returncode 双特征）。"""
    if record.tool_name == "run_whitelisted_command":
        return True
    output = record.output_json if isinstance(record.output_json, dict) else None
    if output is None:
        return False
    return "profile" in output and "returncode" in output


def _bounded_args(value: Any, limit: int) -> str:
    """命令参数 → 有界单行字符串（不展开 secret 键）。"""
    if isinstance(value, list):
        text = " ".join(str(item) for item in value)
    elif isinstance(value, str):
        text = value
    else:
        text = ""
    return text[:limit]


def _bounded_parsed(parsed: dict) -> dict:
    """parsed 摘要有界化：summary/failures 截断，未知键剔除。"""
    bounded: dict[str, Any] = {}
    for key in _PARSED_KEYS:
        if key in parsed:
            bounded[key] = parsed[key]
    summary = bounded.get("summary")
    if isinstance(summary, str) and len(summary) > _MAX_SUMMARY_CHARS:
        bounded["summary"] = summary[:_MAX_SUMMARY_CHARS] + "…（已截断）"
    failures = bounded.get("failures")
    if isinstance(failures, list):
        bounded["failures"] = [
            {
                key: (str(item[key])[:4000] if isinstance(item.get(key), str) else item[key])
                for key in ("file", "line", "column", "code", "message")
                if key in item
            }
            for item in failures[:_MAX_FAILURE_ITEMS]
            if isinstance(item, dict)
        ]
    for key in ("passed", "failed", "skipped", "errors", "warnings"):
        if key in parsed:
            bounded[key] = parsed[key]
    return bounded
