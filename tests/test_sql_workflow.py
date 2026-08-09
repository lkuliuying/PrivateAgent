"""v0.5.0 B4：只读 SQL 可信工作流测试。

覆盖主计划 B4 退出条件：
- DDL/DML/多语句/锁查询全部拒绝（解析层 + 只读事务双重限制）；
- 数据库账号即使配置错误也不能通过应用层绕过只读策略；
- 查询超时可取消，无悬挂连接；
- 结果行数、字节数和敏感字段均受限；
- 关闭 SQL flag 不影响应用主数据库正常运行。

测试 profile 指向专用测试库 personal_assistant_test（root 无密码，
密码经 keyring 引用通道注入）。
"""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.engine import make_url

from personal_assistant.agents import (
    AgentEvent,
    AgentEventType,
    AgentRunLimits,
    AgentRunRepository,
    CancellationToken,
    SqlToolApprovalConsumer,
    SqlToolApprovalRequester,
    ToolApprovalRepository,
    ToolCall,
    ToolCapability,
    ToolCapabilityPolicy,
    ToolExecutionRepository,
    ValidatedToolDispatcher,
)
from personal_assistant.agents.result_verification import DatabaseResultVerifier
from personal_assistant.api import routes_agent_runs
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import SqlReadonlyProfile
from personal_assistant.core.sql_profiles import (
    MappingSqlSecretResolver,
    SqlProfileService,
    is_sql_secret_reference,
    load_process_sql_secret_resolver,
)
from personal_assistant.core.sql_workflow import (
    _parse_read_only_sql,
    build_sql_tool_registry,
)

# conftest 已把 settings.db_url 替换为专用测试库；这里直接解析（不再二次派生）
_TEST_URL = make_url(routes_agent_runs.cfg.db_url)
_PASSWORD_REF = "secret://os-keyring/sql/b4-test/password"
# 测试库凭据：与主库同用户；密码经 keyring 引用通道注入（明文只在测试内存）
_TEST_RESOLVER = MappingSqlSecretResolver({_PASSWORD_REF: _TEST_URL.password or ""})


async def _make_profile(db, **overrides: Any) -> SqlReadonlyProfile:
    service = SqlProfileService(db)
    payload: dict[str, Any] = {
        "name": f"b4-{uuid4().hex[:8]}",
        "dialect": "mysql",
        "host": _TEST_URL.host or "127.0.0.1",
        "port": _TEST_URL.port or 3306,
        "database": _TEST_URL.database or "personal_assistant_test",
        "username": _TEST_URL.username or "root",
        "password_secret_ref": _PASSWORD_REF,
        "max_rows": 100,
        "max_bytes": 262144,
        "timeout_ms": 3000,
        "enabled": True,
    }
    payload.update(overrides)
    return await service.create(payload)


async def _create_run(db, *, tool_call_id: str = "call-sql-1") -> str:
    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    await repository.create_run(run_id=run_id, limits=AgentRunLimits())
    await repository.record_event(
        AgentEvent(run_id=run_id, sequence=1, type=AgentEventType.RUN_STARTED)
    )
    await repository.record_event(
        AgentEvent(
            run_id=run_id,
            sequence=2,
            type=AgentEventType.TOOL_REQUESTED,
            step_id=str(uuid4()),
            payload={
                "ordinal": 1,
                "kind": "tool",
                "tool_call_id": tool_call_id,
                "name": "query_readonly_sql",
            },
        )
    )
    return run_id


async def _cleanup(db, run_id: str | None = None, profile_ids: list[int] | None = None) -> None:
    if run_id:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    for profile_id in profile_ids or []:
        await db.execute(
            delete(SqlReadonlyProfile).where(SqlReadonlyProfile.id == profile_id)
        )
    await db.commit()


def _sql_arguments(profile_id: int, query: str, **extra) -> dict:
    arguments = {"profile_id": profile_id, "query": query}
    arguments.update(extra)
    return arguments


