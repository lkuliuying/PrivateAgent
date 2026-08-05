"""Durable, parameter-bound, expiring and one-time Agent tool approvals."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from personal_assistant.core.models import RunStep as RunStepRecord
from personal_assistant.core.models import ToolApproval as ToolApprovalRecord

from .contracts import ToolCall
from .tools import ToolSpec, build_tool_idempotency_key


class ToolApprovalError(RuntimeError):
    """Base error for durable Agent tool approval state."""


class ToolApprovalNotFoundError(ToolApprovalError):
    pass


class ToolApprovalConflictError(ToolApprovalError):
    pass


class ToolApprovalExpiredError(ToolApprovalError):
    pass


class ToolApprovalTokenError(ToolApprovalError):
    pass


@dataclass(frozen=True, slots=True)
class ApprovedToolCall:
    approval_id: str
    token: str
    expires_at: datetime


Clock = Callable[[], datetime]
TokenFactory = Callable[[], str]

_ACTIVE_STATUSES = {"pending", "approved"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _canonical_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    try:
        serialized = json.dumps(
            arguments,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        value = json.loads(serialized)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("tool approval arguments must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("tool approval arguments must be a JSON object")
    return value


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ToolApprovalRepository:
    """Own the approval state machine and all one-time token verification."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        clock: Clock = _utc_now,
        token_factory: TokenFactory | None = None,
    ) -> None:
        self.db = db
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    async def create_pending(
        self,
        *,
        run_id: str,
        step_id: str | None,
        tool_call_id: str,
        spec: ToolSpec,
        arguments: Mapping[str, Any],
        ttl_seconds: int = 300,
    ) -> ToolApprovalRecord:
        if not 30 <= ttl_seconds <= 3_600:
            raise ValueError("approval ttl_seconds must be between 30 and 3600")
        canonical = _canonical_arguments(arguments)
        arguments_hash = build_tool_idempotency_key(spec, canonical)
        capabilities = sorted(capability.value for capability in spec.required_capabilities)
        now = _utc_naive(self._clock())

        try:
            if step_id is not None:
                step = await self.db.get(RunStepRecord, step_id)
                if step is None or step.run_id != run_id:
                    raise ToolApprovalConflictError(
                        "approval step does not belong to the requested run"
                    )
            existing = (
                await self.db.execute(
                    select(ToolApprovalRecord)
                    .where(
                        ToolApprovalRecord.run_id == run_id,
                        ToolApprovalRecord.tool_call_id == tool_call_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if existing is not None:
                if (
                    existing.step_id == step_id
                    and existing.tool_name == spec.name
                    and existing.tool_version == spec.version
                    and existing.arguments_sha256 == arguments_hash
                    and existing.arguments_json == canonical
                    and existing.risk_level == spec.risk_level.value
                    and existing.required_capabilities_json == capabilities
                ):
                    await self.db.commit()
                    return existing
                raise ToolApprovalConflictError(
                    "tool_call_id is already bound to different tool arguments"
                )

            record = ToolApprovalRecord(
                id=str(uuid4()),
                run_id=run_id,
                step_id=step_id,
                tool_call_id=tool_call_id,
                tool_name=spec.name,
                tool_version=spec.version,
                arguments_json=canonical,
                arguments_sha256=arguments_hash,
                risk_level=spec.risk_level.value,
                required_capabilities_json=capabilities,
                status="pending",
                expires_at=now + timedelta(seconds=ttl_seconds),
            )
            self.db.add(record)
            await self.db.commit()
            await self.db.refresh(record)
            return record
        except Exception:
            await self.db.rollback()
            raise

    async def get(self, approval_id: str) -> ToolApprovalRecord | None:
        return await self.db.get(ToolApprovalRecord, approval_id)

    async def require_consumed_binding(
        self,
        approval_id: str,
        *,
        call: ToolCall,
        spec: ToolSpec,
        arguments: Mapping[str, Any],
    ) -> ToolApprovalRecord:
        """Re-authorize crash recovery without replaying the one-time token."""

        canonical = _canonical_arguments(arguments)
        arguments_hash = build_tool_idempotency_key(spec, canonical)
        capabilities = sorted(capability.value for capability in spec.required_capabilities)
        record = await self.get(approval_id)
        if record is None:
            raise ToolApprovalNotFoundError(
                f"tool approval not found: {approval_id}"
            )
        if record.status != "consumed":
            raise ToolApprovalConflictError(
                f"approval is not consumed: {record.status}"
            )
        if (
            record.tool_call_id != call.id
            or record.tool_name != spec.name
            or record.tool_version != spec.version
            or record.arguments_sha256 != arguments_hash
            or record.arguments_json != canonical
            or record.risk_level != spec.risk_level.value
            or record.required_capabilities_json != capabilities
        ):
            raise ToolApprovalConflictError(
                "consumed approval no longer matches the exact tool call"
            )
        return record

    async def list_for_run(self, run_id: str) -> list[ToolApprovalRecord]:
        result = await self.db.execute(
            select(ToolApprovalRecord)
            .where(ToolApprovalRecord.run_id == run_id)
            .order_by(ToolApprovalRecord.created_at.asc())
        )
        return list(result.scalars().all())

    async def approve(self, approval_id: str) -> ApprovedToolCall:
        record = await self._get_for_update(approval_id)
        now = _utc_naive(self._clock())
        try:
            if self._expire_if_needed(record, now):
                await self.db.commit()
                raise ToolApprovalExpiredError("tool approval expired")
            if record.status != "pending":
                raise ToolApprovalConflictError(
                    f"approval cannot transition from {record.status} to approved"
                )
            token = self._token_factory()
            if not isinstance(token, str) or not 32 <= len(token) <= 512:
                raise RuntimeError("approval token factory returned an unsafe token")
            record.status = "approved"
            record.approval_token_sha256 = _token_hash(token)
            record.decision_at = now
            record.updated_at = now
            await self.db.commit()
            return ApprovedToolCall(
                approval_id=record.id,
                token=token,
                expires_at=record.expires_at,
            )
        except Exception:
            await self.db.rollback()
            raise

    async def reissue_approved(self, approval_id: str) -> ApprovedToolCall:
        """Rotate a lost in-memory token after a process restart, before consumption."""

        record = await self._get_for_update(approval_id)
        now = _utc_naive(self._clock())
        try:
            if self._expire_if_needed(record, now):
                await self.db.commit()
                raise ToolApprovalExpiredError("tool approval expired")
            if record.status != "approved":
                raise ToolApprovalConflictError(
                    f"approval cannot reissue from {record.status}"
                )
            token = self._token_factory()
            if not isinstance(token, str) or not 32 <= len(token) <= 512:
                raise RuntimeError("approval token factory returned an unsafe token")
            record.approval_token_sha256 = _token_hash(token)
            record.decision_at = now
            record.updated_at = now
            await self.db.commit()
            return ApprovedToolCall(
                approval_id=record.id,
                token=token,
                expires_at=record.expires_at,
            )
        except Exception:
            await self.db.rollback()
            raise

    async def reject(self, approval_id: str) -> ToolApprovalRecord:
        record = await self._get_for_update(approval_id)
        now = _utc_naive(self._clock())
        try:
            if self._expire_if_needed(record, now):
                await self.db.commit()
                raise ToolApprovalExpiredError("tool approval expired")
            if record.status != "pending":
                raise ToolApprovalConflictError(
                    f"approval cannot transition from {record.status} to rejected"
                )
            record.status = "rejected"
            record.decision_at = now
            record.updated_at = now
            await self.db.commit()
            await self.db.refresh(record)
            return record
        except Exception:
            await self.db.rollback()
            raise

    async def consume(
        self,
        approval_id: str,
        *,
        token: str,
        spec: ToolSpec,
        arguments: Mapping[str, Any],
    ) -> ToolApprovalRecord:
        canonical = _canonical_arguments(arguments)
        arguments_hash = build_tool_idempotency_key(spec, canonical)
        capabilities = sorted(capability.value for capability in spec.required_capabilities)
        if not isinstance(token, str):
            raise ToolApprovalTokenError("invalid approval token")
        record = await self._get_for_update(approval_id)
        now = _utc_naive(self._clock())
        try:
            if self._expire_if_needed(record, now):
                await self.db.commit()
                raise ToolApprovalExpiredError("tool approval expired")
            if record.status != "approved":
                raise ToolApprovalConflictError(
                    f"approval cannot be consumed from status {record.status}"
                )
            if (
                record.tool_name != spec.name
                or record.tool_version != spec.version
                or record.arguments_sha256 != arguments_hash
                or record.arguments_json != canonical
                or record.risk_level != spec.risk_level.value
                or record.required_capabilities_json != capabilities
            ):
                raise ToolApprovalConflictError(
                    "approved tool name, version, or arguments no longer match"
                )
            expected = record.approval_token_sha256 or ""
            supplied = _token_hash(token)
            if not expected or not hmac.compare_digest(expected, supplied):
                raise ToolApprovalTokenError("invalid approval token")

            record.status = "consumed"
            record.consumed_at = now
            record.updated_at = now
            await self.db.commit()
            await self.db.refresh(record)
            return record
        except Exception:
            await self.db.rollback()
            raise

    async def cancel_for_run(self, run_id: str) -> int:
        now = _utc_naive(self._clock())
        try:
            result = await self.db.execute(
                update(ToolApprovalRecord)
                .where(
                    ToolApprovalRecord.run_id == run_id,
                    ToolApprovalRecord.status.in_(_ACTIVE_STATUSES),
                )
                .values(status="cancelled", decision_at=now, updated_at=now)
            )
            await self.db.commit()
            return int(result.rowcount or 0)
        except Exception:
            await self.db.rollback()
            raise

    async def expire_due(self) -> int:
        now = _utc_naive(self._clock())
        try:
            result = await self.db.execute(
                update(ToolApprovalRecord)
                .where(
                    ToolApprovalRecord.status.in_(_ACTIVE_STATUSES),
                    ToolApprovalRecord.expires_at <= now,
                )
                .values(status="expired", decision_at=now, updated_at=now)
            )
            await self.db.commit()
            return int(result.rowcount or 0)
        except Exception:
            await self.db.rollback()
            raise

    async def _get_for_update(self, approval_id: str) -> ToolApprovalRecord:
        try:
            record = (
                await self.db.execute(
                    select(ToolApprovalRecord)
                    .where(ToolApprovalRecord.id == approval_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
        except Exception:
            await self.db.rollback()
            raise
        if record is None:
            await self.db.rollback()
            raise ToolApprovalNotFoundError(f"tool approval not found: {approval_id}")
        return record

    @staticmethod
    def _expire_if_needed(record: ToolApprovalRecord, now: datetime) -> bool:
        if record.status in _ACTIVE_STATUSES and record.expires_at <= now:
            record.status = "expired"
            record.decision_at = now
            record.updated_at = now
            return True
        return False


class SqlToolApprovalRequester:
    """Create an approval for the running tool step projected just before dispatch."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        run_id: str,
        ttl_seconds: int = 300,
    ) -> None:
        self._db = db
        self._run_id = run_id
        self._ttl_seconds = ttl_seconds

    async def request(
        self,
        spec: ToolSpec,
        call: ToolCall,
        arguments: Mapping[str, Any],
    ) -> str:
        step = (
            await self._db.execute(
                select(RunStepRecord)
                .where(
                    RunStepRecord.run_id == self._run_id,
                    RunStepRecord.tool_call_id == call.id,
                    RunStepRecord.status == "running",
                )
                .order_by(RunStepRecord.ordinal.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if step is None:
            raise ToolApprovalConflictError(
                "no running tool step exists for the approval request"
            )
        record = await ToolApprovalRepository(self._db).create_pending(
            run_id=self._run_id,
            step_id=step.id,
            tool_call_id=call.id,
            spec=spec,
            arguments=arguments,
            ttl_seconds=self._ttl_seconds,
        )
        return record.id


class SqlToolApprovalConsumer:
    """Consume a raw token once or re-authorize its exact consumed binding."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        approval_id: str,
        token: str | None,
    ) -> None:
        self._repository = ToolApprovalRepository(db)
        self._approval_id = approval_id
        self._token = token
        self._used = False

    async def consume(
        self,
        spec: ToolSpec,
        call: ToolCall,
        arguments: Mapping[str, Any],
    ) -> str | None:
        if self._used:
            return None
        record = await self._repository.get(self._approval_id)
        if record is None:
            raise ToolApprovalNotFoundError(
                f"tool approval not found: {self._approval_id}"
            )
        if record.tool_call_id != call.id:
            return None
        if record.status == "consumed":
            await self._repository.require_consumed_binding(
                self._approval_id,
                call=call,
                spec=spec,
                arguments=arguments,
            )
        else:
            if self._token is None:
                raise ToolApprovalTokenError("approval token is required")
            await self._repository.consume(
                self._approval_id,
                token=self._token,
                spec=spec,
                arguments=arguments,
            )
        self._used = True
        return record.id
