"""v0.9.0 H1-B 契约测试：Agent 动手主链（计划 §5.6）。

覆盖：
- 可执行意图识别矩阵：信息问答/教程式提问/可执行请求；
- 内置只读诊断 profile（MySQL 检查固定验收样例）：匹配、精确 argv、
  workspace 复核豁免、未命中仍拒绝；
- workspace 无项目 profile 时诊断集自动放行（§5.3 替我批准真实语义）；
- typed service probe 解析（sc.exe query 输出）；
- min_tool_executions 证据门槛：无执行证据的"完成"宣称失败关闭；
- run 创建链：可执行意图注入证据门槛并持久化（审批恢复可重读）。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete
from test_v070_permissions import _create_coding_env, _post_coding_run

from personal_assistant.agents.tools import ToolRiskLevel
from personal_assistant.agents.verification import (
    WorkflowCompletionFacts,
    WorkflowCompletionOutputVerifier,
)
from personal_assistant.api import routes_agent_runs
from personal_assistant.core.command_workflow import _resolve_command
from personal_assistant.core.diagnostic_profiles import (
    BUILTIN_DIAGNOSTIC_PROFILES,
    diagnostic_profiles_description,
)
from personal_assistant.core.executable_intent import (
    FILE_MUTATION_INTENT_POLICY,
    detect_direct_single_file_write_intent,
    detect_executable_intent,
    detect_file_mutation_intent,
)
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import Project
from personal_assistant.core.permissions import PermissionError_
from personal_assistant.core.result_parsers import parse_command_result

# ===========================================================================
# A. 可执行意图识别矩阵
# ===========================================================================


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # 计划 §5.6 首个固定验收样例与同类可执行请求
        ("看一下本机是否装了 MySQL", True),
        ("检查本机是否安装 MySQL", True),
        ("查看项目里的测试为什么失败", True),
        ("运行项目测试", True),
        ("帮我修改 README 的标题", True),
        ("创建一个新项目目录", True),
        # 信息问答/教程式提问（用户只要方法时不强制工具证据）
        ("如何安装 MySQL", False),
        ("怎么检查本机有没有装 MySQL", False),
        ("MySQL 是什么", False),
        ("给我一份安装 MySQL 的教程", False),
        ("仅回答方法：如何查看服务状态", False),
        ("你好", False),
        ("", False),
        # 咨询语境不误报
        ("我可以安装 MySQL 吗", False),
    ],
)
def test_executable_intent_matrix(message: str, expected: bool):
    assert detect_executable_intent(message) is expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("在根目录下创建一个txt文档，文件名为hello.txt", True),
        ("帮我修改 README 的标题", True),
        ("删除 src/legacy.py 文件", True),
        ("如何创建 hello.txt 文件", False),
        ("创建一个数据库", False),
        ("运行项目测试", False),
    ],
)
def test_file_mutation_intent_matrix(message: str, expected: bool):
    assert detect_file_mutation_intent(message) is expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("创建一个 hello.c 文件，写入打印 hello world 的代码", True),
        ("修改 src/main.ts 文件", True),
        ("修改 src/a.ts 和 src/b.ts 文件", False),
        ("批量修改多个文件", False),
        ("只预览 hello.txt 的修改，不要写入", False),
    ],
)
def test_direct_single_file_write_intent_matrix(message: str, expected: bool):
    assert detect_direct_single_file_write_intent(message) is expected


def test_file_mutation_policy_routes_writes_away_from_command_tool():
    assert "apply_patch_to_workspace" in FILE_MUTATION_INTENT_POLICY
    assert "apply_patch_set" in FILE_MUTATION_INTENT_POLICY
    assert "run_whitelisted_command" in FILE_MUTATION_INTENT_POLICY
    assert "不得重复" in FILE_MUTATION_INTENT_POLICY
    assert "相对路径" in FILE_MUTATION_INTENT_POLICY
    assert "/hello.txt" in FILE_MUTATION_INTENT_POLICY
    assert "预览成功后必须继续" in FILE_MUTATION_INTENT_POLICY
    assert "直接调用 apply_patch_to_workspace" in FILE_MUTATION_INTENT_POLICY


# ===========================================================================
# B. 内置只读诊断 profile（固定 argv 安全诊断）
# ===========================================================================


async def _make_project(db, tmp_path) -> int:
    project = Project(name=f"h1b-{uuid4().hex[:8]}", root_path=str(tmp_path))
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project.id


async def test_diagnostic_profile_matches_fixed_argv(db, tmp_path):
    """where.exe mysql 命中内置诊断 profile（无需项目 profile）。"""
    project_id = await _make_project(db, tmp_path)
    try:
        resolved = await _resolve_command(
            db, project_id, ["where.exe", "mysql"], timeout=None
        )
        assert resolved.matched_profile_name == "diag_where_mysql"
        assert resolved.cwd == str(tmp_path)
    finally:
        await db.execute(
            delete(Project).where(Project.id == project_id)
        )
        await db.commit()


async def test_diagnostic_profile_rejects_appended_args(db, tmp_path):
    """safe 内置诊断必须精确 argv：追加参数即拒绝（模型不能拼接）。"""
    project_id = await _make_project(db, tmp_path)
    try:
        with pytest.raises(PermissionError_):
            await _resolve_command(
                db, project_id, ["where.exe", "mysql", "extra"], timeout=None
            )
        with pytest.raises(PermissionError_):
            await _resolve_command(
                db, project_id, ["sc.exe", "query", "evilsvc"], timeout=None
            )
    finally:
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()


async def test_diagnostic_profile_workspace_toctou_exempt(db, tmp_path):
    """workspace SAFE 复核：内置诊断（零网络结构性成立）不因
    allow_network=False 被 TOCTOU 复核拒绝；未命中诊断的命令仍拒绝。"""
    project_id = await _make_project(db, tmp_path)
    try:
        resolved = await _resolve_command(
            db,
            project_id,
            ["mysql", "--version"],
            timeout=None,
            permission_mode="workspace",
            command_risk=ToolRiskLevel.SAFE,
        )
        assert resolved.matched_profile_name == "diag_mysql_version"
        # workspace 模式未匹配任何 profile 的命令不得自动放行
        with pytest.raises(PermissionError_):
            await _resolve_command(
                db,
                project_id,
                ["cargo", "check"],
                timeout=None,
                permission_mode="workspace",
                command_risk=ToolRiskLevel.SAFE,
            )
    finally:
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()


def test_diagnostic_profiles_are_readonly_and_fixed():
    """内置诊断集全部 safe + 零网络；服务探针仅接受已知服务名白名单。"""
    assert BUILTIN_DIAGNOSTIC_PROFILES
    for profile in BUILTIN_DIAGNOSTIC_PROFILES:
        assert profile.risk_level == "safe"
        assert profile.allow_network is False
        assert profile.builtin is True
    service_args = [
        str(x)
        for p in BUILTIN_DIAGNOSTIC_PROFILES
        if p.name.startswith("diag_service_")
        for x in p.command_json["args"]
    ]
    assert "sc.exe" in service_args and "query" in service_args


def test_command_tool_description_exposes_diagnostic_argv():
    """命令工具描述向模型公开诊断固定 argv（能力就绪不退化为教程的前提）。"""
    description = diagnostic_profiles_description()
    assert "where.exe mysql" in description
    assert "mysql --version" in description
    assert "sc.exe query" in description
    assert "教程" in description


# ===========================================================================
# C. workspace 档：无项目 profile 时诊断集自动放行
# ===========================================================================


async def test_workspace_command_risk_safe_for_builtin_diagnostics(db, tmp_path):
    """无项目命令 profile → 可执行命令面 = 内置只读诊断集 → SAFE。"""
    from personal_assistant.api.routes_agent_runs import _workspace_command_risk

    project_id = await _make_project(db, tmp_path)
    run_id = str(uuid4())
    from personal_assistant.agents import AgentRunLimits, AgentRunRepository

    repository = AgentRunRepository(db)
    await repository.create_run(
        run_id=run_id, limits=AgentRunLimits(), project_id=project_id
    )
    try:
        risk = await _workspace_command_risk(db, run_id)
        assert risk == ToolRiskLevel.SAFE
    finally:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()


# ===========================================================================
# D. typed service probe 解析（sc.exe query）
# ===========================================================================


_SC_QUERY_RUNNING = """
SERVICE_NAME: MySQL80
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 4  RUNNING
                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)
        WIN32_EXIT_CODE    : 0  (0x0)
