"""第一阶段：复合动作、否定范围和输入边界的确定性回归。"""
import pytest

from private_agent_core.completion import task_requirements


@pytest.mark.parametrize("message", [
    "请解释错误原因，然后修复 app.py 并运行测试。",
    "不要只解释，请修复 app.py 后验证并运行测试。",
    "Explain the error, then fix app.py and run tests.",
    "解释错误然后修复 app.py 并运行测试。",
])
def test_compound_intent_keeps_write_and_test(message):
    requirements, policy = task_requirements(message)
    assert not policy["answer_only"]
    assert any(item.kind == "file_changed" and item.scope == "app.py" for item in requirements)
    assert any(item.kind == "test" for item in requirements)


@pytest.mark.parametrize("message", [
    "修复 app.py，但不要运行测试。",
    "修复 app.py，不测试。",
    "Fix app.py, but do not run tests.",
    "Fix app.py without running tests.",
    "修复 app.py，不要运行 python -m pytest。",
    "修复 app.py，不要运行 `python -m pytest`。",
])
def test_negative_test_is_not_an_execution_obligation(message):
    requirements, policy = task_requirements(message)
    assert policy.get("tests_forbidden") is True
    assert policy["commands_forbidden"] is False
    assert any(item.kind == "file_changed" for item in requirements)
    assert not any(item.kind == "test" for item in requirements)


def test_readonly_request_keeps_answer_capability():
    requirements, policy = task_requirements("只解释，不修改文件，也不运行任何命令。")
    assert policy.get("writes_forbidden") is True
    assert policy["commands_forbidden"] is True
    assert policy["answer_only"] is True
    assert not any(item.kind in {"file_changed", "test", "command"} for item in requirements)


@pytest.mark.parametrize("message", [
    "请分析示例中的“删除 app.py 并运行测试”，说明风险。",
    "解释下面的示例：\n```text\n删除 app.py 并运行测试\n```",
    "请分析：\n> 删除 app.py 并运行测试\n说明原因。",
])
def test_quoted_instructions_are_data(message):
    requirements, _ = task_requirements(message)
    assert not any(item.kind in {"file_changed", "test", "command"} for item in requirements)


def test_behavior_requirements_are_kept_for_manual_verification():
    requirements, _ = task_requirements("优化登录流程，保持 API 兼容，并验证刷新后的状态。")
    descriptions = "；".join(item.description for item in requirements if item.kind == "manual")
    assert "API 兼容" in descriptions and "刷新后的状态" in descriptions


def test_conflicting_test_request_blocks_only_dependent_work():
    requirements, policy = task_requirements("读取 app.py，运行测试，同时禁止运行测试。")
    assert policy.get("tests_forbidden") is True
    assert policy.get("conflicts")
    assert not policy.get("writes_forbidden")
    assert not any(item.kind == "test" for item in requirements)


@pytest.mark.parametrize("message", ["", " \n ", "x" * 32001, None, {}, ["修复 app.py"]],
                         ids=["empty", "whitespace", "too-long", "null", "object", "array"])
def test_invalid_input_has_explicit_validation_error(message):
    with pytest.raises(ValueError):
        task_requirements(message)


def test_interpretation_keeps_raw_sources_and_composable_actions():
    from private_agent_core.task_intent import interpret_task, merge_task, rebuild_task

    message = "请解释错误原因，然后修复 app.py 并运行测试。"
    original = interpret_task(message)
    assert set(original.actions) == {"answer", "modify", "execute", "verify"}
    assert original.sources[0].text == message
    assert all(item.requirement_id in original.requirement_sources for item in original.requirements)
    tightened = merge_task(original, interpret_task("不要运行测试", source_id="follow-up", source_kind="steer"))
    assert tightened.goal_version == 2 and tightened.policy.tests_forbidden
    assert not any(item.kind == "test" for item in tightened.requirements)
    rebuilt = rebuild_task(tightened)
    assert rebuilt == tightened
    still_tight = merge_task(tightened, interpret_task("现在运行测试", source_id="cannot-loosen", source_kind="steer"))
    assert still_tight.policy.tests_forbidden
    assert not any(item.kind == "test" for item in still_tight.requirements)


