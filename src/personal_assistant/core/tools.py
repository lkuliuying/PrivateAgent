"""工具调用底座：定义 / 注册 / 执行 / LLM 规划。

设计（docs/phase2-plan.md M1）：
- ToolDefinition：name / description / risk_level / input_schema / output_schema / execute。
- ToolRegistry：注册与查询；for_planning() 提供 LLM 可见的工具清单（排除 restricted）。
- ToolExecutor：按审批状态机执行 confirm 工具，全程写 tool_calls + 同步 activities。
- plan_tool_call：用 LLM 判断用户意图是否匹配某工具，匹配则建 pending_approval 记录。

M1 注册工具：read_file（confirm，校验 trusted_paths，仅 .txt/.md/.markdown）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..logging_setup import get_logger
from . import approvals
from .activities import ActivityService
from .code_tools import (
    apply_patch_to_workspace,
    get_git_diff,
    get_git_status,
    grep_code,
    propose_patch,
    read_code_file,
    run_whitelisted_command,
    search_files,
)
from .files import summarize_path
from .exports import DocNotFound, ExportService
from .learning import LearningNotFound, LearningService
from .models import ToolCall
from .permissions import PermissionError_, RiskLevel, assert_trusted
from .projects import ProjectNotFound
from .provider import OllamaProvider
from .rag import parse_document
from .repo import DocumentRepository
from .repo_tools import ToolCallRepository, TrustedPathRepository
from ..workers.importer import import_document

logger = get_logger(__name__)


class ToolError(RuntimeError):
    """工具执行错误。"""


@dataclass
class ToolContext:
    """工具执行上下文，提供 db 等依赖。"""
    db: AsyncSession


@dataclass
class ToolDefinition:
    name: str
    description: str
    risk_level: str  # RiskLevel 值
    input_schema: dict
    output_schema: dict
    execute: Callable[[dict, ToolContext], Awaitable[dict]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def for_planning(self) -> list[dict]:
        """LLM 可见的工具清单（排除 restricted，第二阶段不开放）。"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "risk_level": t.risk_level,
                "input_schema": t.input_schema,
            }
            for t in self._tools.values()
            if t.risk_level != RiskLevel.RESTRICTED.value
        ]


# ============ read_file 工具 ============

_MAX_FILE_BYTES = 30 * 1024 * 1024  # 30MB
_MAX_CONTENT_CHARS = 50000  # 喂给 LLM 的内容上限
# read_file / import_to_kb 支持的扩展名（与 rag.PARSERS 对齐）
_READABLE_EXT = {".txt", ".md", ".markdown", ".pdf", ".docx"}


def _mime_for(p: Path) -> str:
    ext = p.suffix.lower()
    if ext in {".md", ".markdown"}:
        return "text/markdown"
    if ext == ".pdf":
        return "application/pdf"
    if ext == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "text/plain"


def _assert_readable_file(path: str) -> Path:
    """存在 + 类型 + 大小校验，返回 Path。授权校验由调用方先做。"""
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise ToolError(f"文件不存在或不是文件: {path}")
    if p.suffix.lower() not in _READABLE_EXT:
        raise ToolError(f"仅支持 {sorted(_READABLE_EXT)} 文件")
    size = p.stat().st_size
    if size > _MAX_FILE_BYTES:
        raise ToolError(f"文件过大（{size} 字节，上限 {_MAX_FILE_BYTES} 字节）")
    return p


async def _read_file_execute(inputs: dict, ctx: ToolContext) -> dict:
    path = inputs.get("path")
    if not isinstance(path, str) or not path:
        raise ToolError("缺少参数 path")
    trusted = await TrustedPathRepository(ctx.db).all_paths()
    assert_trusted(path, trusted)  # 未授权/越界抛 PermissionError_
    p = _assert_readable_file(path)
    # parse_document 统一解析 pdf/docx/md/txt（扫描件 PDF 抛 ValueError）
    content = await asyncio.to_thread(parse_document, str(p))
    truncated = len(content) > _MAX_CONTENT_CHARS
    if truncated:
        content = content[:_MAX_CONTENT_CHARS]
    return {
        "path": str(p),
        "content": content,
        "size_bytes": p.stat().st_size,
        "truncated": truncated,
        "mime_type": _mime_for(p),
    }


