"""S5 子进程故障注入：在真实日志或磁盘边界直接退出。"""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from private_agent_local import patchsets
from private_agent_local.runtime import Runtime
from private_agent_local.store import Store


def response(calls=(), text=""):
    return {"text": text, "tool_calls": list(calls), "usage": {"input_tokens": 10, "output_tokens": 5}, "provider": "fixture", "model": "fixture"}


def call(identifier, name, **arguments):
    return {"id": identifier, "name": name, "arguments": arguments}


class Model:
    def __init__(self, command):
        self.round = 0
        self.command = command

    async def identity(self, token):
        return {"id": 1}

    async def profiles(self, token):
        return [{"id": "fixture", "model_name": "fixture", "context_tokens": 128000, "is_default": True, "enabled": True}]

    async def complete(self, token, profile_id, request):
        self.round += 1
        if self.command:
            return response([call("exec", "exec_command", argv=["python", "writer.py"], execution_mode="trusted_project", network_policy="approved", yield_time_ms=0)])
        if self.round == 1:
            return response([call("read-a", "read_code_file", rel_path="a.txt"), call("read-b", "read_code_file", rel_path="b.txt")])
        outputs = [json.loads(item["content"]).get("output", {}) for item in request["messages"] if item["role"] == "tool"]
        if self.round == 2:
            snapshots = {item["rel_path"]: item["snapshot_id"] for item in outputs if "snapshot_id" in item}
            return response([call("proposal", "propose_project_patch", operations=[
                {"operation": "update", "rel_path": path, "snapshot_id": snapshots[path],
                 "edits": [{"start_line": 1, "delete_count": 1, "text": "after"}]} for path in ("a.txt", "b.txt")])])
        if self.round == 3:
            patch = next(item for item in reversed(outputs) if "patch_set_id" in item)
            return response([call("apply", "apply_project_patch", patch_set_id=patch["patch_set_id"], preview_sha256=patch["preview_sha256"])])
        return response(text="两个文件已修改并核对")


async def main(directory, boundary):
    root = directory / "project"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    for path in ("a.txt", "b.txt"):
        (root / path).write_text("before", encoding="utf-8")
    if boundary == "execution.started":
        (root / "writer.py").write_text("import os,time\nfrom pathlib import Path\nPath('writer.pid').write_text(str(os.getpid()))\nwith Path('starts.txt').open('a') as stream: stream.write('started\\n')\ntime.sleep(30)\n", encoding="utf-8")
    store = Store(directory / "state.sqlite3")
    project = store.create("project", {"root_path": str(root), "status": "active", "authorized": True})
    workspace = store.create("workspace", {"project_id": project["id"], "root_path": str(root), "status": "active"})
    session = store.create("session", {"project_id": project["id"], "workspace_id": workspace["id"]})
    # 测试认证值与模型名称分离，不能触发真实的凭据泄露拦截。
    owner = Runtime(store, Model(boundary == "execution.started"), "recovery-fixture-auth-sentinel")
    original_emit = store.emit

    def emit(run, kind, payload, **kwargs):
        result = original_emit(run, kind, payload, **kwargs)
        if kind == boundary:
            os._exit(23)
        return result

    store.emit = emit
    original_replace = patchsets.replace_one

    def replace(root, change):
        result = original_replace(root, change)
        if boundary == "patch.disk":
            os._exit(23)
        return result

    patchsets.replace_one = replace
    original_journal = owner.patches.journal

    def journal(patch, change, status, **facts):
        result = original_journal(patch, change, status, **facts)
        if boundary == "patch.intent" and status == "applying" or boundary == "patch.record" and status == "applied":
            os._exit(23)
        return result

    owner.patches.journal = journal
    original_save = store.execution_sessions.save

    def save_execution(record):
        original_save(record)
        if boundary == "execution.started" and record["status"] == "running":
            os._exit(23)

    store.execution_sessions.save = save_execution
    value = owner.create({"project_id": project["id"], "workspace_id": workspace["id"], "session_id": session["id"],
        "message": "修改 a.txt 和 b.txt", "permission_mode": "confirm" if boundary == "tool.approval_required" else "workspace",
        "model_profile_id": "fixture", "recovery_contract_version": "1.0", "execution_contract_version": "1.0" if boundary == "execution.started" else None})
    for _ in range(1000):
        run = store.run(value["id"])
        if boundary == "execution.started" and run["status"] == "waiting_approval":
            for approval in run["approvals"]:
                if approval["status"] == "pending":
                    owner.decide(run["id"], approval["id"], True)
        if run["status"] in {"failed", "completed", "cancelled"}:
            raise RuntimeError("未到达预期故障点：" + str(run.get("error_code")))
        await asyncio.sleep(0.01)
    raise TimeoutError("故障点未触发")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]).resolve(), sys.argv[2]))
