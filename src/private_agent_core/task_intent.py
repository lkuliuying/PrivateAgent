"""保留用户语义，提取明确的执行约束与可核验要求；模型不裁决权限。"""
from __future__ import annotations

import re
import shlex
from typing import Literal

from pydantic import Field

from .coding_contracts import CodingContract, Requirement
from .completion import canonical_command, command_kind

_WRITE = re.compile(r"创建|新建|写入|生成|修改|修复|修一下|修好|改一下|改好|改掉|改动|更新|编辑|替换|删除|重命名|优化|重构|实现|调整|\b(?:create|write|modify|modifying|fix|update|edit|delete|rename|optimize|refactor|implement)\b", re.I)
_FILE = re.compile(r"(?<![A-Za-z0-9_./-])(?:[A-Za-z0-9_@.-]+/)*[A-Za-z0-9_@.-]+\.(?:py|txt|md|js|jsx|ts|tsx|vue|json|ya?ml|toml|rs|go|java|css|html|sql|sh|ps1)(?![A-Za-z0-9_/-])", re.I)
_COMMAND = re.compile(r"(?<![\w./-])(?:python3?|pytest|npm|pnpm|yarn|node|bun|cargo|go|dotnet|ruff|mypy)(?![\w./-])(?:[ A-Za-z0-9_./:=@-]*[A-Za-z0-9_/-])?", re.I)
_FILE_ACTION = re.compile(
    rf"(?P<negative>(?:不要|不得|不能|不允许|不需要|不必|禁止|别|不用|不|\b(?:do not|don't|never|not|avoid|without)\b)\s*)?"
    rf"(?P<write>{_WRITE.pattern})|"
    r"读取|查看|检查|参考|根据|依据|按照|引用|保留|运行|执行|测试|验证|解释|使用|"
    r"\b(?:read|inspect|check|refer|keep|preserve|run|execute|test|verify|explain|use|using|without|python3?|pytest|npm|cargo|dotnet)\b",
    re.I,
)
_FILE_LIST = re.compile(r"(?:\s|[-、`'\"*]|\d+[.)]|和|及|与|\b(?:and|or)\b)*", re.I)


def _file_change_targets(message: str) -> list[str]:
    """按动作范围提取写入目标；跨逗号或换行只继承纯文件列表，不继承读取或命令引用。"""
    targets, has_write = [], False
    for sentence in re.split(r"[。；;！？!?]|(?<!\d)\.(?=\s|$)", message):
        writing = False
        for clause in re.split(r"[，,\n]", sentence):
            # 文件名中的 fix、test 等单词不是动作，替换为等长空白以保留位置。
            masked = _FILE.sub(lambda match: " " * len(match.group()), clause)
            actions = list(_FILE_ACTION.finditer(masked))
            if not actions:
                if writing and _FILE_LIST.fullmatch(masked):
                    targets.extend(_FILE.findall(clause))
                else:
                    writing = False
                continue
            for index, action in enumerate(actions):
                writing = bool(action.group("write") and not action.group("negative"))
                if not writing:
                    continue
                has_write = True
                # 首个动作允许“将 a.py 修改为”的前置宾语，后续动作不接收上个动作的文件。
                start = 0 if index == 0 else action.end()
                end = actions[index + 1].start() if index + 1 < len(actions) else len(clause)
                targets.extend(_FILE.findall(clause[start:end]))
    return list(dict.fromkeys(targets)) or ([""] if has_write else [])



_NEGATIVE = r"(?:不要|不得|不能|不允许|不需要|不必|禁止|停止|暂时不|暂不|别|不用|不|\b(?:do not|don't|must not|never|not|without|avoid|stop)\b)"
_NEGATIVE_PREFIX = re.compile(_NEGATIVE + r"\s*(?:(?:再|继续|直接|去|进行|运行|执行|任何|所有|一下|the|any|all|running|executing|run|execute)\s*)*$", re.I)
_TEST = re.compile(r"(?:运行|执行|跑|并|和|后|及)\s*(?:一下|所有|全部)?\s*测试|测试(?:并|和)?(?:通过|验证)|\b(?:run|running|execute|executing)\s+(?:the |any |all )?tests?\b", re.I)
_NO_TEST = re.compile(_NEGATIVE + r"\s*(?:(?:运行|执行|跑|进行|再|任何|所有|全部|run|running|execute|executing|the|any|all)\s*)*(?:测试|tests?\b|pytest\b)"
    r"|测试\s*(?:先|暂时|暂且)?\s*(?:别|不要|不用|不必)\s*(?:运行|执行|跑|做)"
    r"|\bskip\s+(?:the |all )?tests?\b", re.I)
_NO_COMMAND = re.compile(_NEGATIVE + r"\s*(?:(?:运行|执行|任何|所有|全部|run|execute|running|executing|the|any|all)\s*)*(?:命令|程序|脚本|commands?\b|scripts?\b)|\bno commands\b"
    r"|(?:命令|脚本|程序)\s*(?:先|暂时|暂且)?\s*(?:别|不要|不用|不必)\s*(?:运行|执行|跑)", re.I)