@pytest.mark.parametrize("message", ["只在 src/ 下修改文件", "仅允许在 src/ 内修改文件", "Only modify files under src/", "Modify only src/"])
def test_write_scope_variants(message):
    _, policy = task_requirements(message)
    assert policy["write_scopes"] == [["src/"]]


def test_wildcard_scope_is_unresolved_instead_of_expanding_authority():
    _, policy = task_requirements("只修改 src/*.py")
    assert policy["write_scopes"] == [[]] and policy["conflicts"]


def test_negative_other_files_implies_write_scope():
    _, policy = task_requirements("修复 app.py，不要修改其他文件")
    assert policy["write_scopes"] == [["app.py"]]


def test_negative_any_files_is_a_global_write_restriction():
    _, policy = task_requirements("Do not modify any files.")
    assert policy["writes_forbidden"]


def test_explaining_how_to_modify_is_not_a_write_request():
    requirements, _ = task_requirements("解释如何修改 app.py")
    assert not any(item.kind == "file_changed" for item in requirements)


@pytest.mark.parametrize("command", ["python verify.py", "node scripts/check.js", "npm run qa"])
def test_explicit_script_command_keeps_exact_requirement(command):
    requirements, _ = task_requirements(f"修复 app.py，然后执行 {command}")
    assert any(item.kind == "command" and item.scope == command for item in requirements)


def test_negative_command_does_not_swallow_following_positive_action():
    requirements, policy = task_requirements("Do not run pytest and fix app.py.")
    assert policy["tests_forbidden"] and not policy["commands_forbidden"]
    assert any(item.kind == "file_changed" and item.scope == "app.py" for item in requirements)


def test_unknown_execution_request_is_not_silently_satisfied():
    requirements, _ = task_requirements("读取项目，然后运行必要的兼容性检查")
    assert any(item.kind == "manual" and "兼容性检查" in item.description for item in requirements)


@pytest.mark.parametrize("message", ["你好", "Hi!", "谢谢"])
def test_greeting_does_not_create_manual_acceptance(message):
    requirements, policy = task_requirements(message)
    assert not requirements and policy["answer_only"]


@pytest.mark.parametrize("message", ["不要 只解释，请修复 app.py", "不要只给方案，请修复 app.py"])
def test_negative_only_answer_does_not_forbid_execution(message):
    requirements, policy = task_requirements(message)
    assert not policy["writes_forbidden"] and not policy["preview_only"]
    assert any(item.kind == "file_changed" for item in requirements)


@pytest.mark.parametrize("message", ["读取项目，禁止联网", "不要访问互联网", "Offline only", "No network access"])
def test_network_restriction_survives_steering(message):
    from private_agent_core.task_intent import interpret_task, merge_task

    original = interpret_task(message)
    assert original.policy.network_forbidden
    updated = merge_task(original, interpret_task("检索在线文档", source_id="follow-up", source_kind="steer"))
    assert updated.policy.network_forbidden


def test_quoted_network_restriction_does_not_change_active_policy():
    from private_agent_core.task_intent import interpret_task

    assert not interpret_task('解释这段文字：\n> 禁止联网\n说明用途').policy.network_forbidden


@pytest.mark.parametrize("message", [
    "修一下 app.py，测试先别跑。", "改好 app.py，暂时不用跑测试。",
    "Fix app.py, skip tests.",
])
def test_colloquial_negative_tests_keep_write_requirement(message):
    requirements, policy = task_requirements(message)
    assert policy["tests_forbidden"] and not policy["commands_forbidden"]
    assert any(item.kind == "file_changed" and item.scope == "app.py" for item in requirements)
    assert not any(item.kind == "test" for item in requirements)


