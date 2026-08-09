"""v0.5.0 B4：只读 SQL 可信执行适配模块。

``query_readonly_sql``（契约见 ``agents/workflow_contracts.py``）只允许引用
用户已保存并启用的只读连接 profile。安全边界
（威胁清单 docs/releases/v0.5.0/v0.5.0-b0-contracts-20260809.md §4.4）：

- 模型不能提供 DSN/用户名/密码；密码只经 OS keyring 通道
  （``PA_SQL_PROFILES_SECRETS_JSON``）注入进程内存；
- **可靠解析（sqlglot AST）+ 数据库只读事务双重限制**：单语句强制；
  语句类型仅 SELECT/EXPLAIN/SHOW/DESCRIBE/WITH；AST 检查写操作、DDL、
  锁（FOR UPDATE/SHARE）、LOCK 语句、存储过程调用；只读事务内任何 DML
  都会被数据库拒绝（账号配置错误也不能绕过）；
- 查询超时（asyncio.wait_for + 关闭连接）与取消（CancellationToken）均可
  取消，无悬挂连接；
- 结果行数/字节数上限、疑似秘密列脱敏、大字段截断。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Mapping

import sqlglot
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.runtime import CancellationToken
from ..agents.tools import (
    ToolSpec,
    VersionedToolRegistry,
)
from ..agents.workflow_contracts import WORKFLOW_CONTRACT_BY_NAME
from .sql_profiles import (
    SqlProfileSecretResolver,
    SqlProfileService,
    is_sql_secret_reference,
    load_process_sql_secret_resolver,
)

_SQL_CONTRACT = WORKFLOW_CONTRACT_BY_NAME["query_readonly_sql"]

process_sql_secret_resolver: SqlProfileSecretResolver = (
    load_process_sql_secret_resolver()
)

_READ_ONLY_STATEMENT_TYPES = frozenset(
    {"SELECT", "EXPLAIN", "SHOW", "DESCRIBE", "DESC", "WITH"}
)
# 锁/危险节点在 AST 中必然出现的类型（保守拒绝）
_FORBIDDEN_EXPR_TYPES = frozenset(
    {
        "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT",
        "CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME",
        "GRANT", "REVOKE", "CALL", "COMMIT", "ROLLBACK",
        "LOCK", "UNLOCK", "USE", "SET", "LOAD", "INTO",
    }
)
_FORBIDDEN_KEYWORDS = frozenset(
    {"FOR UPDATE", "FOR SHARE", "LOCK IN SHARE MODE", "INTO OUTFILE", "LOAD DATA"}
)
# 疑似秘密列名（值替换为 [REDACTED]）
_SENSITIVE_COLUMN_NAMES = re.compile(
    r"(PASSWORD|PASSWD|SECRET|TOKEN|API[_-]?KEY|CREDENTIAL|PRIVATE_KEY)", re.IGNORECASE
)
_MAX_CELL_CHARS = 512
_MAX_ROWS_DEFAULT = 1000


class SqlWorkflowError(RuntimeError):
    """只读 SQL 执行错误。"""


def _parse_read_only_sql(query: str) -> str:
    """解析并校验单条只读 SQL，返回规范化语句类型（失败关闭）。"""
    if not query.strip():
        raise SqlWorkflowError("query 不能为空")
    if "\x00" in query:
        raise SqlWorkflowError("query 包含非法字符")
    try:
        statements = sqlglot.parse(query, read="mysql")
    except Exception as exc:  # noqa: BLE001 - 解析失败一律拒绝
        raise SqlWorkflowError(f"SQL 解析失败，已拒绝执行：{type(exc).__name__}") from exc
    if not statements:
        raise SqlWorkflowError("query 未解析出任何语句")
    if len(statements) > 1:
        raise SqlWorkflowError("多语句查询已拒绝（只允许单条只读语句）")
    statement = statements[0]
    if statement is None:
        raise SqlWorkflowError("query 未解析出有效语句")
    statement_type = type(statement).__name__.upper()
    if statement_type not in _READ_ONLY_STATEMENT_TYPES:
        raise SqlWorkflowError(
            f"语句类型 {statement_type} 不在只读白名单（SELECT/EXPLAIN/SHOW/DESCRIBE/WITH）"
        )
    # AST 遍历：拒绝任何写/锁/危险表达式节点
    for node in statement.walk():
        node_type = type(node).__name__.upper()
        if node_type in _FORBIDDEN_EXPR_TYPES:
            raise SqlWorkflowError(f"语句包含被禁止的节点：{node_type}")
    # 非表达式参数（如 SELECT ... FOR UPDATE 的 lock 参数）也检查
    for key, value in statement.args.items():
        if isinstance(value, str) and value.upper() in _FORBIDDEN_KEYWORDS:
            raise SqlWorkflowError(f"语句包含被禁止的关键字：{value}")
    return statement_type


def _redact_row(columns: list[str], row: tuple[Any, ...]) -> list[Any]:
    out: list[Any] = []
    for column, value in zip(columns, row):
        if _SENSITIVE_COLUMN_NAMES.search(str(column)):
            out.append("[REDACTED]")
            continue
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8", errors="replace")
        if isinstance(value, str) and len(value) > _MAX_CELL_CHARS:
            value = value[:_MAX_CELL_CHARS] + "…（字段已截断）"
        out.append(value)
    return out


async def _run_readonly_query(
    profile,
    password: str,
    query: str,
    params: Mapping[str, Any] | None,
    *,
    cancellation: CancellationToken,
    max_rows: int,
    max_bytes: int,
    timeout_ms: int,
) -> dict[str, Any]:
    import aiomysql

    if cancellation.is_cancelled:
        raise SqlWorkflowError("工具执行已取消")

    connect_args = dict(profile.connect_args_json or {})
    loop = asyncio.get_running_loop()
    started = loop.time()
    connection = None
    try:
        connection = await asyncio.wait_for(
            aiomysql.connect(
                host=profile.host,
                port=int(profile.port),
                user=profile.username or "",
                password=password,
                db=profile.database,
                autocommit=False,
                charset="utf8mb4",
                connect_timeout=min(10, timeout_ms / 1000),
                **connect_args,
            ),
            timeout=timeout_ms / 1000,
        )
    except asyncio.TimeoutError as exc:
        raise SqlWorkflowError("数据库连接超时") from exc
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)[:200] or type(exc).__name__
        raise SqlWorkflowError(f"数据库连接失败：{detail}") from exc

    try:
        async def _query() -> Any:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                # 只读事务：任何 DML 都会被数据库拒绝（双重限制兜底）
                await cursor.execute("START TRANSACTION READ ONLY")
                await cursor.execute(query, params)
                rows: list[dict[str, Any]] = []
                row_count = 0
                byte_budget = max_bytes
                truncated = False
                async for raw in cursor:
                    row_count += 1
                    if row_count > max_rows or byte_budget <= 0:
                        truncated = True
                        break
                    values = list(raw.values())
                    columns = list(raw.keys())
                    redacted = _redact_row(columns, values)
                    rows.append(redacted)
                    byte_budget -= sum(
                        len(str(value)) if value is not None else 4
                        for value in redacted
                    )
                columns = list(raw.keys()) if rows else (
                    [description[0] for description in cursor.description or []]
                )
                return rows, columns, row_count, truncated

        try:
            rows, columns, row_count, truncated = await asyncio.wait_for(
                _query(), timeout=timeout_ms / 1000
            )
        except asyncio.TimeoutError as exc:
            raise SqlWorkflowError("查询超时，连接已关闭") from exc
        finally:
            try:
                await connection.rollback()
            except Exception:  # noqa: BLE001 - 只读事务回滚失败不影响结论
                pass
    finally:
        connection.close()

    elapsed_ms = int((asyncio.get_running_loop().time() - started) * 1000)
    return {
        "profile_id": profile.id,
        "columns": columns,
        "rows": rows,
        "row_count": min(row_count, max_rows),
        "truncated": truncated,
        "elapsed_ms": elapsed_ms,
        "read_only_confirmed": True,
    }


async def query_readonly_sql_trusted(
    db: AsyncSession,
    profile_id: int,
    query: str,
    *,
    params: Mapping[str, Any] | None = None,
    max_rows: int | None = None,
    timeout_ms: int | None = None,
    cancellation: CancellationToken,
    resolver: SqlProfileSecretResolver | None = None,
) -> dict[str, Any]:
    """按已启用只读 profile 执行单条只读 SQL（解析 + 只读事务双重限制）。"""
    profile = await SqlProfileService(db).require_enabled(profile_id)
    statement_type = _parse_read_only_sql(query)
    reference = profile.password_secret_ref
    if not is_sql_secret_reference(reference):
        raise SqlWorkflowError("profile 密码引用格式无效，已拒绝执行")
    secret = (resolver or process_sql_secret_resolver).resolve(reference)
    if secret is None:
        raise SqlWorkflowError(f"keyring 密码不可用：{reference}")
    effective_rows = min(int(max_rows or _MAX_ROWS_DEFAULT), int(profile.max_rows))
    effective_timeout = min(
        int(timeout_ms or profile.timeout_ms), int(profile.timeout_ms)
    )
    result = await _run_readonly_query(
        profile,
        secret,
        query,
        params,
        cancellation=cancellation,
        max_rows=effective_rows,
        max_bytes=int(profile.max_bytes),
        timeout_ms=effective_timeout,
    )
    result["statement_type"] = statement_type
    return result


def build_sql_tool_registry(
    db: AsyncSession,
    *,
    legacy_registry=None,
    resolver: SqlProfileSecretResolver | None = None,
) -> VersionedToolRegistry:
    """Build the versioned registry containing the audited readonly SQL tool."""
    from .tools import default_registry

    source = legacy_registry or default_registry
    if source.get(_SQL_CONTRACT.name) is not None:
        raise RuntimeError(
            f"内建工具冲突：{_SQL_CONTRACT.name} 已存在于 legacy 注册表"
        )
    registry = VersionedToolRegistry()
    registry.register(_build_sql_tool_spec(db, resolver=resolver))
    return registry


def _build_sql_tool_spec(
    db: AsyncSession,
    *,
    resolver: SqlProfileSecretResolver | None = None,
) -> ToolSpec:
    async def execute(arguments: dict[str, Any], cancellation: CancellationToken) -> Any:
        return await query_readonly_sql_trusted(
            db,
            arguments["profile_id"],
            arguments["query"],
            params=arguments.get("params"),
            max_rows=arguments.get("max_rows"),
            timeout_ms=arguments.get("timeout_ms"),
            cancellation=cancellation,
            resolver=resolver,
        )

    return ToolSpec(
        name=_SQL_CONTRACT.name,
        version=_SQL_CONTRACT.version,
        description=_SQL_CONTRACT.description,
        input_schema=_SQL_CONTRACT.input_schema,
        output_schema=_SQL_CONTRACT.output_schema,
        risk_level=_SQL_CONTRACT.risk_level,
        required_capabilities=_SQL_CONTRACT.required_capabilities,
        timeout_ms=_SQL_CONTRACT.timeout_ms,
        max_input_bytes=_SQL_CONTRACT.max_input_bytes,
        max_output_bytes=_SQL_CONTRACT.max_output_bytes,
        idempotency=_SQL_CONTRACT.idempotency,
        supports_cancellation=_SQL_CONTRACT.supports_cancellation,
        redaction_policy=_SQL_CONTRACT.redaction_policy,
        executor=execute,
    )
