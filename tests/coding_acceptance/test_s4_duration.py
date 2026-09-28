"""S4 十分钟真实命令，不以缩短时钟或模拟事件代替。"""
import asyncio
import time

import pytest
from test_local_execution_sessions import session as session
from test_local_execution_sessions import start

pytestmark = pytest.mark.asyncio


async def test_ten_minute_command_survives_yield_and_old_timeout(session):
    before = time.monotonic()
    result = await start(session, "import time; print('STARTED',flush=True); time.sleep(600); print('FINISHED',flush=True)",
                         yield_time_ms=300, timeout_ms=610_000)
    assert result["status"] == "running"
    manager, sid, eid = session[0].execution_sessions, session[1]["session_id"], result["execution_id"]
    cursor = result["next_cursor"]
    chunks = list(result["chunks"])
    async with asyncio.timeout(630):
        while True:
            page = await manager.read(eid, sid, after=cursor, wait_ms=30_000)
            chunks.extend(page["chunks"])
            # 推进游标才能等待新事件，避免重复读取非空页使事件循环无法处理退出。
            cursor = page["next_cursor"]
            if page["status"] not in {"starting", "running"}:
                break
    assert time.monotonic() - before >= 600
    assert page["status"] == "exited" and page["exit_code"] == 0 and page["stopped"]
    assert len({chunk["sequence"] for chunk in chunks}) == len(chunks)
    output = "".join(chunk["data"] for chunk in chunks)
    assert output.count("STARTED") == 1 and output.count("FINISHED") == 1