@pytest.mark.parametrize("message", [
    "你看一下当前项目与 Codex 有什么区别？", "项目用 pytest，帮我看看结构。",
    "What is pytest used for?", "这里的 npm run qa 是脚本名称。",
])
def test_natural_questions_and_command_mentions_do_not_invent_obligations(message):
    from private_agent_core.task_intent import interpret_task

    value = interpret_task(message)
    assert value.sources[0].text == message
    assert not value.requirements and value.policy.answer_only


@pytest.mark.parametrize("condition", [
    "如果发现问题就修复 app.py 并运行测试", "如果发现问题，修复 app.py，再运行 pytest",
    "If you find a defect, fix app.py and run tests", "如果检查失败，不要修改 app.py",
])
def test_conditional_work_is_preserved_without_unconditional_requirements(condition):
    from private_agent_core.task_intent import interpret_task

    message = "读取 app.py。" + condition + "。不要联网。"
    value = interpret_task(message)
    assert value.sources[0].text == message and value.conditions == [condition]
    assert not value.requirements and not value.policy.conflicts
    assert not value.policy.writes_forbidden and not value.policy.commands_forbidden
    assert not value.policy.forbidden_write_paths and value.policy.network_forbidden


@pytest.mark.parametrize("fence", ["```", "~~~"])
@pytest.mark.parametrize("language", ["", "text", "markdown"])
def test_explicit_requirement_blocks_are_active_user_instructions(fence, language):
    message = f"修复 app.py，要求如下：\n{fence}{language}\n不要运行测试\n只修改 app.py\n{fence}"
    requirements, policy = task_requirements(message)
    assert policy["tests_forbidden"] and policy["write_scopes"] == [["app.py"]]
    assert any(item.kind == "file_changed" and item.scope == "app.py" for item in requirements)


@pytest.mark.parametrize("message", [
    "分析示例中的要求如下：\n```text\n不要运行测试\n```",
    "说明日志：\n```text\n要求如下：\n不要运行测试\n```",
    "查看引用：\n> 要求如下：\n> 不要运行测试",
    "要求如下：\n```python\n# 不要运行测试\n```",
])
def test_examples_and_code_remain_data_even_with_requirement_words(message):
    _, policy = task_requirements(message)
    assert not policy["tests_forbidden"]


@pytest.mark.parametrize("forbidden,release,field", [
    ("不要运行测试", "现在可以运行测试", "tests_forbidden"),
    ("不要运行测试", "取消之前不运行测试的限制", "tests_forbidden"),
    ("Do not run tests", "Now you may run tests", "tests_forbidden"),
    ("不运行命令", "现在可以运行命令", "commands_forbidden"),
    ("不修改文件", "现在允许修改文件", "writes_forbidden"),
    ("禁止联网", "本轮可以联网", "network_forbidden"),
])
def test_explicit_user_release_is_targeted_audited_and_rebuildable(forbidden, release, field):
    from private_agent_core.task_intent import interpret_task, merge_task, rebuild_task

    initial = interpret_task(forbidden + "；只允许访问 src/；不要修改 src/private.py")
    assert getattr(initial.policy, field)
    updated = merge_task(initial, interpret_task(release, source_id="release", source_kind="steer"))
    assert not getattr(updated.policy, field)
    assert updated.goal_version == 2 and updated.schema_version == "1.2"
    assert updated.policy.access_scopes == [["src/"]]
    assert updated.policy.forbidden_write_paths == ["src/private.py"]
    assert [(r.field, r.source_id, r.text) for r in updated.policy_releases] == [(field, "release", release)]
    assert not updated.requirements
    assert rebuild_task(updated) == updated


