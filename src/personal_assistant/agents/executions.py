"""Durable lease and audit repository for Agent tool executions."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import AgentToolExecution as ExecutionRecord
from personal_assistant.core.models import RunStep as RunStepRecord
from personal_assistant.core.models import ToolApproval as ToolApprovalRecord

from .contracts import ToolCall
from .tools import ToolIdempotency, ToolSpec, build_tool_idempotency_key


class ToolExecutionError(RuntimeError):
    pass


class ToolExecutionConflictError(ToolExecutionError):
    pass


class ToolExecutionClaimError(ToolExecutionError):
    pass


class ToolExecutionClaimAction(StrEnum):
    EXECUTE = "execute"
    CACHED = "cached"
    IN_PROGRESS = "in_progress"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ToolExecutionClaim:
    execution_id: str
    action: ToolExecutionClaimAction
    claim_token: str | None = None
    output: Any = None
    attempt_count: int = 0


Clock = Callable[[], datetime]
TokenFactory = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _canonical_json_object(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        cloned = json.loads(
            json.dumps(
                value,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("tool execution arguments must be valid JSON") from exc
    if not isinstance(cloned, dict):
        raise ValueError("tool execution arguments must be a JSON object")
    return cloned


def _canonical_json_value(value: Any) -> tuple[Any, bytes]:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("tool execution output must be valid JSON") from exc
    return json.loads(encoded), encoded


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ToolExecutionRepository:
    """Claim tool work with a lease and persist only bounded, redacted results."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        run_id: str,
        clock: Clock = _utc_now,
        token_factory: TokenFactory | None = None,
    ) -> None:
        self.db = db
        self.run_id = run_id
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    async def claim(
        self,
        *,
        spec: ToolSpec,
        call: ToolCall,
        arguments: Mapping[str, Any],
        approval_id: str | None = None,
    ) -> ToolExecutionClaim:
        canonical = _canonical_json_object(arguments)
        arguments_hash = build_tool_idempotency_key(spec, canonical)
        execution_key = (
            arguments_hash
            if spec.idempotency == ToolIdempotency.IDEMPOTENT
            else None
        )
        capabilities = sorted(capability.value for capability in spec.required_capabilities)
        now = _utc_naive(self._clock())

        try:
            # Serialize first insert and lookup for one run. Without this lock,
            # concurrent workers can both observe no row and race on a unique key.
            run_exists = (
                await self.db.execute(
                    select(AgentRunRecord.id)
                    .where(AgentRunRecord.id == self.run_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if run_exists is None:
                raise ToolExecutionConflictError(
                    f"agent run not found: {self.run_id}"
                )
            step = await self._find_step(call.id)
            await self._validate_approval(
                approval_id,
                spec=spec,
                call=call,
                arguments=canonical,
                arguments_hash=arguments_hash,
                capabilities=capabilities,
            )

            identity_predicates = [ExecutionRecord.tool_call_id == call.id]
            if execution_key is not None:
                identity_predicates.append(
                    ExecutionRecord.execution_key_sha256 == execution_key
                )
            existing = (
                await self.db.execute(
                    select(ExecutionRecord)
                    .where(
                        ExecutionRecord.run_id == self.run_id,
                        or_(*identity_predicates),
                    )
                    .order_by(ExecutionRecord.created_at.asc())
                    .limit(1)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if existing is not None:
                self._validate_binding(
                    existing,
                    spec=spec,
                    arguments=canonical,
                    arguments_hash=arguments_hash,
                    capabilities=capabilities,
                    call=call,
                    approval_id=approval_id,
                )
                if existing.status == "succeeded":
                    self._verify_cached_output(existing, spec=spec)
                    await self.db.commit()
                    return ToolExecutionClaim(
                        execution_id=existing.id,
                        action=ToolExecutionClaimAction.CACHED,
                        output=existing.output_json,
                        attempt_count=existing.attempt_count,
                    )
                if existing.status == "running" and (
                    existing.lease_expires_at is not None
                    and existing.lease_expires_at > now
                ):
                    await self.db.commit()
                    return ToolExecutionClaim(
                        execution_id=existing.id,
                        action=ToolExecutionClaimAction.IN_PROGRESS,
                        attempt_count=existing.attempt_count,
                    )
                if spec.idempotency != ToolIdempotency.IDEMPOTENT:
                    existing.status = "unknown"
                    existing.completed_at = now
                    existing.lease_expires_at = None
                    existing.claim_token_sha256 = None
                    existing.error_code = "state_unknown"
                    existing.error_message = "非幂等工具执行状态未知，拒绝自动重试"
                    existing.updated_at = now
                    await self.db.commit()
                    return ToolExecutionClaim(
                        execution_id=existing.id,
                        action=ToolExecutionClaimAction.UNKNOWN,
                        attempt_count=existing.attempt_count,
                    )
                return await self._reclaim(existing, spec=spec, now=now)

            token = self._new_token()
            record = ExecutionRecord(
                id=str(uuid4()),
                run_id=self.run_id,
                step_id=step.id,
                tool_call_id=call.id,
                tool_name=spec.name,
                tool_version=spec.version,
                arguments_json=canonical,
                arguments_sha256=arguments_hash,
                execution_key_sha256=execution_key,
                risk_level=spec.risk_level.value,
                required_capabilities_json=capabilities,
                approval_id=approval_id,
                status="running",
                attempt_count=1,
                claim_token_sha256=_token_hash(token),
                lease_expires_at=now + timedelta(milliseconds=spec.timeout_ms + 5_000),
                started_at=now,
            )
            self.db.add(record)
            await self.db.commit()
            return ToolExecutionClaim(
                execution_id=record.id,
                action=ToolExecutionClaimAction.EXECUTE,
                claim_token=token,
                attempt_count=1,
            )
        except Exception:
            await self.db.rollback()
            raise

    async def complete_success(
        self,
        execution_id: str,
        *,
        claim_token: str,
        output: Any,
        max_output_bytes: int,
    ) -> ExecutionRecord:
        if not 128 <= max_output_bytes <= 10 * 1024 * 1024:
            raise ValueError("invalid tool output size limit")
        canonical, encoded = _canonical_json_value(output)
        if len(encoded) > max_output_bytes:
            raise ValueError("tool execution output exceeds its size limit")
        record = await self._get_for_update(execution_id)
        now = _utc_naive(self._clock())
        try:
            self._verify_active_claim(record, claim_token)
            record.status = "succeeded"
            record.output_json = canonical
            record.output_sha256 = hashlib.sha256(encoded).hexdigest()
            record.output_size_bytes = len(encoded)
            record.error_code = None
            record.error_message = None
            record.claim_token_sha256 = None
            record.lease_expires_at = None
            record.completed_at = now
            record.updated_at = now
            await self.db.commit()
            await self.db.refresh(record)
            return record
        except Exception:
            await self.db.rollback()
            raise

    async def complete_failure(
        self,
        execution_id: str,
        *,
        claim_token: str,
        status: str,
        error_code: str,
        error_message: str,
    ) -> ExecutionRecord:
        if status not in {"failed", "timed_out", "cancelled", "unknown"}:
            raise ValueError("invalid terminal tool execution status")
        record = await self._get_for_update(execution_id)
        now = _utc_naive(self._clock())
        try:
            self._verify_active_claim(record, claim_token)
            record.status = status
            record.error_code = error_code[:64]
            record.error_message = error_message[:2_000]
            record.claim_token_sha256 = None
            record.lease_expires_at = None
            record.completed_at = now
            record.updated_at = now
            await self.db.commit()
            await self.db.refresh(record)
            return record
        except Exception:
            await self.db.rollback()
            raise

    async def get(self, execution_id: str) -> ExecutionRecord | None:
        return await self.db.get(ExecutionRecord, execution_id)

    async def list_for_run(self) -> list[ExecutionRecord]:
        result = await self.db.execute(
            select(ExecutionRecord)
            .where(ExecutionRecord.run_id == self.run_id)
            .order_by(ExecutionRecord.created_at.asc())
        )
        return list(result.scalars().all())

    async def _find_step(self, tool_call_id: str) -> RunStepRecord:
        step = (
            await self.db.execute(
                select(RunStepRecord)
                .where(
                    RunStepRecord.run_id == self.run_id,
                    RunStepRecord.tool_call_id == tool_call_id,
                    RunStepRecord.status.in_({"running", "waiting_approval"}),
                )
                .order_by(RunStepRecord.ordinal.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if step is None:
            await self.db.rollback()
            raise ToolExecutionConflictError(
                "no active tool step exists for the execution claim"
            )
        return step

    async def _validate_approval(
        self,
        approval_id: str | None,
        *,
        spec: ToolSpec,
        call: ToolCall,
        arguments: dict[str, Any],
        arguments_hash: str,
        capabilities: list[str],
    ) -> None:
        if approval_id is None:
            if spec.risk_level.value == "confirm":
                raise ToolExecutionConflictError(
                    "confirm-risk tool execution requires a consumed approval"
                )
            return
        approval = await self.db.get(ToolApprovalRecord, approval_id)
        if approval is None:
            raise ToolExecutionConflictError(
                f"tool approval not found: {approval_id}"
            )
        if (
            approval.run_id != self.run_id
            or approval.tool_call_id != call.id
            or approval.tool_name != spec.name
            or approval.tool_version != spec.version
            or approval.arguments_sha256 != arguments_hash
            or approval.arguments_json != arguments
            or approval.risk_level != spec.risk_level.value
            or approval.required_capabilities_json != capabilities
            or approval.status != "consumed"
        ):
            raise ToolExecutionConflictError(
                "tool approval is not a consumed exact binding for this execution"
            )

    async def _reclaim(
        self,
        record: ExecutionRecord,
        *,
        spec: ToolSpec,
        now: datetime,
    ) -> ToolExecutionClaim:
        token = self._new_token()
        record.status = "running"
        record.attempt_count += 1
        record.claim_token_sha256 = _token_hash(token)
        record.lease_expires_at = now + timedelta(
            milliseconds=spec.timeout_ms + 5_000
        )
        record.error_code = None
        record.error_message = None
        record.completed_at = None
        record.updated_at = now
        await self.db.commit()
        return ToolExecutionClaim(
            execution_id=record.id,
            action=ToolExecutionClaimAction.EXECUTE,
            claim_token=token,
            attempt_count=record.attempt_count,
        )

    async def _get_for_update(self, execution_id: str) -> ExecutionRecord:
        record = (
            await self.db.execute(
                select(ExecutionRecord)
                .where(ExecutionRecord.id == execution_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if record is None:
            await self.db.rollback()
            raise ToolExecutionConflictError(
                f"tool execution not found: {execution_id}"
            )
        return record

    def _new_token(self) -> str:
        token = self._token_factory()
        if not isinstance(token, str) or not 32 <= len(token) <= 512:
            raise RuntimeError("execution token factory returned an unsafe token")
        return token

    @staticmethod
    def _validate_binding(
        record: ExecutionRecord,
        *,
        spec: ToolSpec,
        arguments: dict[str, Any],
        arguments_hash: str,
        capabilities: list[str],
        call: ToolCall,
        approval_id: str | None,
    ) -> None:
        if (
            record.tool_name != spec.name
            or record.tool_version != spec.version
            or record.arguments_sha256 != arguments_hash
            or record.arguments_json != arguments
            or record.risk_level != spec.risk_level.value
            or record.required_capabilities_json != capabilities
        ):
            raise ToolExecutionConflictError(
                "tool execution key is bound to different immutable inputs"
            )
        if record.tool_call_id == call.id:
            if record.approval_id != approval_id:
                raise ToolExecutionConflictError(
                    "tool execution is bound to a different approval"
                )
        elif record.approval_id is not None or approval_id is not None:
            raise ToolExecutionConflictError(
                "approved tool executions cannot be deduplicated across calls"
            )

    @staticmethod
    def _verify_active_claim(record: ExecutionRecord, token: str) -> None:
        if record.status != "running":
            raise ToolExecutionClaimError(
                f"tool execution is not running: {record.status}"
            )
        expected = record.claim_token_sha256 or ""
        supplied = _token_hash(token)
        if not expected or not hmac.compare_digest(expected, supplied):
            raise ToolExecutionClaimError("invalid tool execution claim token")

    @staticmethod
    def _verify_cached_output(record: ExecutionRecord, *, spec: ToolSpec) -> None:
        if (
            record.output_json is None
            or record.output_sha256 is None
            or record.output_size_bytes is None
        ):
            raise ToolExecutionConflictError(
                "succeeded tool execution has no verifiable output"
            )
        _, encoded = _canonical_json_value(record.output_json)
        if (
            len(encoded) != record.output_size_bytes
            or len(encoded) > spec.max_output_bytes
            or not hmac.compare_digest(
                hashlib.sha256(encoded).hexdigest(),
                record.output_sha256,
            )
        ):
            raise ToolExecutionConflictError(
                "cached tool execution output failed integrity validation"
            )
