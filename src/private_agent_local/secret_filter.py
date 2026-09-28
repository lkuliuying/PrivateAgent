"""公开输出边界的秘密过滤；不修改文件、补丁或实际执行参数。"""
from __future__ import annotations

import json
import re
from bisect import bisect_left
from collections.abc import Callable, Iterable

REDACTED = "[REDACTED]"
MAX_STREAM_LINE = 32 * 1024
_KEY = r"(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret|token|密码|密钥|令牌)"
_SENSITIVE_KEY = re.compile(rf"^{_KEY}$", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    rf"(?P<prefix>(?<![\w-]){_KEY}[\"']?\s*[:=]\s*)(?:"
    r'"(?P<double>[^"\r\n]+)"|\'(?P<single>[^\'\r\n]+)\'|(?P<bare>[^\s,;，。；：！？、`“”‘’\"\'{}\[\]<>]+))',
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)(\bbearer[ \t]+)[^\s,;，。；：！？、`“”‘’\"'<>]+")
_URL_PASSWORD = re.compile(r"(?i)((?:\b[a-z][a-z0-9+.-]*)?://[^:/@\s]+:)[^@\s]+(@)")
_TOKEN = re.compile(r"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
_PEM_START = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----")
_PEM = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----.*?(?:-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----|\Z)", re.DOTALL)
_ASSIGNMENT_START = re.compile(rf"(?<![\w-]){_KEY}[\"']?\s*[:=]\s*", re.IGNORECASE)
_KEY_TAIL = re.compile(rf"(?<![\w-]){_KEY}[\"']?[ \t]*$", re.IGNORECASE)
_BEARER_TAIL = re.compile(r"(?i)\bbearer[ \t]+[^\s,;，。；：！？、`“”‘’\"'<>]*$")
_URL_TAIL = re.compile(r"(?i)(?:\b[a-z][a-z0-9+.-]*)?://[^\s/]*$")
_TOKEN_TAIL = re.compile(r"\b(?:sk-|gh[pousr]_|github_pat_)[A-Za-z0-9_-]*$")
_PEM_HEADER_TAIL = re.compile(r"-----BEGIN [A-Z0-9 -]*$")
_TRIGGERS = ("api_key", "api-key", "api key", "apikey", "access_token", "access-token", "access token",
             "accesstoken", "refresh_token", "refresh-token", "refresh token", "refreshtoken", "password", "passwd",
             "secret", "token", "密码", "密钥", "令牌", "bearer", "-----BEGIN ", "https://", "http://",
             "sk-", "ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_", "://")