async def _summarize_file_execute(inputs: dict, ctx: ToolContext) -> dict:
    """读取已授权文件并用 LLM 生成摘要（授权/类型/大小校验由 files.summarize_path 负责）。"""
    path = inputs.get("path")
    if not isinstance(path, str) or not path:
        raise ToolError("缺少参数 path")
    return await summarize_path(ctx.db, path)


def _tool_upload_path(doc_id: int, name: str) -> Path:
    """与 routes_documents._upload_path 一致：data/uploads/{doc_id}{ext}。"""
    ext = Path(name).suffix
    d = Path("./data/uploads")
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{doc_id}{ext}"


# ============ 第三阶段 M1：代码工作区工具 ============

def _require_project_id(inputs: dict) -> int:
    pid = inputs.get("project_id")
    if not isinstance(pid, int) or pid <= 0:
        raise ToolError("缺少有效参数 project_id（正整数）")
    return pid


async def _search_files_execute(inputs: dict, ctx: ToolContext) -> dict:
    return await search_files(ctx.db, _require_project_id(inputs), inputs.get("query", ""))


async def _grep_code_execute(inputs: dict, ctx: ToolContext) -> dict:
    return await grep_code(ctx.db, _require_project_id(inputs), inputs.get("pattern", ""))


async def _read_code_file_execute(inputs: dict, ctx: ToolContext) -> dict:
    pid = _require_project_id(inputs)
    rel = inputs.get("rel_path")
    if not isinstance(rel, str) or not rel:
        raise ToolError("缺少参数 rel_path")
    try:
        return await read_code_file(
            ctx.db,
            pid,
            rel,
            start_line=int(inputs.get("start_line", 1) or 1),
            max_lines=int(inputs.get("max_lines", 2000) or 2000),
        )
    except (PermissionError_, FileNotFoundError, ValueError) as e:
        raise ToolError(str(e)) from e


async def _get_git_status_execute(inputs: dict, ctx: ToolContext) -> dict:
    try:
        return await get_git_status(ctx.db, _require_project_id(inputs))
    except (RuntimeError, TimeoutError) as e:
        raise ToolError(str(e)) from e


async def _get_git_diff_execute(inputs: dict, ctx: ToolContext) -> dict:
    try:
        return await get_git_diff(
            ctx.db,
            _require_project_id(inputs),
            cached=bool(inputs.get("cached", False)),
        )
    except (RuntimeError, TimeoutError) as e:
        raise ToolError(str(e)) from e


async def _propose_patch_execute(inputs: dict, ctx: ToolContext) -> dict:
    rel = inputs.get("rel_path")
    content = inputs.get("new_content")
    if not isinstance(rel, str) or not rel:
        raise ToolError("缺少参数 rel_path")
    if not isinstance(content, str):
        raise ToolError("缺少参数 new_content")
    try:
        return await propose_patch(
            ctx.db,
            _require_project_id(inputs),
            rel,
            content,
            create=bool(inputs.get("create", False)),
        )
    except (ProjectNotFound, PermissionError_, FileNotFoundError, ValueError) as e:
        raise ToolError(str(e)) from e


async def _apply_patch_to_workspace_execute(inputs: dict, ctx: ToolContext) -> dict:
    rel = inputs.get("rel_path")
    content = inputs.get("new_content")
    if not isinstance(rel, str) or not rel:
        raise ToolError("缺少参数 rel_path")
    if not isinstance(content, str):
        raise ToolError("缺少参数 new_content")
    try:
        return await apply_patch_to_workspace(
            ctx.db,
            _require_project_id(inputs),
            rel,
            content,
            expected_old_sha256=inputs.get("expected_old_sha256"),
            create=bool(inputs.get("create", False)),
        )
    except (
        ProjectNotFound,
        PermissionError_,
        FileNotFoundError,
        RuntimeError,
        ValueError,
    ) as e:
        raise ToolError(str(e)) from e


