"""本机隔离联调：初始化非敏感配置、检查范围、预检或调用云 API。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from coding_acceptance_catalog import load_catalog
from coding_acceptance_evidence import digest
from coding_acceptance_local import local_config
from coding_acceptance_schema import plain_path, read_json
from run_coding_validation import ROOT

TEMPLATE = ROOT / "docs/analysis/coding-agent-upgrade-20260908/local-probe.example.json"
CATALOG = ROOT / "tests/coding_acceptance/external_public/catalog.json"
DEFAULT_CONFIG = ROOT / ".run/coding-local-probe.json"


def initialize(path):
    path = plain_path(path, must_exist=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 独占创建避免覆盖用户已经填写的配置。
    with path.open("x", encoding="utf-8", newline="\n") as target:
        target.write(TEMPLATE.read_text(encoding="utf-8"))
    print(f"非敏感配置已创建：{path}\n填写 provider.endpoint、model 并核对预算；API Key 留到终端隐藏输入。")


def check(path):
    path = plain_path(path)
    before = digest(path)
    model = local_config(read_json(path))
    catalog = load_catalog(CATALOG)
    if catalog["purpose"] != "public_calibration" or not set(model["tasks"]) <= {t["id"] for t in catalog["tasks"]}:
        raise ValueError("只能选择现有公开题")
    if digest(path) != before:
        raise ValueError("检查期间配置已改变")
    return model, before


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "check", "preflight", "probe"])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="仅含供应商、模型、参数和预算的 JSON")
    parser.add_argument("--bundle", type=Path, help="可选：包含配套 sidecar、宿主和 source-manifest 的当前构建目录")
    parser.add_argument("--authorize-model-calls", action="store_true", help="按配置内固定任务和预算授权真实云 API 调用")
    args = parser.parse_args(argv)
    try:
        if args.action == "init":
            initialize(args.config)
            return 0
        model, config_hash = check(args.config)
        print("本次范围：本机临时测试身份 → 私有 IPC → Agent → 指定供应商；工具使用 AppContainer。")
        print(f"配置 SHA256：{config_hash}")
        print(f"供应商：{model['provider']['protocol']} {model['provider']['endpoint']}\n模型：{model['model']}")
        print(f"公开任务：{','.join(model['tasks'])}；每题 1 次")
        print("预算：" + json.dumps(model["budget"], ensure_ascii=False))
        print("费用未估算；token 按已知用量结算。平台账单硬上限请在供应商侧设置。", flush=True)
        if args.action == "check":
            print("配置检查通过；尚未连接供应商或验证 API Key。")
            return 0
        if args.action == "probe" and not args.authorize_model_calls:
            print("未授权真实调用。确认上述范围后添加 --authorize-model-calls；未读取凭据。", file=sys.stderr)
            return 2
        from run_coding_acceptance import run

        return run(argparse.Namespace(mode=args.action, model_config=args.config.absolute(), tasks=",".join(model["tasks"]),
                   protocol=model["protocol"], repetitions=1, catalog=CATALOG, isolation="appcontainer",
                   authorize_model_calls=args.authorize_model_calls, bundle=args.bundle,
                   expected_config_sha256=config_hash, work_dir=ROOT / ".run/coding-local-probe"))
    except KeyboardInterrupt:
        print("联调已取消。已启动运行的结果请以证据目录内的终态记录为准。", file=sys.stderr)
        return 130
    except (ValueError, OSError) as error:
        # 配置可能被误填密钥，不能把原始校验异常或输入内容输出到终端。
        print(f"本机联调未启动：{type(error).__name__}。请核对配置字段、路径、占位值及预算，已有文件不会被覆盖。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
