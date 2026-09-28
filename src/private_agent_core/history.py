"""两种旧客户端共用的历史交换格式；只携带记录，不携带有效授权或凭据配置。"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

FORMAT = "privateagent.history.v1"
MAX_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 50000
FIELDS = {
    "projects": "id name root_path status created_at updated_at",
    "workspaces": "id project_id kind root_path branch_name head_sha status last_used_at created_at updated_at",
    "sessions": "id project_id workspace_id kind title last_run_id pinned_at archived_at created_at updated_at",
    "messages": "id session_id role content created_at updated_at",
    "runs": "id session_id project_id workspace_id model_profile_id reasoning_effort permission_mode status provider model input_tokens output_tokens cached_tokens cost_usd output error_code error_message tool_call_count started_at completed_at created_at updated_at",
    "events": "id run_id sequence event_type step_id payload_json created_at",
    "approvals": "id run_id tool_call_id tool_name tool_version arguments_json arguments_sha256 risk_level status decision_at created_at updated_at",
    "executions": "id run_id tool_call_id tool_name tool_version status output_json error_code error_message created_at completed_at",
    "run_steps": "id run_id ordinal kind status name tool_call_id input_json output_json error_code error_message started_at completed_at",
    "agent_tasks": "id session_id title goal status plan_json final_report_md created_at updated_at",
    "agent_task_steps": "id task_id ordinal title tool_name status input_json output_json error_message started_at finished_at created_at",
    "agent_evidence": "id task_id step_id kind title content_md meta_json created_at",
}
FIELDS = {key: tuple(value.split()) for key, value in FIELDS.items()}
RELATIONS = {
    "workspaces": {"project_id": "projects"},
    "sessions": {"project_id": "projects", "workspace_id": "workspaces"},
    "messages": {"session_id": "sessions"},
    "runs": {"session_id": "sessions", "project_id": "projects", "workspace_id": "workspaces"},
    "events": {"run_id": "runs"}, "approvals": {"run_id": "runs"}, "executions": {"run_id": "runs"},
    "run_steps": {"run_id": "runs"}, "agent_tasks": {"session_id": "sessions"},
    "agent_task_steps": {"task_id": "agent_tasks"}, "agent_evidence": {"task_id": "agent_tasks", "step_id": "agent_task_steps"},
}


def encode_archive(value: dict) -> bytes:
    def scalar(item):
        if isinstance(item, (datetime, date)):
            return item.isoformat()
        if isinstance(item, Decimal):
            return str(item)
        raise ValueError("历史包含不支持的值类型")
    result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=scalar).encode("utf-8")
    if len(result) > MAX_BYTES:
        raise ValueError("历史包超过 64 MiB，请分批迁移")
    return result


def validate_archive(archive: dict, *, authority: str, owner_id: int) -> dict:
    if not isinstance(archive, dict) or archive.get("format") != FORMAT or set(archive) != {"format", "source", "records"}:
        raise ValueError("不支持的历史格式")
    source = archive["source"]
    if not isinstance(source, dict) or set(source) != {"authority", "owner_id"} or source.get("authority") != authority or type(source.get("owner_id")) is not int or source["owner_id"] != owner_id:
        raise ValueError("历史包与当前账号或账号服务不匹配；不允许自动合并其他账号")
    records = archive["records"]
    if not isinstance(records, dict) or set(records) != set(FIELDS):
        raise ValueError("历史记录类型不完整")
    keys = {}
    count = 0
    for kind, rows in records.items():
        if not isinstance(rows, list):
            raise ValueError("历史记录必须为数组")
        count += len(rows)
        if count > MAX_RECORDS:
            raise ValueError("历史记录超过 50000 条，请分批迁移")
        seen = set()
        seen_text = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) - set(FIELDS[kind]):
                raise ValueError("历史包含未知字段或不可迁移的授权数据")
            identity = row.get("id")
            if type(identity) not in {str, int} or not str(identity) or len(str(identity)) > 128 or str(identity) in seen_text:
                raise ValueError("历史记录标识重复或无效")
            seen.add(identity)
            seen_text.add(str(identity))
        keys[kind] = seen
    sequences = set()
    for row in records["events"]:
        if (type(row.get("sequence")) is not int or row["sequence"] < 1
                or not isinstance(row.get("event_type"), str) or not row["event_type"]
                or not isinstance(row.get("payload_json", {}), dict)
                or type(row.get("run_id")) not in {str, int}):
            raise ValueError("运行事件序号、类型或内容无效")
        key = (row["run_id"], row["sequence"])
        if key in sequences:
            raise ValueError("运行事件序号重复")
        sequences.add(key)
    for kind, relations in RELATIONS.items():
        for row in records[kind]:
            for field, parent in relations.items():
                value = row.get(field)
                if value is not None and (type(value) not in {str, int} or value not in keys[parent]):
                    raise ValueError("历史记录存在缺失或跨账号的关联，未执行迁移")
    encode_archive(archive)
    return archive