async def _run_whitelisted_command_execute(inputs: dict, ctx: ToolContext) -> dict:
    command = inputs.get("command")
    if not isinstance(command, (str, list)):
        raise ToolError("缺少参数 command")
    try:
        return await run_whitelisted_command(
            ctx.db,
            _require_project_id(inputs),
            command,
            timeout=float(inputs.get("timeout", 120) or 120),
        )
    except (ProjectNotFound, PermissionError_, RuntimeError, TimeoutError, ValueError) as e:
        raise ToolError(str(e)) from e


# ============ 第三阶段 M3：学习系统工具 ============

def _require_topic_id(inputs: dict) -> int:
    tid = inputs.get("topic_id")
    if not isinstance(tid, int) or tid <= 0:
        raise ToolError("缺少有效参数 topic_id（正整数）")
    return tid


async def _create_learning_plan_execute(inputs: dict, ctx: ToolContext) -> dict:
    svc = LearningService(ctx.db)
    try:
        nodes = await svc.generate_plan(
            _require_topic_id(inputs), inputs.get("source_doc_ids")
        )
    except LearningNotFound as e:
        raise ToolError(str(e)) from e
    return {
        "topic_id": _require_topic_id(inputs),
        "nodes": [
            {"id": n.id, "title": n.title, "summary": n.summary} for n in nodes
        ],
        "count": len(nodes),
    }


async def _save_learning_note_execute(inputs: dict, ctx: ToolContext) -> dict:
    title = inputs.get("title")
    body = inputs.get("body_md")
    if not isinstance(title, str) or not title.strip():
        raise ToolError("缺少参数 title")
    if not isinstance(body, str) or not body.strip():
        raise ToolError("缺少参数 body_md")
    svc = LearningService(ctx.db)
    try:
        note = await svc.save_note(
            topic_id=inputs.get("topic_id"),
            title=title,
            body_md=body,
            source_refs=inputs.get("source_refs"),
        )
    except LearningNotFound as e:
        raise ToolError(str(e)) from e
    return {"note_id": note.id, "title": note.title}


async def _generate_quiz_execute(inputs: dict, ctx: ToolContext) -> dict:
    svc = LearningService(ctx.db)
    try:
        quizzes = await svc.generate_quiz(
            _require_topic_id(inputs),
            inputs.get("source_doc_ids"),
            count=int(inputs.get("count", 5) or 5),
        )
    except LearningNotFound as e:
        raise ToolError(str(e)) from e
    return {
        "topic_id": _require_topic_id(inputs),
        "quizzes": [{"id": q.id, "question": q.question} for q in quizzes],
        "count": len(quizzes),
    }


async def _grade_quiz_answer_execute(inputs: dict, ctx: ToolContext) -> dict:
    qid = inputs.get("quiz_id")
    if not isinstance(qid, int) or qid <= 0:
        raise ToolError("缺少有效参数 quiz_id（正整数）")
    user_answer = inputs.get("user_answer")
    if not isinstance(user_answer, str):
        raise ToolError("缺少参数 user_answer")
    svc = LearningService(ctx.db)
    try:
        grade = await svc.grade_attempt(qid, user_answer)
    except LearningNotFound as e:
        raise ToolError(str(e)) from e
    return {"quiz_id": qid, "result": grade.result, "explanation": grade.explanation}


async def _create_review_cards_execute(inputs: dict, ctx: ToolContext) -> dict:
    svc = LearningService(ctx.db)
    try:
        cards = await svc.create_cards(
            _require_topic_id(inputs),
            inputs.get("source_doc_ids"),
            count=int(inputs.get("count", 5) or 5),
        )
    except LearningNotFound as e:
        raise ToolError(str(e)) from e
    return {
        "topic_id": _require_topic_id(inputs),
        "cards": [{"id": c.id, "front": c.front} for c in cards],
        "count": len(cards),
    }


# ============ 第三阶段 M4：文档工作台工具 ============

async def _summarize_document_sections_execute(inputs: dict, ctx: ToolContext) -> dict:
    doc_id = inputs.get("doc_id")
    if not isinstance(doc_id, int) or doc_id <= 0:
        raise ToolError("缺少有效参数 doc_id")
    try:
        sections = await ExportService(ctx.db).summarize_sections(doc_id)
    except DocNotFound as e:
        raise ToolError(str(e)) from e
    return {"doc_id": doc_id, "sections": sections, "count": len(sections)}


