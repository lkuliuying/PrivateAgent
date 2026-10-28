"""两种旧客户端共用的历史交换格式；只携带记录，不携带有效授权或凭据配置。"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal

LEGACY_FORMAT = "privateagent.history.v1"
TEXT_FORMAT = "privateagent.history.v2"
FORMAT = "privateagent.history.v3"
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
LEGACY_FIELDS = dict(FIELDS)
FIELDS.update(attachments=tuple("id project_id workspace_id name language size_bytes sha256 content".split()),
              message_attachments=tuple("id message_id attachment_id ordinal".split()))
TEXT_FIELDS = dict(FIELDS)
FIELDS["attachments"] = (*FIELDS["attachments"], "content_encoding", "kind")
RELATIONS = {
    "attachments": {"project_id": "projects", "workspace_id": "workspaces"},
    "message_attachments": {"message_id": "messages", "attachment_id": "attachments"},
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
    if not isinstance(archive, dict) or archive.get("format") not in {FORMAT, TEXT_FORMAT, LEGACY_FORMAT} or set(archive) != {"format", "source", "records"}:
        raise ValueError("不支持的历史格式")
    source = archive["source"]
    if not isinstance(source, dict) or set(source) != {"authority", "owner_id"} or source.get("authority") != authority or type(source.get("owner_id")) is not int or source["owner_id"] != owner_id:
        raise ValueError("历史包与当前账号或账号服务不匹配；不允许自动合并其他账号")
    fields = LEGACY_FIELDS if archive["format"] == LEGACY_FORMAT else TEXT_FIELDS if archive["format"] == TEXT_FORMAT else FIELDS
    records = archive["records"]
    if not isinstance(records, dict) or set(records) != set(fields):
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
            if not isinstance(row, dict) or set(row) - set(fields[kind]):
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
        for row in records.get(kind, []):
            for field, parent in relations.items():
                value = row.get(field)
                if value is not None and (type(value) not in {str, int} or value not in keys[parent]):
                    raise ValueError("历史记录存在缺失或跨账号的关联，未执行迁移")
    encode_archive(archive)
    validate_attachments(records)
    return archive

def attachment_bytes(item: dict) -> bytes:
    content = item.get("content")
    encoding = item.get("content_encoding", "utf8")
    if not isinstance(content, str) or len(content) > 14 * 1024 * 1024:
        raise ValueError("附件正文无效或超限")
    if encoding == "utf8" and item.get("kind", "text") == "text":
        return content.encode("utf-8")
    if encoding == "base64" and item.get("kind") in {"image", "pdf"}:
        try:
            return base64.b64decode(content, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("附件 Base64 正文损坏") from None
    raise ValueError("不支持的附件编码或类型")


def validate_attachments(records: dict):
    """附件正文有独立摘要，引用必须与消息所在工作区一致。"""
    attachments = {item["id"]: item for item in records.get("attachments", [])}
    sessions = {item["id"]: item for item in records["sessions"]}
    messages = {item["id"]: item for item in records["messages"]}
    for item in attachments.values():
        name, content = item.get("name"), item.get("content")
        if (not isinstance(name, str) or not 1 <= len(name) <= 255 or "/" in name or "\\" in name or "\0" in name
                or not isinstance(content, str) or "\0" in content):
            raise ValueError("附件名称或正文无效")
        raw = attachment_bytes(item)
        maximum = 10 * 1024 * 1024 if item.get("content_encoding") == "base64" else 1024 * 1024
        if (type(item.get("size_bytes")) is not int or len(raw) != item["size_bytes"] or len(raw) > maximum
                or not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
                or hashlib.sha256(raw).hexdigest() != item["sha256"]):
            raise ValueError("附件大小或摘要校验失败")
    seen, positions, counts = set(), set(), {}
    for link in records.get("message_attachments", []):
        message_id, attachment_id, ordinal = link.get("message_id"), link.get("attachment_id"), link.get("ordinal")
        item = attachments.get(attachment_id)
        message = messages.get(message_id)
        session = sessions.get((message or {}).get("session_id"))
        if (not item or not message or message.get("role") != "user" or not session
                or (item.get("project_id"), item.get("workspace_id")) != (session.get("project_id"), session.get("workspace_id"))):
            raise ValueError("附件引用与消息所属工作区不匹配")
        if type(ordinal) is not int or not 0 <= ordinal < 8 or (message_id, attachment_id) in seen or (message_id, ordinal) in positions:
            raise ValueError("附件引用重复或序号无效")
        seen.add((message_id, attachment_id))
        positions.add((message_id, ordinal))
        counts[message_id] = counts.get(message_id, 0) + 1
        if counts[message_id] > 8:
            raise ValueError("每条消息最多 8 个附件")
    if set(attachments) != {item[1] for item in seen}:
        raise ValueError("历史包含未提交附件")