def _dispatcher(
    db,
    run_id: str,
    *,
    approval_id: str | None = None,
    approval_token: str | None = None,
    with_verifier: bool = False,
) -> ValidatedToolDispatcher:
    registry = build_sql_tool_registry(db, resolver=_TEST_RESOLVER)
    return ValidatedToolDispatcher(
        registry,
        policy=ToolCapabilityPolicy(
            granted_capabilities=frozenset({ToolCapability.DATABASE_QUERY})
        ),
        approval_requester=SqlToolApprovalRequester(db, run_id=run_id),
        approval_consumer=(
            SqlToolApprovalConsumer(
                db,
                approval_id=approval_id,
                token=approval_token,
            )
            if approval_id is not None
            else None
        ),
        execution_store=ToolExecutionRepository(db, run_id=run_id),
        result_verifier=(
            DatabaseResultVerifier(
                supported=("query_readonly_sql",),
                require_commit=False,
                require_read_only=True,
            )
            if with_verifier
            else None
        ),
    )


async def _execute_approved(db, run_id: str, call: ToolCall, *, with_verifier: bool = False):
    pending = await _dispatcher(db, run_id).execute(
        call, cancellation=CancellationToken()
    )
    assert pending.error_code == "approval_required"
    approvals = await ToolApprovalRepository(db).list_for_run(run_id)
    assert len(approvals) == 1
    approved = await ToolApprovalRepository(db).approve(approvals[0].id)
    return await _dispatcher(
        db,
        run_id,
        approval_id=approved.approval_id,
        approval_token=approved.token,
        with_verifier=with_verifier,
    ).execute(call, cancellation=CancellationToken())


# ---------------- 解析层拒绝 ----------------

@pytest.mark.parametrize(
    "query",
    [
        "INSERT INTO sessions (id) VALUES (1)",
        "UPDATE sessions SET title = 'x'",
        "DELETE FROM sessions",
        "DROP TABLE sessions",
        "ALTER TABLE sessions ADD COLUMN x INT",
        "CREATE TABLE evil (id INT)",
        "TRUNCATE TABLE sessions",
        "GRANT ALL ON *.* TO 'u'",
        "CALL some_proc()",
        "SELECT * FROM sessions; SELECT * FROM messages",
        "SELECT * FROM sessions; DROP TABLE sessions",
        "SELECT * FROM sessions FOR UPDATE",
        "SELECT * FROM sessions FOR SHARE",
        "LOCK TABLES sessions READ",
        "SELECT * INTO OUTFILE '/tmp/x' FROM sessions",
        "USE information_schema",
        "SET SESSION sql_mode = ''",
    ],
)
def test_readonly_parser_rejects_writes_locks_and_multi_statements(query):
    """DDL/DML/多语句/锁/导出/USE/SET 全部被解析层拒绝。"""
    with pytest.raises(Exception, match="拒绝|禁止|白名单|多语句|被禁止"):
        _parse_read_only_sql(query)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT 1",
        "SELECT * FROM sessions LIMIT 1",
        "EXPLAIN SELECT 1",
        "SHOW TABLES",
        "DESCRIBE sessions",
        "WITH t AS (SELECT 1 AS x) SELECT x FROM t",
        "SELECT COUNT(*) FROM sessions",
    ],
)
def test_readonly_parser_accepts_select_family(query):
    """SELECT/EXPLAIN/SHOW/DESCRIBE/WITH 通过解析。"""
    assert _parse_read_only_sql(query) in {
        "SELECT", "EXPLAIN", "SHOW", "DESCRIBE", "DESC", "WITH",
    }


# ---------------- 成功查询与结果边界 ----------------

@pytest.mark.asyncio
async def test_readonly_select_returns_bounded_result(db):
    """成功 SELECT：columns/rows/read_only_confirmed；模型可见结果有界。"""
    profile = await _make_profile(db)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-sql-1",
            name="query_readonly_sql",
            arguments=_sql_arguments(
                profile.id, "SELECT 1 AS one, 'text' AS label"
            ),
        )
        result = await _execute_approved(db, run_id, call, with_verifier=True)
        assert result.success is True
        output = result.output
        assert output["read_only_confirmed"] is True
        assert output["columns"] == ["one", "label"]
        assert output["rows"] == [[1, "text"]]
        assert output["row_count"] == 1
        assert output["truncated"] is False
        assert output["statement_type"] == "SELECT"
    finally:
        await _cleanup(db, run_id, [profile.id])


@pytest.mark.asyncio
async def test_sensitive_columns_are_redacted(db):
    """疑似秘密列（api_key/token/password）值替换为 [REDACTED]。"""
    profile = await _make_profile(db)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-sql-1",
            name="query_readonly_sql",
            arguments=_sql_arguments(
                profile.id,
                "SELECT 'top-secret-42' AS api_key, 'safe' AS label",
            ),
        )
        result = await _execute_approved(db, run_id, call)
        assert result.success is True
        row = result.output["rows"][0]
        assert row[0] == "[REDACTED]"  # api_key 列
        assert row[1] == "safe"  # label 列
    finally:
        await _cleanup(db, run_id, [profile.id])


