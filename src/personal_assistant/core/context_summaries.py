"""Traceable conversation summaries bound to immutable message ranges."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ChatSession, ConversationSummary, Message

_PROMPT_VERSION = re.compile(r"^[a-zA-Z0-9_.-]{1,32}$")


class ConversationSummaryError(RuntimeError):
    pass


class ConversationSummaryRangeError(ConversationSummaryError):
    pass


@dataclass(frozen=True, slots=True)
class SummarySource:
    first_message_id: int
    last_message_id: int
    message_count: int
    sha256: str


def _source_hash(messages: list[Message]) -> str:
    payload = [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at.isoformat(),
        }
        for message in messages
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ConversationSummaryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def inspect_source(
        self,
        *,
        session_id: int,
        first_message_id: int,
        last_message_id: int,
    ) -> SummarySource:
        if first_message_id > last_message_id:
            raise ConversationSummaryRangeError(
                "summary first_message_id must not exceed last_message_id"
            )
        messages = list(
            (
                await self.db.execute(
                    select(Message)
                    .where(
                        Message.session_id == session_id,
                        Message.id >= first_message_id,
                        Message.id <= last_message_id,
                    )
                    .order_by(Message.id.asc())
                )
            ).scalars()
        )
        if (
            not messages
            or messages[0].id != first_message_id
            or messages[-1].id != last_message_id
        ):
            raise ConversationSummaryRangeError(
                "summary range endpoints must exist in the requested session"
            )
        return SummarySource(
            first_message_id=first_message_id,
            last_message_id=last_message_id,
            message_count=len(messages),
            sha256=_source_hash(messages),
        )

    async def create(
        self,
        *,
        session_id: int,
        first_message_id: int,
        last_message_id: int,
        summary_text: str,
        prompt_version: str,
        provider: str | None = None,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        sensitive: bool = False,
    ) -> ConversationSummary:
        normalized = summary_text.strip()
        if not normalized:
            raise ValueError("conversation summary cannot be empty")
        if len(normalized) > 200_000:
            raise ValueError("conversation summary exceeds size limit")
        if not _PROMPT_VERSION.fullmatch(prompt_version):
            raise ValueError("invalid conversation summary prompt version")
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("conversation summary token counts cannot be negative")

        try:
            session_exists = (
                await self.db.execute(
                    select(ChatSession.id)
                    .where(ChatSession.id == session_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if session_exists is None:
                raise ConversationSummaryRangeError(
                    f"conversation session not found: {session_id}"
                )
            source = await self.inspect_source(
                session_id=session_id,
                first_message_id=first_message_id,
                last_message_id=last_message_id,
            )
            same_source = list(
                (
                    await self.db.execute(
                        select(ConversationSummary)
                        .where(
                            ConversationSummary.session_id == session_id,
                            ConversationSummary.source_sha256 == source.sha256,
                        )
                        .order_by(ConversationSummary.summary_version.desc())
                        .with_for_update()
                    )
                ).scalars()
            )
            latest = same_source[0] if same_source else None
            if latest is not None and (
                latest.summary_text == normalized
                and latest.prompt_version == prompt_version
                and latest.provider == provider
                and latest.model == model
                and latest.sensitive == sensitive
            ):
                await self.db.commit()
                return latest

            overlapping = list(
                (
                    await self.db.execute(
                        select(ConversationSummary)
                        .where(
                            ConversationSummary.session_id == session_id,
                            ConversationSummary.status == "active",
                            ConversationSummary.first_message_id
                            <= last_message_id,
                            ConversationSummary.last_message_id
                            >= first_message_id,
                        )
                        .with_for_update()
                    )
                ).scalars()
            )
            for record in overlapping:
                record.status = "superseded"

            record = ConversationSummary(
                id=str(uuid4()),
                session_id=session_id,
                first_message_id=source.first_message_id,
                last_message_id=source.last_message_id,
                source_message_count=source.message_count,
                source_sha256=source.sha256,
                summary_text=normalized,
                summary_version=(latest.summary_version + 1 if latest else 1),
                prompt_version=prompt_version,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                sensitive=sensitive,
                status="active",
            )
            self.db.add(record)
            await self.db.commit()
            await self.db.refresh(record)
            return record
        except Exception:
            await self.db.rollback()
            raise

    async def list_active(self, session_id: int) -> list[ConversationSummary]:
        result = await self.db.execute(
            select(ConversationSummary)
            .where(
                ConversationSummary.session_id == session_id,
                ConversationSummary.status == "active",
            )
            .order_by(ConversationSummary.last_message_id.asc())
        )
        return list(result.scalars().all())

    async def list_all(self, session_id: int) -> list[ConversationSummary]:
        result = await self.db.execute(
            select(ConversationSummary)
            .where(ConversationSummary.session_id == session_id)
            .order_by(
                ConversationSummary.created_at.asc(),
                ConversationSummary.summary_version.asc(),
            )
        )
        return list(result.scalars().all())

    async def invalidate_missing_sources(self, session_id: int) -> int:
        records = await self.list_active(session_id)
        changed = 0
        for record in records:
            if record.first_message_id is None or record.last_message_id is None:
                record.status = "invalid"
                changed += 1
                continue
            try:
                source = await self.inspect_source(
                    session_id=session_id,
                    first_message_id=record.first_message_id,
                    last_message_id=record.last_message_id,
                )
            except ConversationSummaryRangeError:
                record.status = "invalid"
                changed += 1
                continue
            if (
                source.sha256 != record.source_sha256
                or source.message_count != record.source_message_count
            ):
                record.status = "invalid"
                changed += 1
        if changed:
            await self.db.commit()
        else:
            await self.db.rollback()
        return changed
