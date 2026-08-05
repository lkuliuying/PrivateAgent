"""Default-off background loop for traceable conversation compression."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass

from sqlalchemy import text

from ..config import settings
from ..core.conversation_summarizer import ConversationSummaryService
from ..core.db import async_session_factory, engine
from ..core.provider import ProviderRouter
from ..core.settings import SettingsService
from ..logging_setup import get_logger

logger = get_logger(__name__)

_LOCK_NAME = "private-agent:conversation-summary-worker:v1"
_MINIMUM_SCHEMA_REVISION = 17


@dataclass(frozen=True, slots=True)
class SummaryWorkerOutcome:
    status: str
    reason: str | None = None
    summary_id: str | None = None
    session_id: int | None = None
    first_message_id: int | None = None
    last_message_id: int | None = None


def schema_supports_conversation_summaries(revision: str | None) -> bool:
    if revision is None or len(revision) != 4 or not revision.isdigit():
        return False
    return int(revision) >= _MINIMUM_SCHEMA_REVISION


async def run_conversation_summary_once() -> SummaryWorkerOutcome:
    """Generate at most one summary while holding a cross-process MySQL lock."""

    async with engine.connect() as lock_connection:
        acquired = await lock_connection.scalar(
            text("SELECT GET_LOCK(:lock_name, 0)"),
            {"lock_name": _LOCK_NAME},
        )
        if int(acquired or 0) != 1:
            return SummaryWorkerOutcome(status="skipped", reason="lock_busy")
        try:
            async with async_session_factory() as db:
                schema_revision = await db.scalar(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                )
                if not schema_supports_conversation_summaries(
                    str(schema_revision) if schema_revision is not None else None
                ):
                    return SummaryWorkerOutcome(
                        status="skipped",
                        reason="schema_not_ready",
                    )
                service = ConversationSummaryService(
                    db,
                    min_source_messages=(
                        settings.conversation_summary_min_source_messages
                    ),
                    keep_recent_messages=(
                        settings.conversation_summary_keep_recent_messages
                    ),
                    max_source_messages=(
                        settings.conversation_summary_max_source_messages
                    ),
                    max_source_chars=settings.conversation_summary_max_source_chars,
                )
                candidate = await service.find_candidate()
                if candidate is None:
                    return SummaryWorkerOutcome(
                        status="skipped",
                        reason="no_candidate",
                    )

                provider_settings = await SettingsService(db).get_all()
                router = ProviderRouter(provider_settings)
                privacy = router.privacy_scope()
                if privacy.get("sends") and not (
                    settings.conversation_summary_allow_remote_provider
                ):
                    return SummaryWorkerOutcome(
                        status="skipped",
                        reason="remote_provider_not_allowed",
                        session_id=candidate.session_id,
                        first_message_id=candidate.first_message_id,
                        last_message_id=candidate.last_message_id,
                    )

                record = await service.summarize_candidate(
                    candidate,
                    router.model_gateway(),
                )
                return SummaryWorkerOutcome(
                    status="created",
                    summary_id=record.id,
                    session_id=record.session_id,
                    first_message_id=record.first_message_id,
                    last_message_id=record.last_message_id,
                )
        finally:
            with suppress(Exception):
                await lock_connection.scalar(
                    text("SELECT RELEASE_LOCK(:lock_name)"),
                    {"lock_name": _LOCK_NAME},
                )


async def conversation_summary_tick_loop() -> None:
    """Sleep before each bounded tick; the feature is gated in app lifespan."""

    last_reported_reason: str | None = None
    while True:
        await asyncio.sleep(settings.conversation_summary_tick_seconds)
        try:
            outcome = await run_conversation_summary_once()
            if outcome.status == "created":
                last_reported_reason = None
                logger.info(
                    "conversation summary created",
                    summary_id=outcome.summary_id,
                    session_id=outcome.session_id,
                    first_message_id=outcome.first_message_id,
                    last_message_id=outcome.last_message_id,
                )
            elif (
                outcome.reason not in {None, "no_candidate", "lock_busy"}
                and outcome.reason != last_reported_reason
            ):
                last_reported_reason = outcome.reason
                logger.warning(
                    "conversation summary worker skipped",
                    reason=outcome.reason,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "conversation summary worker failed",
                error_type=type(exc).__name__,
            )
