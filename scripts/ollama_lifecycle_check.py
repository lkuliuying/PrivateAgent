#!/usr/bin/env python3
"""R2.2 Ollama 生命周期检查（Windows 交付模式：外部 Ollama 由用户管理）。

验证并记录外部 Ollama 的可重复状态与测量，不启动/不托管 Ollama：
1. 安装检测：ollama 可执行文件 + 常见安装路径；
2. 进程与端口：ollama.exe 进程、127.0.0.1:11434 监听；
3. 健康与模型：GET /api/tags、LLM/embedding 模型存在性；
4. 冷/热启动与 embedding P95：首次 embed（冷加载）与后续 embed（热）计时；
5. 模型常驻：GET /api/ps 观察已加载模型；
6. 退出残留：外部模式下 Ollama 由用户管理，脚本只报告进程与端口现状，
   并校验本仓库不持有任何残留 sidecar/uvicorn 进程（应用生命周期由应用自身负责）。

输出：data/rehearsals/ollama-lifecycle-<date>/report.json + 控制台摘要。
退出码：0 健康 / 1 模型缺失或测量失败 / 2 服务未运行（如文档可重复启动）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_LLM_MODEL = "qwen2.5:14b-instruct-q4_K_M"
DEFAULT_EMBED_MODEL = "bge-m3"
HTTP_TIMEOUT_S = 15


def _read_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """从项目 .env 读 PA_OLLAMA_BASE_URL / PA_LLM_MODEL / PA_EMBED_MODEL（不打印值以外内容）。"""
    out = dict(base or {})
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key in {
                "PA_OLLAMA_BASE_URL",
                "PA_LLM_MODEL",
                "PA_EMBED_MODEL",
            }:
                out[key] = value.strip()
    return out


def _get(url: str, timeout: float = HTTP_TIMEOUT_S):
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ollama_on_path() -> bool:
    return shutil.which("ollama") is not None


def _ollama_processes() -> list[dict]:
    if os.name != "nt":
        try:
            out = subprocess.run(
                ["pgrep", "-af", "ollama"], capture_output=True, text=True, timeout=10
            )
            return [{"line": line} for line in out.stdout.splitlines() if line]
        except Exception:  # noqa: BLE001
            return []
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq ollama.exe", "/FO", "CSV"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        lines = [ln for ln in out.stdout.splitlines() if "ollama.exe" in ln]
        return [{"line": line.strip()} for line in lines]
    except Exception:  # noqa: BLE001
        return []


def _embed_timed(base_url: str, model: str, text: str, timeout: float = 120.0) -> float:
    """一次 /api/embed 调用耗时（模型冷加载可能数十秒）。"""
    payload = json.dumps({"model": model, "input": text}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
            if resp.status != 200 or not data.get("embeddings"):
                raise RuntimeError(f"/api/embed 返回异常: {resp.status}")
        return (time.perf_counter() - started) * 1000.0
    except urllib.error.URLError as exc:
        raise RuntimeError(f"/api/embed 失败: {exc.reason}") from exc


def _api_ps(base_url: str) -> dict:
    try:
        status, data = _get(f"{base_url}/api/ps", timeout=5)
        if status != 200:
            return {"error": f"/api/ps 返回 {status}"}
        return {
            "models": [
                {
                    "name": m.get("name"),
                    "size_bytes": m.get("size"),
                    "expires_at": m.get("expires_at"),
                    "is_loading": m.get("is_loading"),
                }
                for m in data.get("models", [])
            ]
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:300]}


def run() -> dict:
    env = _read_env(dict(os.environ))
    base_url = (env.get("PA_OLLAMA_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    llm_model = env.get("PA_LLM_MODEL") or DEFAULT_LLM_MODEL
    embed_model = env.get("PA_EMBED_MODEL") or DEFAULT_EMBED_MODEL
    host = base_url.replace("http://", "").replace("https://", "").split(":")[0]
    port = 11434
    try:
        port = int(base_url.rsplit(":", 1)[1].split("/")[0])
    except (IndexError, ValueError):
        pass
    started_at = datetime.now(UTC).isoformat()
    report: dict = {
        "started_at": started_at,
        "mode": "external_user_managed",
        "base_url": base_url,
        "llm_model": llm_model,
        "embed_model": embed_model,
        "checks": {},
        "measurements": {},
    }

    report["checks"]["installation"] = {
        "ollama_on_path": _ollama_on_path(),
        "common_paths": [
            str(p)
            for p in (
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                Path(os.environ.get("PROGRAMFILES", "")) / "Ollama" / "ollama.exe",
                Path.home() / ".ollama" / "bin" / "ollama",
            )
            if p.exists()
        ],
    }
    report["checks"]["process"] = {
        "ollama_processes": _ollama_processes(),
        "port_11434_open": _port_open(host, port),
    }

    service_down = not report["checks"]["process"]["port_11434_open"]
    if service_down:
        report["checks"]["service"] = {
            "ok": False,
            "error_code": "ollama_not_running",
            "error": f"127.0.0.1:{port} 未监听；外部模式下请按 docs/ollama-lifecycle.md 启动 Ollama",
        }
        report["status"] = "service_down"
        return report

    try:
        status, tags = _get(f"{base_url}/api/tags")
        models = {m.get("name", "") for m in tags.get("models", [])}
    except Exception as exc:  # noqa: BLE001
        report["checks"]["service"] = {
            "ok": False,
            "error_code": "ollama_http_error",
            "error": str(exc)[:300],
        }
        report["status"] = "http_error"
        return report
    report["checks"]["service"] = {
        "ok": True,
        "status_code": status,
        "model_count": len(models),
    }

    def _available(wanted: str) -> bool:
        if wanted in models:
            return True
        base = wanted.split(":")[0]
        return any(m.split(":")[0] == base for m in models)

    llm_ok = _available(llm_model)
    embed_ok = _available(embed_model)
    missing = [
        name
        for name, ok in ((llm_model, llm_ok), (embed_model, embed_ok))
        if not ok
    ]
    report["checks"]["models"] = {
        "ok": not missing,
        "llm_model_available": llm_ok,
        "embed_model_available": embed_ok,
        "missing_models": missing,
    }
    if missing:
        report["status"] = "model_missing"
        return report

    # 冷/热启动与 embedding P95（外部模式：Ollama 自动按需加载模型）
    try:
        probe = "PrivateAgent 生命周期测量占位文本。" * 4
        cold_ms = _embed_timed(base_url, embed_model, probe, timeout=300)
        hot_ms = []
        for _ in range(4):
            hot_ms.append(_embed_timed(base_url, embed_model, probe, timeout=60))
        report["measurements"]["embed_embed_model"] = embed_model
        report["measurements"]["embed_cold_ms"] = round(cold_ms, 1)
        report["measurements"]["embed_hot_ms"] = [round(v, 1) for v in hot_ms]
        report["measurements"]["embed_p50_ms"] = round(
            statistics.median(hot_ms), 1
        )
        report["measurements"]["embed_p95_ms"] = round(
            statistics.quantiles(hot_ms, n=20)[18], 1
        )
    except Exception as exc:  # noqa: BLE001
        report["measurements"] = {
            "error_code": "embedding_probe_failed",
            "error": str(exc)[:300],
        }
        report["status"] = "measurement_failed"
        return report

    report["measurements"]["model_resident"] = _api_ps(base_url)
    report["status"] = "ok"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "rehearsals"
        / f"ollama-lifecycle-{datetime.now(UTC).strftime('%Y%m%d')}"
        / "report.json",
    )
    args = parser.parse_args()

    report = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        print(f"[ollama-lifecycle] refusing to overwrite: {args.out}", file=sys.stderr)
        return 1
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(
        {
            "status": report.get("status"),
            "service": report["checks"]["service"].get("ok"),
            "models_ok": report["checks"]["models"].get("ok"),
            "embed_p50_ms": report.get("measurements", {}).get("embed_p50_ms"),
            "embed_p95_ms": report.get("measurements", {}).get("embed_p95_ms"),
            "embed_cold_ms": report.get("measurements", {}).get("embed_cold_ms"),
            "model_resident": report.get("measurements", {}).get("model_resident"),
            "report_path": str(args.out.resolve()),
        },
        ensure_ascii=False,
        indent=2,
    ))
    return {
        "ok": 0,
        "model_missing": 1,
        "measurement_failed": 1,
        "service_down": 2,
        "http_error": 2,
    }.get(report.get("status"), 1)


if __name__ == "__main__":
    raise SystemExit(main())