_NO_NETWORK = re.compile(_NEGATIVE + r"\s*(?:联网|上网|访问网络|访问互联网|使用网络|network access\b|browse\b|browsing\b|use (?:the )?internet\b)|\b(?:offline only|no network|no internet)\b", re.I)
_PREVIEW = re.compile(r"(?:只|仅)[^，,。；;！？!?\n]*(?:方案|预览)|\bpreview only\b|\bonly (?:a )?(?:plan|patch|preview)\b", re.I)
_ONLY_ANSWER = re.compile(r"(?<!不要)(?:只|仅)(?:解释|分析|说明)|\bonly (?:explain|analyze|describe)\b", re.I)
_ANSWER = re.compile(r"解释|说明|分析|为什么|怎么|如何|是什么|\b(?:explain|describe|analy[sz]e|why|how|what)\b", re.I)
_READ = re.compile(r"读取|查看|检查|参考|搜索|\b(?:read|inspect|check|search)\b", re.I)
_VERIFY = re.compile(r"验证|验收|\b(?:verify|validate)\b", re.I)
_BEHAVIOR = re.compile(r"保持|兼容|确保|保证|刷新|不得改变|不能改变|\b(?:compatible|compatibility|preserve|ensure|refresh)\b", re.I)
_SCOPE = re.compile(r"(?:只|仅)(?:允许|能|可)?\s*(修改|写入|编辑|访问|读取|操作)|\bonly\s+(modify|edit|write|access|read)\b|\b(modify|edit|write|access|read)\s+only\b", re.I)
_SCOPE_BEFORE = re.compile(r"(?:只|仅)(?:允许|能|可)?在\s*(.+?)\s*(?:下|内)?\s*(修改|写入|编辑|访问|读取|操作)", re.I)
_PATH = re.compile(r"(?<![\w./\\-])[A-Za-z0-9_@.-]+(?:[/\\][A-Za-z0-9_@.-]+)*[/\\]?(?![\w/-])")
_CLAUSES = re.compile(r"[，,。；;！？!?\n]|(?<!\d)\.(?=\s|$)")
_GREETING = re.compile(r"你好|您好|早上好|晚上好|谢谢|多谢|hello|hi|thanks|thank you", re.I)
_NEGATIVE_PROGRAM = re.compile(_NEGATIVE + r"\s*(?:运行|执行|run|execute|running|executing)\s*(?P<command>(?:python3?|pytest|npm|pnpm|yarn|node|bun|cargo|go|dotnet)\b(?:(?!\s+(?:and|then|but)\s)[^，。；;！？!?\n])*)", re.I)
_CONDITIONAL = re.compile(r"(?:如果|假如|若(?!干)|(?<![\w./\\-])(?:if|unless)\b(?![./\\-]))(?:(?![。；;！？!?\n]|(?<!\d)\.(?=\s|$)).)*", re.I)
_SENTENCES = re.compile(r"[。；;！？!?\n]|(?<!\d)\.(?=\s|$)")
_REQUIREMENT_BLOCK = re.compile(r"(?:本次|任务)?(?:要求|约束|限制|指令)(?:如下|是)?\s*[:：]\s*$")
_EXECUTE = re.compile(r"运行|执行|\b(?:run|execute)\b", re.I)
_TEST_NOTE = "用户禁止运行测试；本轮未执行测试，测试结果未验证"
_COMMAND_NOTE = "用户要求不运行命令；本轮未执行命令验证"
_STEER_CONFLICTS = {
    "tests_forbidden": "追加测试要求与禁止测试冲突；请明确撤销对应限制后重新提出执行要求",
    "commands_forbidden": "追加命令要求与禁止命令冲突；请明确撤销对应限制后重新提出执行要求",
    "writes_forbidden": "追加修改要求与禁止写入冲突；请明确撤销对应限制后重新提出执行要求",
}


class PolicyRelease(CodingContract):
    field: Literal["tests_forbidden", "commands_forbidden", "writes_forbidden", "network_forbidden"]
    source_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=2000)


