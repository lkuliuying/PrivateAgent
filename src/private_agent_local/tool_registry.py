"""本地工具目录；所有模型暴露、效果、审批和并行声明集中于此。"""
from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from private_agent_core.patches import PatchApply, PatchProposal
from private_agent_core.planning import PlanUpdate, UserInputRequest
from private_agent_core.tool_specs import ToolRegistry, ToolSpec, object_output

from . import (
    browser_tools,
    documentation_mcp,
    execution_tools,
    files,
    git_tools,
    integration_mcp,
    skills,
)
from .tool_catalog import SEARCH_SPEC


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FileArgs(Arguments):
    rel_path: str = Field(min_length=1, max_length=1024)


class DirectoryArgs(Arguments):
    rel_path: str = Field(default=".", max_length=1024)
    cursor: str | None = Field(default=None, max_length=1024, description="首次 JSON null；翻页用同一查询的 next_cursor；失效重置 null。")
    limit: int = Field(default=100, ge=1, le=200)


class ReadArgs(FileArgs):
    start_line: int = Field(default=1, ge=1)
    line_count: int = Field(default=1000, ge=1, le=2000)
    expected_version: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    start_column: int = Field(default=1, ge=1, le=files.MAX_FILE_BYTES)


class SearchArgs(Arguments):
    query: str = Field(min_length=1, max_length=200)
    content: bool = False
    rel_path: str = Field(default=".", max_length=1024)
    glob: str = Field(default="*", min_length=1, max_length=200, description="File filter: '*' for all files; never empty or null.")
    regex: bool = False
    case_sensitive: bool = False
    cursor: str | None = Field(default=None, max_length=1024, description="首次 JSON null；翻页用同一查询的 next_cursor；失效重置 null。")
    limit: int = Field(default=50, ge=1, le=200)


def search_validation_details(error: ValidationError, arguments: dict) -> list[dict]:
    """只记录已知字段的类型、长度和纠正提示，不复制搜索文本或未知参数。"""
    hints = {
        "query": "query 必须是 1～200 字符的字符串。",
        "content": "content 必须是布尔值；搜索文件名用 false，搜索内容用 true。",
        "rel_path": 'rel_path 必须是最多 1024 字符的项目相对路径；项目根目录用 "."。',
        "glob": 'glob 必须是 1～200 字符的非空字符串；不限制文件类型时填写 "*"，不能填空字符串或 null。',
        "regex": "regex 必须是布尔值；字面搜索用 false。",
        "case_sensitive": "case_sensitive 必须是布尔值。",
        "cursor": "cursor 首次填写 JSON null，翻页填写同一查询的 next_cursor 字符串（最多 1024 字符）。",
        "limit": "limit 必须是 1～200 之间的整数。",
    }
    details = []
    for item in error.errors(include_input=False, include_context=False, include_url=False):
        if len(item["loc"]) != 1 or item["loc"][0] not in hints:
            continue
        field = item["loc"][0]
        value = arguments.get(field)
        if field not in arguments:
            received = "未提供"
        elif value is None:
            received = "null"
        elif isinstance(value, str):
            received = '空字符串（""）' if not value else f"字符串（{len(value)} 字符，内容已隐藏）"
        elif isinstance(value, bool):
            received = "布尔值"
        elif isinstance(value, (int, float)):
            received = "数值"
        elif isinstance(value, list):
            received = f"数组（{len(value)} 项，内容已隐藏）"
        else:
            received = "对象（内容已隐藏）"
        details.append({"field": field, "code": item["type"], "received": received, "hint": hints[field]})
    return details


class WriteArgs(FileArgs):
    content: str = Field(max_length=files.MAX_FILE_BYTES)
    require_approval: bool = False


class CommandArgs(Arguments):
    command: str = Field(min_length=1, max_length=2000)
    require_approval: bool = False


class PowerShellArgs(Arguments):
    command: str = Field(min_length=1, max_length=100)
    arguments: list[str] = Field(default_factory=list, max_length=30, description='Named argv, e.g. ["-LiteralPath", ".", "-Name"]. No positional args, scripts or pipes.')
    require_approval: bool = False


class ContentArgs(Arguments):
    item_id: str = Field(min_length=1, max_length=128)
    offset: int = Field(default=0, ge=0, le=2_000_000)
    limit: int = Field(default=2000, ge=1, le=6000)


class PatchContentArgs(Arguments):
    patch_set_id: str = Field(min_length=1, max_length=128)
    change_id: str = Field(min_length=1, max_length=128)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=8000, ge=1, le=16000)