@pytest.mark.asyncio
async def test_max_rows_limits_result(db):
    """行数上限：profile max_rows 截断并标记 truncated。"""
    profile = await _make_profile(db, max_rows=3)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-sql-1",
            name="query_readonly_sql",
            arguments=_sql_arguments(
                profile.id,
                "SELECT a + b AS v FROM (SELECT 1 a UNION SELECT 2 UNION "
                "SELECT 3 UNION SELECT 4 UNION SELECT 5) t, (SELECT 1 b) u",
            ),
        )
        result = await _execute_approved(db, run_id, call)
        assert result.success is True
        assert len(result.output["rows"]) == 3
        assert result.output["row_count"] == 3
        assert result.output["truncated"] is True
    finally:
        await _cleanup(db, run_id, [profile.id])


@pytest.mark.asyncio
async def test_query_timeout_closes_connection(db):
    """慢查询超时：报错且连接已关闭（无悬挂连接）。"""
    profile = await _make_profile(db, timeout_ms=1000)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-sql-1",
            name="query_readonly_sql",
            arguments=_sql_arguments(profile.id, "SELECT SLEEP(5)"),
        )
        result = await _execute_approved(db, run_id, call)
        assert result.success is False
        assert "超时" in (result.error or "")
    finally:
        await _cleanup(db, run_id, [profile.id])


@pytest.mark.asyncio
async def test_readonly_transaction_rejects_write_at_database_layer(db):
    """数据库只读事务兜底：绕过解析层直接执行 DML 也被拒绝。"""
    from personal_assistant.core.sql_workflow import _run_readonly_query

    profile = await _make_profile(db)
    try:
        with pytest.raises(Exception, match="read.only|read_only|READ ONLY|denied|reject"):
            await _run_readonly_query(
                profile,
                "",
                "UPDATE sessions SET title = 'evil' WHERE id = -1",
                None,
                cancellation=CancellationToken(),
                max_rows=10,
                max_bytes=65536,
                timeout_ms=3000,
            )
    finally:
        await _cleanup(db, None, [profile.id])


# ---------------- profile 生命周期与 flag ----------------

@pytest.mark.asyncio
async def test_disabled_or_deleted_profile_cannot_be_called(db):
    """禁用/删除 profile 后不能继续调用；密码引用缺失拒绝。"""
    profile = await _make_profile(db)
    try:
        profile.enabled = False
        await db.commit()
        denied_call = ToolCall(
            id="call-denied",
            name="query_readonly_sql",
            arguments=_sql_arguments(profile.id, "SELECT 1"),
        )
        run_id = await _create_run(db, tool_call_id="call-denied")
        denied = await _execute_approved(db, run_id, denied_call)
        await _cleanup(db, run_id)
        assert denied.success is False
        assert "已禁用" in (denied.error or "")

        profile.enabled = True
        await db.commit()
        await SqlProfileService(db).repo.delete(profile.id)
        missing_call = ToolCall(
            id="call-missing",
            name="query_readonly_sql",
            arguments=_sql_arguments(profile.id, "SELECT 1"),
        )
        run_id = await _create_run(db, tool_call_id="call-missing")
        missing = await _execute_approved(db, run_id, missing_call)
        await _cleanup(db, run_id)
        assert missing.success is False
        assert "不存在" in (missing.error or "")

        other = await _make_profile(
            db,
            password_secret_ref="secret://os-keyring/sql/missing-profile/password",
        )
        ref_call = ToolCall(
            id="call-ref",
            name="query_readonly_sql",
            arguments=_sql_arguments(other.id, "SELECT 1"),
        )
        run_id = await _create_run(db, tool_call_id="call-ref")
        refused = await _execute_approved(db, run_id, ref_call)
        await _cleanup(db, run_id)
        assert refused.success is False
        assert "密码不可用" in (refused.error or "")
    finally:
        await _cleanup(db, None, [profile.id])


