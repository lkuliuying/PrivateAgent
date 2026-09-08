"""按账号、工作区和会话绑定的有界宿主槽位，管理真实进程生命周期。"""
from __future__ import annotations

import asyncio
import os
import secrets
import sys
import time
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from private_agent_core.completion import interpret_execution
from private_agent_core.execution.contracts import ExecStartParams, ExecStdinParams
from private_agent_core.execution.exec_host_client import (
    ExecHostClient,
    ExecutorUnavailable,
)

from . import files
from .completion import content_ref, workspace_state
from .execution_store import ACTIVE
from .executor import host_path, verify_host
from .store import now


class ExecutionSessions:
    def __init__(self, owner):
        self.owner = owner
        self.store = owner.store.execution_sessions
        self.slots = {}
        self.lock = asyncio.Lock()
        self.closed = False

    def _check(self, run, root):
        if self.closed or not self.owner.token:
            raise ValueError("账号或执行服务已关闭")
        if self.owner.root(run["project_id"], run["workspace_id"]) != root:
            raise ValueError("工作区位置已变化")
        if files.file_identity(root) != run.get("root_identity", files.file_identity(root)):
            raise ValueError("工作区身份已变化")
        if self.owner.project_context_set and self.owner.active_project_id != run["project_id"]:
            raise ValueError("当前项目已切换")
        self.owner.require_grant(run)
        if self.owner.store.get("session", run["session_id"]).get("archived_at"):
            raise ValueError("会话已关闭，不能继续执行")

    async def start(self, run, execution, root, cwd, argv, args, *, prepared=None):
        self._check(run, root)
        async with self.lock:
            if len(self.slots) >= 4 or sum(s["record"]["workspace_id"] == run["workspace_id"] for s in self.slots.values()) >= 2:
                raise ValueError("活动执行已达上限：每工作区 2 个、账号 4 个")
            if self.store.db.execute("SELECT COUNT(*) FROM managed_executions WHERE run_id=?", (run["id"],)).fetchone()[0] >= 256:
                raise ValueError("本任务执行记录已达 256 条上限")
            path = host_path()
            digest = verify_host(path)
            command, env = prepared or files.prepare_process(argv)
            client = ExecHostClient([str(path)], cwd=str(root), env=env)
            record = {"execution_id": execution["id"], "operation_id": execution["operation_id"],
                      "host_instance_id": str(uuid.uuid4()), "run_id": run["id"], "session_id": run["session_id"],
                      "project_id": run["project_id"], "workspace_id": run["workspace_id"], "tool_call_id": execution["tool_call_id"],
                      "argv": argv, "cwd": args.cwd, "status": "starting", "state_version": 1,
                      "retention": args.retention, "stdin_open": args.stdin, "tty": args.tty,
                      "execution_mode": args.execution_mode, "network_policy": args.network_policy,
                      "host_sha256": digest, "timeout_ms": args.timeout_ms,
                      "created_at": now(), "completed_at": None, "exit_code": None, "stopped": False,
                      "last_output_sequence": 0, "total_output_bytes": 0, "dropped_bytes": 0,
                      "error": None, "authorization_sha256": execution.get("authorization_sha256", execution["arguments_sha256"]),
                      "expires_at": (datetime.now(timezone.utc) + timedelta(milliseconds=args.timeout_ms)).isoformat()}
            slot = {"record": record, "client": client, "nonce": secrets.token_urlsafe(32), "changed": asyncio.Event(),
                    "task": None, "lock": asyncio.Lock(), "run": run, "root": root, "execution": execution, "cancel_requested": False}
            self.slots[record["execution_id"]] = slot
            try:
                self.store.save(record)
                dll_search = nullcontext()
                if os.name == "nt" and getattr(sys, "frozen", False):
                    from .windows_process import system_dll_search
                    dll_search = system_dll_search()
                with dll_search:
                    health = await client.start()
                if health.session_protocol != 1 or not health.process_tree_termination:
                    raise ValueError("执行宿主缺少持续会话或进程树回收能力，请升级完整客户端")
                # 当前原生隔离探测尚未闭环，不能把可信执行伪装成受限执行。
                if args.execution_mode != "trusted_project" or args.network_policy != "approved":
                    raise ValueError("当前宿主未验证文件或网络隔离；受限执行不可用，需明确批准可信项目执行及网络范围")
                if args.tty and "pty" not in health.modes:
                    raise ValueError("当前宿主不支持 PTY")
                self._check(run, root)
                await client.start_execution(ExecStartParams(execution_id=record["execution_id"], argv=command, cwd=str(cwd), env_diff=env,
                    timeout_ms=args.timeout_ms, output_limit_bytes=1024 * 1024, sandbox_policy_hash=record["authorization_sha256"],
                    network_policy="approved", stdin_mode="pipe" if args.stdin else "closed", session_nonce=slot["nonce"],
                    mode="pty" if args.tty else "argv"))
                record.update(status="running", state_version=2)
                self.store.save(record)
                slot["task"] = asyncio.create_task(self._monitor(slot))
            except BaseException:
                try:
                    await client.close()
                    record.update(status="failed", error="执行启动失败，未降级执行", completed_at=now(), stopped=True, state_version=2)
                    self.store.save(record)
                finally:
                    self.slots.pop(record["execution_id"], None)
                raise
        return await self.read(record["execution_id"], run["session_id"], wait_ms=args.yield_time_ms, limit=args.output_budget)

    async def _monitor(self, slot):
        record, client, run = slot["record"], slot["client"], slot["run"]
        chunks, expected, cancelled, last_flush, last_auth = [], 0, False, time.monotonic(), time.monotonic()

        def flush():
            nonlocal chunks, last_flush
            if chunks:
                self.store.append(record, chunks)
                self.owner.store.emit(run, "execution.output", {"execution_id": record["execution_id"],
                    "last_output_sequence": record["last_output_sequence"], "dropped_bytes": record["dropped_bytes"]}, lightweight=True)
                chunks = []
                slot["changed"].set()
            last_flush = time.monotonic()

        try:
            while True:
                self._check(run, slot["root"])
                if time.monotonic() - last_auth >= 15:
                    async with asyncio.timeout(5):
                        await self.owner.cloud.identity(self.owner.token)
                    last_auth = time.monotonic()
                event = await client.next_event(timeout=0.05)
                if event is None:
                    client.ensure_alive()
                else:
                    if event.execution_id != record["execution_id"] or event.sequence != expected:
                        raise ExecutorUnavailable("宿主输出序号缺失或执行归属不匹配")
                    expected += 1
                    if event.stream and event.data:
                        chunks.append((event.stream, event.data, event.sequence))
                    if event.notification.value == "execution/cancelled":
                        cancelled = True
                    if event.notification.value == "execution/failed":
                        raise ExecutorUnavailable("宿主无法确认完整执行结果")
                    if event.notification.value == "execution/exited":
                        if event.exit_code is None:
                            raise ExecutorUnavailable("宿主未报告退出码")
                        record.update(status="timed_out" if event.cancelled_by_timeout else "cancelled" if cancelled or slot["cancel_requested"] else "exited",
                                      exit_code=event.exit_code)
                        break
                if time.monotonic() - last_flush >= 0.1 or len(chunks) >= 16:
                    flush()
        except asyncio.CancelledError:
            record.update(status="cancelled", error="执行已取消")
        except Exception:
            # 账号撤销、磁盘故障与协议中断均回收整个独占宿主，未知结果不自动重试。
            record.update(status="unknown", error="执行通信、授权或持久化失败；未重放操作")
        finally:
            try:
                await client.close()
                record["stopped"] = True
            except Exception:
                record.update(status="unknown", stopped=False, error="无法确认进程树已停止")
            record.update(completed_at=now(), stdin_open=False, state_version=record["state_version"] + 1)
            try:
                # 证据检查完成前不发布终态，避免续读先看到退出而工具结果尚未保存。
                after = await asyncio.to_thread(workspace_state, slot["root"])
                flush()
                self.store.save(record)
                execution = slot["execution"]
                page = self.store.read(record)
                output = {"execution_id": record["execution_id"], "args": record["argv"],
                          "stdout": "".join(chunk["data"] for chunk in page["chunks"] if chunk["stream"] == "stdout"),
                          "stderr": "".join(chunk["data"] for chunk in page["chunks"] if chunk["stream"] == "stderr"),
                          "truncated": bool(record["dropped_bytes"] or page["has_more"]), "stopped": record["stopped"],
                          "returncode": record["exit_code"] if record["status"] == "exited" else None}
                result = interpret_execution(execution_id=record["execution_id"], operation_id=record["operation_id"],
                    argv=record["argv"], outcome=record["status"], exit_code=record["exit_code"] if record["status"] == "exited" else None,
                    output_ref=content_ref(output))
                execution["workspace_changed"] = after["digest"] is None or after["digest"] != execution.get("workspace_digest")
                if execution["workspace_changed"]:
                    run["workspace_version"] = run.get("workspace_version", 0) + 1
                execution.update(output=output, execution_result=result.model_dump(mode="json"), completed_at=now(),
                    status="completed" if record["status"] == "exited" and result.validation_outcome != "failed" else "failed",
                    error_code=None if record["status"] == "exited" and result.validation_outcome != "failed" else "execution_unknown" if record["status"] == "unknown" else "command_failed")
                with self.owner.store.transaction():
                    record["execution_result"] = execution["execution_result"]
                    self.store.save(record)
                    event = self.owner.store.emit(run, "tool.failed" if execution["status"] == "failed" else "tool.completed",
                        {"name": "exec_command", "tool_call_id": execution["tool_call_id"], "execution_id": execution["id"],
                         "operation_id": execution["operation_id"], "error_type": execution["error_code"]}, lightweight=True)
                    execution["source_sequence"] = event["sequence"]
                    if execution["error_code"] == "execution_unknown" and execution.get("scope"):
                        uncertain = {"operation_id": execution["operation_id"], "scope": execution["scope"]}
                        run.setdefault("uncertain_operations", []).append(uncertain)
                        state = self.owner.store.run_state(run["id"])
                        state.setdefault("uncertain_operations", []).append(uncertain)
                        self.store.db.execute("UPDATE runs SET data=? WHERE id=?", (self.owner.store._pack(state), run["id"]))
                    self.store.db.execute("UPDATE executions SET data=? WHERE run_id=? AND id=?", (self.owner.store._pack(execution), run["id"], execution["id"]))
                self.owner.store.emit(run, "execution.terminal", {"execution_id": record["execution_id"], "status": record["status"],
                    "stopped": record["stopped"], "exit_code": record["exit_code"]}, lightweight=True)
            except Exception:
                # 输出仓库失败时仍尝试保存最小终态；失败不能伪装成命令成功。
                record.update(status="unknown", error="进程已请求回收，但执行证据无法完整保存")
                try:
                    self.store.save(record)
                except Exception:
                    self.closed = True
            finally:
                slot["changed"].set()
                self.slots.pop(record["execution_id"], None)

    async def read(self, execution_id, session_id, *, after=0, wait_ms=0, limit=32_000):
        record = self.store.get(execution_id, session_id)
        slot = self.slots.get(execution_id)
        if not slot and record["status"] in ACTIVE:
            record.update(status="unknown", stopped=False, error="活动进程的内存状态缺失，无法确认执行结果")
        if slot and record["status"] in ACTIVE and record["last_output_sequence"] <= after and wait_ms:
            slot["changed"].clear()
            try:
                await asyncio.wait_for(slot["changed"].wait(), min(wait_ms, 30_000) / 1000)
            except TimeoutError:
                pass
            record = self.store.get(execution_id, session_id)
        return self.store.read(record, after, limit)

    def list(self, session_id):
        records = self.store.list(session_id)
        for record in records:
            if record["execution_id"] not in self.slots and record["status"] in ACTIVE:
                record.update(status="unknown", stopped=False, error="活动进程的内存状态缺失，无法确认执行结果")
        return records

    async def write(self, execution_id, session_id, data, close, version):
        record = self.store.get(execution_id, session_id)
        slot = self.slots.get(execution_id)
        if not slot:
            raise ValueError("执行已经结束，不能写入 stdin")
        async with slot["lock"]:
            record = slot["record"]
            self._check(slot["run"], slot["root"])
            if record["state_version"] != version or not record["stdin_open"]:
                raise ValueError("执行状态已变化或 stdin 已关闭，请重新读取状态")
            await slot["client"].write_stdin(ExecStdinParams(execution_id=execution_id, session_nonce=slot["nonce"], data=data, close=close))
            slot["record"]["state_version"] += 1
            slot["record"]["stdin_open"] = not close
            self.store.save(slot["record"])
        return await self.read(execution_id, session_id)

    async def cancel(self, execution_id, session_id):
        record = self.store.get(execution_id, session_id)
        slot = self.slots.get(execution_id)
        if slot and slot["task"]:
            slot["cancel_requested"] = True
            if not slot["task"].cancelling():
                slot["task"].cancel()
            await asyncio.shield(asyncio.gather(slot["task"], return_exceptions=True))
            if execution_id in self.slots:
                # 任务在第一次调度前被取消时，其 finally 尚未建立。
                await slot["client"].close()
                slot["record"].update(status="cancelled", stopped=True, stdin_open=False, completed_at=now(),
                                      state_version=slot["record"]["state_version"] + 1)
                self.store.save(slot["record"])
                self.slots.pop(execution_id, None)
            record = self.store.get(execution_id, session_id)
        return record

    async def stop_matching(self, predicate):
        for slot in list(self.slots.values()):
            if predicate(slot["record"]):
                await self.cancel(slot["record"]["execution_id"], slot["record"]["session_id"])

    async def close(self):
        self.closed = True
        await self.stop_matching(lambda record: True)

    async def capabilities(self):
        from private_agent_core.coding_contracts import CapabilitySnapshot

        from .execution_tools import TOOLS
        snapshot = CapabilitySnapshot()
        health = None
        client = None
        try:
            path = host_path()
            verify_host(path)
            _, env = files.prepare_process([str(path)])
            client = ExecHostClient([str(path)], env=env)
            health = await client.start()
            enabled = health.session_protocol == 1 and health.process_tree_termination
            snapshot = CapabilitySnapshot(execution=enabled, stdin=enabled, output_streaming=enabled,
                tools=[{"name": name, "version": "1"} for name in TOOLS] if enabled else [])
        except (ValueError, OSError, ExecutorUnavailable):
            pass
        finally:
            if client:
                await client.close()
        return {"contract": snapshot.model_dump(mode="json"), "session_protocol": "1.0" if snapshot.execution else None,
                "file_read_isolation": False, "file_write_isolation": False, "network_isolation": False,
                "pty": "probe_on_request" if health and "pty" in health.modes else "unavailable",
                "trusted_project_requires_approval": True, "workspace_limit": 2, "account_limit": 4}
