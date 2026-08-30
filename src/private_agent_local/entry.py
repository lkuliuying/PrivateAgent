"""Packaged entrypoint; never loads server settings, databases or dotenv files."""
import argparse
import asyncio
import os
from pathlib import Path

import uvicorn

from private_agent_local.app import create_app
from private_agent_local.cloud import Cloud


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args()
    nonce = os.environ.pop("PRIVATEAGENT_LOCAL_NONCE", "")
    server = None

    def shutdown():
        server.should_exit = True

    app = create_app(data_dir=args.data_dir, cloud=Cloud(args.server), nonce=nonce, port=args.port, shutdown=shutdown)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, access_log=False,
                                          log_level="warning", loop="asyncio", http="h11", ws="none",
                                          timeout_graceful_shutdown=5))

    async def watch_parent():
        while not server.should_exit:
            await asyncio.sleep(2)
            if args.parent_pid and not parent_alive(args.parent_pid):
                await app.state.desktop.clear()
                server.should_exit = True

    async def serve():
        watcher = asyncio.create_task(watch_parent())
        try:
            await server.serve()
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

    asyncio.run(serve())


def parent_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    main()