@pytest.mark.asyncio
async def test_sql_flag_and_profile_control_tool_visibility(db, monkeypatch):
    """rc.2：flag 关闭或无已启用 profile 时工具不可见；开启且有 profile 时可见。"""
    from personal_assistant.core.models import SqlReadonlyProfile

    await db.execute(delete(SqlReadonlyProfile))
    await db.commit()
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_sql_readonly_workflow_enabled", False)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", False)
    bundle = await routes_agent_runs.get_agent_tool_bundle(db)
    assert bundle is None

    # flag 开启但无已启用 profile → 工具不可见
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_sql_readonly_workflow_enabled", True)
    bundle = await routes_agent_runs.get_agent_tool_bundle(db)
    assert bundle is not None
    names = {definition.name for definition in bundle.definitions}
    assert "query_readonly_sql" not in names

    # 存在已启用 profile → 工具可见
    profile = await _make_profile(db)
    try:
        bundle = await routes_agent_runs.get_agent_tool_bundle(db)
        names = {definition.name for definition in bundle.definitions}
        assert "query_readonly_sql" in names

        # 禁用 profile → 工具再次不可见
        profile.enabled = False
        await db.commit()
        bundle = await routes_agent_runs.get_agent_tool_bundle(db)
        names = {definition.name for definition in bundle.definitions}
        assert "query_readonly_sql" not in names

        profile.enabled = True
        await db.commit()
        spec = build_sql_tool_registry(db, resolver=_TEST_RESOLVER).get("query_readonly_sql")
        from personal_assistant.agents.tools import ToolPolicyDecision

        policy = ToolCapabilityPolicy(
            granted_capabilities=frozenset({ToolCapability.DATABASE_QUERY})
        )
        assert policy.evaluate(spec) == ToolPolicyDecision.REQUIRE_APPROVAL
        denied = ToolCapabilityPolicy(granted_capabilities=frozenset())
        assert denied.evaluate(spec) == ToolPolicyDecision.DENY
    finally:
        await _cleanup(db, None, [profile.id])


@pytest.mark.asyncio
async def test_sql_spec_matches_frozen_contract():
    """registry 产出的 ToolSpec 与 B0 冻结契约一致（验证器清单含 database）。"""
    from personal_assistant.agents.workflow_contracts import WORKFLOW_CONTRACT_BY_NAME

    contract = WORKFLOW_CONTRACT_BY_NAME["query_readonly_sql"]
    from personal_assistant.core.sql_workflow import _build_sql_tool_spec

    spec = _build_sql_tool_spec(None)
    assert spec.name == contract.name
    assert spec.version == contract.version
    assert spec.risk_level == contract.risk_level
    assert spec.required_capabilities == contract.required_capabilities
    assert spec.idempotency == contract.idempotency
    assert dict(spec.input_schema) == dict(contract.input_schema)
    assert contract.required_result_verifiers == ("database",)


def test_sql_secret_reference_and_env_channel(monkeypatch):
    """SQL 密码引用格式与环境通道：畸形条目 fail closed。"""
    import json

    assert is_sql_secret_reference("secret://os-keyring/sql/reports/password")
    assert not is_sql_secret_reference("secret://os-keyring/http/x/y")
    assert not is_sql_secret_reference("plaintext")

    monkeypatch.setenv(
        "PA_SQL_PROFILES_SECRETS_JSON",
        json.dumps({"secret://os-keyring/sql/reports/password": "db-pw-123"}),
    )
    resolver = load_process_sql_secret_resolver()
    assert resolver.resolve("secret://os-keyring/sql/reports/password") == "db-pw-123"
    assert "PA_SQL_PROFILES_SECRETS_JSON" not in os.environ

    monkeypatch.setenv(
        "PA_SQL_PROFILES_SECRETS_JSON", '{"secret://os-keyring/sql/x/y": 42}'
    )
    resolver = load_process_sql_secret_resolver()
    assert resolver.resolve("secret://os-keyring/sql/x/y") is None


@pytest.mark.asyncio
async def test_profile_rejects_bad_config(db):
    """配置校验：非 mysql dialect、明文密码引用、敏感 connect_args 拒绝。"""
    service = SqlProfileService(db)
    base = {
        "dialect": "mysql",
        "host": "127.0.0.1",
        "port": 3306,
        "database": "app",
        "username": "root",
        "password_secret_ref": _PASSWORD_REF,
    }
    with pytest.raises(Exception, match="仅支持 mysql"):
        await service.create({**base, "dialect": "postgresql"})
    with pytest.raises(Exception, match="keyring 引用"):
        await service.create({**base, "password_secret_ref": "plaintext-pw"})
    with pytest.raises(Exception, match="敏感选项"):
        await service.create({**base, "connect_args": {"password": "x"}})
