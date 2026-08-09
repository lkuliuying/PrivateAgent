"""v0.5.0 B4：只读 SQL connection profile 仓储与校验。

- 只保存非敏感连接元数据与 keyring 密码引用；明文密码只经
  ``PA_SQL_PROFILES_SECRETS_JSON`` 通道注入当前 sidecar 内存；
- dialect 仅支持 mysql（v0.5.0 正式支持面）；
- connect_args 只允许非敏感选项，键名命中敏感词即拒绝；
- 只读边界由 ``sql_workflow`` 的解析层 + 数据库只读事务双重限制。
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SqlReadonlyProfile

SQL_SECRET_REFERENCE_PATTERN = re.compile(
    r"^secret://os-keyring/sql/[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
    r"/[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
)
SQL_PROFILES_SECRETS_ENV = "PA_SQL_PROFILES_SECRETS_JSON"

_ALLOWED_DIALECTS = frozenset({"mysql"})
_SENSITIVE_OPTION_NAMES = re.compile(
    r"(PASSWORD|PASSWD|SECRET|TOKEN|API[_-]?KEY|CREDENTIAL)", re.IGNORECASE
)


class SqlProfileError(ValueError):
    """SQL profile 配置/查询错误。"""


class SqlProfileNotFound(SqlProfileError):
    pass


class SqlProfileDisabled(SqlProfileError):
    pass


class SqlProfileConflict(SqlProfileError):
    pass


class SqlProfileSecretResolver(Protocol):
    def resolve(self, reference: str) -> str | None: ...


class MappingSqlSecretResolver:
    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = dict(secrets)

    def resolve(self, reference: str) -> str | None:
        return self._secrets.get(reference)


def is_sql_secret_reference(value: str) -> bool:
    return bool(SQL_SECRET_REFERENCE_PATTERN.fullmatch(value))


def load_process_sql_secret_resolver(
    environ: dict[str, str] | None = None,
) -> SqlProfileSecretResolver:
    """一次性消费启动环境中的 SQL profile 密码通道（引用→明文 map）。"""
    source = dict(environ) if environ is not None else __import__("os").environ
    raw = source.pop(SQL_PROFILES_SECRETS_ENV, "")
    if not raw:
        return MappingSqlSecretResolver({})
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return MappingSqlSecretResolver({})
    secrets: dict[str, str] = {}
    if not isinstance(parsed, dict) or len(parsed) > 32:
        return MappingSqlSecretResolver({})
    for reference, value in parsed.items():
        if not isinstance(reference, str) or not is_sql_secret_reference(reference):
            return MappingSqlSecretResolver({})
        if not isinstance(value, str) or not value or len(value) > 8_192:
            return MappingSqlSecretResolver({})
        if "\x00" in value:
            return MappingSqlSecretResolver({})
        secrets[reference] = value
    return MappingSqlSecretResolver(secrets)


class SqlProfileRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        name: str,
        dialect: str,
        host: str,
        port: int,
        database: str,
        username: str | None,
        password_secret_ref: str,
        connect_args: dict[str, Any] | None,
        max_rows: int,
        max_bytes: int,
        timeout_ms: int,
        enabled: bool,
    ) -> SqlReadonlyProfile:
        existing = (
            await self.db.execute(
                select(SqlReadonlyProfile.id).where(SqlReadonlyProfile.name == name)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise SqlProfileConflict(f"SQL profile 名称已存在: {name}")
        profile = SqlReadonlyProfile(
            name=name,
            dialect=dialect,
            host=host,
            port=port,
            database=database,
            username=username,
            password_secret_ref=password_secret_ref,
            connect_args_json=connect_args,
            max_rows=max_rows,
            max_bytes=max_bytes,
            timeout_ms=timeout_ms,
            enabled=enabled,
        )
        self.db.add(profile)
        await self.db.commit()
        await self.db.refresh(profile)
        return profile

    async def get(self, profile_id: int) -> SqlReadonlyProfile | None:
        return await self.db.get(SqlReadonlyProfile, profile_id)

    async def list(self, *, enabled_only: bool = False) -> list[SqlReadonlyProfile]:
        stmt = select(SqlReadonlyProfile).order_by(SqlReadonlyProfile.name.asc())
        if enabled_only:
            stmt = stmt.where(SqlReadonlyProfile.enabled.is_(True))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(self, profile_id: int, **values: Any) -> SqlReadonlyProfile:
        profile = await self.get(profile_id)
        if profile is None:
            raise SqlProfileNotFound(f"SQL profile 不存在: {profile_id}")
        for key, value in values.items():
            if value is not None:
                setattr(profile, key, value)
        profile.version = profile.version + 1
        await self.db.commit()
        await self.db.refresh(profile)
        return profile

    async def delete(self, profile_id: int) -> None:
        profile = await self.get(profile_id)
        if profile is None:
            raise SqlProfileNotFound(f"SQL profile 不存在: {profile_id}")
        await self.db.delete(profile)
        await self.db.commit()


def _validate_connect_args(connect_args: dict[str, Any] | None) -> None:
    for key in (connect_args or {}):
        if _SENSITIVE_OPTION_NAMES.search(key):
            raise SqlProfileError(f"connect_args 不允许敏感选项: {key}")
        if not isinstance(key, str) or len(key) > 128:
            raise SqlProfileError("connect_args 键名无效")


class SqlProfileService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = SqlProfileRepository(db)

    async def create(self, payload: dict[str, Any]) -> SqlReadonlyProfile:
        dialect = payload["dialect"].lower()
        if dialect not in _ALLOWED_DIALECTS:
            raise SqlProfileError(f"v0.5.0 仅支持 mysql dialect：{dialect}")
        host = payload["host"].strip()
        if not host or len(host) > 255:
            raise SqlProfileError("host 无效")
        if not 1 <= int(payload["port"]) <= 65_535:
            raise SqlProfileError("port 无效")
        if not payload.get("database") or len(payload["database"]) > 255:
            raise SqlProfileError("database 无效")
        reference = payload.get("password_secret_ref") or ""
        if not is_sql_secret_reference(reference):
            raise SqlProfileError("password_secret_ref 必须是 OS keyring 引用")
        _validate_connect_args(payload.get("connect_args"))
        max_rows = int(payload.get("max_rows", 1000))
        max_bytes = int(payload.get("max_bytes", 1_048_576))
        timeout_ms = int(payload.get("timeout_ms", 30_000))
        if not 1 <= max_rows <= 100_000:
            raise SqlProfileError("max_rows 必须在 1..100000")
        if not 1_024 <= max_bytes <= 8 * 1_048_576:
            raise SqlProfileError("max_bytes 必须在 1KB..8MB")
        if not 1_000 <= timeout_ms <= 60_000:
            raise SqlProfileError("timeout_ms 必须在 1000..60000")
        return await self.repo.create(
            name=payload["name"],
            dialect=dialect,
            host=host,
            port=payload["port"],
            database=payload["database"],
            username=payload.get("username"),
            password_secret_ref=reference,
            connect_args=payload.get("connect_args"),
            max_rows=max_rows,
            max_bytes=max_bytes,
            timeout_ms=timeout_ms,
            enabled=payload.get("enabled", False),
        )

    async def require_enabled(self, profile_id: int) -> SqlReadonlyProfile:
        profile = await self.repo.get(profile_id)
        if profile is None:
            raise SqlProfileNotFound(f"SQL profile 不存在: {profile_id}")
        if not profile.enabled:
            raise SqlProfileDisabled(f"SQL profile 已禁用: {profile.name}")
        return profile