"""


def test_windows_service_probe_parses_running_state():
    parsed = parse_command_result("windows_service_probe", _SC_QUERY_RUNNING)
    assert parsed["parser"] == "windows_service_probe"
    assert parsed["found"] is True
    assert parsed["service_name"] == "MySQL80"
    assert parsed["state"] == "RUNNING"
    assert parsed["state_code"] == 4
    assert "MySQL80" in parsed["summary"]


def test_windows_service_probe_without_state_facts():
    parsed = parse_command_result("windows_service_probe", "无结构化输出")
    assert parsed["found"] is False
    assert parsed["summary"] == "sc.exe query 输出未含服务状态事实"


# ===========================================================================
# E. min_tool_executions 证据门槛（可执行请求不得退化为纯问答）
# ===========================================================================


def _verifier(
    executions: list[dict],
    *,
    minimum: int,
    require_successful_file_write: bool = False,
):
    async def loader() -> WorkflowCompletionFacts:
        return WorkflowCompletionFacts(executions=executions)

    # max_failed_tools 放宽：隔离验证最小证据门槛（诊断命令失败也是证据，
    # 与 run 创建链注入口径一致）。
    return WorkflowCompletionOutputVerifier(
        loader,
        min_tool_executions=minimum,
        max_failed_tools=16,
        require_successful_file_write=require_successful_file_write,
    )


async def test_min_tool_executions_fails_without_evidence():
    """零执行证据 → 失败关闭，未满足项要求调用工具（不伪装完成）。"""
    verification = await _verifier([], minimum=1).verify("已完成", attempt=1)
    assert verification.passed is False
    assert verification.code == "completion_not_met"
    assert "执行证据" in verification.message
    assert "教程" in verification.message


async def test_min_tool_executions_counts_failed_commands_as_evidence():
    """失败的命令也是执行证据（退出码非 0 ≠ 未执行）；结论由模型按证据陈述。"""
    verification = await _verifier(
        [{"tool_name": "run_whitelisted_command", "status": "failed"}],
        minimum=1,
    ).verify("PATH 未命中 mysql", attempt=1)
    assert verification.passed is True


async def test_min_tool_executions_default_off():
    """未设置门槛时行为不变（信息问答不被误伤）。"""
    async def loader() -> WorkflowCompletionFacts:
        return WorkflowCompletionFacts(executions=[])

    verifier = WorkflowCompletionOutputVerifier(loader)
    verification = await verifier.verify("回答", attempt=1)
    assert verification.passed is True


async def test_file_mutation_rejects_failed_command_only_evidence():
    """复现试用反馈：非白名单命令即使执行过，也不能让文件任务 completed。"""
    verification = await _verifier(
        [
            {"tool_name": "run_whitelisted_command", "status": "failed"},
            {"tool_name": "run_whitelisted_command", "status": "failed"},
            {"tool_name": "run_whitelisted_command", "status": "failed"},
        ],
        minimum=1,
        require_successful_file_write=True,
    ).verify("无法创建文件", attempt=1)
    assert verification.passed is False
    assert verification.code == "completion_not_met"
    assert "Patch 写入" in verification.message
    assert "run_whitelisted_command 不能用于创建或编辑文件" in (
        verification.correction or ""
    )


async def test_file_mutation_preview_feedback_requires_immediate_apply():
    verification = await _verifier(
        [{"tool_name": "propose_patch", "status": "succeeded"}],
        minimum=1,
        require_successful_file_write=True,
    ).verify("预览已生成", attempt=1)
    assert verification.passed is False
    assert "预览 propose_patch 已成功" in (verification.correction or "")
    assert "立即" in (verification.correction or "")
    assert "apply_patch_to_workspace" in (verification.correction or "")
    assert "不要重复预览" in (verification.correction or "")


@pytest.mark.parametrize("tool_name", ["apply_patch_to_workspace", "apply_patch_set"])
async def test_file_mutation_accepts_successful_patch_write(tool_name: str):
    verification = await _verifier(
        [{"tool_name": tool_name, "status": "succeeded"}],
        minimum=1,
        require_successful_file_write=True,
    ).verify("文件已创建", attempt=1)
    assert verification.passed is True


# ===========================================================================
# F. run 创建链：可执行意图注入证据门槛并持久化
# ===========================================================================


async def test_executable_intent_run_persists_evidence_gate(
    client, monkeypatch, tmp_path
):
    """可执行意图 → completion_conditions.min_tool_executions=1 持久化到
    run 记录（审批恢复/重启续跑重读同一组条件）。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    env = await _create_coding_env(client, tmp_path)
    resp = await _post_coding_run(
        client, env, message="看一下本机是否装了 MySQL"
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]

    from personal_assistant.core.db import async_session_factory

    async with async_session_factory() as db:
        record = await db.get(AgentRunRecord, run_id)
        assert record is not None
        conditions = record.completion_conditions_json or {}
        assert conditions.get("min_tool_executions") == 1


