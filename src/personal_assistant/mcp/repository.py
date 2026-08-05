"""SQL repository for MCP servers, discovery cache, and metadata-only call audit."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from personal_assistant.core.models import McpCallLog, McpServer
from personal_assistant.core.timeutil import utcnow

from .contracts import McpDiscovery, McpServerConfig, McpTransport


def server_config(record: McpServer) -> McpServerConfig:
    return McpServerConfig(
        id=record.id,
        name=record.name,
        transport=McpTransport(record.transport),
        command=record.command,
        args=tuple(record.args_json or ()),
        working_directory=record.working_directory,
        url=record.url,
        env=dict(record.env_json or {}),
        secret_refs=dict(record.secret_refs_json or {}),
        allow_insecure_local=record.allow_insecure_local,
        allow_private_network=record.allow_private_network,
        trusted=record.trusted,
        enabled=record.enabled,
        allowed_tools=frozenset(record.allowed_tools_json or ()),
        timeout_ms=record.timeout_ms,
        max_output_bytes=record.max_output_bytes,
    )


class McpRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, config: McpServerConfig) -> McpServer:
        record = McpServer(
            id=config.id,
            name=config.name,
            transport=config.transport.value,
            command=config.command,
            args_json=list(config.args),
            working_directory=config.working_directory,
            url=config.url,
            env_json=dict(config.env or {}),
            secret_refs_json=dict(config.secret_refs or {}),
            allow_insecure_local=config.allow_insecure_local,
            allow_private_network=config.allow_private_network,
            trusted=config.trusted,
            enabled=config.enabled,
            allowed_tools_json=sorted(config.allowed_tools),
            timeout_ms=config.timeout_ms,
            max_output_bytes=config.max_output_bytes,
            status="disconnected" if config.enabled else "disabled",
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def replace(self, record: McpServer, config: McpServerConfig) -> McpServer:
        record.name = config.name
        record.transport = config.transport.value
        record.command = config.command
        record.args_json = list(config.args)
        record.working_directory = config.working_directory
        record.url = config.url
        record.env_json = dict(config.env or {})
        record.secret_refs_json = dict(config.secret_refs or {})
        record.allow_insecure_local = config.allow_insecure_local
        record.allow_private_network = config.allow_private_network
        record.trusted = config.trusted
        record.enabled = config.enabled
        record.allowed_tools_json = sorted(config.allowed_tools)
        record.timeout_ms = config.timeout_ms
        record.max_output_bytes = config.max_output_bytes
        record.status = "disconnected" if config.enabled else "disabled"
        record.last_error_code = None
        record.discovery_tools_json = None
        record.discovery_resources_json = None
        record.discovery_prompts_json = None
        record.discovery_sha256 = None
        record.discovered_at = None
        record.updated_at = utcnow()
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def get(self, server_id: str) -> McpServer | None:
        return await self.db.get(McpServer, server_id)

    async def list(self) -> list[McpServer]:
        statement = select(McpServer).order_by(McpServer.created_at.asc())
        return list((await self.db.execute(statement)).scalars().all())

    async def list_active(self) -> list[McpServer]:
        statement = (
            select(McpServer)
            .where(McpServer.enabled.is_(True), McpServer.trusted.is_(True))
            .order_by(McpServer.created_at.asc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def delete(self, record: McpServer) -> None:
        await self.db.delete(record)
        await self.db.commit()

    async def update_state(
        self,
        record: McpServer,
        *,
        trusted: bool,
        enabled: bool,
        allowed_tools: frozenset[str],
    ) -> McpServer:
        """Update trust/activation without round-tripping hidden secret values."""

        record.trusted = trusted
        record.enabled = enabled
        record.allowed_tools_json = sorted(allowed_tools)
        if not enabled:
            record.status = "disabled"
        elif record.status == "disabled":
            record.status = "disconnected"
        record.updated_at = utcnow()
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def save_discovery(self, record: McpServer, discovery: McpDiscovery) -> McpServer:
        now = utcnow()
        record.discovery_tools_json = list(discovery.tools)
        record.discovery_resources_json = list(discovery.resources)
        record.discovery_prompts_json = list(discovery.prompts)
        record.discovery_sha256 = discovery.sha256
        record.status = "healthy"
        record.last_error_code = None
        record.last_checked_at = now
        record.discovered_at = now
        record.updated_at = now
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def mark_failure(self, record: McpServer, *, error_code: str) -> None:
        now = utcnow()
        record.status = "error"
        record.last_error_code = error_code[:64]
        record.last_checked_at = now
        record.updated_at = now
        await self.db.commit()

    async def log_call(
        self,
        *,
        server_id: str,
        run_id: str | None,
        tool_name: str,
        request_sha256: str,
        status: str,
        error_code: str | None,
        duration_ms: int,
        output_bytes: int,
    ) -> McpCallLog:
        record = McpCallLog(
            server_id=server_id,
            run_id=run_id,
            tool_name=tool_name[:128],
            request_sha256=request_sha256,
            status=status[:32],
            error_code=error_code[:64] if error_code else None,
            duration_ms=max(0, min(duration_ms, 2_147_483_647)),
            output_bytes=max(0, min(output_bytes, 2_147_483_647)),
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def list_calls(self, server_id: str, *, limit: int = 100) -> list[McpCallLog]:
        statement = (
            select(McpCallLog)
            .where(McpCallLog.server_id == server_id)
            .order_by(McpCallLog.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
        return list((await self.db.execute(statement)).scalars().all())