async def _compare_documents_execute(inputs: dict, ctx: ToolContext) -> dict:
    doc_ids = inputs.get("doc_ids")
    if not isinstance(doc_ids, list) or len(doc_ids) < 2:
        raise ToolError("doc_ids 需至少 2 个文档 ID")
    try:
        return await ExportService(ctx.db).compare_documents([int(d) for d in doc_ids])
    except (ValueError, DocNotFound) as e:
        raise ToolError(str(e)) from e


async def _export_markdown_execute(inputs: dict, ctx: ToolContext) -> dict:
    content = inputs.get("content")
    filename = inputs.get("filename")
    target_dir = inputs.get("target_dir")
    if not isinstance(content, str) or not content:
        raise ToolError("缺少参数 content")
    if not isinstance(filename, str) or not filename:
        raise ToolError("缺少参数 filename")
    if not isinstance(target_dir, str) or not target_dir:
        raise ToolError("缺少参数 target_dir（须为已授权目录）")
    try:
        return await ExportService(ctx.db).export_markdown(
            content=content, filename=filename, target_dir=target_dir
        )
    except (PermissionError_, ValueError) as e:
        raise ToolError(str(e)) from e


async def _import_generated_note_to_kb_execute(inputs: dict, ctx: ToolContext) -> dict:
    title = inputs.get("title")
    content = inputs.get("content")
    if not isinstance(content, str) or not content:
        raise ToolError("缺少参数 content")
    try:
        return await ExportService(ctx.db).import_note_to_kb(
            title=title if isinstance(title, str) else "note", content=content
        )
    except ValueError as e:
        raise ToolError(str(e)) from e


async def _import_to_kb_execute(inputs: dict, ctx: ToolContext) -> dict:
    """将已授权文件导入知识库（去重 + 创建 doc + 保存 + 后台导入）。"""
    path = inputs.get("path")
    if not isinstance(path, str) or not path:
        raise ToolError("缺少参数 path")
    trusted = await TrustedPathRepository(ctx.db).all_paths()
    assert_trusted(path, trusted)
    p = _assert_readable_file(path)
    data = await asyncio.to_thread(p.read_bytes)
    c_hash = hashlib.sha256(data).hexdigest()
    docs = DocumentRepository(ctx.db)
    existing = await docs.get_by_hash(c_hash)
    if existing:
        return {"doc_id": existing.id, "status": "duplicate", "name": existing.name}
    doc = await docs.create(
        name=p.name,
        source_path=str(p),
        mime_type=_mime_for(p),
        size_bytes=p.stat().st_size,
        content_hash=c_hash,
        embedding_model=settings.embed_model,
    )
    upload_path = _tool_upload_path(doc.id, p.name)
    await asyncio.to_thread(upload_path.write_bytes, data)
    asyncio.create_task(import_document(doc.id, str(upload_path)))
    return {"doc_id": doc.id, "status": "imported", "name": p.name}


