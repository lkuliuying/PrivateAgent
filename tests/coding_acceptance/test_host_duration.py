"""独立慢探针：从本机 API 执行超过 120 秒的真实命令。"""
import asyncio
import time

from test_baseline import record
from test_local_executor import call, close, response, setup

from private_agent_local.entry import parent_alive


async def test_s0_t05_real_command_timeout(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    (root / "duration_probe.py").write_text(
        "import os,time\nfrom pathlib import Path\n"
        "Path('duration.pid').write_text(str(os.getpid()))\n"
        "print('EARLY_OUTPUT', flush=True)\ntime.sleep(130)\n",
        encoding="utf-8",
    )
    server.responses = [response(call("run_project_command", {"command": "python duration_probe.py"})), response(text="命令已停止")]
    started = time.monotonic()
    try:
        run_id = (await client.post("/agent-runs", json={**body, "permission_mode": "workspace"})).json()["id"]
        async with asyncio.timeout(10):
            while not (root / "duration.pid").exists():
                await asyncio.sleep(0.05)
        execution = (await client.get(f"/agent-runs/{run_id}/executions")).json()[0]
        early_output_visible = execution["output"] is not None
        await asyncio.wait_for(app.state.desktop.runtime.tasks[run_id], timeout=130)
        elapsed = time.monotonic() - started
        run = app.state.desktop.runtime.store.run(run_id)
        alive = parent_alive(int((root / "duration.pid").read_text()))
        record("S0-T05-REAL", elapsed_seconds=round(elapsed, 3), early_output_visible=early_output_visible,
               status=run["status"], execution_status=run["executions"][0]["status"], child_alive=alive,
               execution_output=run["executions"][0]["output"])
        assert 115 <= elapsed <= 130
        assert run["executions"][0]["status"] == "failed" and not alive
        assert not early_output_visible
    finally:
        await close(app, client)