def _policy_releases(text: str, source_id: str) -> tuple[list[PolicyRelease], str]:
    """只承认当前用户直接、明确的撤销；引述、条件、疑问和泛化允许都不能放宽策略。"""
    targets = {
        "tests_forbidden": (r"(?:运行|执行|跑)测试", r"(?:run|execute) tests?"),
        "commands_forbidden": (r"(?:运行|执行)命令", r"(?:run|execute) commands?"),
        "writes_forbidden": (r"(?:修改|写入|编辑)(?:文件|代码)", r"(?:modify|write|edit) (?:files|code)"),
        "network_forbidden": (r"(?:联网|访问网络|访问互联网)", r"(?:access the network|use the internet)"),
    }
    sentences, start = [], 0
    for boundary in [*_SENTENCES.finditer(text), None]:
        end = boundary.end() if boundary else len(text)
        sentence = text[start:end]
        sentences.append((end, bool(_CONDITIONAL.search(sentence) or re.search(r"[?？]|(?:吗|么)\s*[。！!]?\s*$", sentence))))
        start = end
    releases, pieces, start, sentence_index = [], [], 0, 0
    for separator in [*_CLAUSES.finditer(text), None]:
        end = separator.start() if separator else len(text)
        clause = text[start:end]
        # 条件和疑问可出现在逗号另一侧，必须按整句判断授权是否明确。
        while sentence_index + 1 < len(sentences) and start >= sentences[sentence_index][0]:
            sentence_index += 1
        ambiguous = sentences[sentence_index][1]
        field = next((key for key, (target, english) in targets.items() if not ambiguous and (
            re.fullmatch(rf"\s*(?:现在|本轮|接下来)(?:可以|允许){target}了?\s*", clause)
            or re.fullmatch(rf"\s*(?:请)?(?:解除|撤销|取消)(?:之前|此前|先前)?的?(?:禁止|不允许|不要|不){target}的?(?:限制|要求)\s*", clause)
            or re.fullmatch(rf"\s*(?:now you (?:may|can)|you (?:may|can) now) {english}\s*", clause, re.I)
        )), None)
        if field:
            releases.append(PolicyRelease(field=field, source_id=source_id, text=clause.strip()))
            pieces.append(" " * len(clause))
        else:
            pieces.append(clause)
        if separator:
            pieces.append(separator.group())
            start = separator.end()
    return releases, "".join(pieces)


class TaskSource(CodingContract):
    source_id: str = Field(min_length=1, max_length=128)
    kind: Literal["user", "steer"] = "user"
    text: str = Field(min_length=1, max_length=32000, strict=True)


class TaskPolicy(CodingContract):
    preview_only: bool = False
    answer_only: bool = False
    writes_forbidden: bool = False
    tests_forbidden: bool = False
    commands_forbidden: bool = False
    network_forbidden: bool = False
    # 各组之间取交集；空组表示范围未确定，不能将其解释为无限制。
    write_scopes: list[list[str]] = Field(default_factory=list, max_length=257)
    access_scopes: list[list[str]] = Field(default_factory=list, max_length=257)
    forbidden_write_paths: list[str] = Field(default_factory=list, max_length=256)
    conflicts: list[str] = Field(default_factory=list, max_length=256)
    unperformed: list[str] = Field(default_factory=list, max_length=256)


class ScopedConstraint(CodingContract):
    source_id: str = Field(min_length=1, max_length=128)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=32000)
    kind: Literal["answer_only", "preview_only", "writes_forbidden", "tests_forbidden", "commands_forbidden",
                  "network_forbidden", "write_scopes", "access_scopes"]
    scope: Literal["task", "path", "topic"]
    targets: list[str] = Field(default_factory=list, max_length=256)


class TaskInterpretation(CodingContract):
    # 无版本的持久化数据按旧契约处理；只有当前解释器显式创建新版本。
    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    goal_version: int = Field(default=1, ge=1)
    sources: list[TaskSource] = Field(min_length=1, max_length=257)
    goals: list[str] = Field(default_factory=list, max_length=512)
    actions: list[Literal["answer", "read", "modify", "execute", "verify"]] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list, max_length=32)
    requirement_sources: dict[str, str] = Field(default_factory=dict)
    explicit_requirements: list[Requirement] = Field(default_factory=list, max_length=32)
    conditions: list[str] = Field(default_factory=list, max_length=512)
    policy_releases: list[PolicyRelease] = Field(default_factory=list, max_length=1024)
    constraints: list[ScopedConstraint] = Field(default_factory=list, max_length=2048)
    policy: TaskPolicy


def _blank(match):
    return " " * len(match.group())


def active_text(message: str) -> str:
    """隔离示例与引述；保留带引号的文件路径和显式执行的行内命令。"""
    def fenced(match):
        prefix = message[:match.start()].rstrip().splitlines()[-1:]
        cue = _CLAUSES.split(prefix[0])[-1].strip() if prefix else ""
        if match.group("language").strip().lower() in {"", "text", "md", "markdown"} and _REQUIREMENT_BLOCK.fullmatch(cue):
            return " " * (match.start("body") - match.start()) + match.group("body") + " " * (match.end() - match.end("body"))
        return _blank(match)

    text = re.sub(r"(?P<fence>```|~~~)(?P<language>[^\n]*)\n(?P<body>[\s\S]*?)(?:(?P=fence)|$)", fenced, message)
    text = re.sub(r"(?m)^\s*>[^\n]*", _blank, text)
    quoted = r'“[^”]*”|「[^」]*」|"[^"\n]*"|(?<!\w)\x27[^\x27\n]*\x27(?!\w)'
    def quotation(match):
        prefix = _CLAUSES.split(text[:match.start()])[-1].strip()
        adopted = re.fullmatch(r"(?:请)?(?:执行|完成|落实)(?:以下|下列|这项|这个|本次)?(?:任务|要求|指令)\s*[:：]?", prefix)
        if _FILE.fullmatch(match.group()[1:-1]) or adopted:
            return " " + match.group()[1:-1] + " "
        return _blank(match)

    text = re.sub(quoted, quotation, text)
    # 反引号中的路径仍可成为操作对象，示例代码不能产生隐含命令。
    text = re.sub(r"`[^`\n]+`", lambda m: " " + m.group()[1:-1] + " " if _FILE.fullmatch(m.group()[1:-1])
                  or re.search(r"(?:运行|执行|run|execute)\s*$", text[:m.start()], re.I) else _blank(m), text)
    return text


