"""从共享 Pydantic 契约生成 Coding JSON Schema 和 TypeScript。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from private_agent_core.coding_contracts import CONTRACTS  # noqa: E402


def typescript_type(schema: dict) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    if "enum" in schema:
        return " | ".join(json.dumps(item, ensure_ascii=False) for item in schema["enum"])
    if "anyOf" in schema:
        return " | ".join(typescript_type(item) for item in schema["anyOf"])
    kind = schema.get("type")
    if kind == "array":
        return f"Array<{typescript_type(schema['items'])}>"
    if kind == "object":
        if "properties" in schema:
            required = set(schema.get("required", []))
            fields = [f"{json.dumps(key)}{'' if key in required else '?'}: {typescript_type(value)}"
                      for key, value in schema["properties"].items()]
            return "{ " + "; ".join(fields) + " }"
        value = schema.get("additionalProperties", {})
        return "Record<string, " + (typescript_type(value) if isinstance(value, dict) else "unknown") + ">"
    if kind in {"string", "integer", "number", "boolean", "null"}:
        return {"integer": "number"}.get(kind, kind)
    if not schema:
        return "unknown"
    raise ValueError(f"不支持的契约结构：{schema}")


def generate() -> dict[str, str]:
    definitions = {}
    for model in CONTRACTS:
        schema = model.model_json_schema()
        for name, value in schema.pop("$defs", {}).items():
            if name in definitions and definitions[name] != value:
                raise ValueError(f"同名契约结构冲突：{name}")
            definitions[name] = value
        definitions[model.__name__] = schema
    bundle = {"$schema": "https://json-schema.org/draft/2020-12/schema",
              "$id": "urn:private-agent:coding:1.0", "$defs": definitions}
    header = "// 由 scripts/protocol_codegen.py 生成，禁止手改。\n// 唯一类型源：private_agent_core/coding_contracts.py；应用边界提供版本化扩展。\n"
    types = [f"export type {name} = {typescript_type(value)};" for name, value in sorted(definitions.items())]
    return {
        str(ROOT / "src/private_agent_core/coding_contracts.schema.json"): json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        str(ROOT / "apps/desktop/src/features/coding/model/generated/codingContracts.ts"): header + "\n" + "\n\n".join(types) + "\n",
    }
