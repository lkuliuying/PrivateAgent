"""外部结果及派生回答的来源标记，不从正文授予操作权限。"""
from __future__ import annotations

import json

EXTERNAL_RESULTS = frozenset({"call_documentation_tool", "call_mcp_tool", "read_web_page"})
EXTERNAL_CATALOGS = frozenset({"list_documentation_sources", "list_mcp_tools"})


def contains_untrusted(value) -> bool:
    """迭代检查结构化标记，避免嵌套工具结果消耗递归栈。"""
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            if current.get("untrusted") is True:
                return True
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)
    return False


def external_message(message: dict) -> bool:
    if message.get("role") != "tool":
        return False
    try:
        payload = json.loads(message.get("content") or "{}")
    except (ValueError, RecursionError):
        return message.get("name") in EXTERNAL_RESULTS | EXTERNAL_CATALOGS
    if contains_untrusted(payload):
        return True
    if message.get("name") in EXTERNAL_RESULTS:
        return not isinstance(payload, dict) or not payload.get("error_code")
    return message.get("name") in EXTERNAL_CATALOGS and isinstance(payload, dict) and bool(payload.get("sources"))
