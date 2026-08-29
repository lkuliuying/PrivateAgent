"""v0.9.0 H1-B（计划 §5.6）：可执行意图识别。

提交后先区分信息问答与可执行意图：包含“检查本机”“查看项目”“运行测试”
“修改文件”等动作意图的请求，在项目/workspace/Provider/Runtime 就绪时
必须进入 durable Agent Runtime 并经权限判定与真实工具/命令，不得静默
退回纯文字教程。

实现约束：

- 纯启发式低基数判定（关键词），不调用模型、不产生副作用；
- 教程式提问（如何/怎么/教程/仅回答方法）显式优先，用户明确只要方法时
  不强制工具证据（§5.6 最后一条）；
- 判定为可执行意图时，run 创建方注入最小工具证据完成条件
  （completion_conditions.min_tool_executions），由 durable executions
  事实求值——无执行证据的"完成"宣称会被输出验证失败关闭。
"""

from __future__ import annotations

import re

# 动作动词：出现即倾向可执行意图（配合教程标记排除）。
_ACTION_VERB_RE = re.compile(
    "检查|查看|查一下|查询|检测|确认一下|运行|执行|跑一下|跑下|测试|"
    "修改|改一下|创建|新建|删除|移除|安装|卸载|构建|编译|启动|停止|"
    "重启|扫描|分析|清理|升级|部署|生成|重命名|更新|修复|整理|"
    "看一下|看看|看下|是否安装|是否装了|有没有装|有没有安装|装了没"
)

# 教程/方法式提问标记：用户只要操作说明时不强制工具证据（§5.6）。
# 注：不含“为什么”——“查看测试为什么失败”等排障请求仍属可执行意图。
_TUTORIAL_MARKER_RE = re.compile(
    "教程|步骤说明|仅回答方法|只回答方法|告诉我方法|告诉我怎么|教我|"
    "如何|怎么|怎样|是什么|什么意思|解释一下|科普|区别是|原理"
)

# 命中动作词但整体是疑问/咨询语境的高频短语（防止误报为可执行）。
_INFO_QUESTION_RE = re.compile(
    "可以吗|能不能|是否应该|要不要|有什么建议|推荐|可以[^。！？\n]{0,16}吗"
)

# 文件变更意图必须同时命中动作与文件目标，避免把“创建数据库”“更新服务”
# 等非文件任务误判为 Patch 工作流。扩展名只覆盖常见 coding 文本文件；
# “文件/文档/代码/脚本/README”等显式目标不受扩展名限制。
_FILE_MUTATION_ACTION_RE = re.compile(
    "创建|新建|写入|生成|修改|改一下|编辑|更新|替换|追加|删除|移除|"
    "重命名|移动|修复|整理"
)
_FILE_TARGET_RE = re.compile(
    r"文件|文档|代码|源码|脚本|配置|README|readme|"
    r"(?:一个|1个)\s*(?:python|javascript|typescript|java|go|rust|c\+\+|c#)"
    r"(?:程序|脚本|文件)?(?!\s*(?:项目|工程))|"
    r"[\w.-]+\.(?:txt|md|py|js|jsx|ts|tsx|vue|json|ya?ml|toml|ini|cfg|"
    r"rs|go|java|kt|kts|c|cc|cpp|h|hpp|cs|sh|ps1|bat|cmd|html?|css|scss|sql)",
    re.IGNORECASE,
)
_EXPLICIT_FILE_NAME_RE = re.compile(
    r"(?<![\w.-])(?:[\w.-]+\.)+(?:txt|md|py|js|jsx|ts|tsx|vue|json|ya?ml|toml|ini|cfg|"
    r"rs|go|java|kt|kts|c|cc|cpp|h|hpp|cs|sh|ps1|bat|cmd|html?|css|scss|sql)"
    r"(?![\w.-])",
    re.IGNORECASE,
)
_MULTI_FILE_MARKER_RE = re.compile(
    "多文件|多个文件|一批文件|批量|所有文件|全部文件|这些文件|两个文件|两份文件|"
    "三个文件|三份文件"
)
_PREVIEW_ONLY_MARKER_RE = re.compile(
    "只预览|仅预览|先预览|预览一下|不要写入|不写入|只看补丁|仅看补丁"
)
_IMPLICIT_SINGLE_SOURCE_FILE_RE = re.compile(
    r"(?:一个|1个)\s*(?:python|javascript|typescript|java|go|rust|c\+\+|c#)"
    r"(?:程序|脚本|文件)?(?!\s*(?:项目|工程))",
    re.IGNORECASE,
)


