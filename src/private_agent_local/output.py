"""可选结构化交付的格式边界；格式正确不代表任务执行正确。"""
from __future__ import annotations

import json
from copy import deepcopy

from jsonschema import Draft202012Validator, validators
from referencing import Registry
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from private_agent_core.contracts import ModelOutputFormat
from private_agent_core.verification import OutputVerification

MAX_OUTPUT_BYTES = 1024 * 1024
MAX_VALUE_NODES = 4096
MAX_VALIDATION_STEPS = 20000
MAX_VALIDATION_BYTES = 16 * 1024 * 1024
SCHEMA_KEYWORDS = {
    "$schema", "$ref", "$defs", "definitions", "$anchor", "type", "enum", "const",
    "title", "description", "default", "examples", "properties", "required", "additionalProperties",
    "items", "prefixItems", "minItems", "maxItems", "minProperties", "maxProperties",
    "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "multipleOf", "anyOf", "allOf", "oneOf", "not",
}


def _schema_nodes(schema):
    pending = [schema]
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, bool):
            continue
        for key in ("properties", "$defs", "definitions"):
            pending.extend(node.get(key, {}).values())
        for key in ("anyOf", "allOf", "oneOf", "prefixItems"):
            pending.extend(node.get(key, []))
        for key in ("items", "additionalProperties", "not"):
            if key in node:
                pending.append(node[key])


def validate_output_schema(value: dict | None) -> dict | None:
    if value is None:
        return None
    schema = ModelOutputFormat(json_schema=value).json_schema
    nodes = list(_schema_nodes(schema))
    node_ids, anchors = {id(node) for node in nodes}, set()
    for node in nodes:
        if isinstance(node, bool):
            continue
        if set(node) - SCHEMA_KEYWORDS:
            raise ValueError("输出 Schema 含不支持的关键字；不支持正则、唯一项、格式断言或未求值属性规则")
        if "$schema" in node and node["$schema"] != "https://json-schema.org/draft/2020-12/schema":
            raise ValueError("输出 Schema 只支持 JSON Schema 2020-12")
        if "$anchor" in node:
            if node["$anchor"] in anchors:
                raise ValueError("输出 Schema 含重复的本地锚点")
            anchors.add(node["$anchor"])
    resolver = Registry().with_resource("", DRAFT202012.create_resource(schema)).resolver()
    for node in nodes:
        if isinstance(node, dict) and "$ref" in node:
            try:
                target = resolver.lookup(node["$ref"]).contents
            except Unresolvable as exc:
                raise ValueError("输出 Schema 的本地引用无法解析") from exc
            if id(target) not in node_ids:
                raise ValueError("输出 Schema 的本地引用必须指向有效 Schema 节点")
    return schema


def _bounded_instance(value):
    pending, count = [(value, 0)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > MAX_VALUE_NODES or depth > 32:
            raise ValueError("结构化结果超过节点数或深度限制")
        if isinstance(node, dict):
            pending.extend((item, depth + 1) for item in node.values())
        elif isinstance(node, list):
            pending.extend((item, depth + 1) for item in node)


def _instance_weights(value):
    weights = {}

    def weigh(node):
        if isinstance(node, dict):
            size = sum(len(key.encode("utf-8")) + weigh(item) + 4 for key, item in node.items()) + 2
        elif isinstance(node, list):
            size = sum(weigh(item) + 1 for item in node) + 2
        else:
            size = len(json.dumps(node, ensure_ascii=False).encode("utf-8"))
        weights[id(node)] = size
        return size

    weigh(value)
    return weights


def _bounded_validator(schema, value):
    remaining = MAX_VALIDATION_STEPS
    remaining_bytes = MAX_VALIDATION_BYTES
    weights = _instance_weights(value)
    schema = deepcopy(schema)
    for node in _schema_nodes(schema):
        if isinstance(node, dict):
            # 已在创建边界限定方言；避免子 Schema 切换验证器而绕过共享计算预算。
            node.pop("$schema", None)

    def bounded(name, check):
        def validate(validator, constraint, instance, current_schema):
            nonlocal remaining, remaining_bytes
            count = max(1, len(constraint)) if name in {"allOf", "anyOf", "oneOf", "enum"} else 1
            remaining -= count
            remaining_bytes -= weights.get(id(instance), MAX_OUTPUT_BYTES) * count
            if remaining < 0 or remaining_bytes < 0:
                raise ValueError("结构化格式验证超过计算预算")
            yield from check(validator, constraint, instance, current_schema)
        return validate

    # 组合分支预留全部实例检查量，避免大量失败分支复制大正文形成错误上下文。
    checks = {name: bounded(name, check) for name, check in Draft202012Validator.VALIDATORS.items()}
    return validators.extend(Draft202012Validator, checks)(schema)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("结构化输出包含重复字段")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("结构化输出包含非 JSON 数值")


def parse_structured_output(text: str, schema: dict) -> dict:
    """只接受完整 JSON 对象，不从 Markdown 或不完整正文中猜测结果。"""
    if len(text.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("结构化输出超过大小限制")
    value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("结构化输出必须是 JSON 对象")
    _bounded_instance(value)
    json.dumps(value, allow_nan=False)
    if not _bounded_validator(schema, value).is_valid(value):
        raise ValueError("结构化输出不符合指定格式")
    return value


def verify_structured_output(text: str, schema: dict) -> OutputVerification | None:
    try:
        parse_structured_output(text, schema)
    except Unresolvable:
        return OutputVerification(passed=False, code="output_schema_invalid",
            message="输出格式中的本地引用无法解析，请修正任务的 JSON Schema", retryable=False)
    except (ValueError, RecursionError):
        # 不把模型正文或 schema 错误中的实例值放进错误事件与纠正提示。
        return OutputVerification(passed=False, code="output_schema_mismatch",
            message="最终回答未满足指定的 JSON Schema",
            correction="请保留原任务和权限约束，继续必要工作；最终仅返回符合指定 JSON Schema 的完整 JSON 对象，不要包含代码围栏、重复字段或额外说明。")
    return None