class SecretFilter:
    def __init__(self, secret_values: Callable[[], Iterable[str]] | None = None):
        self._secret_values = secret_values or (lambda: ())

    def values(self) -> tuple[str, ...]:
        return tuple(sorted({value for value in self._secret_values() if isinstance(value, str) and value}, key=len, reverse=True))

    def redact_text(self, text: str, *, context: str = "") -> str:
        for value in self.values():
            text = text.replace(value, REDACTED)
        text = _PEM.sub(REDACTED, text)
        text = _TOKEN.sub(REDACTED, text)
        text = _BEARER.sub(lambda match: match[1] + REDACTED, text)
        text = _URL_PASSWORD.sub(lambda match: match[1] + REDACTED + match[2], text)
        ticks = [match.start() for match in re.finditer("`", text)]
        context_ticks = context.count("`")

        def assignment(match):
            prefix = (context if match.start() < 512 else "") + text[max(0, match.start() - 512):match.start()]
            clause = re.split(r"[,，。；;！？!?\n]", prefix[-512:])[-1]
            code = bool(re.search(r"(?:代码|表达式|变量(?:名|引用|赋值)?)(?:片段|示例)?(?:\s*[:：]|\s*(?:改成|改为|写成|为|是))"
                                 r"|\b(?:code|expression|variable)\s*[:：]|\b(?:def|class|const|let|var)\s+", clause, re.I)
                        or (context_ticks + bisect_left(ticks, match.start())) % 2)
            if match["bare"] in {"str", "string", "int", "float", "bool", "bytes", "None", "null", "true", "false"} or (
                    match["bare"] is not None and (re.match(r"[A-Za-z_][\w.]*\(", match["bare"])
                        or code and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", match["bare"]))):
                return match[0]
            quote = '"' if match["double"] is not None else "'" if match["single"] is not None else ""
            return match["prefix"] + quote + REDACTED + quote

        return _ASSIGNMENT.sub(assignment, text)

    def redact_value(self, value: object) -> object:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                safe_key = self.redact_text(key) if isinstance(key, str) else key
                if safe_key != key:
                    index = 1
                    candidate = safe_key
                    while candidate in result or candidate in value:
                        candidate = f"{safe_key}#{index}"
                        index += 1
                    safe_key = candidate
                result[safe_key] = (REDACTED if isinstance(key, str) and _SENSITIVE_KEY.fullmatch(key) and isinstance(item, str) and item
                                    else self.redact_value(item))
            return result
        if isinstance(value, list):
            return [self.redact_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact_value(item) for item in value)
        return value

    def contains_known_secret(self, value: object) -> bool:
        if isinstance(value, dict):
            return any(self.contains_known_secret(key) or self.contains_known_secret(item) for key, item in value.items())
        if isinstance(value, (list, tuple)):
            return any(self.contains_known_secret(item) for item in value)
        return isinstance(value, str) and any(secret in value for secret in self.values())

    def contains_secret(self, value: object) -> bool:
        if isinstance(value, dict):
            return any(self.contains_secret(key) or self.contains_secret(item)
                       or isinstance(key, str) and _SENSITIVE_KEY.fullmatch(key) and isinstance(item, str) and bool(item) and item != REDACTED
                       for key, item in value.items())
        if isinstance(value, (list, tuple)):
            return any(self.contains_secret(item) for item in value)
        return isinstance(value, str) and self.redact_text(value) != value

    @staticmethod
    def _provider_items(output_json: str):
        items = json.loads(output_json)
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise ValueError("供应商续接内容无效")
        return items

    def contains_public_provider_secret(self, output_json: str) -> bool:
        try:
            for item in self._provider_items(output_json):
                kind = item.get("type")
                if kind not in {"message", "reasoning", "function_call"}:
                    return True
                public = {key: value for key, value in item.items() if not (kind == "reasoning" and key == "encrypted_content")}
                if kind == "function_call":
                    public["arguments"] = json.loads(item["arguments"])
                if self.contains_secret(public):
                    return True
                parts = item.get("content", []) if kind == "message" else item.get("summary", []) if kind == "reasoning" else []
                if self.contains_secret("".join(part.get("text", part.get("refusal", "")) for part in parts)):
                    return True
            return False
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            return True

    def redact_provider_output(self, output_json: str) -> str:
        items = self._provider_items(output_json)
        changed = False
        for item in items:
            if item.get("type") == "message":
                content = self.redact_value(item.get("content", []))
                if content != item.get("content", []):
                    item["content"] = content
                    changed = True
            elif item.get("type") == "reasoning" and "summary" in item:
                # 推理摘要是公开文本；encrypted_content 属于供应商不透明状态，不能改写。
                summary = self.redact_value(item["summary"])
                if summary != item["summary"]:
                    item["summary"] = summary
                    changed = True
            elif item.get("type") == "function_call":
                arguments = json.loads(item["arguments"])
                filtered = self.redact_value(arguments)
                if filtered != arguments:
                    item["arguments"] = json.dumps(filtered, ensure_ascii=False)
                    changed = True
        # 无需遮蔽的原生状态保持字节不变，避免改变供应商续接参数的原始表示。
        result = json.dumps(items, ensure_ascii=False) if changed else output_json
        if self.contains_public_provider_secret(result):
            raise ValueError("供应商公开续接内容无法安全过滤")
        return result

    def stream(self) -> StreamingSecretFilter:
        return StreamingSecretFilter(self)


class StreamingSecretFilter:
    """仅保留可能敏感的未完成尾部，普通无换行输出可立即展示。"""

    def __init__(self, secret_filter: SecretFilter):
        self._source = secret_filter
        self._known = set(secret_filter.values())
        self._filter = SecretFilter(self._values)
        self._buffer = ""
        self._discard = None
        self._discard_tail = ""
        self._finished = False
        self._context = ""
        self._tick_parity = 0

    def _values(self):
        # 流开始后撤销或更换的凭据仍须遮蔽已收到的旧输出。
        self._known.update(self._source.values())
        return self._known

    def _pending(self, text: str) -> int:
        cutoff = len(text)
        for value in self._filter.values():
            # 已完整出现的秘密直接替换，只有未完成的前缀必须跨增量保留。
            lower = max(0, len(text) - len(value) + 1)
            start = text.find(value[0], lower)
            while start >= 0:
                if value.startswith(text[start:]):
                    cutoff = min(cutoff, start)
                    break
                start = text.find(value[0], start + 1)
        folded = text.casefold()
        for trigger in _TRIGGERS:
            trigger = trigger.casefold()
            for size in range(min(len(trigger), len(text)), 0, -1):
                start = len(text) - size
                if folded.endswith(trigger[:size]) and (trigger == "://" or start == 0 or not (text[start - 1].isalnum() or text[start - 1] == "_")):
                    cutoff = min(cutoff, start)
                    break
        for pattern in (_KEY_TAIL, _BEARER_TAIL, _TOKEN_TAIL, _PEM_HEADER_TAIL):
            match = pattern.search(text)
            if match:
                cutoff = min(cutoff, match.start())
        match = _URL_TAIL.search(text)
        if match and "@" not in match[0]:
            cutoff = min(cutoff, match.start())
        for match in _ASSIGNMENT_START.finditer(text):
            remaining = text[match.end():]
            if not remaining or remaining[0] in "\"'" and remaining[0] not in remaining[1:]:
                cutoff = min(cutoff, match.start())
            elif remaining[0] not in "\"'" and not re.search(r"[\s,;，。；：！？、`“”‘’\"'{}\[\]<>]", remaining):
                cutoff = min(cutoff, match.start())
        for match in _PEM_START.finditer(text):
            if not _PEM_END.search(text, match.end()):
                cutoff = min(cutoff, match.start())
        return cutoff

    def feed(self, text: str) -> str:
        if self._finished:
            raise ValueError("秘密过滤流已关闭")
        prefix = ""
        if self._discard == "pem":
            combined = self._discard_tail + text
            end = _PEM_END.search(combined)
            if end is None:
                self._discard_tail = combined[-128:]
                return ""
            text = combined[end.end():]
            self._discard, self._discard_tail = None, ""
        elif self._discard == "line":
            end = text.find("\n")
            if end < 0:
                return ""
            self._discard = None
            text, prefix = text[end + 1:], "\n"
        self._buffer += text
        cutoff = self._pending(self._buffer)
        # 截断点不能落在已知秘密内部，否则前半段会先于替换被输出。
        for value in self._filter.values():
            start = self._buffer.rfind(value, 0, cutoff + len(value))
            if start >= 0 and start < cutoff < start + len(value):
                cutoff = start
        for pattern in (_PEM, _ASSIGNMENT, _BEARER, _URL_PASSWORD, _TOKEN):
            for match in pattern.finditer(self._buffer):
                if match.start() < cutoff < match.end():
                    cutoff = match.start()
        output = prefix + self._filter.redact_text(self._buffer[:cutoff], context=self._context)
        self._context = (self._context + output)[-512:]
        self._tick_parity = (self._tick_parity + output.count("`")) % 2
        if self._context.count("`") % 2 != self._tick_parity:
            self._context = "`" + self._context
        self._buffer = self._buffer[cutoff:]
        if len(self._buffer) > MAX_STREAM_LINE:
            # 未结束值超限后整段遮蔽，不因缓冲上限释放未经校验的正文。
            self._discard = "pem" if _PEM_START.search(self._buffer) else "line"
            self._discard_tail = self._buffer[-128:] if self._discard == "pem" else ""
            self._buffer = ""
            output += REDACTED
        return output

    def finish(self) -> str:
        if self._finished:
            return ""
        self._finished = True
        text, self._buffer = self._buffer, ""
        if self._discard:
            return ""
        # 取消或断连可能只收到密钥前缀；不把这类未完成尾部写入公开记录。
        for value in self._filter.values():
            for size in range(min(len(value) - 1, len(text)), 3, -1):
                if text.endswith(value[:size]):
                    text = text[:-size] + REDACTED
                    break
        return self._filter.redact_text(text, context=self._context)