def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            name="read_file",
            description="读取用户已授权的本地文件（.txt/.md/.markdown/.pdf/.docx）内容。需用户先授权路径。",
            risk_level=RiskLevel.CONFIRM.value,
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "已授权的文件绝对路径"}
                },
                "required": ["path"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "size_bytes": {"type": "integer"},
                    "truncated": {"type": "boolean"},
                },
            },
            execute=_read_file_execute,
        )
    )
    reg.register(
        ToolDefinition(
            name="summarize_file",
            description="读取用户已授权的本地文件并用 LLM 生成摘要（.txt/.md/.markdown/.pdf/.docx）。需用户先授权路径。",
            risk_level=RiskLevel.CONFIRM.value,
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "已授权的文件绝对路径"}
                },
                "required": ["path"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "name": {"type": "string"},
                    "truncated": {"type": "boolean"},
                },
            },
            execute=_summarize_file_execute,
        )
    )
    reg.register(
        ToolDefinition(
            name="import_to_kb",
            description="将用户已授权的本地文件导入知识库（重复文件自动跳过）。支持 .txt/.md/.markdown/.pdf/.docx。",
            risk_level=RiskLevel.CONFIRM.value,
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "已授权的文件绝对路径"}
                },
                "required": ["path"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "integer"},
                    "status": {"type": "string"},
                    "name": {"type": "string"},
                },
            },
            execute=_import_to_kb_execute,
        )
    )
    # ---- 第三阶段 M1：代码工作区只读工具 ----
    reg.register(
        ToolDefinition(
            name="search_files",
            description="在已授权的项目中按文件名/相对路径搜索文件（需先授权项目并在聊天或项目页获得 project_id）。",
            risk_level=RiskLevel.SAFE.value,
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "已授权项目 ID"},
                    "query": {"type": "string", "description": "文件名或路径片段"},
                },
                "required": ["project_id", "query"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "results": {"type": "array"},
                    "count": {"type": "integer"},
                },
            },
            execute=_search_files_execute,
        )
    )
    reg.register(
        ToolDefinition(
            name="grep_code",
            description="在已授权项目内按正则搜索代码内容，返回文件路径、行号与上下文。",
            risk_level=RiskLevel.SAFE.value,
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "已授权项目 ID"},
                    "pattern": {"type": "string", "description": "正则表达式"},
                },
                "required": ["project_id", "pattern"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "results": {"type": "array"},
                    "count": {"type": "integer"},
                    "truncated": {"type": "boolean"},
                },
            },
            execute=_grep_code_execute,
        )
    )
    reg.register(
        ToolDefinition(
            name="read_code_file",
            description="读取已授权项目内的代码文件片段（按行分页）。rel_path 必须为项目内相对路径。",
            risk_level=RiskLevel.CONFIRM.value,
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "已授权项目 ID"},
                    "rel_path": {"type": "string", "description": "项目内相对路径"},
                    "start_line": {"type": "integer", "description": "起始行，默认 1"},
                    "max_lines": {"type": "integer", "description": "最多读取行数，默认 2000"},
                },
                "required": ["project_id", "rel_path"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "language": {"type": "string"},
                    "line_count": {"type": "integer"},
                    "truncated": {"type": "boolean"},
                },
            },
            execute=_read_code_file_execute,
        )
    )
    reg.register(
        ToolDefinition(
            name="get_git_status",
            description="读取已授权项目的 git 状态（分支、改动文件列表）。只读，不修改。",
            risk_level=RiskLevel.SAFE.value,
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "已授权项目 ID"}
                },
                "required": ["project_id"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "branch": {"type": "string"},
                    "clean": {"type": "boolean"},
                    "changed": {"type": "array"},
                },
            },
            execute=_get_git_status_execute,
        )
    )
    reg.register(
        ToolDefinition(
            name="get_git_diff",
            description="读取已授权项目的 git diff（未暂存或已暂存）。只读，不修改。",
            risk_level=RiskLevel.SAFE.value,
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "已授权项目 ID"},
                    "cached": {"type": "boolean", "description": "是否查看已暂存 diff"},
                },
                "required": ["project_id"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "diff": {"type": "string"},
                    "truncated": {"type": "boolean"},
                },
            },
            execute=_get_git_diff_execute,
        )
    )
    # ---- 第三阶段 M5：编码修改与命令验证 ----
    reg.register(
        ToolDefinition(
            name="propose_patch",
            description="为已授权项目中的单个文件生成替换式 unified diff 预览；只读，不写入文件。",
            risk_level=RiskLevel.SAFE.value,
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "已授权项目 ID"},
                    "rel_path": {"type": "string", "description": "项目内相对路径"},
                    "new_content": {"type": "string", "description": "拟写入的完整新文件内容"},
                    "create": {"type": "boolean", "description": "文件不存在时是否按新文件预览"},
                },
                "required": ["project_id", "rel_path", "new_content"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "diff": {"type": "string"},
                    "old_sha256": {"type": "string"},
                    "new_sha256": {"type": "string"},
                    "changed": {"type": "boolean"},
                },
            },
            execute=_propose_patch_execute,
        )
    )
    reg.register(
        ToolDefinition(
            name="apply_patch_to_workspace",
            description="审批后把拟定内容写入已授权项目文件；可带 expected_old_sha256 防止应用过期补丁。",
            risk_level=RiskLevel.CONFIRM.value,
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "已授权项目 ID"},
                    "rel_path": {"type": "string", "description": "项目内相对路径"},
                    "new_content": {"type": "string", "description": "完整新文件内容"},
                    "expected_old_sha256": {"type": "string", "description": "预览时返回的旧内容哈希"},
                    "create": {"type": "boolean", "description": "是否允许创建新文件"},
                },
                "required": ["project_id", "rel_path", "new_content"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "rel_path": {"type": "string"},
                    "old_sha256": {"type": "string"},
                    "new_sha256": {"type": "string"},
                    "size_bytes": {"type": "integer"},
                    "diff": {"type": "string"},
                },
            },
            execute=_apply_patch_to_workspace_execute,
        )
    )
    reg.register(
        ToolDefinition(
            name="run_whitelisted_command",
            description="审批后在已授权项目根目录运行白名单命令，如 pytest、npm run build、cargo check。",
            risk_level=RiskLevel.CONFIRM.value,
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "已授权项目 ID"},
                    "command": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                        "description": "命令字符串或参数数组",
                    },
                    "timeout": {"type": "number", "description": "超时时间，最大 120 秒"},
                },
                "required": ["project_id", "command"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "returncode": {"type": "integer"},
                    "output": {"type": "string"},
                    "truncated": {"type": "boolean"},
                    "succeeded": {"type": "boolean"},
                },
            },
            execute=_run_whitelisted_command_execute,
        )
    )
    # ---- 第三阶段 M3：学习系统工具 ----
    reg.register(
        ToolDefinition(
            name="create_learning_plan",
            description="基于知识库资料为已创建的学习主题生成学习路线（知识节点列表）。",
            risk_level=RiskLevel.CONFIRM.value,
            input_schema={
                "type": "object",
                "properties": {
                    "topic_id": {"type": "integer", "description": "学习主题 ID"},
                    "source_doc_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "可选：限定资料文档 ID",
                    },
                },
                "required": ["topic_id"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "nodes": {"type": "array"},
                    "count": {"type": "integer"},
                },
            },
            execute=_create_learning_plan_execute,
        )
    )
    reg.register(
        ToolDefinition(
            name="save_learning_note",
            description="把一段内容保存为学习主题下的笔记（Markdown 正文）。",
            risk_level=RiskLevel.CONFIRM.value,
            input_schema={
                "type": "object",
                "properties": {
                    "topic_id": {"type": "integer", "description": "学习主题 ID（可空）"},
                    "title": {"type": "string"},
                    "body_md": {"type": "string", "description": "Markdown 正文"},
                    "source_refs": {"type": "array"},
                },
                "required": ["title", "body_md"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer"},
                    "title": {"type": "string"},
                },
            },
            execute=_save_learning_note_execute,
        )
    )
    reg.register(
        ToolDefinition(
            name="generate_quiz",
            description="基于知识库资料为学习主题生成练习题（含参考答案与解析）。",
            risk_level=RiskLevel.CONFIRM.value,
            input_schema={
                "type": "object",
                "properties": {
                    "topic_id": {"type": "integer", "description": "学习主题 ID"},
                    "source_doc_ids": {"type": "array", "items": {"type": "integer"}},
                    "count": {"type": "integer", "description": "题数，默认 5"},
                },
                "required": ["topic_id"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "quizzes": {"type": "array"},
                    "count": {"type": "integer"},
                },
            },
            execute=_generate_quiz_execute,
        )
    )
    reg.register(
        ToolDefinition(
            name="grade_quiz_answer",
            description="批改用户对某道练习题的答案，返回 correct/partial/wrong 与说明。",
            risk_level=RiskLevel.CONFIRM.value,
            input_schema={
                "type": "object",
                "properties": {
                    "quiz_id": {"type": "integer", "description": "练习题 ID"},
                    "user_answer": {"type": "string"},
                },
                "required": ["quiz_id", "user_answer"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "result": {"type": "string"},
                    "explanation": {"type": "string"},
                },
            },
            execute=_grade_quiz_answer_execute,
        )
    )
    reg.register(
        ToolDefinition(
            name="create_review_cards",
            description="基于知识库资料为学习主题生成复习卡片（正面问题/背面答案）。",
            risk_level=RiskLevel.CONFIRM.value,
            input_schema={
                "type": "object",
                "properties": {
                    "topic_id": {"type": "integer", "description": "学习主题 ID"},
                    "source_doc_ids": {"type": "array", "items": {"type": "integer"}},
                    "count": {"type": "integer", "description": "卡片数，默认 5"},
                },
                "required": ["topic_id"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "cards": {"type": "array"},
                    "count": {"type": "integer"},
                },
            },
            execute=_create_review_cards_execute,
        )
    )
    # ---- 第三阶段 M4：文档工作台工具 ----
    reg.register(
        ToolDefinition(
            name="summarize_document_sections",
            description="为知识库中某文档生成章节摘要（标题 + 摘要列表）。",
            risk_level=RiskLevel.SAFE.value,
            input_schema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "integer", "description": "知识库文档 ID"}
                },
                "required": ["doc_id"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "sections": {"type": "array"},
                    "count": {"type": "integer"},
                },
            },
            execute=_summarize_document_sections_execute,
        )
    )
    reg.register(
        ToolDefinition(
            name="compare_documents",
            description="对比知识库中多个文档，输出共同点/差异/冲突/推荐阅读顺序。",
            risk_level=RiskLevel.SAFE.value,
            input_schema={
                "type": "object",
                "properties": {
                    "doc_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "待对比文档 ID（2-5 个）",
                    }
                },
                "required": ["doc_ids"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "common": {"type": "array"},
                    "differences": {"type": "array"},
                    "conflicts": {"type": "array"},
                    "reading_order": {"type": "array"},
                },
            },
            execute=_compare_documents_execute,
        )
    )
    reg.register(
        ToolDefinition(
            name="export_markdown",
            description="把生成的内容导出为 Markdown 文件到已授权目录（默认新文件名，不覆盖）。需用户授权目标目录。",
            risk_level=RiskLevel.CONFIRM.value,
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Markdown 正文"},
                    "filename": {"type": "string", "description": "文件名（不含路径/扩展名）"},
                    "target_dir": {"type": "string", "description": "已授权的目录绝对路径"},
                },
                "required": ["content", "filename", "target_dir"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "size_bytes": {"type": "integer"},
                },
            },
            execute=_export_markdown_execute,
        )
    )
    reg.register(
        ToolDefinition(
            name="import_generated_note_to_kb",
            description="把生成的 Markdown 内容作为新文档导入知识库（自动切分向量化）。",
            risk_level=RiskLevel.CONFIRM.value,
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "Markdown 正文"},
                },
                "required": ["content"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "integer"},
                    "status": {"type": "string"},
                    "name": {"type": "string"},
                },
            },
            execute=_import_generated_note_to_kb_execute,
        )
    )
    return reg


