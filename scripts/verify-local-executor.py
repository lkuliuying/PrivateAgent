"""Smoke-test a packaged local executor without any account/provider credentials."""
import argparse
import hashlib
import json
import os
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve(strict=True)
    root = Path(__file__).resolve().parents[1]
    output = root / ".run" / f"local-executor-smoke-{secrets.token_hex(4)}"
    output.mkdir(parents=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    nonce = secrets.token_hex(32)
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "USERPROFILE"}}
    env["PRIVATEAGENT_LOCAL_NONCE"] = nonce
    # Deliberately no Python, project venv, database or model tools in PATH.
    env["PATH"] = str(Path(os.environ["SYSTEMROOT"]) / "System32")
    process = subprocess.Popen([str(executable), "--port", str(port), "--server", "https://unused.example.test",
                                "--data-dir", str(output / "data"), "--parent-pid", str(os.getpid())],
                               cwd=output, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path, *, method="GET", token=nonce, origin="http://tauri.localhost"):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                     headers={"X-PrivateAgent-Local": token, "Origin": origin})
        try:
            with opener.open(req, timeout=2) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    try:
        for _ in range(150):
            if process.poll() is not None:
                raise RuntimeError("Packaged local executor exited before becoming ready")
            try:
                status, health = request("/health")
                if status == 200 and health.get("mode") == "desktop-local":
                    break
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("Packaged local executor startup timed out")
        assert request("/health", token="invalid")[0] == 403
        assert request("/health", origin="https://untrusted.example.test")[0] == 403
        assert request("/projects")[0] == 401
        assert request("/internal/shutdown", method="POST")[0] == 200
        assert process.wait(timeout=10) == 0
        result = {"passed": True, "packaged_executable": str(executable), "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                  "python_on_path": False, "checks": ["startup", "health", "nonce", "origin", "account-required", "graceful-shutdown"],
                  "production_requests": 0}
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        print("Result:", output / "result.json")
    finally:
        if process.poll() is None:
            subprocess.run([str(Path(os.environ["SYSTEMROOT"]) / "System32" / "taskkill.exe"), "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