def _scoped_constraints(text: str, source: TaskSource) -> tuple[list[ScopedConstraint], str]:
    """只把明确的全任务限制送入全局规则；局部语义保留原文位置供模型判断。"""
    constraints, pieces, start = [], [], 0
    inherited = None
    positions = [match.start() for match in _WRITE.finditer(_FILE.sub(_blank, text)) if not _negative(text, match.start())]
    boundaries = re.compile(_CLAUSES.pattern + r"|另外|此外|但是|然后|随后|\b(?:but|then)\b", re.I)
    for separator in [*boundaries.finditer(text), None]:
        end = separator.start() if separator else len(text)
        clause = text[start:end]
        masked = _FILE.sub(_blank, clause)
        matches = [(kind, match) for kind, pattern in (
            ("preview_only", _PREVIEW), ("answer_only", _ONLY_ANSWER),
            ("tests_forbidden", _NO_TEST), ("commands_forbidden", _NO_COMMAND),
            ("network_forbidden", _NO_NETWORK),
        ) for match in pattern.finditer(masked) if kind.endswith("forbidden") or not _negative(masked, match.start())]
        matches.extend(("writes_forbidden", match) for match in _WRITE.finditer(masked)
                       if _negative(masked, match.start()) and not re.search(
                           r"接口|API|行为|逻辑|签名|schema", clause[match.end():], re.I))
        matches.extend(("answer_only", match) for match in re.finditer(r"不动工|不实施", masked))
        for match in _NEGATIVE_PROGRAM.finditer(masked):
            command = clause[match.start("command"):match.end("command")].strip().rstrip(".")
            argv = shlex.split(command)
            matches.append(("tests_forbidden" if command_kind(argv) == "test" or "pytest" in argv else "commands_forbidden", match))
        local = False
        next_inherited = None
        for kind, match in matches:
            prefix = clause[:match.start()].strip()
            positive_prefix = any(not _negative(prefix, action.start()) for action in _WRITE.finditer(_FILE.sub(_blank, prefix)))
            paths = _FILE.findall(clause) if not positive_prefix else _FILE.findall(clause[match.end():])
            if kind in {"tests_forbidden", "commands_forbidden", "network_forbidden"}:
                paths = _FILE.findall(prefix) if not positive_prefix else []
            whole = bool(re.search(r"整个任务|整个项目|本次任务|全局|所有文件|任何文件|\b(?:whole task|entire task|all files|any files)\b", clause, re.I))
            subject = re.sub(r"^(?:(?:请你|请|另外|此外|同时|但是|但|而|也|先|仅|只|暂时|现在|本轮|接下来|后续|本次|but\b|also\b|now\b|please\b)\s*)+", "", prefix, flags=re.I)
            named_topic = bool(re.search(r"模块|方向|部分|子任务|这一项|这个问题|\b(?:module|subtask|topic)\b", clause, re.I))
            unnamed_topic = bool(subject and not re.fullmatch(r"(?:不要|不得|不能|禁止|不|仅|只|先|暂时|请|\s|do not|don't|never|must not|avoid)+", subject, re.I))
            topic = not positive_prefix and (named_topic or unnamed_topic and kind in {"answer_only", "preview_only"})
            scope = "task" if whole else "path" if paths else "topic" if topic else "task"
            other_write = bool(positions and (positions[0] < start or positions[-1] >= end))
            if kind in {"answer_only", "preview_only"} and not other_write and not positive_prefix and not topic:
                scope = "task"
            if not whole and scope == "task" and inherited and not positive_prefix:
                scope, paths = inherited
            if kind == "writes_forbidden" and re.search(r"其他|其它|其余|\bother\b", clause[match.end():], re.I):
                kind, scope = "write_scopes", "path"
                paths = [path for path in _file_change_targets(text) if path]
            constraints.append(ScopedConstraint(source_id=source.source_id, start=start, end=end,
                text=source.text[start:end], kind=kind, scope=scope, targets=list(dict.fromkeys(paths))))
            local |= scope != "task" and kind != "write_scopes"
            if scope != "task" and kind != "write_scopes":
                next_inherited = (scope, paths)
        # 文件白名单沿用原有交集规则；来源记录不能把它变成局部建议。
        standard_scope = _SCOPE.search(masked)
        before_scope = _SCOPE_BEFORE.search(clause)
        scope_match = standard_scope or before_scope
        if scope_match and not _negative(masked, scope_match.start()):
            constraints.append(ScopedConstraint(source_id=source.source_id, start=start, end=end,
                text=source.text[start:end], kind="write_scopes" if re.search(r"修改|写入|编辑|modify|edit|write", scope_match[0], re.I)
                else "access_scopes", scope="path", targets=_paths(clause[scope_match.end():] if standard_scope else before_scope.group(1))))
        if local:
            first = min(match.start() for _, match in matches)
            # 同一分句有明确的前置修改动作时，只屏蔽限制部分，不吞掉独立动作。
            keep = first if any(not _negative(masked, action.start()) for action in _WRITE.finditer(masked[:first])) else 0
            pieces.append(clause[:keep] + " " * (len(clause) - keep))
        else:
            pieces.append(clause)
        if separator:
            pieces.append(separator.group())
            start = separator.end()
        inherited = next_inherited if separator and separator.group() in {"，", ","} else None
    return constraints, "".join(pieces)