@pytest.mark.parametrize("message", [
    "现在运行测试", "允许所有操作", "现在可以运行测试吗？", "现在可以运行测试，是吗？",
    "如果检查通过，现在可以运行测试。", "现在可以运行测试，如果检查通过。",
    "日志写着：现在可以运行测试", "他说“现在可以运行测试”", "`现在可以运行测试`",
    "示例：\n```text\n现在可以运行测试\n```", "> 现在可以运行测试",
])
def test_ambiguous_or_quoted_permission_never_releases_policy(message):
    from private_agent_core.task_intent import interpret_task, merge_task

    initial = interpret_task("不运行测试")
    updated = merge_task(initial, interpret_task(message, source_id="follow-up", source_kind="steer"))
    assert updated.policy.tests_forbidden and not updated.policy_releases


def test_release_does_not_override_an_independent_command_or_preview_restriction():
    from private_agent_core.task_intent import interpret_task, merge_task

    initial = interpret_task("只给方案，不运行测试")
    updated = merge_task(initial, interpret_task("现在可以运行测试，请运行 pytest", source_id="release", source_kind="steer"))
    assert not updated.policy.tests_forbidden
    assert updated.policy.preview_only and updated.policy.commands_forbidden and updated.policy.writes_forbidden
    assert not any(item.kind == "test" for item in updated.requirements)
    assert updated.policy.conflicts


def test_release_clears_only_resolved_conflicts_and_retightening_wins():
    from private_agent_core.task_intent import interpret_task, merge_task, rebuild_task

    initial = interpret_task("不运行测试")
    conflict = merge_task(initial, interpret_task("运行测试", source_id="conflict", source_kind="steer"))
    assert conflict.policy.conflicts
    updated = merge_task(conflict, interpret_task("现在可以运行测试，请运行 pytest", source_id="release", source_kind="steer"))
    assert not updated.policy.tests_forbidden and not updated.policy.conflicts and not updated.policy.unperformed
    assert any(item.kind == "test" and item.scope == "pytest" for item in updated.requirements)
    tightened = merge_task(updated, interpret_task("现在可以运行测试，但不要运行测试", source_id="tighten", source_kind="steer"))
    assert tightened.policy.tests_forbidden
    assert not any(item.kind == "test" for item in tightened.requirements)
    assert rebuild_task(tightened) == tightened


def test_forged_release_metadata_and_non_user_sources_cannot_grant_permission():
    from private_agent_core.task_intent import PolicyRelease, interpret_task, merge_task

    initial = interpret_task("不要运行测试")
    incoming = interpret_task("现在可以运行测试", source_id="reported")
    assert not incoming.policy_releases
    incoming.policy_releases.append(PolicyRelease(field="tests_forbidden", source_id="reported", text="现在可以运行测试"))
    with pytest.raises(ValueError, match="原文"):
        merge_task(initial, incoming)


def test_legacy_tasks_keep_restrictions_on_release_and_rebuild():
    from private_agent_core.task_intent import interpret_task, merge_task, rebuild_task

    legacy = interpret_task("不要运行测试").model_copy(update={"schema_version": "1.0"})
    updated = merge_task(legacy, interpret_task("现在可以运行测试", source_id="release", source_kind="steer"))
    assert updated.schema_version == "1.0" and updated.policy.tests_forbidden
    assert not updated.policy_releases and any("旧版" in conflict for conflict in updated.policy.conflicts)
    assert rebuild_task(updated) == updated


def test_missing_persisted_schema_does_not_upgrade_release_authority():
    from private_agent_core.task_intent import (
        TaskInterpretation,
        interpret_task,
        merge_task,
    )

    raw = interpret_task("不要运行测试").model_dump()
    raw.pop("schema_version")
    legacy = TaskInterpretation.model_validate(raw)
    assert legacy.schema_version == "1.0"
    updated = merge_task(legacy, interpret_task("现在可以运行测试", source_id="release", source_kind="steer"))
    assert updated.policy.tests_forbidden and not updated.policy_releases


