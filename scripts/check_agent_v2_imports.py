"""agent_v2 依赖方向检查（上位计划 §6.1 / §3.3 目标指标 2）。

规则：
  1. 依赖方向：domain <- runtime/application <- adapters；
     domain 不得导入 runtime/application/adapters/persistence/providers 之外的实现层；
  2. domain 与 runtime/application 不得导入 FastAPI、SQLAlchemy、Tauri
     或具体 Provider SDK；
  3. domain/runtime/application 不得导入 adapters；
  4. generated/ 目录只允许由 codegen 写入（文件头必须带 GENERATED 标记）。

Usage:
    uv run python scripts/check_agent_v2_imports.py         # 违规退出码 1
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENT_V2 = PROJECT_ROOT / "src" / "personal_assistant" / "agent_v2"

# 上位计划 §3.3/§6.1：核心层禁止的传输/ORM/Provider 实现依赖
FORBIDDEN_PREFIXES = (
    "fastapi",
    "sqlalchemy",
    "tauri",
    "starlette",
    "uvicorn",
    # 具体 Provider SDK（1.0 只允许 providers/ 适配层内的端口实现）
    "openai",
    "anthropic",
    "ollama",
)

CORE_LAYERS = ("domain", "runtime", "application")
IMPLEMENTATION_LAYERS = ("adapters", "persistence", "providers", "execution")


def iter_python_files(root: Path):
    if not root.exists():
        return
    yield from sorted(root.rglob("*.py"))


def module_imports(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def layer_of(path: Path) -> str | None:
    try:
        rel = path.relative_to(AGENT_V2)
    except ValueError:
        return None
    parts = rel.parts
    return parts[0] if parts else None


def check() -> list[str]:
    violations: list[str] = []
    for path in iter_python_files(AGENT_V2):
        rel = path.relative_to(PROJECT_ROOT)
        if "generated" in path.parts:
            head = path.read_text(encoding="utf-8")[:200]
            if "GENERATED" not in head:
                violations.append(f"{rel}: generated 文件缺少 GENERATED 头（疑似手改）")
            continue
        layer = layer_of(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            violations.append(f"{rel}: 语法错误 {exc}")
            continue
        imports = module_imports(tree)
        if layer in CORE_LAYERS:
            for name in imports:
                if name.startswith(FORBIDDEN_PREFIXES):
                    violations.append(
                        f"{rel}: {layer}/ 禁止导入实现依赖 `{name}`（§6.1 依赖规则）"
                    )
                root_pkg = name.split(".")[0]
                if root_pkg in ("personal_assistant",) or name.startswith(
                    "personal_assistant.agent_v2"
                ):
                    tail = name.split(".")
                    if "agent_v2" in tail:
                        sub = tail[tail.index("agent_v2") + 1] if len(tail) > tail.index(
                            "agent_v2"
                        ) + 1 else None
                        if layer == "domain" and sub in IMPLEMENTATION_LAYERS:
                            violations.append(
                                f"{rel}: domain 禁止导入 `{name}`（依赖方向反转）"
                            )
                        if layer in CORE_LAYERS and sub == "adapters":
                            violations.append(
                                f"{rel}: {layer}/ 禁止导入 adapters（依赖方向反转）"
                            )
    return violations


def main() -> int:
    violations = check()
    if violations:
        print("agent_v2 dependency violations:")
        for item in violations:
            print(f"  - {item}")
        return 1
    print("agent_v2 dependency rules: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