def detect_executable_intent(message: str) -> bool:
    """判定用户消息是否为可执行意图（低基数启发式，纯函数）。

    规则（按优先级）：
    1. 教程/方法式标记或纯咨询语境 → False（信息问答）；
    2. 含动作动词 → True（可执行意图）；
    3. 其他 → False。
    """
    text = (message or "").strip()
    if not text:
        return False
    if _TUTORIAL_MARKER_RE.search(text):
        return False
    if _INFO_QUESTION_RE.search(text):
        return False
    return bool(_ACTION_VERB_RE.search(text))


def detect_file_mutation_intent(message: str) -> bool:
    """识别需要真实写入项目文件的明确请求。

    仅在请求本身属于可执行意图，且同时包含文件变更动作和文件目标时返回
    ``True``。该结果用于注入成功写入完成门槛，不用于授予任何额外权限。
    """
    text = (message or "").strip()
    if not detect_executable_intent(text):
        return False
    return bool(
        _FILE_MUTATION_ACTION_RE.search(text) and _FILE_TARGET_RE.search(text)
    )


def detect_direct_single_file_write_intent(message: str) -> bool:
    """识别可直接进入单文件审批写入的明确请求。

    请求明确给出一个文件名，或以“创建一个 Python/Java ……”表达单文件
    产物，且没有多文件或仅预览口径时返回 ``True``。该结果只缩小模型可见
    工具面，不改变审批、能力或工作区边界。
    """
    text = (message or "").strip()
    if not detect_file_mutation_intent(text):
        return False
    if _MULTI_FILE_MARKER_RE.search(text) or _PREVIEW_ONLY_MARKER_RE.search(text):
        return False
    names = {match.group(0).lower() for match in _EXPLICIT_FILE_NAME_RE.finditer(text)}
    if names:
        return len(names) == 1
    implicit_files = list(_IMPLICIT_SINGLE_SOURCE_FILE_RE.finditer(text))
    return len(implicit_files) == 1


def has_preview_only_marker(message: str) -> bool:
    """v1.0 CT1-02（专项计划 §7.4/F-008）：显式"仅预览/不要写入"标记。

    用户明确只要预览时必须清除 filesystem.write 副作用要求——proposal
    即可完成，不得强制真实落盘。该判定只降低完成门槛，不授予任何权限。
    """
    text = (message or "").strip()
    return bool(_PREVIEW_ONLY_MARKER_RE.search(text))


# 可执行意图 run 的系统提示附加段：公开决策链语义（不读取隐藏推理）。
EXECUTABLE_INTENT_POLICY = (
    "本请求被识别为可执行意图（动手任务）。你必须：\n"
    "1. 使用已注册的工具/命令真实执行，禁止只返回手工操作教程；\n"
    "2. 检查类任务优先使用内置只读诊断命令收集证据，逐项检查并记录"
    "命令输出与退出码；\n"
    "3. 结论必须基于实际执行证据并注明依据；没有取得足够证据时不得"
    "断言“已安装/未安装/已完成”，必须说明未完成检查与下一步；\n"
    "4. 单个 PATH 未命中不等于未安装，需继续检查服务端可执行文件与"
    "系统服务事实；\n"
    "5. 命令被拒绝、缺失或失败时如实报告结构化原因，不得伪装成功。"
)


FILE_MUTATION_INTENT_POLICY = (
    "本请求还被识别为项目文件变更任务。你必须：\n"
    "1. 创建、修改、删除或重命名文件时使用 Patch 工具真实落盘；单文件优先"
    "直接调用 apply_patch_to_workspace，它会先进入用户审批并展示变更预览，"
    "不要先调用只读的 propose_patch；只有用户明确要求仅预览时才调用 "
    "propose_patch。多文件使用 propose_patch_set / apply_patch_set；单文件任务"
    "不要调用 PatchSet 工具。propose 只生成预览，预览成功后必须继续调用对应 apply "
    "工具；rel_path 必须是项目内相对路径，根目录文件写 hello.txt，不能写 "
    "/hello.txt、绝对路径或包含 ..；new_content 必须是文件的原始完整内容，"
    "不要包 Markdown 代码围栏，也不要再次 JSON 序列化或把换行写成字面量 \\n；\n"
    "2. run_whitelisted_command 只用于已公开的测试、构建和只读诊断命令，"
    "禁止用 echo、重定向、Set-Content、cmd 或 shell 命令创建/编辑文件；\n"
    "3. 收到非白名单错误后必须改用对应 Patch 工具，不得重复提交同类命令；\n"
    "4. 最终回答前必须取得至少一个 succeeded 的文件写入执行事实；只有预览、"
    "失败命令或文字说明都不代表任务完成。"
)