def _negative(text: str, position: int) -> bool:
    prefix = _CLAUSES.split(text[:position])[-1]
    return bool(_NEGATIVE_PREFIX.search(prefix))


def _paths(text: str) -> list[str]:
    ignored = {"and", "or", "file", "files", "directory", "directories", "folder", "only", "under", "in",
               "any", "all", "the", "these", "this", "other", "current", "project", "source"}
    return list(dict.fromkeys(m.group().replace("\\", "/") for m in _PATH.finditer(text)
                             if m.group().casefold() not in ignored))


def merge_policy(previous: TaskPolicy, incoming: TaskPolicy) -> TaskPolicy:
    values = {}
    for key in TaskPolicy.model_fields:
        old, new = getattr(previous, key), getattr(incoming, key)
        if key == "answer_only":
            values[key] = new
        elif isinstance(old, bool):
            values[key] = old or new
        else:
            values[key] = list(old)
            values[key].extend(item for item in new if item not in values[key])
    return TaskPolicy.model_validate(values)


def requirement_blocked(item: Requirement, policy: TaskPolicy) -> bool:
    groups = policy.access_scopes + (policy.write_scopes if item.kind == "file_changed" else [])
    if item.kind in {"file_changed", "artifact"}:
        if any(not group for group in groups):
            return True
        if item.scope and any(not any(item.scope == path.rstrip("/") or item.scope.startswith(path.rstrip("/") + "/")
                                      for path in group) for group in groups):
            return True
        if item.kind == "file_changed" and item.scope and any(
                item.scope == path.rstrip("/") or item.scope.startswith(path.rstrip("/") + "/")
                for path in policy.forbidden_write_paths):
            return True
    return (item.kind == "file_changed" and (policy.writes_forbidden or policy.preview_only)
            or item.kind in {"test", "command"} and (policy.commands_forbidden or policy.preview_only)
            or item.kind == "test" and policy.tests_forbidden)


def _effective_requirements(requirements, sources, policy):
    kept, origins, notes = [], {}, list(policy.unperformed)
    for item in requirements:
        file_note = "用户限制阻止该文件验收要求，尚未验证：" + (item.scope or item.description)[:1500]
        if requirement_blocked(item, policy):
            if item.kind in {"file_changed", "artifact"}:
                notes.append(file_note)
            continue
        if item.kind in {"file_changed", "artifact"}:
            notes = [note for note in notes if note != file_note]
        kept.append(item)
        origins[item.requirement_id] = sources[item.requirement_id]
    return kept, origins, policy.model_copy(update={"unperformed": list(dict.fromkeys(notes))})