# 模块级默认注册表（API 路由直接复用）
default_registry: ToolRegistry = build_default_registry()


# ============ 执行器 ============

class ToolExecutor:
    def __init__(self, db: AsyncSession, registry: ToolRegistry | None = None) -> None:
        self.db = db
        self.registry = registry or default_registry
        self.repo = ToolCallRepository(db)
        self.activities = ActivityService(db)

    async def _reload_sync(self, tool_call_id: int) -> ToolCall:
        tc = await self.repo.get_fresh(tool_call_id)
        assert tc is not None
        await self.activities.sync_tool_call(tc)
        return tc

    async def execute_tool_call(self, tool_call_id: int) -> ToolCall:
        """批准后执行工具调用：pending_approval -> running -> succeeded|failed。

        用原子 claim 保证并发 approve 仅一个执行（避免 TOCTOU 双执行）。
        """
        tc = await self.repo.get(tool_call_id)
        if tc is None:
            raise ToolError("工具调用不存在")
        # 原子占用 pending_approval -> running；失败说明已被其他请求处理
        if not await self.repo.claim(
            tc.id, from_status="pending_approval", to_status="running"
        ):
            raise approvals.ApprovalError("工具调用已被处理或状态已变更")
        await self._reload_sync(tool_call_id)

        tool = self.registry.get(tc.tool_name)
        if tool is None:
            err = f"未知工具: {tc.tool_name}"
            await self.repo.update_status(tc.id, status="failed", error_message=err)
            await self._reload_sync(tool_call_id)
            raise ToolError(err)

        try:
            output = await tool.execute(tc.input_json or {}, ToolContext(self.db))
        except Exception as e:  # noqa: BLE001
            err = str(e) or e.__class__.__name__
            logger.warning("tool execute failed", tool=tc.tool_name, error=err)
            await self.repo.update_status(
                tc.id, status="failed", error_message=err
            )
            await self._reload_sync(tool_call_id)
            raise ToolError(err) from e

        await self.repo.update_status(tc.id, status="succeeded", output_json=output)
        return await self._reload_sync(tool_call_id)


