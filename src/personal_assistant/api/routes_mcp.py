"""Default-off management API for trusted MCP client connections."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from personal_assistant.config import settings
from personal_assistant.core.db import get_session
from personal_assistant.core.models import McpCallLog, McpServer
from personal_assistant.mcp import McpClientError, McpManager, McpRepository
from personal_assistant.mcp.contracts import McpServerConfig, McpTransport
from personal_assistant.mcp.repository import server_config
from personal_assistant.mcp.validation import (
    UnsafeMcpConfigurationError,
    validate_mcp_config,
)

router = APIRouter(prefix="/mcp", tags=["mcp"])


def require_mcp_api() -> None:
    if not settings.mcp_enabled:
        raise HTTPException(status_code=404, detail="Not found")


class McpServerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    transport: McpTransport
    command: str | None = Field(default=None, max_length=2_048)
    args: list[str] = Field(default_factory=list, max_length=64)
    working_directory: str | None = Field(default=None, max_length=2_048)
    url: str | None = Field(default=None, max_length=2_048)
    env: dict[str, str] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    allow_insecure_local: bool = False
    allow_private_network: bool = False
    trusted: bool = False
    enabled: bool = False
    allowed_tools: list[str] = Field(default_factory=list, max_length=512)
    timeout_ms: int = Field(default=30_000, ge=100, le=600_000)
    max_output_bytes: int = Field(
        default=256 * 1024, ge=128, le=10 * 1024 * 1024
    )

    def to_config(self, server_id: str) -> McpServerConfig:
        return McpServerConfig(
            id=server_id,
            name=self.name,
            transport=self.transport,
            command=self.command,
            args=tuple(self.args),
            working_directory=self.working_directory,
            url=self.url,
            env=dict(self.env),
            secret_refs=dict(self.secret_refs),
            allow_insecure_local=self.allow_insecure_local,
            allow_private_network=self.allow_private_network,
            trusted=self.trusted,
            enabled=self.enabled,
            allowed_tools=frozenset(self.allowed_tools),
            timeout_ms=self.timeout_ms,
            max_output_bytes=self.max_output_bytes,
        )


class McpServerResponse(BaseModel):
    id: str
    name: str
    transport: str
    command: str | None
    args: list[str]
    working_directory: str | None
    url: str | None
    env_names: list[str]
    secret_ref_names: list[str]
    allow_insecure_local: bool
    allow_private_network: bool
    trusted: bool
    enabled: bool
    allowed_tools: list[str]
    timeout_ms: int
    max_output_bytes: int
    status: str
    last_error_code: str | None
    tools: list[dict]
    resources: list[dict]
    prompts: list[dict]
    discovery_sha256: str | None
    last_checked_at: datetime | None
    discovered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class McpCallLogResponse(BaseModel):
    id: int
    run_id: str | None
    tool_name: str
    request_sha256: str
    status: str
    error_code: str | None
    duration_ms: int
    output_bytes: int
    created_at: datetime


class McpServerStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trusted: bool
    enabled: bool
    allowed_tools: list[str] = Field(default_factory=list, max_length=512)


def _server_response(record: McpServer) -> McpServerResponse:
    return McpServerResponse(
        id=record.id,
        name=record.name,
        transport=record.transport,
        command=record.command,
        args=list(record.args_json or []),
        working_directory=record.working_directory,
        url=record.url,
        env_names=sorted((record.env_json or {}).keys()),
        secret_ref_names=sorted((record.secret_refs_json or {}).keys()),
        allow_insecure_local=record.allow_insecure_local,
        allow_private_network=record.allow_private_network,
        trusted=record.trusted,
        enabled=record.enabled,
        allowed_tools=list(record.allowed_tools_json or []),
        timeout_ms=record.timeout_ms,
        max_output_bytes=record.max_output_bytes,
        status=record.status,
        last_error_code=record.last_error_code,
        tools=list(record.discovery_tools_json or []),
        resources=list(record.discovery_resources_json or []),
        prompts=list(record.discovery_prompts_json or []),
        discovery_sha256=record.discovery_sha256,
        last_checked_at=record.last_checked_at,
        discovered_at=record.discovered_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _call_response(record: McpCallLog) -> McpCallLogResponse:
    return McpCallLogResponse(
        id=record.id,
        run_id=record.run_id,
        tool_name=record.tool_name,
        request_sha256=record.request_sha256,
        status=record.status,
        error_code=record.error_code,
        duration_ms=record.duration_ms,
        output_bytes=record.output_bytes,
        created_at=record.created_at,
    )


async def _get_server(repository: McpRepository, server_id: str) -> McpServer:
    record = await repository.get(server_id)
    if record is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return record


@router.get(
    "/servers",
    response_model=list[McpServerResponse],
    dependencies=[Depends(require_mcp_api)],
)
async def list_mcp_servers(db: AsyncSession = Depends(get_session)):
    return [_server_response(record) for record in await McpRepository(db).list()]


@router.post(
    "/servers",
    response_model=McpServerResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_mcp_api)],
)
async def create_mcp_server(
    body: McpServerRequest,
    db: AsyncSession = Depends(get_session),
):
    config = body.to_config(str(uuid4()))
    try:
        validate_mcp_config(config)
        record = await McpRepository(db).create(config)
    except UnsafeMcpConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="MCP server name already exists") from exc
    return _server_response(record)


@router.put(
    "/servers/{server_id}",
    response_model=McpServerResponse,
    dependencies=[Depends(require_mcp_api)],
)
async def replace_mcp_server(
    server_id: str,
    body: McpServerRequest,
    db: AsyncSession = Depends(get_session),
):
    repository = McpRepository(db)
    record = await _get_server(repository, server_id)
    config = body.to_config(server_id)
    try:
        validate_mcp_config(config)
        record = await repository.replace(record, config)
    except UnsafeMcpConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="MCP server name already exists") from exc
    return _server_response(record)


@router.patch(
    "/servers/{server_id}/state",
    response_model=McpServerResponse,
    dependencies=[Depends(require_mcp_api)],
)
async def update_mcp_server_state(
    server_id: str,
    body: McpServerStateRequest,
    db: AsyncSession = Depends(get_session),
):
    repository = McpRepository(db)
    record = await _get_server(repository, server_id)
    config = replace(
        server_config(record),
        trusted=body.trusted,
        enabled=body.enabled,
        allowed_tools=frozenset(body.allowed_tools),
    )
    try:
        validate_mcp_config(config)
    except UnsafeMcpConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record = await repository.update_state(
        record,
        trusted=config.trusted,
        enabled=config.enabled,
        allowed_tools=config.allowed_tools,
    )
    return _server_response(record)


@router.delete(
    "/servers/{server_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_mcp_api)],
)
async def delete_mcp_server(server_id: str, db: AsyncSession = Depends(get_session)):
    repository = McpRepository(db)
    record = await _get_server(repository, server_id)
    await repository.delete(record)


@router.post(
    "/servers/{server_id}/discover",
    response_model=McpServerResponse,
    dependencies=[Depends(require_mcp_api)],
)
async def discover_mcp_server(
    server_id: str,
    db: AsyncSession = Depends(get_session),
):
    repository = McpRepository(db)
    record = await _get_server(repository, server_id)
    try:
        await McpManager(db).discover(record)
    except (UnsafeMcpConfigurationError, McpClientError) as exc:
        raise HTTPException(status_code=502, detail="MCP discovery failed") from exc
    return _server_response(record)


@router.post(
    "/servers/{server_id}/health",
    response_model=McpServerResponse,
    dependencies=[Depends(require_mcp_api)],
)
async def check_mcp_server_health(
    server_id: str,
    db: AsyncSession = Depends(get_session),
):
    return await discover_mcp_server(server_id, db)


@router.get(
    "/servers/{server_id}/calls",
    response_model=list[McpCallLogResponse],
    dependencies=[Depends(require_mcp_api)],
)
async def list_mcp_calls(
    server_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_session),
):
    repository = McpRepository(db)
    await _get_server(repository, server_id)
    return [_call_response(record) for record in await repository.list_calls(server_id, limit=limit)]
