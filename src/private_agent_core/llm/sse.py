"""Small, bounded Server-Sent Events parser shared by model providers."""

from __future__ import annotations

from collections.abc import AsyncIterator


async def iter_sse_events(
    lines: AsyncIterator[str],
    *,
    max_line_chars: int = 1_048_576,
    max_event_chars: int = 2_097_152,
) -> AsyncIterator[tuple[str | None, str]]:
    """Yield ``(event_name, data)`` while preserving multi-line data fields."""

    if max_line_chars <= 0 or max_event_chars <= 0:
        raise ValueError("SSE size limits must be positive")
    event_name: str | None = None
    data_lines: list[str] = []
    data_chars = 0

    def flush() -> tuple[str | None, str] | None:
        nonlocal event_name, data_lines, data_chars
        if not data_lines:
            event_name = None
            data_chars = 0
            return None
        event = (event_name, "\n".join(data_lines))
        event_name = None
        data_lines = []
        data_chars = 0
        return event

    async for line in lines:
        if len(line) > max_line_chars:
            raise ValueError("provider SSE line exceeds the configured limit")
        if line == "":
            event = flush()
            if event is not None:
                yield event
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_name = value
        elif field == "data":
            data_chars += len(value)
            if data_chars > max_event_chars:
                raise ValueError("provider SSE event exceeds the configured limit")
            data_lines.append(value)

    event = flush()
    if event is not None:
        yield event