# ============ LLM 规划 ============

_PLAN_PROMPT = """你是一个工具规划器。根据用户消息判断是否需要调用工具。

可用工具：
{tools}

规则：
- 仅当用户意图明确匹配某工具时才提议调用；普通问答不要调用工具。
- read_file：读取文件内容；summarize_file：生成文件摘要；import_to_kb：把文件加入知识库。
- search_files/grep_code/read_code_file/get_git_status/get_git_diff：读取已授权项目的代码、状态与 diff。
- propose_patch：只生成 diff 预览，不写入；apply_patch_to_workspace：审批后写入授权项目文件。
- run_whitelisted_command：审批后运行白名单验证命令，如 pytest、npm run build、cargo check。
- 需要文件路径、project_id、topic_id 等参数时，必须从用户消息或当前上下文中提取；不要编造。
- 用户未授权的路径也可提议（执行时会校验），但优先用消息中出现的路径。

请只输出一个 JSON 对象，不要输出任何其他内容。格式：
{{"use_tool": true, "tool": "工具名", "input": {{...}}, "reason": "简短中文理由"}}
或：
{{"use_tool": false}}
"""


def _parse_plan(raw: str) -> dict | None:
    """从 LLM 输出中提取首个平衡 JSON 对象，解析失败返回 None。

    不用贪婪正则 ``\\{.*\\}``（会从首个 '{' 吞到末尾 '}'，遇尾部多余 '}'/
    多个 JSON 对象/前导花括号散文时整体解析失败）。改为：先整体解析（含去 markdown
    围栏），再回退到从首个 '{' 做括号配对找第一个平衡对象。
    """
    text = raw.strip()
    # 去 markdown 代码围栏
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    # 快路径：整体即单个 JSON 对象
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        pass
    # 回退：从首个 '{' 做括号配对，找第一个平衡 JSON 对象
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        end = -1
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            try:
                obj = json.loads(text[start : end + 1])
                if isinstance(obj, dict):
                    return obj
            except Exception:  # noqa: BLE001
                pass
        start = text.find("{", start + 1)
    return None


