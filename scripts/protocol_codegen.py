"""从共享核心生成本机 Python/TypeScript 使用的 JSON Schema 与类型。"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def generate() -> dict[str, str]:
    # 测试按文件路径加载入口，不依赖 scripts 已加入导入路径。
    spec = importlib.util.spec_from_file_location(
        "coding_contract_codegen", PROJECT_ROOT / "scripts/coding_contract_codegen.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 Coding 契约生成器")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.generate()


def main() -> int:
    parser = argparse.ArgumentParser(description="本机 Agent 契约生成")
    parser.add_argument("--check", action="store_true", help="只校验零 diff，不写入")
    args = parser.parse_args()

    artifacts = generate()
    drifted: list[str] = []
    for path_text, content in artifacts.items():
        path = Path(path_text)
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing != content:
            drifted.append(path_text)

    if args.check:
        if drifted:
            print("protocol codegen drift detected（运行 scripts/protocol_codegen.py 重新生成）:")
            for item in drifted:
                print(f"  - {item}")
            return 1
        print("protocol codegen in sync: OK")
        return 0

    for path_text, content in artifacts.items():
        path = Path(path_text)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"generated: {path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
