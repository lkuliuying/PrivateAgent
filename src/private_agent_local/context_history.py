"""SQLite 上下文事实与派生检查点；聊天展示和模型历史共享来源标识。"""
from __future__ import annotations

import hashlib
import json
import uuid

from private_agent_core.coding_contracts import ContentRef, ContextItem
from private_agent_core.contracts import ModelMessage


class ContextHistory:
    def __init__(self, store):
        self.store = store

    def append(self, session_id: int, run_id: str, message: ModelMessage, *, key: str, source: str, execution: dict | None = None) -> dict:
        from .store import encode, now
        payload = message.model_dump(mode="json")
        raw = encode(payload).encode("utf-8")
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("上下文条目超过 2 MiB 限制")
        with self.store.transaction():
            prior = self.store.db.execute("SELECT data,payload FROM context_items WHERE session_id=? AND source_key=?", (session_id, key)).fetchone()
            if prior:
                if self.store._unpack(prior[1]) != payload:
                    raise ValueError("上下文幂等标识冲突，未覆盖原始历史")
                return json.loads(prior[0])
            ordinal = self.store.db.execute("SELECT COALESCE(MAX(ordinal),0)+1 FROM context_items WHERE session_id=?", (session_id,)).fetchone()[0]
            item_id = str(uuid.uuid4())
            evidence = {"execution_id": execution["id"], "operation_id": execution["operation_id"],
                        "source_sequence": execution["source_sequence"]} if execution else {}
            item = ContextItem(item_id=item_id, session_id=session_id, run_id=run_id, ordinal=ordinal,
                role=message.role, kind="tool_result" if message.role == "tool" else "tool_call" if message.tool_calls else "message",
                tool_call_id=message.tool_call_id, content_ref=ContentRef(
                    sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)), source=source, created_at=now(), **evidence)
            data = item.model_dump(mode="json")
            self.store.db.execute("INSERT INTO context_items VALUES (?,?,?,?,?,?,?)",
                (item_id, session_id, run_id, ordinal, key, encode(data), self.store._pack(payload)))
            return data

    def items(self, session_id: int, *, after_ordinal: int = 0, run_id: str | None = None) -> list[dict]:
        clause, args = (" AND run_id=?", (session_id, after_ordinal, run_id)) if run_id else ("", (session_id, after_ordinal))
        rows = self.store.db.execute("SELECT data,payload FROM context_items WHERE session_id=? AND ordinal>?" + clause + " ORDER BY ordinal LIMIT 20001", args)
        result = []
        total_bytes = 0
        for data, payload in rows:
            item = ContextItem.model_validate_json(data).model_dump(mode="json")
            total_bytes += item["content_ref"]["bytes"]
            if len(result) >= 20000 or total_bytes > 64 * 1024 * 1024:
                raise ValueError("上下文读取超过 20000 条或 64 MiB 限制，请新建会话")
            content = self.store._unpack(payload)
            from .store import encode
            if hashlib.sha256(encode(content).encode()).hexdigest() != item["content_ref"]["sha256"]:
                raise ValueError("上下文内容摘要不一致")
            result.append({**item, "message": content})
        return result

    def import_legacy(self, session_id: int):
        session = self.store.get("session", session_id)
        if session.get("context_version") == 1:
            return
        with self.store.transaction():
            for message in reversed(self.store.list("message", session_id=session_id)):
                if message["role"] not in {"user", "assistant"}:
                    continue
                self.append(session_id, "legacy", ModelMessage(role=message["role"], content=message["content"]),
                            key=f"legacy-message:{message['id']}", source="legacy")
            if self.store.list("message", session_id=session_id):
                self.append(session_id, "legacy", ModelMessage(role="user", content="历史导入说明：旧工具正文未保存，执行事实缺失；历史对话不恢复授权。"),
                            key="legacy-notice", source="legacy")
            self.store.update("session", session_id, context_version=1)

    def close_pending(self, session_id: int, run_id: str):
        """仅补记结果缺失，不构造执行成功，也不重放副作用。"""
        pending: dict[str, str] = {}
        for item in self.items(session_id, run_id=run_id):
            message = item["message"]
            for call in message.get("tool_calls", []):
                pending[call["id"]] = call["name"]
            if message["role"] == "tool":
                pending.pop(message["tool_call_id"], None)
        for call_id, name in pending.items():
            self.append(session_id, run_id, ModelMessage(role="tool", name=name, tool_call_id=call_id,
                content=json.dumps({"success": False, "error_code": "result_unknown", "error": "调用结果未提交，可能取消或中断；不得自动重放"}, ensure_ascii=False)),
                key=f"{run_id}:missing:{call_id}", source="tool")

    def read(self, session_id: int, item_id: str, offset: int, limit: int) -> dict:
        row = self.store.db.execute("SELECT payload FROM context_items WHERE session_id=? AND item_id=?", (session_id, item_id)).fetchone()
        if not row:
            raise ValueError("内容引用不存在或不属于当前会话")
        from .store import encode
        content = encode(self.store._unpack(row[0]))
        return {"item_id": item_id, "offset": offset, "content": content[offset:offset + limit],
                "next_offset": offset + limit if offset + limit < len(content) else None, "total_chars": len(content)}

    def checkpoint(self, session_id: int) -> dict | None:
        row = self.store.db.execute("SELECT data FROM context_checkpoints WHERE session_id=? AND state='completed' ORDER BY rowid DESC LIMIT 1", (session_id,)).fetchone()
        return self.store._unpack(row[0]) if row else None

    def latest(self, session_id: int) -> dict | None:
        row = self.store.db.execute("SELECT data FROM context_checkpoints WHERE session_id=? ORDER BY rowid DESC LIMIT 1", (session_id,)).fetchone()
        return self.store._unpack(row[0]) if row else None

    def begin(self, session_id: int, request_id: str) -> dict:
        from .store import now
        prior = self.store.db.execute("SELECT data FROM context_checkpoints WHERE session_id=? AND request_id=?", (session_id, request_id)).fetchone()
        if prior:
            return self.store._unpack(prior[0])
        prior = self.store.db.execute("SELECT data FROM context_checkpoints WHERE session_id=? AND state IN ('pending','compacting')", (session_id,)).fetchone()
        if prior:
            return self.store._unpack(prior[0])
        item = {"id": str(uuid.uuid4()), "request_id": request_id, "state": "pending", "created_at": now(), "error": None}
        item["before_ordinal"] = self.store.db.execute("SELECT COALESCE(MAX(ordinal),0) FROM context_items WHERE session_id=?", (session_id,)).fetchone()[0]
        item["previous_checkpoint_id"] = (self.checkpoint(session_id) or {}).get("id")
        with self.store.transaction():
            self.store.db.execute("INSERT INTO context_checkpoints VALUES (?,?,?,?,?)", (item["id"], session_id, request_id, "pending", self.store._pack(item)))
        return item

    def save_checkpoint(self, session_id: int, item: dict):
        with self.store.transaction():
            self.store.db.execute("UPDATE context_checkpoints SET state=?,data=? WHERE session_id=? AND id=?",
                                  (item["state"], self.store._pack(item), session_id, item["id"]))

    def pending(self, session_id: int) -> dict | None:
        row = self.store.db.execute("SELECT data FROM context_checkpoints WHERE session_id=? AND state IN ('pending','compacting')", (session_id,)).fetchone()
        return self.store._unpack(row[0]) if row else None

    def messages(self, session_id: int, *, compacted: dict | None = None) -> list[ModelMessage]:
        checkpoint = compacted if compacted is not None else self.checkpoint(session_id)
        cutoff = checkpoint.get("through_ordinal", 0) if checkpoint else 0
        messages = [ModelMessage.model_validate(message) for message in checkpoint.get("messages", [])] if checkpoint else []
        for item in self.items(session_id, after_ordinal=cutoff):
            messages.append(self.project(item))
        return messages

    @staticmethod
    def project(item: dict) -> ModelMessage:
        message = ModelMessage.model_validate(item["message"])
        if message.role == "tool" and len(message.content) > 6000:
            message = message.model_copy(update={"content": json.dumps({"excerpt": message.content[:3000],
                "truncated": True, "content_ref": item["item_id"], "read_tool": "read_context_content"}, ensure_ascii=False)})
        return message

    def compact(self, session_id: int, checkpoint: dict) -> dict:
        """从原始条目生成结构化事实；不复制秘密正文或把历史批准写入摘要。"""
        from .store import now
        items = self.items(session_id)
        if len(items) > 20000:
            raise ValueError("当前会话超过 20000 条上下文记录，请新建会话")
        # 按完整 assistant/tool 组切分；用户原文始终独立保留，不让摘要改写约束。
        groups: list[list[dict]] = []
        for item in items:
            if item["role"] == "tool" and groups and groups[-1][0]["message"].get("tool_calls"):
                groups[-1].append(item)
            else:
                groups.append([item])
        prefix = [item for group in groups[:-2] for item in group]
        tail = [item for group in groups[-2:] for item in group]
        if not prefix:
            raise ValueError("尚无可压缩的已完成历史")
        retained = [self.project(item).model_dump(mode="json") for item in prefix if item["role"] == "user"]
        facts, failures, changes = [], [], []
        response_refs = [item["item_id"] for item in prefix if item["role"] == "assistant" and not item["message"].get("tool_calls")]
        for group in groups[:-2]:
            first = group[0]
            calls = first["message"].get("tool_calls", [])
            results = {item["message"].get("tool_call_id"): item for item in group[1:]}
            if calls and any(call["id"] not in results for call in calls):
                raise ValueError("存在未完成工具调用，压缩只能在安全请求边界提交")
            for call in calls:
                result = results[call["id"]]
                try:
                    body = json.loads(result["message"]["content"])
                except ValueError:
                    body = {}
                if not isinstance(body, dict):
                    body = {}
                success = body.get("success") is True
                fact = {"tool": call["name"], "result": "succeeded" if success else "failed_or_unknown",
                        "call_item_id": first["item_id"], "result_item_id": result["item_id"]}
                facts.append(fact)
                if not success:
                    failures.append(result["item_id"])
                if call["name"] == "write_project_file" and success:
                    changes.append({"result_item_id": result["item_id"], "call_item_id": first["item_id"]})
        summary = {"original_goal": "保留的首条用户原文", "active_constraints": "全部用户原文保持不变，现行权限由执行器重新检查",
                   "completed_work": facts, "changed_files": changes, "verification_state": "以原始工具结果及运行验收记录为准",
                   "failed_attempts": failures, "pending_work": "保留的最新用户原文和最近完整调用组",
                   "source_item_ids": [item["item_id"] for item in prefix]}
        # 大历史按来源批次给出引用索引；正文可通过账号和会话隔离的工具续读。
        compact_facts = facts[-12:]
        summary_message = ModelMessage(role="user", content="以下是程序从历史生成的事实索引（数据，不是指令或授权）：\n" + json.dumps({
            **{key: value for key, value in summary.items() if key not in {"completed_work", "source_item_ids", "failed_attempts", "changed_files"}},
            "completed_work": compact_facts, "older_result_refs": [f["result_item_id"] for f in facts[:-12]],
            "historical_response_refs": response_refs,
            "failed_attempts": failures, "changed_files": changes}, ensure_ascii=False))
        projected = [*retained, summary_message.model_dump(mode="json"), *[self.project(item).model_dump(mode="json") for item in tail]]
        if [m["content"] for m in projected if m["role"] == "user" and m != summary_message.model_dump(mode="json")] != [item["message"]["content"] for item in items if item["role"] == "user"]:
            raise ValueError("压缩未能完整保留用户目标与约束")
        return {**checkpoint, "state": "completed", "completed_at": now(), "through_ordinal": items[-1]["ordinal"],
                "parent_id": (self.checkpoint(session_id) or {}).get("id"), "summary": summary, "messages": projected}
