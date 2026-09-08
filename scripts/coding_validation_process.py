"""管理隔离验证子进程；退出、异常和超时时回收所属进程树。"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def managed_process(command, **options):
    job = None
    process = subprocess.Popen(command, **options, **(
        {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    ))
    try:
        if os.name == "nt":
            source = str(Path(__file__).resolve().parents[1] / "src")
            if source not in sys.path:
                sys.path.insert(0, source)
            from private_agent_local.windows_process import ProcessJob

            job = ProcessJob()
            job.assign(process.pid)
        yield process
    finally:
        if job is not None:
            job.close()
        elif os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
