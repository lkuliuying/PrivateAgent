#!/usr/bin/env python3
"""R3 预算口径评估：保守估算 vs provider 真实 token 计数。

- 对代表性文本（中文、代码、混合、长文本）用 ``ConservativeTokenEstimator`` 估算；
- 用真实 Ollama ``/api/chat`` 的 ``prompt_eval_count`` 作为精确计数（num_predict=1，
  单次小请求）；
- 记录比值/方向与结论，输出 JSON 报告。不可用时如实标记 unsupported。

结论将写入 docs/agent-runtime-gray-verification.md 的 tokenizer 条目。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from personal_assistant.config import settings  # noqa: E402
from personal_assistant.context.builder import ConservativeTokenEstimator  # noqa: E402

REPRESENTATIVE_TEXTS = {
    "chinese_short": "操作系统是管理硬件资源的软件，进程是运行中的程序实例。",
    "chinese_long": "操作系统管理硬件资源。进程是运行实例。线程是轻量执行单元。" * 12,
    "code": 'def handler(event):\n    if event.type == "run":\n        return {"ok": True}\n    return None\n',
    "mixed": "私有助手 PrivateAgent 支持 RAG 检索、approval 审批与 tool execution。",
    "english": "The operating system manages hardware resources and schedules processes.",
}


def _ollama_usage(model: str, prompt: str) -> int | None:
    """真实 /api/chat 请求的 prompt_eval_count（num_predict=1）。失败返回 None。"""
    base = settings.ollama_base_url.rstrip("/")
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"num_predict": 1},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[tokenizer] /api/chat 不可用: {type(exc).__name__}", file=sys.stderr)
        return None
    count = data.get("prompt_eval_count")
    return int(count) if isinstance(count, int) else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=settings.llm_model)
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "data" / "rehearsals" / "r3-tokenizer-20260806" / "report.json",
    )
    args = parser.parse_args()

    estimator = ConservativeTokenEstimator(settings.token_estimate_safety_factor)
    rows = []
    for name, text in REPRESENTATIVE_TEXTS.items():
        estimated = estimator.estimate_text(text)
        actual = _ollama_usage(args.model, text)
        row = {
            "text_kind": name,
            "chars": len(text),
            "estimated_tokens_safety_adjusted": estimated,
            "actual_prompt_eval_count": actual,
            "ratio_estimate_over_actual": (
                round(estimated / actual, 3) if actual else None
            ),
            "safety_factor": settings.token_estimate_safety_factor,
        }
        rows.append(row)
        print(
            f"[tokenizer] {name:14s} chars={len(text):5d} "
            f"estimate={estimated:5d} actual={actual}"
        )

    usable = [r for r in rows if r["actual_prompt_eval_count"]]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": args.model,
        "method": (
            "ConservativeTokenEstimator(safety_factor="
            f"{settings.token_estimate_safety_factor}) vs "
            "/api/chat prompt_eval_count (num_predict=1)"
        ),
        "api_tokenize_endpoint": "unavailable (404 on this Ollama version)",
        "rows": rows,
        "conclusion": None,
    }
    if usable and len(usable) == len(rows):
        ratios = [r["ratio_estimate_over_actual"] for r in usable]
        over_estimates = sum(1 for r in ratios if r and r >= 1.0)
        report["conclusion"] = (
            f"安全系数 {settings.token_estimate_safety_factor} 下 "
            f"估算不小于真实值（{over_estimates}/{len(ratios)} 项 >=1.0），"
            f"比率范围 {min(ratios):.3f}..{max(ratios):.3f}；保守上界成立。"
            if over_estimates == len(ratios)
            else (
                f"仍存在低估（{len(ratios) - over_estimates} 项 <1.0）："
                "需要提高 PA_TOKEN_ESTIMATE_SAFETY_FACTOR。"
            )
        )
    else:
        report["conclusion"] = "真实 usage 不可用：仅记录估算口径，精确 tokenizer 评估未完成。"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        print(f"[tokenizer] refusing to overwrite: {args.out}", file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[tokenizer] report: {args.out}")
    print(f"[tokenizer] conclusion: {report['conclusion']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
