#!/usr/bin/env python3
"""M0 观察：安装版 Agent Runs API 驱动脚本（真实 Ollama 有效 run 采集）。

用途：0.2.1 安装版批 A 已开启 ``PA_AGENT_RUNS_API_ENABLED``，桌面普通聊天
仍走 legacy（不产生 agent_run）。本脚本对安装版 sidecar 发起真实 Agent API
调用，用于积累 M0 门槛要求的"有效 Agent run"样本，并支持顺带制造用户取消
与 RAG run 观察样本。

连接方式（二选一）：
1. 自动发现（推荐）：桌面正在运行，本机唯一 sidecar 进程
   ``personal-assistant-server``。脚本通过 PEB 只读读取其
   ``PA_API_PORT`` / ``PA_API_TOKEN``（QA 既有工具
   ``scripts/read_process_env.py``），无需手动传 token。
2. 显式指定：``--base-url`` + ``--token``（如开发模式 127.0.0.1:8000）。

记录只含低基数元数据（prompt 池 id、状态、usage、耗时），不保存聊天正文。

用法：
    uv run python scripts/m0_agent_run_driver.py --runs 20
    uv run python scripts/m0_agent_run_driver.py --runs 10 --knowledge 0.2 \
        --cancel-one --out data/rehearsals/m0-agent-drive/20260807.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "timed_out", "limit_exceeded"}

# 低基数 prompt 池：只记录 id 与 knowledge_base，不落正文。
# knowledge 组的题目设计为"知识库资料中可查到的事实"，便于模型命中检索工具；
# 若无证据模型应拒答（这也是合法观察样本）。
PROMPT_POOL: list[dict] = [
    {"id": "daily:01", "knowledge_base": False, "text": "请用三句话概括今天的日程管理建议。"},
    {"id": "daily:02", "knowledge_base": False, "text": "帮我列一个周末读书计划的要点。"},
    {"id": "daily:03", "knowledge_base": False, "text": "解释一下什么是可靠引用，举例说明。"},
    {"id": "daily:04", "knowledge_base": False, "text": "写一封简短的工作周报开头。"},
    {"id": "daily:05", "knowledge_base": False, "text": "介绍一种提高专注力的方法。"},
    {"id": "daily:06", "knowledge_base": False, "text": "用中文总结：本地优先的隐私原则有哪些好处。"},
    {"id": "daily:07", "knowledge_base": False, "text": "给出三条备份个人数据的最佳实践。"},
    {"id": "daily:08", "knowledge_base": False, "text": "什么是向量检索？一句话说明。"},
    {"id": "rag:01", "knowledge_base": True, "text": "根据知识库资料回答：系统的部署要求是什么？请给出资料中提到的具体内容。"},
    {"id": "rag:02", "knowledge_base": True, "text": "在知识库中查找：部署窗口的时间安排，并说明来源。"},
    {"id": "rag:03", "knowledge_base": True, "text": "查询知识库：该项目的更新机制是如何描述的？没有资料请说明。"},
    {"id": "rag:04", "knowledge_base": True, "text": "知识库里关于隐私保护有哪些约定？请引用文档。"},
    {"id": "rag:05", "knowledge_base": True, "text": "数据库升级流程在知识库中有哪些要点？"}, 
    {"id": "rag:06", "knowledge_base": True, "text": "知识库中是否提到测试门禁？如果有请说明包括哪些步骤。"},
]


async def _find_sidecar_port_and_token() -> tuple[str, str]:
    """通过 PEB 只读读取 sidecar 进程的 PA_API_PORT / PA_API_TOKEN。"""
    import read_process_env  # scripts/ 下同名模块

    # PyInstaller onefile 内层 python 与 bootloader 同名：
    # personal-assistant-server-x86_64-pc-windows-msvc[.exe]
    proc = await asyncio.create_subprocess_exec(
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-Process -Name 'personal-assistant-server*' -ErrorAction "
        "SilentlyContinue | Select-Object -ExpandProperty Id",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    pids = out.decode(errors="replace").split()
    if not pids:
        raise SystemExit(
            "[m0-driver] 未找到 sidecar 进程 personal-assistant-server*；"
            "请先启动桌面应用，或改用 --base-url/--token 显式连接"
        )
    if len(set(pids)) > 1:
        raise SystemExit(
            f"[m0-driver] 存在多个 sidecar 进程 {sorted(set(pids))}，"
            "请先关闭多余实例（owner lock 单持有者）"
        )
    pid = pids[0]
    env = read_process_env.read_process_env(int(pid))
    port = env.get("PA_API_PORT")
    token = env.get("PA_API_TOKEN")
    if not port or not token:
        raise SystemExit(
            f"[m0-driver] sidecar {pid} 缺少 PA_API_PORT/PA_API_TOKEN"
        )
    return f"http://127.0.0.1:{port}", token


async def _wait_for_terminal(
    client: httpx.AsyncClient, base: str, run_id: str, timeout_s: float = 600
) -> dict:
    started = datetime.now(timezone.utc)
    deadline = started.timestamp() + timeout_s
    while True:
        resp = await client.get(f"{base}/agent-runs/{run_id}")
        resp.raise_for_status()
        body = resp.json()
        if body["status"] in TERMINAL_STATUSES:
            body["latency_s"] = round(
                (datetime.now(timezone.utc) - started).total_seconds(), 1
            )
            return body
        if datetime.now(timezone.utc).timestamp() > deadline:
            body["status"] = "driver_timeout"
            body["latency_s"] = timeout_s
            return body
        await asyncio.sleep(1.0)


async def _run_one(
    client: httpx.AsyncClient,
    base: str,
    prompt: dict,
    session_id: int | None,
) -> dict:
    payload: dict = {
        "message": prompt["text"],
        "knowledge_base": prompt["knowledge_base"],
    }
    if session_id is not None:
        payload["session_id"] = session_id
    created = await client.post(f"{base}/agent-runs", json=payload)
    if created.status_code == 503:
        return {"prompt_id": prompt["id"], "status": "owner_unavailable", "detail": created.text[:200]}
    created.raise_for_status()
    run = created.json()
    run["prompt_id"] = prompt["id"]
    run["knowledge_base"] = prompt["knowledge_base"]
    return run


async def _cancel_one(
    client: httpx.AsyncClient, base: str, run: dict, timeout_s: float = 120
) -> dict:
    """等待 run 进入 model.started 后发起取消，验证 cancelled 持久化。"""
    run_id = run["id"]
    for _ in range(int(timeout_s)):
        events = (await client.get(f"{base}/agent-runs/{run_id}/events")).json()
        if any(item["type"] == "model.started" for item in events["items"]):
            break
        await asyncio.sleep(1.0)
    resp = await client.post(f"{base}/agent-runs/{run_id}/cancel")
    if resp.status_code != 202:
        run["cancel_note"] = f"cancel rejected: {resp.status_code}"
        return run
    run["cancel_note"] = "cancel accepted"
    return run


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=10, help="本次驱动的 run 数")
    parser.add_argument(
        "--knowledge", type=float, default=0.15, help="知识库 run 占比（0..1）"
    )
    parser.add_argument(
        "--cancel-one", action="store_true", help="第一个 run 进入 model.started 后取消"
    )
    parser.add_argument("--base-url", default=None, help="显式 API 地址")
    parser.add_argument("--token", default=None, help="显式 Bearer token")
    parser.add_argument("--out", type=Path, default=None, help="结果 JSONL 输出路径")
    args = parser.parse_args()

    if args.base_url and args.token:
        base, token = args.base_url.rstrip("/"), args.token
    elif args.base_url or args.token:
        raise SystemExit("--base-url 与 --token 必须同时提供")
    else:
        base, token = await _find_sidecar_port_and_token()
    print(f"[m0-driver] sidecar: {base}")

    headers = {"Authorization": f"Bearer {token}"}
    results: list[dict] = []
    async with httpx.AsyncClient(headers=headers, timeout=60) as client:
        session = await client.post(f"{base}/sessions", headers=headers)
        if session.status_code == 401:
            raise SystemExit("[m0-driver] 认证失败：token 不匹配")
        session.raise_for_status()
        session_id = session.json()["id"]

        cancel_done = not args.cancel_one
        knowledge_target = max(0, min(args.runs, int(args.runs * args.knowledge)))
        # 均匀交错分布知识库 run（平滑分配，避免集中在开头/结尾）
        kb_indexes = {
            i
            for i in range(args.runs)
            if (i + 1) * knowledge_target // max(1, args.runs)
            != i * knowledge_target // max(1, args.runs)
        }
        for index in range(args.runs):
            use_kb = index in kb_indexes
            pool = [p for p in PROMPT_POOL if p["knowledge_base"] == use_kb]
            prompt = pool[index % len(pool)]
            run = await _run_one(client, base, prompt, session_id)
            if run["status"] == "owner_unavailable":
                results.append(run)
                break
            if not cancel_done and run["status"] in {
                "running",
                "waiting_approval",
            }:
                run = await _cancel_one(client, base, run)
                cancel_done = True
            terminal = await _wait_for_terminal(client, base, run["id"])
            terminal["prompt_id"] = run["prompt_id"]
            terminal["knowledge_base"] = run["knowledge_base"]
            terminal["cancel_note"] = run.get("cancel_note")
            # 0.3.0 M2：在 client 生命周期内收集验证事件，避免退出上下文后
            # 使用已关闭的 AsyncClient（生命周期修复）。
            events = await _events_if_available(client, base, run["id"])
            terminal["validation_passed"] = any(
                e.get("type") == "output.validation_passed" for e in events
            )
            results.append(terminal)
            print(
                f"[m0-driver] #{index + 1} {run['prompt_id']} "
                f"status={terminal['status']} latency={terminal.get('latency_s')}s "
                f"valid={terminal['validation_passed']} "
                f"tokens={terminal.get('input_tokens')}/{terminal.get('output_tokens')}"
            )
            if run["status"] == "owner_unavailable":
                break

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "runs_requested": args.runs,
        "runs_recorded": len(results),
        "by_status": {
            status: sum(1 for r in results if r["status"] == status)
            for status in sorted({r["status"] for r in results})
        },
        "validation_passed": sum(
            1 for r in results if r.get("validation_passed")
        ),
    }
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        if args.out.exists():
            print(f"[m0-driver] refusing to overwrite: {args.out}", file=sys.stderr)
            return 1
        lines = [json.dumps(summary, ensure_ascii=False)]
        lines += [json.dumps(r, ensure_ascii=False, default=str) for r in results]
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[m0-driver] record: {args.out}")
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


async def _events_if_available(
    client: httpx.AsyncClient, base: str, run_id: str | None
) -> list[dict]:
    if run_id is None:
        return []
    resp = await client.get(f"{base}/agent-runs/{run_id}/events")
    if resp.status_code != 200:
        return []
    return resp.json()["items"]


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