def interpret_task(message: str, explicit=(), *, source_id="initial", source_kind="user") -> TaskInterpretation:
    if not isinstance(message, str) or not message.strip() or len(message) > 32000:
        raise ValueError("任务输入必须为 1 至 32000 字符的非空文本")
    source = TaskSource(source_id=source_id, kind=source_kind, text=message)
    explicit = [Requirement.model_validate(item) for item in explicit]
    text = active_text(message)
    releases, text = _policy_releases(text, source_id) if source_kind == "steer" else ([], text)

    def negative_program(match):
        argv = shlex.split(match.group("command").strip().rstrip("."))
        return "禁止运行测试" if command_kind(argv) == "test" or any("pytest" == part for part in argv) else "禁止运行命令"

    conditions = list(_CONDITIONAL.finditer(text))
    # 条件正文完整保留给模型，不将尚未满足的条件转为无条件权限或验收要求。
    text = _CONDITIONAL.sub(_blank, text)
    constraints, text = _scoped_constraints(text, source)
    text = _NEGATIVE_PROGRAM.sub(negative_program, text)
    policy = TaskPolicy()
    data = policy.model_dump()
    data["preview_only"] = any(not _negative(text, match.start()) for match in _PREVIEW.finditer(text))
    data["tests_forbidden"] = bool(_NO_TEST.search(text))
    data["commands_forbidden"] = data["preview_only"] or bool(_NO_COMMAND.search(text))
    data["network_forbidden"] = bool(_NO_NETWORK.search(text))
    for constraint in constraints:
        if constraint.scope == "path" and constraint.kind in {"writes_forbidden", "answer_only", "preview_only"}:
            data["forbidden_write_paths"].extend(constraint.targets)
        elif constraint.scope == "task" and constraint.kind == "answer_only":
            data["writes_forbidden"] = data["commands_forbidden"] = True
    other_files_forbidden = False
    positive_parts, goals, actions, manual, read_only_scopes = [], [], [], [], []
    has_positive_test = False
    clauses = _CLAUSES.split(text)
    for clause_index, clause in enumerate(clauses):
        clause = clause.strip()
        if not clause:
            continue
        if _GREETING.fullmatch(clause):
            goals.append(clause)
            actions.append("answer")
            positive_parts.append(clause)
            continue
        masked = _FILE.sub(_blank, clause)
        writes = list(_WRITE.finditer(masked))
        positive_writes = [m for m in writes if not _negative(masked, m.start())]
        # “解释如何修改”是说明对象；后续独立动作仍照常提取。
        explanatory = bool(re.match(r"(?:请\s*)?(?:解释|说明|分析|explain|describe|how|why|what)", clause, re.I))
        descriptive = explanatory and not re.search(r"然后|随后|再|并(?:修复|修改|创建)|\b(?:then|and (?:fix|modify|create|run))\b", clause, re.I)
        if descriptive:
            positive_writes = []
        for match in writes:
            if not _negative(masked, match.start()):
                continue
            end = next((m.start() for m in writes if m.start() > match.start()), len(clause))
            if re.search(r"接口|API|行为|逻辑|签名|schema", clause[match.end():end], re.I) and not _FILE.search(clause[match.end():end]):
                manual.append(clause)
                continue
            targets = _paths(clause[match.end():end])
            if not targets and clause.endswith((":", "：")):
                for following in clauses[clause_index + 1:]:
                    if not _FILE_LIST.fullmatch(_FILE.sub(_blank, following)):
                        break
                    targets.extend(_FILE.findall(following))
            if targets:
                data["forbidden_write_paths"].extend(targets)
            elif re.search(r"其他|其它|其余|other", clause[match.end():], re.I):
                other_files_forbidden = True
            else:
                data["writes_forbidden"] = True
        scope_match = _SCOPE.search(masked)
        before_scope = _SCOPE_BEFORE.search(clause)
        if scope_match and _negative(masked, scope_match.start()):
            scope_match = None
        if before_scope and _negative(clause, before_scope.start()):
            before_scope = None
        if scope_match or before_scope:
            tail = clause[scope_match.end():] if scope_match else before_scope.group(1)
            # 读取参考对象不能进入写入白名单。
            tail = re.split(r"读取|查看|参考|\b(?:read|inspect|refer)\b", tail, maxsplit=1, flags=re.I)[0]
            paths = _paths(tail)
            if not paths and clause.endswith((":", "：")):
                for following in clauses[clause_index + 1:]:
                    if not _FILE_LIST.fullmatch(_FILE.sub(_blank, following)):
                        break
                    paths.extend(_FILE.findall(following))
            if re.search(r"[?*]|(?<!\w)\.\.(?:[/\\]|$)|[A-Za-z]:|//", tail):
                paths = []
            action = next(group for group in scope_match.groups() if group) if scope_match else before_scope.group(2)
            key = "write_scopes" if action.lower() in {"修改", "写入", "编辑", "modify", "edit", "write"} else "access_scopes"
            if action.lower() in {"读取", "read"}:
                read_only_scopes.append(paths)
            else:
                data[key].append(paths)
            if not paths:
                data["conflicts"].append("路径限制未能确定，请明确项目相对路径：" + clause[:1500])
        if any(not _negative(masked, match.start()) for match in _ONLY_ANSWER.finditer(masked)):
            data["writes_forbidden"] = True
            data["commands_forbidden"] = True
        if _ANSWER.search(masked):
            actions.append("answer")
        if _READ.search(masked):
            actions.append("read")
        if positive_writes:
            actions.append("modify")
            positive_parts.append(clause)
        elif not writes:
            # 保留写入动作之后的纯文件清单，复用既有目标识别规则。
            positive_parts.append(clause)
        else:
            positive_parts.append(_WRITE.sub(_blank, clause) if descriptive else clause)
        tests = [m for m in _TEST.finditer(masked) if not _negative(masked, m.start())]
        # 中文“不测试”没有肯定候选；“解释测试”同样不生成执行要求。
        if tests and not descriptive:
            has_positive_test = True
            actions.extend(["execute", "verify"])
        if _VERIFY.search(masked) and not any(_negative(masked, m.start()) for m in _VERIFY.finditer(masked)):
            actions.append("verify")
            if not tests:
                manual.append(clause)
        elif _BEHAVIOR.search(masked) and not any(_negative(masked, m.start()) for m in writes):
            manual.append(clause)
        if (not descriptive and _EXECUTE.search(masked) and not tests and not _COMMAND.search(clause)
                and not _NO_COMMAND.search(masked) and not _NO_TEST.search(masked)):
            manual.append(clause)
        if any((positive_writes, _ANSWER.search(masked), _READ.search(masked), tests, _BEHAVIOR.search(masked), _VERIFY.search(masked), _COMMAND.search(clause))):
            goals.append(clause)
        elif not (writes or _NO_COMMAND.search(masked) or _NO_TEST.search(masked) or _FILE_LIST.fullmatch(masked) or scope_match
                  or before_scope or re.search(r"运行|执行|\b(?:run|execute|wait)\b", masked, re.I)):
            # 无法归类的自然语言仍交给模型理解，不伪造必须人工验收的执行要求。
            goals.append(clause)
    if other_files_forbidden:
        targets = [target for target in _file_change_targets(text) if target]
        data["write_scopes"].append(targets)
        if not targets:
            data["conflicts"].append("其他文件的排除范围不明确，请明确允许修改的路径")
    if read_only_scopes:
        if "modify" in actions:
            data["forbidden_write_paths"].extend(path for group in read_only_scopes for path in group)
        else:
            data["access_scopes"].extend(read_only_scopes)
            data["writes_forbidden"] = True
    if data["preview_only"]:
        data["writes_forbidden"] = True
    elif data["writes_forbidden"] and "modify" in actions:
        data["conflicts"].append("同时要求修改与禁止写入；写入操作已阻止，请明确任务范围")
    if data["tests_forbidden"]:
        data["unperformed"].append(_TEST_NOTE)
    if data["commands_forbidden"] and not data["preview_only"]:
        data["unperformed"].append(_COMMAND_NOTE)
    if has_positive_test and (data["tests_forbidden"] or data["commands_forbidden"]):
        data["conflicts"].append("同时要求测试与禁止测试或命令；测试操作已阻止，请明确任务范围")
    data["forbidden_write_paths"] = list(dict.fromkeys(data["forbidden_write_paths"]))
    policy = TaskPolicy.model_validate(data)
    requirements, origins = [], {}

    def add(kind, scope, description, evidence_policy, origin="intent_rule", required=True):
        if any(item.kind == kind and item.scope == scope for item in requirements):
            return
        identifier = f"{source_id}-requirement-{len(requirements) + 1}"
        requirements.append(Requirement(requirement_id=identifier, kind=kind, scope=scope,
                            description=description[:4000], evidence_policy=evidence_policy, origin=origin, required=required))
        origins[identifier] = source_id

    if policy.preview_only:
        add("preview", "", "仅提供方案或补丁预览，不执行修改或命令", "response")
    else:
        for target in _file_change_targets("，".join(positive_parts)):
            add("file_changed", target, f"实际修改文件：{target or '所选项目'}", "disk")
        for match in _COMMAND.finditer(text):
            if _negative(text, match.start()):
                continue
            prefix = _CLAUSES.split(text[:match.start()])[-1]
            if _ANSWER.search(prefix) and not re.search(r"然后|随后|\bthen\b", prefix, re.I):
                continue
            suffix = _CLAUSES.split(text[match.end():])[0]
            if not _EXECUTE.search(prefix) and (prefix.strip() or suffix.strip()):
                continue
            command = canonical_command(re.split(r"\s+(?:and|then|but|please)\b", match.group(), maxsplit=1, flags=re.I)[0].strip())
            kind = "test" if command_kind(shlex.split(command)) == "test" else "command"
            add(kind, command, f"{'测试通过' if kind == 'test' else '执行命令'}：{command}", "test_exit" if kind == "test" else "exit")
            actions.append("execute")
        if has_positive_test and not any(item.kind == "test" for item in requirements):
            add("test", "", "在最后一次修改后运行测试并通过", "test_exit")
        for clause in dict.fromkeys(manual):
            add("manual", clause[:2000], "待人工核验：" + clause, "manual")
    for item in explicit:
        if policy.preview_only and item.kind != "preview":
            raise ValueError("仅预览约束与执行验收要求冲突，请明确本次任务范围")
        add(item.kind, item.scope, item.description, item.evidence_policy, "user", item.required)
        if requirement_blocked(item, policy):
            policy = merge_policy(policy, TaskPolicy(conflicts=["显式验收与用户限制冲突：" + item.description[:1500]]))
    requirements, origins, policy = _effective_requirements(requirements, origins, policy)
    if len(requirements) > 32:
        raise ValueError("验收要求超过 32 项，请缩小任务范围")
    # 回答型是组合解析后的结果，不再根据句首提前短路。
    policy = policy.model_copy(update={"answer_only": not requirements and not policy.conflicts or policy.preview_only})
    return TaskInterpretation(schema_version="1.2", sources=[source], goals=list(dict.fromkeys(goals)), actions=list(dict.fromkeys(actions)),
                              requirements=requirements, requirement_sources=origins, explicit_requirements=explicit,
                              conditions=list(dict.fromkeys(match.group() for match in conditions)), policy_releases=releases,
                              constraints=constraints, policy=policy)


