"""每个会话保留一条后续任务，运行结束和队列领取以事务连接。"""
from __future__ import annotations

import asyncio

from .store import now


class TurnQueue:
    def __init__(self, owner):
        self.owner = owner
        self.closed = False
        for session in owner.store.list("session"):
            item = session.get("queued_turn")
            if item and item["state"] == "pending":
                item.update(state="blocked", error="应用重启后保留后续输入，请撤回并重新发送。")
                owner.store.update("session", session["id"], queued_turn=item)

    def get(self, session_id):
        return self.owner.store.get("session", session_id).get("queued_turn")

    def enqueue(self, session_id, run_id, request_id, message):
        store = self.owner.store
        run = store.run_state(run_id)
        if run["session_id"] != session_id or run.get("recovery_contract_version") != "1.0":
            raise ValueError("队列与任务不匹配或运行协议不支持")
        previous = self.get(session_id)
        if previous and previous["request_id"] == request_id:
            if previous["message"] != message or previous["after_run_id"] != run_id:
                raise ValueError("重复请求内容不一致")
            return previous
        if previous and previous["state"] in {"pending", "blocked"}:
            raise ValueError("已有一条后续任务，请先撤回")
        if run["status"] in {"completed", "failed", "cancelled", "timed_out", "limit_exceeded", "interrupted"}:
            raise ValueError("任务已经结束，请直接发送下一条")
        item = {"request_id": request_id, "after_run_id": run_id, "message": message,
                "state": "pending", "created_at": now(), "result_run_id": None, "error": None}
        store.update("session", session_id, queued_turn=item)
        return item

    def cancel(self, session_id, request_id):
        item = self.get(session_id)
        if not item or item["request_id"] != request_id:
            raise ValueError("队列已经变化，请刷新")
        if item["state"] not in {"pending", "blocked", "cancelled"}:
            raise ValueError("后续任务已经启动，请停止对应运行")
        item.update(state="cancelled")
        self.owner.store.update("session", session_id, queued_turn=item)
        return item

    def settled(self, run):
        item = self.get(run["session_id"])
        if not self.closed and item and item["state"] == "pending" and item["after_run_id"] == run["id"]:
            # 当前运行先释放工作区，下一条再重新走权限与模型配置检查。
            asyncio.get_running_loop().call_soon(self.advance, run["session_id"], run["id"])

    def advance(self, session_id, run_id):
        if self.closed:
            return
        store = self.owner.store
        try:
            item = self.get(session_id)
        except KeyError:
            return
        if not item or item["state"] != "pending" or item["after_run_id"] != run_id:
            return
        run = store.run_state(run_id)
        if run["status"] != "completed":
            item.update(state="blocked", error="上一轮未正常结束；后续输入保留，可撤回后重新发送。")
            store.update("session", session_id, queued_turn=item)
            return
        try:
            with store.transaction():
                data = {key: run.get(key) for key in ("session_id", "project_id", "workspace_id", "permission_mode",
                        "collaboration_mode", "model_profile_id", "reasoning_effort", "context_limits",
                        "execution_contract_version", "recovery_contract_version")}
                data.update(message=item["message"], client_request_id="queue:" + item["request_id"])
                created = self.owner.create(data, launch=False)
                item.update(state="launched", result_run_id=created["id"])
                store.update("session", session_id, queued_turn=item)
            self.owner.launch(store.run(created["id"]))
        except (ValueError, KeyError):
            item.update(state="blocked", error="启动检查未通过，请检查项目、权限和模型配置后重新发送。")
            store.update("session", session_id, queued_turn=item)
