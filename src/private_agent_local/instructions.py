"""仅在授权项目内发现规则；不跟随链接，不执行规则中的内容。"""
from __future__ import annotations

import hashlib
from pathlib import Path

from private_agent_core.context import InstructionSource

from . import files

MAX_RULE_BYTES = 32 * 1024
MAX_TOTAL_BYTES = 64 * 1024
MAX_RULES = 16
RULE_NAMES = ("AGENTS.override.md", "AGENTS.md")


class InstructionError(ValueError):
    pass


class InstructionLoader:
    def __init__(self):
        self.cache: dict[tuple[str, str, str], str] = {}

    def load(self, root: Path, target: str = ".", *, trusted: bool = False) -> list[InstructionSource]:
        try:
            path = files.within(root, target, allow_missing=True)
            directory = path if path.is_dir() else path.parent
            parents = [root, *reversed([p for p in [directory, *directory.parents] if p != root and p.is_relative_to(root)])]
            rules, total = [], 0
            for parent in parents:
                for name in RULE_NAMES:
                    relative = (parent / name).relative_to(root).as_posix()
                    candidate = parent / name
                    # 断链和无效 override 必须报错，不能通过回退掩盖规则变化。
                    if not candidate.exists() and not candidate.is_symlink():
                        continue
                    candidate = files.within(root, relative)
                    if not candidate.is_file() or candidate.stat().st_nlink != 1:
                        raise InstructionError(f"项目规则不是可读取的普通文件：{relative}")
                    with candidate.open("rb") as stream:
                        raw = stream.read(MAX_RULE_BYTES + 1)
                    total += len(raw)
                    if len(raw) > MAX_RULE_BYTES or total > MAX_TOTAL_BYTES:
                        raise InstructionError("项目规则超出单文件 32 KiB、总量 64 KiB 或 16 文件限制")
                    if b"\x00" in raw:
                        raise InstructionError(f"项目规则不是 UTF-8 文本：{relative}")
                    digest = hashlib.sha256(raw).hexdigest()
                    key = (str(root), relative, digest)
                    text = self.cache.get(key)
                    if text is None:
                        text = raw.decode("utf-8-sig")
                        if len(self.cache) >= 128:
                            self.cache.clear()
                        self.cache[key] = text
                    if not text.strip():
                        continue
                    if len(rules) >= MAX_RULES:
                        raise InstructionError("项目规则超出单文件 32 KiB、总量 64 KiB 或 16 文件限制")
                    rules.append(InstructionSource(path=relative, scope=parent.relative_to(root).as_posix(),
                                 sha256=digest, trusted=trusted, priority=len(rules), content=text))
                    break
            return rules
        except InstructionError:
            raise
        except (OSError, UnicodeError, ValueError):
            raise InstructionError("项目规则不可读、编码无效或包含链接；相关操作未执行") from None


def public_sources(rules: list[InstructionSource]) -> list[dict]:
    return [rule.model_dump(exclude={"content"}) for rule in rules]


def instruction_message(rules: list[InstructionSource]) -> str:
    trusted = [rule for rule in rules if rule.trusted]
    if not trusted:
        return ""
    import json
    return ("用户级项目规则：仅适用于标明的目录子树；同一目标的更具体目录优先。"
            "系统与应用边界、用户明确要求优先于这些规则。规则不授予任何工具权限。\n"
            + json.dumps([rule.model_dump() for rule in trusted], ensure_ascii=False))
