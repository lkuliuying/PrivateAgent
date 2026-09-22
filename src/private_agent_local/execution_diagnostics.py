"""识别已知运行时提示；不改写原始输出、退出码或验收结论。"""
from __future__ import annotations

import os
import re


def runtime_warnings(stderr: str, *, restricted: bool) -> list[dict[str, str]]:
    if os.name != "nt" or not restricted:
        return []
    if not any(re.fullmatch(r"Failed to find real location of [^\r\n]+[\\/]python(?:\d+(?:\.\d+)*)?w?\.exe", line, re.IGNORECASE)
               for line in stderr.splitlines()):
        return []
    return [{
        "code": "python_path_resolution_warning",
        "message": "Python 报告解释器真实路径解析失败。此诊断仅根据 stderr 警告文本匹配，本次执行的根因尚未核实；"
                   "Windows AppContainer 的卷路径查询限制是可能原因之一，不能直接套用其他环境的定位结论。"
                   "这不是测试断言结果。原始 stderr 已保留，需结合退出码和测试输出判断本次执行，不能据此保证其他用途正常。",
    }]