async def plan_tool_call(
    provider: OllamaProvider,
    db: AsyncSession,
    session_id: int | None,
    message: str,
    registry: ToolRegistry | None = None,
) -> ToolCall | None:
    """用 LLM 判断是否需调用工具；匹配则建 pending_approval 记录并返回，否则 None。"""
    reg = registry or default_registry
    tools_json = json.dumps(reg.for_planning(), ensure_ascii=False)
    prompt = _PLAN_PROMPT.format(tools=tools_json)
    msgs = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": message},
    ]
    try:
        raw = await provider.chat(msgs)
    except Exception as e:  # noqa: BLE001
        logger.warning("tool plan LLM failed", error=str(e))
        return None

    plan = _parse_plan(raw)
    if not plan or not plan.get("use_tool"):
        return None
    tool_name = plan.get("tool")
    tool = reg.get(tool_name) if isinstance(tool_name, str) else None
    if tool is None:
        logger.info("tool plan: unknown tool proposed", tool=tool_name)
        return None

    inputs = plan.get("input")
    if not isinstance(inputs, dict):
        inputs = {}
    repo = ToolCallRepository(db)
    tc = await repo.create(
        session_id=session_id,
        tool_name=tool.name,
        risk_level=tool.risk_level,
        status="pending_approval",
        input_json=inputs,
    )
    await ActivityService(db).sync_tool_call(tc)
    logger.info("tool plan created", tool=tool.name, tool_call_id=tc.id)
    return tc
