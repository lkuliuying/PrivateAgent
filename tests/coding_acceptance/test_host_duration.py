"""旧 API 兼容探针：S4 后真实命令应能越过 S0 的 120 秒旧限制。"""
import asyncio
import time

from test_baseline import record
from test_local_executor import call, close, response, setup

from private_agent_local.entry import parent_alive


async def test_legacy_command_survives_old_timeout(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    (root / "duration_probe.cjs").write_text(
        "const fs = require('node:fs');\n"
        "fs.writeFileSync('duration.pid', String(process.pid));\n"
        "console.log('EARLY_OUTPUT');\nsetTimeout(() => console.log('FINISHED'), 130000);\n",
        encoding="utf-8",
    )
    # 使用已支持的受限工具入口，不扩大 Python 工具目录的授权扫描上限。
    server.responses = [response(call("run_project_command", {"command": "node --preserve-symlinks-main duration_probe.cjs"}))]
    requested = time.monotonic()
    try:
        run_id = (await client.post("/agent-runs", json={**body, "permission_mode": "workspace"})).json()["id"]
        async with asyncio.timeout(45):
            while not (root / "duration.pid").exists():
                await asyncio.sleep(0.05)
        # 授权准备耗时独立记录，运行时长从真实进程启动后计时。
        started = time.monotonic()
        execution = (await client.get(f"/agent-runs/{run_id}/executions")).json()[0]
        early_output_visible = execution["output"] is not None
        # 此专项核对原命令终态，不把后续模型等待或完成验证耗时算作进程运行时长。
        async with asyncio.timeout(145):
            while True:
                execution = (await client.get(f"/agent-runs/{run_id}/executions")).json()[0]
                if execution["status"] not in {"pending", "running"}:
                    break
                await asyncio.sleep(0.05)
        elapsed = time.monotonic() - started
        run = app.state.desktop.runtime.store.run(run_id)
        alive = parent_alive(int((root / "duration.pid").read_text()))
        record("S4-LEGACY-DURATION", elapsed_seconds=round(elapsed, 3), startup_seconds=round(started - requested, 3), early_output_visible=early_output_visible,
               status=run["status"], execution_status=run["executions"][0]["status"], child_alive=alive,
               execution_output=run["executions"][0]["output"])
        assert 129 <= elapsed <= 145
        execution = run["executions"][0]
        assert execution["status"] == "completed" and execution["output"]["returncode"] == 0 and not alive
        assert execution["output"]["stdout"].count("FINISHED") == 1
        assert not early_output_visible
    finally:
        await close(app, client)