async def test_file_mutation_run_persists_successful_write_gate(
    client, monkeypatch, tmp_path
):
    """明确文件写入请求必须持久化成功写入门槛，供审批恢复和终态复核。

    v1.0 CT1-04 起（专项计划 F-002）：文件写入意图在没有任何可用写工具时
    创建即被预检阻断；本用例开启单文件 Patch 工作流后验证门槛持久化。
    """
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", True)
    env = await _create_coding_env(client, tmp_path)
    resp = await _post_coding_run(
        client,
        env,
        message="在根目录创建 hello.txt 文件，内容为 hello world",
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]

    from personal_assistant.core.db import async_session_factory

    async with async_session_factory() as db:
        record = await db.get(AgentRunRecord, run_id)
        assert record is not None
        conditions = record.completion_conditions_json or {}
        assert conditions.get("min_tool_executions") == 1
        assert conditions.get("require_successful_file_write") is True


async def test_direct_single_file_run_only_exposes_direct_apply_tool(
    client, monkeypatch, tmp_path
):
    """明确单文件写入缩小模型工具面；apply 仍由原审批执行器把关。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    monkeypatch.setattr(
        routes_agent_runs.cfg, "agent_run_read_only_tools_enabled", True
    )
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "coding_patchset_enabled", True)
    captured: dict = {}
    monkeypatch.setattr(
        routes_agent_runs.agent_run_coordinator,
        "start",
        lambda **kwargs: captured.update(kwargs),
    )
    env = await _create_coding_env(client, tmp_path)
    resp = await _post_coding_run(
        client,
        env,
        message="创建一个 hello.c 文件，写入打印 hello world 的代码",
    )
    assert resp.status_code == 202, resp.text
    names = {definition.name for definition in captured["tool_definitions"]}
    assert "apply_patch_to_workspace" in names
    assert "propose_patch" not in names
    assert "propose_patch_set" not in names
    assert "apply_patch_set" not in names


async def test_informational_run_has_no_evidence_gate(
    client, monkeypatch, tmp_path
):
    """信息问答不注入证据门槛（允许直接回答）。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    env = await _create_coding_env(client, tmp_path)
    resp = await _post_coding_run(client, env, message="如何安装 MySQL")
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]

    from personal_assistant.core.db import async_session_factory

    async with async_session_factory() as db:
        record = await db.get(AgentRunRecord, run_id)
        conditions = record.completion_conditions_json or {}
        assert "min_tool_executions" not in conditions