def merge_task(previous: TaskInterpretation, incoming: TaskInterpretation) -> TaskInterpretation:
    """明确撤销只作用于指定禁止项；权限模式、路径范围和历史副作用不随之放宽。"""
    if {s.source_id for s in previous.sources} & {s.source_id for s in incoming.sources}:
        raise ValueError("任务解释来源标识重复")
    derived_releases = [release for source in incoming.sources if source.kind == "steer"
                        for release in _policy_releases(active_text(source.text), source.source_id)[0]]
    if incoming.policy_releases != derived_releases:
        raise ValueError("限制撤销必须对应当前用户追加消息原文")
    prior_policy = previous.policy
    releases = incoming.policy_releases if previous.schema_version in {"1.1", "1.2"} else []
    if releases:
        values = prior_policy.model_dump()
        for release in releases:
            values[release.field] = False
        prior_policy = TaskPolicy.model_validate(values)
    policy = merge_policy(prior_policy, incoming.policy)
    notes = list(policy.unperformed)
    conflicts = list(policy.conflicts)
    if releases:
        if not policy.tests_forbidden:
            notes = [note for note in notes if note != _TEST_NOTE]
        if not policy.commands_forbidden:
            notes = [note for note in notes if note != _COMMAND_NOTE]
        if not (policy.tests_forbidden or policy.commands_forbidden or policy.preview_only):
            conflicts = [note for note in conflicts if not note.startswith("同时要求测试与禁止测试或命令")]
        if not (policy.writes_forbidden or policy.preview_only):
            conflicts = [note for note in conflicts if not note.startswith("同时要求修改与禁止写入")]
        conflicts = [note for note in conflicts if not any(
            note == message and not getattr(policy, field) and not policy.preview_only
            for field, message in _STEER_CONFLICTS.items())]
        resolved = {"显式验收与用户限制冲突：" + item.description[:1500]
                    for item in previous.explicit_requirements if not requirement_blocked(item, policy)}
        conflicts = [note for note in conflicts if note not in resolved]
        policy = policy.model_copy(update={"unperformed": notes, "conflicts": conflicts})
    elif incoming.policy_releases:
        policy = merge_policy(policy, TaskPolicy(conflicts=["旧版任务的限制保留；请新建任务应用撤销指令"]))
    for item in incoming.requirements:
        if not requirement_blocked(item, prior_policy):
            continue
        if item.kind == "test" and prior_policy.tests_forbidden:
            reason = _STEER_CONFLICTS["tests_forbidden"]
        elif item.kind in {"command", "test"} and prior_policy.commands_forbidden:
            reason = _STEER_CONFLICTS["commands_forbidden"]
        elif item.kind == "file_changed" and prior_policy.writes_forbidden:
            reason = _STEER_CONFLICTS["writes_forbidden"]
        else:
            reason = "追加执行要求与路径或预览限制冲突；请新建任务明确执行范围"
        policy = merge_policy(policy, TaskPolicy(conflicts=[reason]))
    requirements = list(previous.requirements)
    origins = dict(previous.requirement_sources)
    for item in incoming.requirements:
        if not any(existing.kind == item.kind and existing.scope == item.scope for existing in requirements):
            requirements.append(item)
            origins[item.requirement_id] = incoming.requirement_sources[item.requirement_id]
    if releases:
        # 显式验收契约不能因一次临时禁止被永久丢弃，来源仍归属最初用户。
        for index, item in enumerate(previous.explicit_requirements):
            if requirement_blocked(item, policy) or any(existing.kind == item.kind and existing.scope == item.scope for existing in requirements):
                continue
            source_id = previous.sources[0].source_id
            restored = item.model_copy(update={"requirement_id": f"{source_id}-explicit-{index + 1}", "origin": "user"})
            requirements.append(restored)
            origins[restored.requirement_id] = source_id
    requirements, origins, policy = _effective_requirements(requirements, origins, policy)
    if len(requirements) > 32:
        raise ValueError("累计验收要求超过 32 项，请缩小范围")
    policy = policy.model_copy(update={"answer_only": not requirements and not policy.conflicts or policy.preview_only})
    return TaskInterpretation(schema_version=previous.schema_version, goal_version=previous.goal_version + 1, sources=[*previous.sources, *incoming.sources],
        goals=list(dict.fromkeys([*previous.goals, *incoming.goals])), actions=list(dict.fromkeys([*previous.actions, *incoming.actions])),
        requirements=requirements, requirement_sources=origins, explicit_requirements=previous.explicit_requirements,
        conditions=list(dict.fromkeys([*previous.conditions, *incoming.conditions])),
        policy_releases=[*previous.policy_releases, *releases], constraints=[*previous.constraints, *incoming.constraints], policy=policy)


def rebuild_task(value: TaskInterpretation) -> TaskInterpretation:
    """当前版本从原文重建派生策略；旧版本在核验来源之前保留既有限制。"""
    first, *remaining = value.sources
    current = interpret_task(first.text, value.explicit_requirements, source_id=first.source_id, source_kind=first.kind)
    current = current.model_copy(update={"schema_version": value.schema_version})
    for source in remaining:
        current = merge_task(current, interpret_task(source.text, source_id=source.source_id, source_kind=source.kind))
    policy = current.policy if value.schema_version == "1.2" else merge_policy(current.policy, value.policy)
    requirements, origins, policy = _effective_requirements(current.requirements, current.requirement_sources, policy)
    policy = policy.model_copy(update={"answer_only": not requirements and not policy.conflicts or policy.preview_only})
    return current.model_copy(update={"goal_version": value.goal_version, "policy": policy,
                                      "requirements": requirements, "requirement_sources": origins})
