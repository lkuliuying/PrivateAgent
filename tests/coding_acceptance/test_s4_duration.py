"""S4 十分钟真实命令，不以缩短时钟或模拟事件代替。"""
import asyncio
import time

import pytest
from test_local_execution_sessions import start

pytestmark = pytest.mark.asyncio


async def test_ten_minute_command_survives_yield_and_old_timeout(session):
    before = time.monotonic()
    result = await start(session, "import time; print('STARTED',flush=True); time.sleep(600); print('FINISHED',flush=True)",
                         yield_time_ms=300, timeout_ms=610_000)
    assert result["status"] == "running"
    manager, sid, eid = session[0].execution_sessions, session[1]["session_id"], result["execution_id"]
    async with asyncio.timeout(630):
        while True:
            page = await manager.read(eid, sid, after=result["next_cursor"], wait_ms=30_000)
            if page["status"] not in {"starting", "running"}:
                break
    assert time.monotonic() - before >= 600
    assert page["status"] == "exited" and page["exit_code"] == 0 and page["stopped"]
    assert "FINISHED" in "".join(chunk["data"] for chunk in page["chunks"])