async def test_min_tool_executions_request_validation(client):
    """客户端显式传入非法 min_tool_executions → 422。"""
    monkey = pytest.MonkeyPatch()
    monkey.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    try:
        resp = await client.post(
            "/agent-runs",
            json={
                "message": "x",
                "completion_conditions": {"min_tool_executions": 0},
            },
        )
        assert resp.status_code == 422
    finally:
        monkey.undo()


async def test_coding_run_create_persists_user_message_and_last_run_once(
    client, monkeypatch, tmp_path, db
):
    """Coding API 创建成功即 durable 保存用户请求与 session.last_run_id；
    client_request_id 重放不能重复消息。
    """
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    monkeypatch.setattr(
        routes_agent_runs.agent_run_coordinator,
        "start",
        lambda **_: None,
    )
    async def no_git_snapshot(_root: str):
        return None

    monkeypatch.setattr(routes_agent_runs, "read_git_snapshot", no_git_snapshot)
    env = await _create_coding_env(client, tmp_path)
    request_id = str(uuid4())
    payload = {
        "message": "保留这条任务对话",
        "client_request_id": request_id,
    }
    first = await _post_coding_run(client, env, **payload)
    assert first.status_code == 202, first.text
    replay = await _post_coding_run(client, env, **payload)
    assert replay.status_code == 202, replay.text
    assert replay.json()["id"] == first.json()["id"]

    messages = await client.get(f"/sessions/{env['session_id']}/messages")
    assert messages.status_code == 200
    matching = [
        item
        for item in messages.json()
        if item["role"] == "user" and item["content"] == payload["message"]
    ]
    assert len(matching) == 1
    detail = await client.get(f"/sessions/{env['session_id']}")
    assert detail.json()["last_run_id"] == first.json()["id"]

    await db.execute(
        delete(AgentRunRecord).where(AgentRunRecord.id == first.json()["id"])
    )
    await db.commit()