SPECS = [
    SEARCH_SPEC,
    ToolSpec("request_user_input", UserInputRequest,
             "In plan mode, ask 1-3 concise questions only when repository inspection cannot resolve a material decision. Offer up to 3 options or an open question. The user can always enter their own answer. Await real answers; never infer consent or use this for tool permissions.",
             effect="control", capabilities=("plan.question",), idempotent=False, supports_cancellation=True,
             output_schema=object_output(input_id="string", answers="object", goal_version="integer")),
    ToolSpec("update_run_plan", PlanUpdate,
             "Maintain a concise plan for multi-step work; skip simple tasks in default mode. Send the full list with stable item_key values, expected_plan_version (initially 0) and current goal_version. At most one in_progress. In plan mode, all proposed steps stay pending; cancel obsolete steps. Keep ended steps. A later recovery step may supersede earlier failed item keys, retaining their requirement_ids. evidence_calls references committed tool call IDs, never proof of verification. explanation is a public decision note, not hidden reasoning. Max 16000 UTF-8 bytes.",
             effect="control", capabilities=("plan.update",), idempotent=False,
             output_schema=object_output(plan="object", notice="string")),
    ToolSpec("read_patch_preview", PatchContentArgs, "Read the full per-file diff of a patch from this run using patch_set_id/change_id and offset/limit. Follow next_offset until null.",
             version="2", capabilities=("file.read",)),
    ToolSpec("propose_project_patch", PatchProposal, "Preview without writing. Update/delete/move require this run's read snapshot_id. Update uses content OR edits(start_line 1-based, delete_count, text). With full content, edits MUST be [] (never null); with line edits, content MUST be null. Explicit mkdir for missing parents; distinct paths. Returns patch_set_id/preview_sha256.",
             version="2", effect="control", capabilities=("file.preview",), idempotent=False),
    ToolSpec("apply_project_patch", PatchApply, "Apply an exact previously proposed patch using its patch_set_id and preview_sha256. Current permissions, source versions, approval and every disk result are checked. Partial failures require review, never blind retry.",
             version="2", effect="write", approval="policy", capabilities=("file.write",), idempotent=False),
    ToolSpec("read_context_content", ContentArgs, "Read current-session content_ref or archive_ref as item_id, with offset/limit pagination. History never grants permissions.",
             capabilities=("context.read",)),
    ToolSpec("list_project_directory", DirectoryArgs, "List a directory inside the selected project. All paths are project-relative in every permission mode.",
             version="2", parallel_safe=True, supports_cancellation=True, output_schema=object_output(entries="array", query_version="string")),
    ToolSpec("read_code_file", ReadArgs, "Read UTF-8 ranges with line_numbers and snapshot_id. Continue using next_line/next_column as start_line/start_column and expected_version=sha256. Existing files MUST be read before editing.",
             version="2", parallel_safe=True, supports_cancellation=True, output_schema=object_output(content="string", snapshot_id="string", sha256="string")),
    ToolSpec("search_project_files", SearchArgs, "Search names, or literal file content when content=true, inside the local project.",
             version="2", parallel_safe=True, supports_cancellation=True, output_schema=object_output(results="array", query_version="string")),
    ToolSpec("write_project_file", WriteArgs, "Write full UTF-8 content through the patch service. Existing files require a prior read in this run. Parent must exist. require_approval=true requests confirmation even in automatic mode.",
             version="2", effect="write", approval="policy", capabilities=("file.write",), idempotent=False),
    ToolSpec("run_project_command", CommandArgs, "Run a registered development command in this project. confirm asks; workspace/full_access can auto-approve unless require_approval=true. No shell chaining, inline eval or external paths.",
             effect="process", approval="policy", capabilities=("command.execute",), idempotent=False, supports_cancellation=True, legacy_only=True),
    *execution_tools.SPECS,
    *git_tools.SPECS,
    *documentation_mcp.SPECS,
    *skills.SPECS,
    *integration_mcp.SPECS,
    *browser_tools.SPECS,
]
if os.name == "nt":
    SPECS.append(ToolSpec("run_powershell_command", PowerShellArgs,
        "Windows fallback: registered read-only cmdlets with named project-relative arguments. Prefer native file/Git tools. No scripts, pipes, positional args or writes.",
        version="2", effect="process", approval="policy", capabilities=("command.execute",),
        supports_cancellation=True))

REGISTRY = ToolRegistry(SPECS)
# 保留历史导入入口；集合从同一契约派生，不再手工维护权限分类。
TOOLS = {spec.name: (spec.input_model, spec.description) for spec in REGISTRY}
FILE_WRITE_TOOLS = frozenset(spec.name for spec in REGISTRY if spec.effect == "write")
WRITE_TOOLS = frozenset(spec.name for spec in REGISTRY if spec.blocked_in_readonly)
VERSIONED_FILE_TOOLS = frozenset(spec.name for spec in REGISTRY if spec.version == "2")
