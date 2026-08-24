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
from personal_assistant.core.executable_intent import detect_executable_intent
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


def _verifier(executions: list[dict], *, minimum: int):
    async def loader() -> WorkflowCompletionFacts:
        return WorkflowCompletionFacts(executions=executions)

    # max_failed_tools 放宽：隔离验证最小证据门槛（诊断命令失败也是证据，
    # 与 run 创建链注入口径一致）。
    return WorkflowCompletionOutputVerifier(
        loader, min_tool_executions=minimum, max_failed_tools=16
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