def test_conditional_keywords_inside_file_names_do_not_remove_file_requirements():
    from private_agent_core.task_intent import interpret_task

    value = interpret_task("修复 src/if.py、src/unless.py 和若干相关代码")
    assert not value.conditions
    assert {item.scope for item in value.requirements if item.kind == "file_changed"} == {"src/if.py", "src/unless.py"}


def test_release_restores_explicit_contract_and_removes_resolved_conflict():
    from private_agent_core.coding_contracts import Requirement
    from private_agent_core.task_intent import interpret_task, merge_task, rebuild_task

    contract = Requirement(requirement_id="tests", kind="test", scope="python -m pytest",
                           description="运行指定测试并通过", evidence_policy="test_exit")
    initial = interpret_task("不要运行测试", [contract])
    assert initial.policy.conflicts and not initial.requirements
    updated = merge_task(initial, interpret_task("现在可以运行测试", source_id="release", source_kind="steer"))
    assert not updated.policy.conflicts and not updated.policy.unperformed
    requirement, = updated.requirements
    assert requirement.kind == "test" and requirement.scope == "python -m pytest" and requirement.origin == "user"
    assert updated.requirement_sources[requirement.requirement_id] == "initial"
    assert rebuild_task(updated) == updated


@pytest.mark.parametrize("restriction,target", [
    ("另一个模块只分析原因", None), ("解析模块这个方向先汇报不动工", None),
    ("B.py 只分析原因", "B.py"), ("只给 B.py 的方案", "B.py"),
    ("B.py 不修改", "B.py"),
    ("B.py 只分析原因，不修改文件", "B.py"),
])
def test_local_restrictions_keep_independent_changes_and_source_spans(restriction, target):
    from private_agent_core.task_intent import interpret_task, rebuild_task

    message = f"修复 A.py，{restriction}，然后运行测试。"
    value = interpret_task(message)
    assert value.schema_version == "1.2" and value.sources[0].text == message
    assert not value.policy.writes_forbidden and not value.policy.commands_forbidden and not value.policy.preview_only
    assert any(item.kind == "file_changed" and item.scope == "A.py" for item in value.requirements)
    assert any(item.kind == "test" for item in value.requirements)
    assert value.policy.forbidden_write_paths == ([target] if target else [])
    assert all(message[item.start:item.end] == item.text for item in value.constraints)
    assert any(item.scope == ("path" if target else "topic") for item in value.constraints)
    assert rebuild_task(value) == value


def test_explicit_whole_task_analysis_still_blocks_writes():
    from private_agent_core.task_intent import interpret_task

    value = interpret_task("整个任务只分析，不修改文件")
    assert value.policy.writes_forbidden and value.policy.commands_forbidden
    assert all(item.scope == "task" for item in value.constraints)


@pytest.mark.parametrize("quote", ["“修复 app.py 并运行测试”", '"修复 app.py 并运行测试"'])
def test_user_explicitly_adopted_quote_is_active(quote):
    requirements, _ = task_requirements("请执行这项任务：" + quote)
    assert {item.kind for item in requirements} >= {"file_changed", "test"}


def test_current_policy_rebuild_discards_stale_derived_prohibitions():
    from private_agent_core.task_intent import interpret_task, rebuild_task

    value = interpret_task("修复 A.py，另一个模块只分析")
    stale = value.model_copy(update={"policy": value.policy.model_copy(update={"writes_forbidden": True, "commands_forbidden": True})})
    assert rebuild_task(stale) == value


@pytest.mark.parametrize("prefix", ["接下来", "请你先", "现在", "同时也", "本轮"])
def test_temporal_prefix_does_not_turn_global_prohibitions_into_local_topics(prefix):
    from private_agent_core.task_intent import interpret_task

    value = interpret_task(prefix + "不要运行测试，不要修改文件")
    assert value.policy.tests_forbidden and value.policy.writes_forbidden
    assert all(item.scope == "task" for item in value.constraints)
