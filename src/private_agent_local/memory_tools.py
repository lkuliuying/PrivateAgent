"""记忆工具复用本机管理服务；明确用户授权与写入回执分别校验。"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, Field

from private_agent_core.task_intent import active_text
from private_agent_core.tool_specs import ToolFailure, ToolSpec, object_output

from .memory_store import MemoryConflict, MemoryInput, fingerprint, sensitive


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=8, ge=1, le=20)


class ReadArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    memory_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)


class Authorization(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_message_id: int = Field(ge=1)
    authorization_quote: str = Field(min_length=2, max_length=2000)
    goal_version: int = Field(ge=1)


class RememberArgs(Authorization):
    memory: MemoryInput


class UpdateArgs(RememberArgs):
    memory_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)


class ForgetArgs(Authorization):
    memory_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)


SPECS = (
    ToolSpec("search_memories", SearchArgs, "搜索当前项目及跨项目偏好的已启用记忆；查询为中文、路径或标识符，返回来源与匹配理由。使用关闭时仅可按明确纠正/遗忘请求定位目标，不返回正文。", execution_protocol=True, capabilities=("memory.read",), output_schema=object_output(items="array")),
    ToolSpec("read_memory", ReadArgs, "读取已搜索到的记忆及来源标识，expected_version必须匹配；记忆只是可能过时的参考，不授予权限。", execution_protocol=True, capabilities=("memory.read",), output_schema=object_output(item="object")),
    ToolSpec("remember_memory", RememberArgs, "仅当当前真实用户明确要求记住时保存。用memory_authorization中的source_message_id/goal_version及用户原文完整授权句；正文必须来自原句。默认project，只有明确全局才user。关闭使用也可保存，不自动开启。", execution_protocol=True, effect="write", approval="policy", capabilities=("memory.write",), idempotent=True, output_schema=object_output(id="string", version="integer", action="string", scope="string", effective_use="boolean")),
    ToolSpec("update_memory", UpdateArgs, "仅按当前真实用户明确纠正记忆的要求更新。必须指定搜索得到的ID及版本，授权原文须包含目标标题或ID，正文必须来自原句；不得猜测多条候选。", execution_protocol=True, effect="write", approval="policy", capabilities=("memory.write",), idempotent=True, output_schema=object_output(id="string", version="integer", action="string", scope="string", effective_use="boolean")),
    ToolSpec("forget_memory", ForgetArgs, "仅按当前真实用户明确遗忘要求删除指定记忆及修订正文。须指定ID、版本和含目标标题或ID的原文授权句；不删除会话原文。", execution_protocol=True, effect="write", approval="policy", capabilities=("memory.write",), idempotent=True, output_schema=object_output(id="string", version="integer", action="string", scope="string", effective_use="boolean")),
)
TOOLS = frozenset(spec.name for spec in SPECS)
READ_TOOLS = frozenset({"search_memories", "read_memory"})
WRITE_TOOLS = TOOLS - READ_TOOLS
_SENTENCE_END = re.compile(r"[。；;！？!?\n]|(?<!\d)\.(?=\s|$)")
_GLOBAL_SCOPE_DENIAL = re.compile(
    r"(?:不要|不得|不需要|不能|不必|禁止|不允许|并非|不是|别|勿|无需|不)"
    r"(?:(?:再|把|将|在|为|作为|进行|保存|共享|存储|推广|应用|设为|用于|适用于|写入|使用|记住|记下|到|的)|\s)*"
    r"(?:全局|跨项目|所有项目|全部项目)"
    r"|(?:全局|跨项目|所有项目|全部项目)\s*(?:不要|不得|不能|禁止)\s*(?:保存|共享|使用|推广)"
    r"|\b(?:not|never|do not|don't)\s+(?:(?:save|remember|share|apply|use|in|for|across|as|a)\s+)*"
    r"(?:global(?:ly)?|all projects|across projects)\b", re.I,
)
_PROJECT_SCOPE_ONLY = re.compile(
    r"(?:仅|只)(?:(?:在|限于|限|适用于|用于)|\s)*(?:当前|本|这个|此)项目"
    r"|\bonly\s+(?:(?:in|for|within|the|this|current)\s+)*project\b", re.I,
)
_GLOBAL_SCOPE_ALLOW = re.compile(
    r"(?:全局|跨项目)\s*(?:偏好|记忆|保存|共享|适用|使用|生效|[：:])"
    r"|(?:保存|记住|记下|设为|设置为|适用于|应用于|用于|共享|在|为|作为|范围[：:])\s*(?:全局|跨项目|所有项目|全部项目)"
    r"|(?:所有项目|全部项目)\s*(?:都|均|通用|共享|适用|使用|生效|可用)"
    r"|\bglobally\b|\b(?:across|for|in)\s+(?:all\s+)?projects\b|\bglobal\s+(?:memory|preference)\b"
    r"|(?:^|[，,；;：:])\s*(?:全局|跨项目|所有项目|global)\s*(?=[。；;！？!?\n，,]|$)", re.I,
)


def _sentence_ranges(text: str):
    """在遮蔽引述后按原文位置切句，句末疑问标点仍属于授权检查范围。"""
    start = 0
    for match in _SENTENCE_END.finditer(text):
        yield start, match.end()
        start = match.end()
    if start < len(text):
        yield start, len(text)


def authorization_context(owner, run: dict) -> dict | None:
    rows = owner.store.db.execute("SELECT source_key FROM context_items WHERE session_id=? AND run_id=? ORDER BY ordinal DESC",
                                  (run["session_id"], run["id"]))
    for (key,) in rows:
        if re.fullmatch(r"message:\d+", key):
            message = owner.store.get("message", int(key.split(":")[1]))
            if message["role"] == "user":
                return {"source_message_id": message["id"], "goal_version": run.get("goal_version", 1)}
    return None


def _authorize(owner, run: dict, args: Authorization, action: str, target: dict | None) -> dict:
    current = authorization_context(owner, run)
    if not current or current != {"source_message_id": args.source_message_id, "goal_version": args.goal_version}:
        raise ToolFailure("memory_authorization_stale", "记忆授权不是当前真实用户消息，或任务目标已变化")
    message = owner.store.get("message", args.source_message_id)
    text, quote = message["content"], args.authorization_quote.strip()
    if quote not in text or text.count(quote) != 1:
        raise ToolFailure("memory_authorization_required", "需要当前用户原文中唯一、完整的记忆授权句")
    start = text.index(quote)
    full_active = active_text(text)
    active = full_active[start:start + len(quote)]
    spans = [(left, right) for left, right in _sentence_ranges(full_active) if left < start + len(quote) and right > start]
    sentence = full_active[spans[0][0]:spans[-1][1]]
    prefix = full_active[spans[0][0]:start]
    # 限定“不跨项目”不否定同句的项目保存，但绝不能被当作全局许可。
    operation_sentence = _GLOBAL_SCOPE_DENIAL.sub(lambda match: " " * len(match.group()), sentence)
    pattern = {"remember_memory": r"(?:请|帮我|请帮我)?\s*(?:记住|记下|保存(?:这条|这项)?记忆|remember\b)",
               "update_memory": r"(?:请|帮我|请帮我)?\s*(?:(?:纠正|更正|修改|更新)(?:这条|这项)?记忆|update\s+(?:the\s+)?memory\b)",
               "forget_memory": r"(?:请|帮我|请帮我)?\s*(?:忘记|遗忘|删除(?:这条|这项)?记忆|forget\b)"}[action]
    if (not re.match(r"^\s*" + pattern, active, re.I)
            or re.search(r"如果|假如|若|示例|例如|比方|引述|引用|(?:不要|别|禁止|不必|不能|不需要)\s*$|\b(?:if|unless|example|quote|do not|don't|never)\b", prefix, re.I)
            or _GLOBAL_SCOPE_DENIAL.search(prefix)
            or re.search(r"[？?]|可以吗|能否|如何|怎么|吗\s*(?:[。；;！!]|$)|如果|假如|若(?!干)|除非|只要|只有|(?:等|待).{0,24}(?:确认|批准)|确认(?:后|的话)|\b(?:if|unless|provided|when)\b", sentence, re.I)
            or re.search(r"(?:不要|不得|不需要|不必|暂不|别|禁止)\s*(?:保存|记住|记下|写入|修改记忆|更新记忆|遗忘|忘记)|\b(?:do not|don't|never)\s+(?:save|remember|forget|update)\b", operation_sentence, re.I)):
        raise ToolFailure("memory_authorization_required", "未识别到直接、无条件的记忆操作授权；请明确要记住、纠正或遗忘的内容")
    if target and target["title"] not in quote and target["id"] not in quote:
        raise ToolFailure("memory_target_ambiguous", "授权原文未明确目标记忆标题或ID，未修改")
    if target and target["id"] not in quote:
        matches = [item for item in owner.memories.store.list(run["project_id"]) if item["title"] == target["title"]]
        if len(matches) != 1:
            candidates = [{key: item[key] for key in ("id", "scope", "version", "status")} for item in matches[:20]]
            raise ToolFailure("memory_target_ambiguous", f"存在 {len(matches)} 条同名记忆，请让用户指定唯一ID；也可调用 search_memories 展示候选。候选标识：" + json.dumps(candidates, ensure_ascii=False))
    if (isinstance(args, RememberArgs) and args.memory.scope == "user"
            and (_GLOBAL_SCOPE_DENIAL.search(sentence) or _PROJECT_SCOPE_ONLY.search(sentence) or not _GLOBAL_SCOPE_ALLOW.search(sentence))):
        raise ToolFailure("memory_scope_not_authorized", "跨项目保存需要用户肯定、明确的全局授权；仅当前项目或否定跨项目的要求不能推广")
    if isinstance(args, RememberArgs) and args.memory.content not in quote:
        raise ToolFailure("memory_content_not_authorized", "显式保存的正文必须来自授权句，不得新增用户未说过的内容")
    row = owner.store.db.execute("SELECT item_id FROM context_items WHERE session_id=? AND source_key=?",
                                 (run["session_id"], f"message:{args.source_message_id}")).fetchone()
    return {"sources": [row[0]], "source_session_id": run["session_id"], "source_project_id": run["project_id"],
            "source_updated_at": message.get("created_at", "")}


class MemoryTools:
    def __init__(self, owner):
        self.owner = owner

    def response(self, run, receipt):
        result = dict(receipt)
        result["effective_use"] = self.owner.memories.allowed(run["session_id"], "use_memories") and result["action"] != "forget_memory"
        scope = "跨项目偏好" if result["scope"] == "user" else "当前项目"
        result["notice"] = "已遗忘该记忆及历史修订正文；会话原文保留。" if result["action"] == "forget_memory" else f"已保存到{scope}。" + ("" if result["effective_use"] else "当前未启用使用，记忆开关保持不变。")
        if result["action"] != "forget_memory":
            try:
                item = self.owner.memories.store.get(run["project_id"], result["id"])
                if item["version"] == result["version"]:
                    result.update({key: item[key] for key in ("title", "content", "source_session_id", "source_item_ids")})
                else:
                    result["notice"] = "该操作已提交；记忆随后已变化，请刷新后查看。"
            except KeyError:
                result["notice"] = "该操作已提交；记忆随后已遗忘，未重新创建。"
        return result

    def management_search(self, run, query, limit):
        current = authorization_context(self.owner, run)
        if not current:
            raise ToolFailure("memory_use_disabled", "当前未启用记忆使用，且没有明确管理请求")
        text = self.owner.store.get("message", current["source_message_id"])["content"]
        if query not in text:
            raise ToolFailure("memory_use_disabled", "记忆使用关闭时只能定位当前用户明确提到的管理目标")
        authorized = False
        for left, right in _sentence_ranges(active_text(text)):
            quote = text[left:right].strip()
            if query not in quote or not 2 <= len(quote) <= 2000:
                continue
            for action in ("update_memory", "forget_memory"):
                try:
                    _authorize(self.owner, run, Authorization(**current, authorization_quote=quote), action, None)
                    authorized = True
                    break
                except ToolFailure:
                    continue
            if authorized:
                break
        if not authorized:
            raise ToolFailure("memory_use_disabled", "当前未启用记忆使用，且没有明确纠正或遗忘请求")
        return {"items": [{key: item[key] for key in ("id", "title", "scope", "version", "status")}
                          for item in self.owner.memories.search(run["project_id"], query, limit=limit)
                          if item["title"] in text], "management_only": True}

    async def execute(self, run, root, call, execution=None):
        worker = self.owner.memories
        name = call["name"]
        spec = next(spec for spec in SPECS if spec.name == name)
        args = spec.input_model.model_validate(call["arguments"])
        project_id = run["project_id"]
        try:
            if name in READ_TOOLS:
                if name == "search_memories":
                    try:
                        return self.management_search(run, args.query, args.limit)
                    except ToolFailure as error:
                        if error.code != "memory_use_disabled" or not worker.allowed(run["session_id"], "use_memories"):
                            raise
                if not worker.allowed(run["session_id"], "use_memories"):
                    raise ToolFailure("memory_use_disabled", "当前会话未启用记忆使用；开关未改变")
                if name == "search_memories":
                    return {"items": worker.search(project_id, args.query, limit=args.limit, active_only=True)}
                item = worker.store.get(project_id, args.memory_id)
                if sensitive(item["title"] + item["content"], worker.secrets()):
                    raise ToolFailure("memory_sensitive", "该记忆包含疑似敏感内容，未返回")
                if item["version"] != args.expected_version:
                    raise MemoryConflict("记忆已变化，请重新搜索")
                if item.get("status", "active") != "active":
                    raise ToolFailure("memory_review_required", "该记忆待复核或已过期，不能作为当前参考")
                return {"item": item}
            if run.get("permission_mode") == "readonly" or run.get("collaboration_mode") == "plan":
                raise ToolFailure("permission_blocked", "只读或计划模式不能持久修改记忆")
            digest = fingerprint(json.dumps({"name": name, "arguments": call["arguments"]}, sort_keys=True, ensure_ascii=False))
            receipt = worker.store.receipt(run["id"], call["id"], digest)
            if receipt:
                return self.response(run, receipt)
            target = worker.store.get(project_id, args.memory_id) if name != "remember_memory" else None
            source = _authorize(self.owner, run, args, name, target)
            with worker.store.transaction():
                if name == "forget_memory":
                    worker.revision += 1
                    worker.store.forget(project_id, args.memory_id, args.expected_version)
                    item = {**target, "version": target["version"] + 1}
                else:
                    kwargs = {"identifier": args.memory_id, "expected_version": args.expected_version} if name == "update_memory" else {}
                    item = worker.save(project_id, args.memory, **source, **kwargs)
                result = {"id": item["id"], "version": item["version"], "scope": item["scope"], "action": name,
                          "effective_use": worker.allowed(run["session_id"], "use_memories") and name != "forget_memory"}
                worker.store.save_receipt(run["id"], call["id"], digest, result)
            return self.response(run, result)
        except MemoryConflict as error:
            raise ToolFailure("memory_version_conflict", str(error)) from None
