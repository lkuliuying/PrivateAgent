"""意图规则层桥接：v0.9 启发式 → v2 ExecutionIntent（CT1-02/CT1-04）。

单一规则源：关键词启发式仍以 ``core.executable_intent`` 为准（v0.9 兼容
层，专项计划 §4.3）；本模块只做 tag 投影，不复制第二套正则。

P0 映射（保守、可测试）：
- 非可执行 → ``answer.only``；
- 文件变更 + 显式仅预览 → ``file.preview``（清除 filesystem.write 要求）；
- 文件变更 → ``file.mutate``；
- 其余可执行请求 → ``command.run``。
"""

from __future__ import annotations

from personal_assistant.core.executable_intent import (
    detect_executable_intent,
    detect_file_mutation_intent,
    has_preview_only_marker,
)

from ..domain.intents import ExecutionIntent, IntentTag


def classify_message(message: str) -> ExecutionIntent:
    """规则层意图分类（纯函数、零副作用、不调用模型）。"""
    text = message or ""
    if not detect_executable_intent(text):
        return ExecutionIntent.answer_only()
    if detect_file_mutation_intent(text):
        preview_only = has_preview_only_marker(text)
        tags = frozenset(
            {IntentTag.CODE_INSPECT, IntentTag.FILE_PREVIEW}
            if preview_only
            else {IntentTag.CODE_INSPECT, IntentTag.FILE_MUTATE}
        )
        return ExecutionIntent.from_tags(tags, preview_only=preview_only)
    return ExecutionIntent.from_tags(
        frozenset({IntentTag.CODE_INSPECT, IntentTag.COMMAND_RUN})
    )
